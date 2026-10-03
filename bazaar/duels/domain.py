"""DuelsDomain: Claude negotiates every live duel in parallel; code keeps it safe and keeps a fallback.

decide()   one Claude call per live duel (threads), each with the structured state, the opponent model,
           the economics table, the lessons and the rival's words wrapped as untrusted. Whatever comes
           back goes through policy.guard (limit, days, no repeats, exact price in the text).
fallback() the pure-code concession schedule (policy.plan), instant.
observe()  outcomes of our own actions; observe_closed() takes finished duels (/api/duels?done=true).
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import time
from typing import Any

from ..core.types import Action, Outcome
from .model import DuelView, parse_duel, points
from .opponent import OpponentMemory
from .policy import Move, economics, guard, plan
from .prompt import DUEL_MOVE_TOOL, parse_tool, system_blocks, user_message

log = logging.getLogger("bazaar.duels")

ACCEPT_PRIORITY = 100.0      # duel accepts outrank everything else in the team's one accept per tick
SAFETY_S = 0.25              # stop waiting for Claude this long before the tick deadline


def _lazy_llm():
    try:
        from ..llm import client
        return client
    except Exception:            # CORE-A may not have shipped it yet: code-only until it does
        return None


class DuelsDomain:
    name = "duels"

    def __init__(self, memory: OpponentMemory | None = None, llm: Any = None, model: str | None = None,
                 max_workers: int = 6, llm_every: int = 3, use_llm: bool = True,
                 max_calls: int | None = None):
        self.memory = memory or OpponentMemory()
        self._llm = llm
        self.model = model
        self.use_llm = use_llm
        self.llm_every = llm_every          # re-ask Claude at least every N ticks even if nothing moved
        self.max_calls = max_calls          # hard cap on Claude calls (tournament / tests)
        self.calls = 0
        self.cost_usd = 0.0
        self._pool = cf.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="duel")
        self._last_ask: dict[int, tuple] = {}      # duel -> (tick, rival offer count, rival offer key)
        self._sent: dict[str, tuple[int, str, Any]] = {}    # action id -> (duel, kind, price)
        self.last_notes: dict[int, list[str]] = {}

    # --- helpers -------------------------------------------------------------------------------------
    def _views(self, sit, ctx) -> list[DuelView]:
        tick = int(getattr(sit, "tick", 0) or 0)
        used = (getattr(ctx, "budget", None) or {}).get("messages", {}) if ctx is not None else {}
        out = []
        for d in getattr(sit, "duels", None) or []:
            v = parse_duel(d, tick)
            if v is None or v.ticks_left <= 0:
                continue
            if v.sent_this_tick() or used.get(str(v.id)):
                continue          # one message per conversation per tick: already spent
            out.append(v)
        return out

    def _action(self, v: DuelView, mv: Move, opp: dict) -> Action | None:
        if mv.action == "wait":
            return None
        if mv.action == "accept":
            r = v.rival_offer
            margin = v.utility(r.price, r.days)
            pts = points(margin, v.decay, v.rounds)
            urgency = 50.0 if v.ticks_left <= 2 else 0.0
            return Action(kind="duel_accept", params={"duel": v.id, "expect": self._expect(v)}, domain=self.name,
                          reason=mv.reason, big=True, priority=ACCEPT_PRIORITY + urgency + pts, source=mv.source,
                          expected={"points": round(pts, 2), "margin": round(margin, 1), "rounds": v.rounds,
                                    "price": r.price, "days": r.days, "rival_type": opp.get("type"),
                                    "pie_est": opp.get("pie_estimate")})
        params = {"duel": v.id, "price": int(mv.price), "text": mv.text}
        if v.uses_days:
            params["days"] = int(mv.days if mv.days is not None else 0)
        margin = v.utility(mv.price, mv.days)
        return Action(kind="duel_message", params=params, domain=self.name, reason=mv.reason, big=False,
                      priority=round(mv.expected_points, 2), source=mv.source,
                      expected={"points": mv.expected_points, "points_if_accepted": mv.expected_points,
                                "margin": round(margin, 1), "rounds_if_accepted": v.rounds_if_we_send(),
                                "rival_type": opp.get("type"), "pie_est": opp.get("pie_estimate")})

    @staticmethod
    def _expect(v: DuelView) -> dict:
        """The rival's standing offer exactly as the server gave it (rails compare it on a fresh read)."""
        raw = v.raw.get("rival_offer")
        return dict(raw) if isinstance(raw, dict) else v.rival_offer.as_expect()

    def _base(self, v: DuelView) -> tuple[dict, Move]:
        opp = self.memory.assess(v)
        mv = plan(v, opp)
        mv, notes = guard(v, mv)
        mv.source = "fallback"
        self.last_notes[v.id] = notes
        return opp, mv

    def _finish(self, actions: list[Action]) -> list[Action]:
        self.memory.save()
        return actions

    # --- Domain protocol -----------------------------------------------------------------------------
    def fallback(self, sit, ctx) -> list[Action]:
        actions = []
        for v in self._views(sit, ctx):
            opp, mv = self._base(v)
            a = self._action(v, mv, opp)
            if a:
                actions.append(a)
        return self._finish(actions)

    def _needs_llm(self, v: DuelView) -> bool:
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
        res = llm.ask(purpose="duels", system=system_blocks(ctx),
                      messages=[{"role": "user", "content": user_message(v, opp, econ, base)}],
                      tools=[DUEL_MOVE_TOOL], tool_choice={"type": "auto"}, model=self.model,
                      max_tokens=2000, deadline=(deadline - SAFETY_S) if deadline else None)
        self.cost_usd += float(getattr(res, "cost_usd", 0.0) or 0.0)
        mv = parse_tool(res)
        if mv is not None:
            mv.econ = econ
        return mv

    def decide(self, sit, ctx) -> list[Action]:
        views = self._views(sit, ctx)
        bases = {v.id: self._base(v) for v in views}
        llm = self._llm or (getattr(ctx, "llm", None) if ctx is not None else None) or _lazy_llm()
        if not self.use_llm or llm is None or (ctx is not None and getattr(ctx, "llm_ok", True) is False):
            return self._finish([a for v in views if (a := self._action(v, bases[v.id][1], bases[v.id][0]))])

        futures: dict[cf.Future, DuelView] = {}
        for v in views:
            if not self._needs_llm(v):
                continue
            if self.max_calls is not None and self.calls >= self.max_calls:
                break
            self.calls += 1
            self._last_ask[v.id] = (v.tick, len(v.rival_msgs()), v.rival_offer.key() if v.rival_offer else None)
            opp, base = bases[v.id]
            futures[self._pool.submit(self._ask, llm, v, opp, base, ctx)] = v
        deadline = getattr(ctx, "deadline", None) if ctx is not None else None
        timeout = None if deadline is None else max(0.0, deadline - SAFETY_S - time.time())
        done, _ = cf.wait(futures, timeout=timeout) if futures else (set(), set())

        claude: dict[int, Move] = {}
        for f in done:
            v = futures[f]
            try:
                mv = f.result()
            except Exception as e:      # LLMUnavailable, LLMTimeout, network: the fallback covers it
                log.warning("duel %s: claude failed: %s", v.id, e)
                continue
            if mv is not None:
                claude[v.id] = mv

        actions = []
        for v in views:
            opp, base = bases[v.id]
            mv = claude.get(v.id)
            if mv is not None:
                safe, notes = guard(v, mv, fallback=base)
                if notes:
                    self.last_notes[v.id] = notes
                    log.info("duel %s: guard %s", v.id, notes)
                mv = safe
            else:
                mv = base
            a = self._action(v, mv, opp)
            if a:
                actions.append(a)
        return self._finish(actions)

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
        for a in actions:
            if a.domain == self.name:
                self._sent[a.id] = (a.params.get("duel"), a.kind,
                                    a.params.get("price", (a.params.get("expect") or {}).get("price")))

    def observe_closed(self, duels: list[dict]) -> None:
        """Finished duels from GET /api/duels?done=true: results feed the opponent model."""
        for d in duels or []:
            if not isinstance(d, dict) or d.get("status") == "live":
                continue
            did = d.get("duel", d.get("id"))
            if str(did) not in self.memory.data["duels"]:
                v = parse_duel({**d, "status": "live", "result": None}, int(d.get("deadline_tick") or 0))
                if v is not None:
                    self.memory.observe_duel(v)
            self.memory.record_result(did, str(d.get("status")), price=d.get("price"),
                                      rounds=d.get("rounds"), days=d.get("days"))
