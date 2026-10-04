"""DuelsDomain: Claude negotiates every live duel in parallel; code keeps it safe and keeps a fallback.

decide()   one Claude call per live duel (threads), each with the structured state, the opponent model,
           the economics table, the lessons and the rival's words wrapped as untrusted. Whatever comes
           back goes through policy.guard (limit, days, no repeats, exact price in the text).
fallback() the pure-code concession schedule (policy.plan), instant.
observe()  outcomes of our own actions; observe_closed() takes finished duels (/api/duels?done=true) and
           logs one closing outcome per duel to the ledger (deal|no_deal, points, the actions and the
           lesson ids Claude cited) for the Lab's feedback loop.
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import time
from typing import Any

from ..core.context import conv_key
from ..core.types import Action, Outcome
from ..lab import feedback
from .model import MIN_SURPLUS, DuelView, parse_duel, points
from .opponent import OpponentMemory
from .policy import (PARAMS, Move, bound_claude, claude_mode, economics, guard, hold_if_rival_unchanged, hold_rule, replace_losing_offer,
                     hold_vs_unmoved_rival, plan)
from .prompt import DUEL_MOVE_TOOL, parse_tool, system_blocks, user_message

log = logging.getLogger("bazaar.duels")

# Accept priorities (Action.priority; the team gets ONE accept per tick). Shared scale with dealers/domain.py:
#   150 - 199   duel accept with <= 2 ticks left (the duel dies at the deadline)
#   140         dealer FINAL offer inside our limits (dealers.domain.FINAL_ACCEPT_PRIORITY: it walks otherwise)
#   100 - 130   other duel accepts (100 + expected points, capped at 30)
#   < 100       other accepts
ACCEPT_PRIORITY = 100.0
ACCEPT_SPAN = 30.0
URGENT_PRIORITY = 150.0
URGENT_SPAN = 49.0
URGENT_TICKS = 2


def urgent_ticks(n_accepting: int = 1) -> int:
    """One accept per tick for the team: with N duels wanting to accept, the last waits N ticks."""
    return max(URGENT_TICKS, int(n_accepting or 0))


def accept_priority(pts: float, ticks_left: int, n_accepting: int = 1) -> float:
    pts = max(0.0, float(pts))
    if ticks_left <= urgent_ticks(n_accepting):
        # The duel closest to its deadline goes first among the urgent ones (still within 150-199).
        return round(URGENT_PRIORITY + min(pts, URGENT_SPAN - 10) + max(0, 10 - ticks_left), 2)
    return round(ACCEPT_PRIORITY + min(pts, ACCEPT_SPAN), 2)


LATE_GRACE_S = 10.0          # a duel call may run this long past the tick deadline: its answer is used next tick
SAFETY_S = 0.25              # stop waiting for Claude this long before the tick deadline
SHORT_TICK_S = 20.0          # Sunday's 15 s ticks: race Opus against Sonnet


def _opus_rung(llm) -> bool:
    """True while the router still serves Opus today; once it has stepped down, a race would pay twice for Sonnet."""
    try:
        s = llm.spend_today()
        return float(s.get("usd") or 0) < float(s.get("degrade_at") or float("inf"))
    except Exception:  # noqa: BLE001
        return True
SONNET_ONLY_S = 5.0          # less time than this left: Sonnet alone


def _lazy_llm():
    try:
        from ..llm import client
        return client
    except Exception:            # CORE-A may not have shipped it yet: code-only until it does
        return None


def _strategy_text() -> str:
    try:
        from bazaar.brain.strategy import prompt_block
        b = prompt_block("duels")
    except Exception:  # noqa: BLE001
        return ""
    return ("\n\n" + b) if b else ""


class DuelsDomain:
    name = "duels"

    def __init__(self, memory: OpponentMemory | None = None, llm: Any = None, model: str | None = None,
                 max_workers: int = 6, llm_every: int = 1, use_llm: bool = True,
                 max_calls: int | None = None):
        self.memory = memory or OpponentMemory()
        self._llm = llm
        self.model = model
        self.use_llm = use_llm
        # Claude decides every move: asked each tick (llm_every=1). With a larger value the code schedule
        # used to fill the ticks in between and conceded faster than Claude had chosen to.
        self.llm_every = llm_every
        self._fails: dict[int, int] = {}           # duel -> Claude failures in a row
        self._pending: dict[int, tuple] = {}       # duel -> (future, asked key): a call that ran past the tick
        self.max_calls = max_calls          # hard cap on Claude calls (tournament / tests)
        self.calls = 0
        self.cost_usd = 0.0
        self._pool = cf.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="duel")
        self._last_ask: dict[int, tuple] = {}      # duel -> (tick, rival offer count, rival offer key)
        self._sent: dict[str, tuple[int, str, Any]] = {}    # action id -> (duel, kind, price)
        self._ledger: Any = None                            # ctx.ledger, captured each tick for closings
        self.last_notes: dict[int, list[str]] = {}

    # --- helpers -------------------------------------------------------------------------------------
    def _views(self, sit, ctx) -> list[DuelView]:
        tick = int(getattr(sit, "tick", 0) or 0)
        used = (getattr(ctx, "budget", None) or {}).get("messages", {}) if ctx is not None else {}
        ctl = getattr(ctx, "control", None) if ctx is not None else None
        out = []
        for d in getattr(sit, "duels", None) or []:
            v = parse_duel(d, tick)
            if v is None or v.ticks_left <= 0:
                continue
            ds = ctl.get("duel_days_sign") if isinstance(ctl, dict) else None
            if ds in ("value", "cost"):
                v.days_sign_override = ds
            if self.memory.note_days_reading(v):
                log.info("duels II session %s: days sign reading = %s", v.session, v.days_label)
            v.rival_w_prior = self.memory.rival_day_prior(v)
            v.total_ticks = self.memory.duel_length(v)
            if v.sent_this_tick() or used.get(conv_key(Action(kind="duel_message", params={"duel": v.id}, domain=self.name))):
                continue          # one message per conversation per tick: already spent (core conv_key)
            out.append(v)
        return out

    @staticmethod
    def _fallback_message(v: DuelView) -> dict:
        """What to send instead if the arbiter gives the team's single accept to another action: an offer
        of exactly the rival's standing price/days (they can take it; the core arbiter substitutes it)."""
        r = v.rival_offer
        d = f" with delivery in {r.days} days" if v.uses_days and r.days is not None else ""
        fm = {"duel": v.id, "price": int(r.price),
              "text": f"Your terms work for me: {r.price} P{d}. Take it and we close now."}
        if v.uses_days:
            fm["days"] = int(r.days if r.days is not None else 0)
        return fm

    def _action(self, v: DuelView, mv: Move, opp: dict, n_accepting: int = 1) -> Action | None:
        if mv.action == "wait":
            return None
        if mv.action == "accept":
            r = v.rival_offer
            margin = v.safe_utility(r.price, r.days)
            pts = points(margin, v.decay, v.rounds)
            params = {"duel": v.id, "expect": self._expect(v), "fallback_message": self._fallback_message(v)}
            return Action(kind="duel_accept", params=params, domain=self.name,
                          reason=mv.reason, big=True, priority=accept_priority(pts, v.ticks_left, n_accepting),
                          source=mv.source,
                          lesson_ids=list(mv.lesson_ids),
                          expected={"points": round(pts, 2), "margin": round(margin, 1), "rounds": v.rounds,
                                    "price": r.price, "days": r.days, "rival_type": opp.get("type"),
                                    "pie_est": opp.get("pie_estimate")})
        params = {"duel": v.id, "price": int(mv.price), "text": mv.text}
        if v.uses_days:
            params["days"] = int(mv.days if mv.days is not None else 0)
        margin = v.utility(mv.price, mv.days)
        return Action(kind="duel_message", params=params, domain=self.name, reason=mv.reason, big=False,
                      priority=round(mv.expected_points, 2), source=mv.source, lesson_ids=list(mv.lesson_ids),
                      expected={"points": mv.expected_points, "points_if_accepted": mv.expected_points,
                                "margin": round(margin, 1), "rounds_if_accepted": v.rounds_if_we_send(),
                                "rival_type": opp.get("type"), "pie_est": opp.get("pie_estimate")})

    @staticmethod
    def _expect(v: DuelView) -> dict:
        """The rival's standing offer exactly as the server gave it (rails compare it on a fresh read)."""
        raw = v.raw.get("rival_offer")
        return dict(raw) if isinstance(raw, dict) else v.rival_offer.as_expect()

    @staticmethod
    def _accept_queue(views: list[DuelView]) -> int:
        """Duels with a rival offer we could take right now (they compete for one accept per tick)."""
        n = 0
        for v in views:
            r = v.rival_offer
            if r is not None and v.surplus(r.price) >= MIN_SURPLUS and (not v.uses_days or r.days is not None) \
                    and v.safe_utility(r.price, r.days) >= MIN_SURPLUS:
                n += 1
        return n

    def _base(self, v: DuelView, queue: int = 0) -> tuple[dict, Move]:
        opp = self.memory.assess(v)
        opp["accept_queue"] = queue
        mv = plan(v, opp)
        mv, notes = guard(v, mv)
        mv, hnotes = hold_rule(v, mv, opp)
        if not hnotes:
            mv, hnotes = hold_if_rival_unchanged(v, mv)
        notes = notes + hnotes
        mv, rnotes = replace_losing_offer(v, mv)
        notes = notes + rnotes
        mv.source = "fallback"
        self.last_notes[v.id] = notes
        return opp, mv

    def _finish(self, views: list[DuelView], moves: dict, bases: dict) -> list[Action]:
        n_acc = sum(1 for mv in moves.values() if mv.action == "accept")
        actions = [a for v in views if (a := self._action(v, moves[v.id], bases[v.id][0], n_acc))]
        self.memory.save()
        return actions

    # --- Domain protocol -----------------------------------------------------------------------------
    def fallback(self, sit, ctx) -> list[Action]:
        self._ledger = getattr(ctx, "ledger", None) or self._ledger
        views = self._views(sit, ctx)
        q = self._accept_queue(views)
        bases = {v.id: self._base(v, q) for v in views}
        return self._finish(views, {k: b[1] for k, b in bases.items()}, bases)

    def _needs_llm(self, v: DuelView) -> bool:
        if (v.our_offer is not None or v.our_offers()) and not v.unanswered_rival_offer():
            return False        # the rival owes us an answer: hold in silence, then the coded short finish
        key = (len(v.rival_msgs()), v.rival_offer.key() if v.rival_offer else None)
        last = self._last_ask.get(v.id)
        if last is None or last[1:] != key:
            return True
        if v.ticks_left <= 3:
            return True
        return v.tick - last[0] >= self.llm_every

    def _ask(self, llm, v: DuelView, opp: dict, base: Move, ctx) -> Move | None:
        econ = economics(v, opp, (base.price, base.days) if base.action == "offer" else None)
        deadline = getattr(ctx, "deadline", None)
        kw = dict(purpose="duels", system=system_blocks(ctx),
                  messages=[{"role": "user", "content": user_message(v, opp, econ, base) + _strategy_text()}],
                  tools=[DUEL_MOVE_TOOL], tool_choice={"type": "auto"},
                  max_tokens=2000, deadline=(deadline - SAFETY_S + LATE_GRACE_S) if deadline else None)
        tick_s = getattr(ctx, "tick_seconds", None) if ctx is not None else None
        if isinstance(tick_s, (int, float)) and 0 < tick_s <= SHORT_TICK_S:
            from .. import config
            left = (deadline - SAFETY_S - time.time()) if deadline else None
            kw["deadline"] = (deadline - SAFETY_S) if deadline else None     # short ticks: no grace
            if left is not None and left < SONNET_ONLY_S:
                res = llm.ask(model=config.SONNET, **kw)
            elif hasattr(llm, "race") and _opus_rung(llm):
                res = llm.race(models=[config.OPUS, config.SONNET], **kw)
            else:
                res = llm.ask(model=self.model, **kw)
        else:
            res = llm.ask(model=self.model, **kw)
        self.cost_usd += float(getattr(res, "cost_usd", 0.0) or 0.0)
        mv = parse_tool(res)
        if mv is not None:
            mv.econ = econ
        return mv

    def decide(self, sit, ctx) -> list[Action]:
        self._ledger = getattr(ctx, "ledger", None) or self._ledger
        views = self._views(sit, ctx)
        q = self._accept_queue(views)
        bases = {v.id: self._base(v, q) for v in views}
        llm = self._llm or (getattr(ctx, "llm", None) if ctx is not None else None) or _lazy_llm()
        mode = claude_mode(ctx)
        if not self.use_llm or llm is None or mode == "code" or \
                (ctx is not None and getattr(ctx, "llm_ok", True) is False):
            why = ("duel mode is 'code'" if mode == "code" else "Claude is switched off for this tick (breaker)"
                   if (ctx is not None and getattr(ctx, "llm_ok", True) is False) else "no Claude client")
            for _, b in bases.values():
                b.reason = f"[fallback: {why}] {b.reason}"
            return self._finish(views, {k: b[1] for k, b in bases.items()}, bases)

        futures: dict[cf.Future, DuelView] = {}
        asked: dict[int, tuple] = {}
        live = {v.id for v in views}
        for k in [k for k in self._pending if k not in live]:
            self._pending.pop(k)
        for v in views:
            if not self._needs_llm(v):
                self._pending.pop(v.id, None)
                continue
            key = (len(v.rival_msgs()), v.rival_offer.key() if v.rival_offer else None)
            pend = self._pending.pop(v.id, None)
            if pend is not None and pend[1][1:] == key and (pend[0].done() or pend[1][0] >= v.tick - 1):
                # last tick's call ran past the deadline and the rival has not moved since: use its answer
                asked[v.id] = (v.tick, *key)
                futures[pend[0]] = v
                continue
            if self.max_calls is not None and self.calls >= self.max_calls:
                break
            self.calls += 1
            # _last_ask is stamped only when the call succeeds: a timed-out call is retried next tick.
            asked[v.id] = (v.tick, len(v.rival_msgs()), v.rival_offer.key() if v.rival_offer else None)
            opp, base = bases[v.id]
            futures[self._pool.submit(self._ask, llm, v, opp, base, ctx)] = v
        deadline = getattr(ctx, "deadline", None) if ctx is not None else None
        timeout = None if deadline is None else max(0.0, deadline - SAFETY_S - time.time())
        done, _ = cf.wait(futures, timeout=timeout) if futures else (set(), set())

        claude: dict[int, Move] = {}
        why: dict[int, str] = {}                    # duel -> why Claude did not decide this tick
        for f, v in futures.items():
            if f not in done:
                why[v.id] = "Claude did not answer before the tick deadline"
                self._pending[v.id] = (f, asked[v.id])      # its answer is used next tick
                continue
            try:
                mv = f.result()
            except Exception as e:      # LLMUnavailable, LLMTimeout, network: the fallback covers it
                log.warning("duel %s: claude failed: %s", v.id, e)
                why[v.id] = f"Claude failed ({type(e).__name__})"
                continue
            if mv is not None:
                claude[v.id] = mv
                self._last_ask[v.id] = asked[v.id]
                self._fails.pop(v.id, None)
            else:
                why[v.id] = "Claude gave no usable move"
        for v in views:
            if v.id not in claude:
                why.setdefault(v.id, "Claude call cap reached" if v.id not in asked and self._needs_llm(v)
                               else "not asked this tick")
                if v.id in asked:
                    self._fails[v.id] = self._fails.get(v.id, 0) + 1

        moves: dict[int, Move] = {}
        for v in views:
            opp, base = bases[v.id]
            mv = claude.get(v.id)
            if mv is not None:
                mv.lesson_ids = feedback.cited(ctx, mv.lesson_ids)
                mv, bnotes = bound_claude(v, mv, base, opp, mv.econ, mode)
                if bnotes:
                    log.info("duel %s: %s", v.id, bnotes)
                safe, notes = guard(v, mv, fallback=base)
                notes = bnotes + notes
                if safe is not base and safe.source == mv.source and not safe.lesson_ids:
                    safe.lesson_ids = list(mv.lesson_ids)
                safe, hnotes = hold_rule(v, safe, opp)
                if not hnotes:
                    safe, hnotes = hold_vs_unmoved_rival(v, safe)
                notes = notes + hnotes
                safe, rnotes = replace_losing_offer(v, safe)
                notes = notes + rnotes
                if notes:
                    self.last_notes[v.id] = notes
                    log.info("duel %s: guard %s", v.id, notes)
                mv = safe
            else:
                mv = self._without_claude(v, base, why.get(v.id, "not asked this tick"))
                mv, _ = replace_losing_offer(v, mv)
            moves[v.id] = mv
        return self._finish(views, moves, bases)

    def _without_claude(self, v: DuelView, base: Move, why: str) -> Move:
        """Claude did not decide this duel this tick. If Claude already set our line, the rival has not moved
        since and there is time, hold that line for a tick instead of conceding on the code schedule; the
        code fallback is the last resort (rival moved, deadline close, Claude failing twice in a row)."""
        last = self._last_ask.get(v.id)
        key = (len(v.rival_msgs()), v.rival_offer.key() if v.rival_offer else None)
        hold = (last is not None and last[1:] == key and v.ticks_left > 3 and base.action == "offer"
                and self._fails.get(v.id, 0) < 2 and v.our_offer is not None)
        if v.id in self._pending and v.ticks_left > 3 and base.action != "accept" \
                and self._fails.get(v.id, 0) < 2 and (v.our_offer is not None or v.our_offers()):
            return Move("wait", reason=f"[hold: {why}] its answer is used next tick instead of a blind step",
                        source="fallback")
        if hold:
            return Move("wait", reason=f"[hold: {why}] keep Claude's standing offer; the rival has not moved",
                        source="fallback")
        if base.action != "wait" and not base.reason.startswith("finish vs a silent rival"):
            base.reason = f"[fallback: {why}] {base.reason}"
        return base

    def observe(self, outcome: Outcome) -> None:
        resp = outcome.response or {}
        info = self._sent.get(outcome.action_id)
        duel = resp.get("duel") or (info[0] if info else None)
        if outcome.status == "deal" and duel is not None:
            price = (outcome.realised or {}).get("price", info[2] if info else None)
            self.memory.record_result(duel, "deal", price=price, rounds=resp.get("rounds"),
                                      days=resp.get("days"), accepted_by="us")

    def remember(self, actions: list[Action]) -> None:
        """Optional: let observe() map action ids back to duels (run.py may call it after arbitration)."""
        book = self.memory.data.setdefault("feedback", {})
        for a in actions:
            if a.domain == self.name:
                self._sent[a.id] = (a.params.get("duel"), a.kind,
                                    a.params.get("price", (a.params.get("expect") or {}).get("price")))
                if a.params.get("duel") is not None:
                    feedback.track(book, str(a.params["duel"]), a.id, a.lesson_ids)

    def observe_closed(self, duels: list[dict]) -> None:
        """Finished duels from GET /api/duels?done=true: results feed the opponent model."""
        for d in duels or []:
            if not isinstance(d, dict) or d.get("status") == "live":
                continue
            did = d.get("duel", d.get("id"))
            known = self.memory.data["duels"].get(str(did))
            seen_live = bool(known) and (known.get("status") == "live"     # this bot saw it while it ran
                                         or str(did) in (self.memory.data.get("feedback") or {}))
            if str(did) not in self.memory.data["duels"]:
                v = parse_duel({**d, "status": "live", "result": None}, int(d.get("deadline_tick") or 0))
                if v is not None:
                    self.memory.observe_duel(v)
            self.memory.record_result(did, str(d.get("status")), price=d.get("price"),
                                      rounds=d.get("rounds"), days=d.get("days"))
            if seen_live:
                self._log_closing(did, d)

    def _log_closing(self, did, d: dict) -> None:
        """One closing outcome per finished duel (idempotent across calls and restarts)."""
        reported = self.memory.data.setdefault("closings_logged", {})
        if str(did) in reported or self._ledger is None:
            return
        fb = (self.memory.data.get("feedback") or {}).get(str(did)) or {}
        status = "deal" if d.get("status") == "deal" else "no_deal"
        rec = feedback.close(self._ledger, domain=self.name, key=f"duel:{did}", status=status,
                             tick=d.get("deadline_tick") or d.get("tick") or 0,
                             action_ids=fb.get("actions") or [], lesson_ids=fb.get("lessons") or [],
                             realised={"points": d.get("result") if status == "deal" else 0.0,
                                       "price": d.get("price"), "rounds": d.get("rounds")},
                             response={**d, "duel": did})
        if rec is not None:
            reported[str(did)] = rec.get("id", True)
            self.memory.save()
