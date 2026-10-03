"""The main loop: one perceive -> decide -> review -> select -> rails -> execute pass per tick.

    python -m bazaar.run --sim           # against the simulated Bazaar on config.SIM_PORT, real writes there
    python -m bazaar.run --live          # the real game: writes only with BAZAAR_ALLOW_REAL=1 AND control armed
    python -m bazaar.run --live --once   # a single tick, then exit

Without the write conditions it is a dry run: it decides, checks the rails and logs, but sends nothing.
Touch bazaar/STOP to stop every write at once (decisions keep being logged).

Each tick:
  1. wait for a new tick (poll /api/clock using next_tick_in; while the doors are closed or the game
     is paused, only record the public feed every WAIT_POLL_S)
  2. perceive (core.state), build the TickContext (core.context)
  3. every registered domain decides in its own thread until ctx.deadline (55 % of the tick);
     a late or crashing domain contributes its fallback() instead
  4. big actions go through brain.council while time remains (until COUNCIL_SHARE of the tick)
  5. arbiter.select -> rails.check -> executor.execute -> domain.observe(outcome), all to the ledger
  6. outcome tracking (score delta attributed to recent actions) and circuit breakers
  7. data/live/status.json and tick_latest.json for the dashboard

Control (data/live/control.json, written by the dashboard through api/server.py):
  {"armed": false, "mode": "auto", "caps": {}, "protected": [], "paused_domains": []}
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import importlib
import inspect
import json
import logging
import math
import os
import sys
import time
import traceback
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from . import config
from .core.context import Budget, TickContext, ValueCache, _cash_out
from .core.state import Situation, perceive
from .core.types import ACCEPT_KINDS, Action, Outcome, Verdict

log = logging.getLogger("bazaar.run")

DOMAINS = [("duels", "bazaar.duels.domain", "DuelsDomain"),
           ("dealers", "bazaar.dealers.domain", "DealersDomain"),
           ("market", "bazaar.market.domain", "MarketDomain")]
DEFAULT_CONTROL = {"armed": False, "mode": "auto", "caps": {}, "protected": [], "paused_domains": []}
WAIT_POLL_S = 30.0               # doors closed / paused: record the feed this often
COUNCIL_SHARE = 0.70             # the council may run until this share of the tick
SEND_CUTOFF = 0.90               # no non-accept writes after this share of the tick
COUNCIL_MIN_S = 4.0              # ...and only if at least this many seconds remain
DROP_PCT = 0.05                  # breaker: score or portfolio down 5 % ...
DROP_WINDOW = 10                 # ...within 10 ticks -> cautious (no buys) for CAUTIOUS_TICKS
VENUE_BOND = 250
CAUTIOUS_TICKS = 10
REFUSALS_TO_PAUSE = 3            # consecutive refusals of one domain -> pause it PAUSE_TICKS
NEVER_PAUSE = {"duels", "packs", "broker"}         # a 10-tick pause is most of a 16-tick duel: duels are never paused
TRANSIENT_CODES = {"wait_for_tick", "rate_limited", "too_early", "duel_closed", "not_live", "closed",
                   "expired", "offer_gone", "thread_closed", "too_many_requests"}
PAUSE_TICKS = 10
INJECTION_FLOOD = 4              # flagged texts from others in one tick -> code-only for FLOOD_TICKS
FLOOD_TICKS = 5
ATTRIBUTE_TICKS = 3              # score deltas go to actions sent in the last N ticks
STUCK_TICKS = 3                  # a domain's decide() still busy after this many ticks -> exit, supervisor restarts
STUCK_EXIT_CODE = 3
GATEWAY_RETRY_S = 3.0            # clock read failed: write a gateway_down heartbeat and retry this often


# --------------------------------------------------------------------------- small helpers

def _write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str, indent=1))
    tmp.replace(path)


def load_control(live: Path, defaults: dict | None = None) -> dict:
    base = dict(defaults or DEFAULT_CONTROL)
    try:
        data = json.loads((live / "control.json").read_text())
        if isinstance(data, dict):
            base.update(data)
    except (OSError, ValueError):
        pass
    caps = base.get("caps")
    if isinstance(caps, dict):                                 # the dashboard stores caps nested; rails read them flat
        for k, v in caps.items():
            if k != "caps":
                base[k] = v
    return base


_ALIASES = {"action": ("action", "a"), "gw": ("gw", "gateway", "client"), "sit": ("sit", "situation"),
            "ctx": ("ctx", "context"), "ledger": ("ledger",), "budget": ("budget",), "actions": ("actions", "candidates"),
            "dry_run": ("dry_run",)}


def call_flex(fn: Callable, **avail):
    """Call fn binding its parameters by name (with aliases), so small signature drifts don't break us."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(*avail.values())
    kwargs, args = {}, []
    lookup = {alias: key for key, names in _ALIASES.items() for alias in names}
    for name, p in params.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        key = lookup.get(name, name)
        if key in avail:
            if p.kind == p.POSITIONAL_ONLY:
                args.append(avail[key])
            else:
                kwargs[name] = avail[key]
        elif p.default is p.empty:
            raise TypeError(f"{getattr(fn, '__name__', fn)} needs {name!r}")
    return fn(*args, **kwargs)


def _import(name: str):
    try:
        return importlib.import_module(name)
    except ImportError as e:
        log.warning("module %s not available: %s", name, e)
        return None


def load_domains(only: list[str] | None = None, gw=None) -> list:
    out = []
    for name, mod, cls in DOMAINS:
        if only and name not in only:
            continue
        m = _import(mod)
        if m is not None and hasattr(m, cls):
            try:
                try:
                    out.append(getattr(m, cls)(gw=gw))           # read-only gateway: catalog, values, books
                except TypeError:
                    out.append(getattr(m, cls)())
            except Exception as e:  # noqa: BLE001
                log.error("domain %s failed to start: %s", name, e)
    return out


def _own_venue(sit: Situation) -> str | None:
    try:
        from .core.rails import own_venue
        return own_venue(sit)
    except Exception:  # noqa: BLE001
        return None


ANNOUNCE_EVERY_H = 1.0           # broker_announce for our venue: once on opening, then every game hour


def _urgent_duel_accept(a: Action, sit: Situation) -> bool:
    """A duel accept with <= 3 ticks left skips the council: a veto there means the duel scores 0."""
    if a.kind != "duel_accept":
        return False
    d = next((d for d in (sit.duels or []) if str(d.get("duel")) == str((a.params or {}).get("duel"))), None)
    dl = (d or {}).get("deadline_tick")
    return dl is not None and dl - sit.tick <= 3


def _is_buy(a: Action) -> bool:
    if a.domain == "duels":
        return False
    if _cash_out(a) > 0:
        return True
    p = a.params or {}
    topic = p.get("topic") or {}
    return a.kind == "open_thread" and isinstance(topic, dict) and "buy" in topic


def _is_team(who) -> bool:
    try:
        from .core.rails import is_team
        return is_team(who)
    except Exception:  # noqa: BLE001
        return False


def _texts_from_others(sit: Situation) -> list[str]:
    """Texts that reach our prompts this tick, one per counterparty. Team threads are closed unread (no prompt
    sees them), so a rival flooding them cannot push us into code-only mode."""
    me = (sit.me or {}).get("id")
    out, seen = [], set()
    for t in sit.threads:
        if _is_team(t.get("with")):
            continue
        for m in t.get("messages") or []:
            if m.get("tick") == sit.tick and m.get("sender") != me and m.get("sender") not in seen:
                seen.add(m.get("sender"))
                out.append(m.get("text") or "")
    for d in sit.duels:
        for m in d.get("messages") or []:
            if m.get("tick") == sit.tick and m.get("from") != "you":
                out.append(m.get("text") or "")
    return out


def _fallback_select(actions: list[Action]) -> list[Action]:
    """Used only while core/arbiter.py is missing: domain rank, then priority, one accept."""
    rank = {"duels": 0, "market": 1, "broker": 1, "dealers": 2, "lab": 3}
    out, accepted = [], False
    for a in sorted(actions, key=lambda a: (rank.get(a.domain, 9), -a.priority)):
        if a.kind in ACCEPT_KINDS and a.kind != "duel_accept":   # duel accepts have their own limit
            if accepted:
                continue
            accepted = True
        out.append(a)
    return out


# --------------------------------------------------------------------------- the runner

class Runner:
    def __init__(self, gw, *, domains: list, mode: str = "live", live: Path | None = None,
                 make_write_gw: Callable[[], Any] | None = None, ledger=None, lessons=None, llm=None,
                 rails=None, executor=None, arbiter=None, council=None, control_defaults: dict | None = None,
                 clock_fn: Callable[[], float] = time.time):
        self.gw = gw
        self.closed_team_threads: set = set()
        self.last_packs: set = set()
        self.pack_backoff: dict = {}
        self.last_announce = -99.0
        self.domains = domains
        self.mode = mode                         # "sim" | "live"
        self.live = Path(live or config.LIVE)
        self.live.mkdir(parents=True, exist_ok=True)
        self.make_write_gw = make_write_gw
        self._write_gw = None
        self.ledger = ledger
        self.lessons = lessons
        self.llm = llm
        self.rails, self.executor, self.arbiter, self.council = rails, executor, arbiter, council
        self.control_defaults = control_defaults or DEFAULT_CONTROL
        self.now = clock_fn
        self.budget = Budget(self.live / "budget.json")
        self.values = ValueCache(gw)
        self.pools = {d.name: cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"dom-{d.name}")
                      for d in domains}
        self.running: dict[str, cf.Future] = {}
        self.prev: Situation | None = None
        self.last_tick: int | None = None
        self.history: deque = deque(maxlen=DROP_WINDOW + 1)   # (tick, score, portfolio)
        self.refusals: dict[str, int] = {}
        self.paused_until: dict[str, int] = {}
        self.cautious_until = -1
        self.flood_until = -1
        self.recent: deque = deque(maxlen=200)                 # (tick, action, status)
        self.errors: deque = deque(maxlen=20)
        self.dom_status: dict[str, dict] = {d.name: {"state": "idle"} for d in domains}
        self.last_report: dict = {}
        self.submitted_tick: dict[str, int] = {}               # domain -> tick its running decide() was submitted
        self.exit_fn: Callable[[int], Any] = os._exit           # stuck threads would block a normal exit

    # ----- plumbing -----
    def _err(self, where: str, e: BaseException | str):
        row = {"at": self.now(), "where": where, "error": str(e)[:300],
               "code": getattr(e, "code", type(e).__name__ if isinstance(e, BaseException) else "")}
        self.errors.append(row)
        log.warning("%s: %s", where, row["error"])

    def _ledger(self, kind: str, *args, **kw):
        if self.ledger is None:
            return
        try:
            if kind == "append":
                self.ledger.append(*args, **kw)
            else:
                getattr(self.ledger, kind)(*args, **kw)
        except Exception as e:  # noqa: BLE001
            self._err("ledger", e)

    def control(self) -> dict:
        ctl = load_control(self.live, self.control_defaults)
        try:                                    # the strategist's cash policy/pauses sit under the operator's
            from bazaar.brain.strategy import overlay
            return overlay(ctl, self.live)
        except Exception:  # noqa: BLE001
            return ctl

    def can_write(self, control: dict) -> bool:
        if config.STOP_FILE.exists() or not control.get("armed") or self.executor is None:
            return False
        if self.mode == "sim":
            return True
        return config.ALLOW_REAL

    def write_gw(self):
        if self._write_gw is None and self.make_write_gw is not None:
            self._write_gw = self.make_write_gw()
        return self._write_gw

    # ----- one tick -----
    def build_ctx(self, sit: Situation, control: dict) -> TickContext:
        self.values.refresh(sit.me)
        sit.values = self.values.values
        return TickContext(value=self.values, tick=sit.tick, day=sit.day, deadline=sit.deadline, lessons=self.lessons, llm=self.llm,
                           ledger=self.ledger, budget=self.budget.for_tick(sit.tick, sit.limits, self.now()),
                           control=control, tick_seconds=sit.tick_seconds, tick_start=sit.tick_start,
                           cautious=sit.tick <= self.cautious_until, llm_ok=sit.tick > self.flood_until)

    def active_domains(self, sit: Situation, control: dict) -> list:
        paused = set(control.get("paused_domains") or [])
        out = []
        for d in self.domains:
            st = self.dom_status.setdefault(d.name, {})
            if d.name in paused:
                st.update(state="paused_by_operator")
            elif self.paused_until.get(d.name, -1) >= sit.tick:
                st.update(state="paused_refusals", until=self.paused_until[d.name])
            else:
                out.append(d)
        return out

    def collect(self, sit: Situation, ctx: TickContext, domains: list) -> list[Action]:
        futs = {}
        for d in domains:
            st = self.dom_status.setdefault(d.name, {})
            busy = self.running.get(d.name)
            if busy is not None and not busy.done():
                since = self.submitted_tick.get(d.name, sit.tick)
                if sit.tick - since >= STUCK_TICKS:
                    self.stuck(d.name, since, sit, ctx)
                continue                                      # still thinking since an earlier tick
            if not ctx.llm_ok:
                continue                                      # code only
            futs[d.name] = self.running[d.name] = self.pools[d.name].submit(d.decide, sit, ctx)
            self.submitted_tick[d.name] = sit.tick
        if futs:
            cf.wait(list(futs.values()), timeout=max(0.0, ctx.deadline - self.now()))
        actions: list[Action] = []
        for d in domains:
            st = self.dom_status[d.name]
            f = futs.get(d.name)
            src = "decide"
            got = None
            if f is not None and f.done():
                try:
                    got = list(f.result() or [])
                except Exception as e:  # noqa: BLE001
                    self._err(f"{d.name}.decide", e)
                    log.debug("decide crashed", exc_info=True)
            if got is None:
                src = "fallback" if f is None or f.done() else "late"
                try:
                    got = [replace(a, source="fallback") if a.source != "fallback" else a
                           for a in (d.fallback(sit, ctx) or [])]
                except Exception as e:  # noqa: BLE001
                    self._err(f"{d.name}.fallback", e)
                    got = []
            for a in got:
                a.domain = a.domain or d.name
            st.update(state="ok", last_source=src, actions=len(got), tick=sit.tick)
            actions.extend(got)
        return actions

    def stuck(self, name: str, since: int, sit: Situation, ctx: TickContext):
        """decide() has been busy for STUCK_TICKS ticks: its thread cannot be killed, so mark the domain stuck,
        write status.json and exit non-zero; the supervisor starts a fresh process."""
        st = self.dom_status.setdefault(name, {})
        st.update(state="stuck", since_tick=since, tick=sit.tick)
        msg = f"{name}.decide busy since tick {since} ({sit.tick - since} ticks): exiting so the supervisor restarts us"
        self._err("stuck", msg)
        log.error(msg)
        try:
            self.write_status(sit, ctx.control, False, ctx, state="stuck")
        except Exception:  # noqa: BLE001
            pass
        sys.stdout.flush()
        sys.stderr.flush()
        self.exit_fn(STUCK_EXIT_CODE)

    def review_big(self, actions: list[Action], sit: Situation, ctx: TickContext) -> list[Action]:
        council = self.council
        if not ctx.llm_ok:
            # No council while the LLM is off: big non-duel buys and accepts wait instead of going unreviewed.
            keep = [a for a in actions if not a.big or a.kind == "duel_accept"]
            for a in actions:
                if a not in keep:
                    self._ledger("decision", a, Verdict(False, "council", "LLM off: big action held"),
                                 tick=sit.tick, dry_run=not self.can_write(ctx.control or {}))
                    self._observe(a, Outcome(a.id, sit.tick, "vetoed",
                                             {"rail": "council", "detail": "LLM off: big action held, no council"}))
            return keep
        if council is None:
            return actions
        cdead = sit.tick_start + COUNCIL_SHARE * sit.tick_seconds
        out = []
        for a in actions:
            if not a.big or cdead - self.now() < COUNCIL_MIN_S or _urgent_duel_accept(a, sit):
                out.append(a)
                continue
            try:
                r = council(a, sit, ctx.with_deadline(cdead))
            except Exception as e:  # noqa: BLE001
                self._err("council", e)
                r = a
            if r is None:
                why = (getattr(sys.modules.get("bazaar.brain.council"), "LAST_WHY", {}) or {}).get(a.id, "")
                self._ledger("decision", a, Verdict(False, "council", ("vetoed by the council: " + why)[:400]
                                                    if why else "vetoed by the council"),
                             tick=sit.tick, dry_run=False)
                self._observe(a, Outcome(a.id, sit.tick, "vetoed",
                                         {"by": "council", "why": why, "rail": "council",
                                          "detail": why or "vetoed by the council (no reason recorded)"}))
                alt = None
                if self.arbiter is not None and hasattr(self.arbiter, "alternative"):
                    try:
                        alt = self.arbiter.alternative(a)       # a vetoed duel accept still answers the rival
                    except Exception:  # noqa: BLE001
                        alt = None
                if alt is not None:
                    out.append(alt)
            else:
                out.append(r)
        return out

    def select(self, actions: list[Action], sit: Situation, ctx: TickContext) -> list[Action]:
        # The tick's single accept must go to an accept the rails will let through, not to one they veto.
        if self.rails is not None:
            kept = []
            for a in actions:
                if a.kind in ("accept_offer", "duel_accept"):
                    try:
                        v = self.rails.check(a, sit, ctx)
                    except Exception as e:  # noqa: BLE001
                        v = Verdict(False, "rails_error", str(e)[:200])
                    if not v.ok:
                        dry = not self.can_write(ctx.control or {})
                        self._ledger("decision", a, v, source=a.source, tick=sit.tick, dry_run=dry)
                        if not dry:
                            self._observe(a, Outcome(a.id, sit.tick, "vetoed", {"rail": v.rail, "detail": v.detail}))
                        alt = None
                        if self.arbiter is not None and hasattr(self.arbiter, "alternative"):
                            try:
                                alt = self.arbiter.alternative(a)   # a vetoed duel accept still answers the rival
                            except Exception:  # noqa: BLE001
                                alt = None
                        if alt is not None:
                            kept.append(alt)
                        continue
                kept.append(a)
            actions = kept
        if self.arbiter is None:
            return _fallback_select(actions)
        try:
            got = call_flex(self.arbiter.select, actions=actions, sit=sit, ctx=ctx, budget=ctx.budget)
        except Exception as e:  # noqa: BLE001
            self._err("arbiter", e)
            return _fallback_select(actions)
        if isinstance(got, tuple) and len(got) == 2:         # core.arbiter: (chosen, [(action, why)])
            chosen, dropped = got
            for a, why in dropped or []:
                if a.kind != "noop":
                    self._ledger("decision", a, Verdict(False, "arbiter", str(why)), tick=sit.tick,
                                 dry_run=False)
                    if a.kind == "accept_offer":         # the domain (and the brain) learn why it did not go
                        self._observe(a, Outcome(a.id, sit.tick, "vetoed", {"rail": "arbiter", "detail": str(why)}))
            return list(chosen or [])
        return list(got or [])

    def _observe(self, a: Action, outcome: Outcome):
        for d in self.domains:
            if d.name == a.domain:
                try:
                    d.observe(outcome)
                except Exception as e:  # noqa: BLE001
                    self._err(f"{d.name}.observe", e)

    def act(self, actions: list[Action], sit: Situation, ctx: TickContext, write: bool) -> list[dict]:
        report = []
        # Accepts first (one per tick, the most valuable), then the rest; nothing but accepts after 90 % of the tick,
        # so writes never spill into the next tick (wait_for_tick).
        actions = sorted(actions, key=lambda a: a.kind not in ("accept_offer", "duel_accept"))
        cutoff = (sit.tick_start + SEND_CUTOFF * sit.tick_seconds) if sit.tick_start and sit.tick_seconds else None
        for a in actions:
            t0 = self.now()
            if (write and cutoff and t0 > cutoff and a.kind not in ("accept_offer", "duel_accept")
                    and a.kind != "noop"):
                self._ledger("decision", a, Verdict(False, "late", "past the send cutoff of this tick"),
                             source=a.source, tick=sit.tick, dry_run=False)
                report.append({"id": a.id, "domain": a.domain, "kind": a.kind, "params": a.params, "source": a.source,
                               "reason": a.reason, "verdict": {"ok": False, "rail": "late", "detail": "send cutoff"},
                               "status": "skipped_late"})
                continue
            if self.rails is not None:
                try:
                    verdict = self.rails.check(a, sit, ctx)
                except Exception as e:  # noqa: BLE001 - a crashing rail is a veto
                    self._err("rails", e)
                    verdict = Verdict(False, "rails_error", str(e)[:200])
            else:
                verdict = Verdict(False, "rails_missing", "core/rails.py not importable")
            from_executor = False                              # the executor logs the outcomes of what it runs
            if not verdict.ok:
                outcome = Outcome(a.id, sit.tick, "vetoed", {"rail": verdict.rail, "detail": verdict.detail})
            elif not write:
                outcome = None
            else:
                try:
                    outcome = call_flex(self.executor.execute, action=a, gw=self.write_gw(), sit=sit, ctx=ctx,
                                        ledger=self.ledger)
                    if not isinstance(outcome, Outcome):
                        outcome = Outcome(a.id, sit.tick, "sent", outcome if isinstance(outcome, dict) else {})
                    else:
                        from_executor = True
                except Exception as e:  # noqa: BLE001
                    self._err("executor", e)
                    outcome = Outcome(a.id, sit.tick, "error", {"error": getattr(e, "code", type(e).__name__),
                                                                "message": str(e)[:200]})
            self._ledger("decision", a, verdict, source=a.source, latency_s=round(self.now() - t0, 3),
                         tick=sit.tick, dry_run=not write)
            status = outcome.status if outcome else "dry_run"
            if outcome is not None:
                if not from_executor:
                    self._ledger("outcome", outcome, a)
                self._observe(a, outcome)
                self.budget.record(a, outcome.status, self.now())
                ctx.budget = self.budget.for_tick(sit.tick, sit.limits, self.now())   # rails see it at once
                self._count_refusal(a.domain, outcome.status, sit.tick, (outcome.response or {}).get("error"))
                if outcome.status in ("sent", "deal"):
                    self.recent.append((sit.tick, a, outcome.status))
                    if a.kind == "broker_announce":
                        self.last_announce = sit.t_hours or 0
                elif a.kind == "broker_announce":               # the game allows one per venue every 20 ticks
                    self.announce_retry_tick = sit.tick + 20
                elif a.kind == "open_pack":
                    self.pack_backoff[(a.params or {}).get("asset")] = sit.tick + 20
            report.append({"id": a.id, "domain": a.domain, "kind": a.kind, "params": a.params, "source": a.source,
                           "reason": a.reason, "verdict": {"ok": verdict.ok, "rail": verdict.rail,
                                                           "detail": verdict.detail}, "status": status})
        return report

    def _count_refusal(self, domain: str, status: str, tick: int, code: str | None = None):
        if status == "refused" and (domain in NEVER_PAUSE or code in TRANSIENT_CODES):
            return                                             # timing noise, not a broken strategy
        if status == "refused":
            self.refusals[domain] = self.refusals.get(domain, 0) + 1
            if self.refusals[domain] >= REFUSALS_TO_PAUSE:
                self.paused_until[domain] = tick + PAUSE_TICKS
                self.refusals[domain] = 0
                self._err("breaker", f"{domain} paused {PAUSE_TICKS} ticks after {REFUSALS_TO_PAUSE} refusals")
        elif status in ("sent", "deal"):
            self.refusals[domain] = 0

    def breakers(self, sit: Situation):
        me = sit.me or {}
        # The venue bond (250 P) is refundable: count it, or opening our venue would trip the breaker.
        portfolio = (float(me.get("cash") or 0) + float(me.get("collection_value") or 0)
                     + (VENUE_BOND if _own_venue(sit) else 0))
        if self.history and self.history[-1][0] == sit.tick:
            self.history.pop()
        packs = {a.get("id") for a in me.get("assets") or [] if a.get("kind") == "pack"}
        if packs != self.last_packs:                       # opening a pack revalues the collection: new baseline
            self.history.clear()
        self.last_packs = packs
        self.history.append((sit.tick, sit.score, portfolio))
        window = [h for h in self.history if sit.tick - h[0] <= DROP_WINDOW]
        for i, label in ((2, "portfolio"),):                  # score is relative to the leader: not a loss signal
            top = max(h[i] for h in window)
            if top > 0 and window[-1][i] < top * (1 - DROP_PCT) and sit.tick > self.cautious_until:
                self.cautious_until = sit.tick + CAUTIOUS_TICKS
                self._err("breaker", f"{label} fell from {top:.1f} to {window[-1][i]:.1f}: cautious mode")
                last = self.history[-1]
                self.history.clear()                  # measure the next drop from here
                self.history.append(last)
                break
        flagged = 0
        try:
            from .core.untrusted import scan
            flagged = sum(1 for t in _texts_from_others(sit) if scan(t))
        except ImportError:
            pass
        if flagged >= INJECTION_FLOOD:
            self.flood_until = sit.tick + FLOOD_TICKS
            self._err("breaker", f"injection flood ({flagged} texts): code only for {FLOOD_TICKS} ticks")

    def track_outcomes(self, sit: Situation):
        """Attribute the score change since the last tick to the actions sent in the last few ticks."""
        prev = self.prev
        if prev is None or prev.tick == sit.tick:
            return
        d_score = round(sit.score - prev.score, 4)
        d_cash = sit.cash - prev.cash
        recent = [(t, a, s) for t, a, s in self.recent if sit.tick - t <= ATTRIBUTE_TICKS]
        if not recent and not d_score and not d_cash:
            return
        expected = sum(float((a.expected or {}).get("points") or 0) for _, a, _ in recent)
        self._ledger("append", "attribution", {
            "tick": sit.tick, "score": sit.score, "score_delta": d_score, "cash_delta": d_cash,
            "expected_points": round(expected, 3),
            "actions": [{"id": a.id, "tick": t, "domain": a.domain, "kind": a.kind, "status": s,
                         "expected": a.expected} for t, a, s in recent]})

    def scheduled_actions(self, sit: Situation, ctx: TickContext) -> list[Action]:
        """Code-driven actions outside the domains: open our venue at hour 4.05; feed finished duels to memory."""
        out: list[Action] = []
        try:
            from bazaar.broker import venue
            if venue.should_open(sit):
                out.append(venue.open_action(sit))
        except Exception as e:  # noqa: BLE001
            self._err("venue.should_open", e)
        for t in sit.threads or []:
            tid = t.get("id") or t.get("thread")
            if (tid is not None and _is_team(t.get("with")) and (t.get("status") or "open") == "open"
                    and tid not in self.closed_team_threads):
                if self.can_write(ctx.control if ctx is not None else self.control()):
                    self.closed_team_threads.add(tid)
                who = t.get("team") if t.get("team") not in (None, (sit.me or {}).get("id")) else t.get("with")
                out.append(Action(kind="close_thread", params={"thread": tid}, domain="market", source="code",
                                  reason=f"Close the thread {who} opened with us: it holds one of our 6 "
                                         "thread slots and the bot trades with teams through offers."))
        vid = _own_venue(sit)
        if (vid and (sit.t_hours or 0) - self.last_announce >= ANNOUNCE_EVERY_H
                and sit.tick >= getattr(self, "announce_retry_tick", -1)):
            try:
                from bazaar.market.protocol import broker_pitch
                text = broker_pitch(vid)
            except Exception:  # noqa: BLE001
                text = None
            if text:
                out.append(Action(kind="broker_announce", params={"text": text}, domain="broker", source="code",
                                  reason="Invite other teams' bids and swaps to our fee-0 venue: their trades score for us."))
        packs = [x for x in (sit.me or {}).get("assets") or [] if x.get("kind") == "pack"
                 and sit.tick >= self.pack_backoff.get(x.get("id"), -1)]
        if packs:                                               # cards in the album and tradeable; one pack per tick
            out.append(Action(kind="open_pack", params={"asset": packs[0]["id"]}, domain="packs", source="code",
                              reason=f"Open {packs[0].get('ref', 'pack')}: its cards count in the album and can be traded."))
        if sit.tick % 5 == 0:
            duels = next((d for d in self.domains if getattr(d, "name", "") == "duels"), None)
            if duels is not None and hasattr(duels, "observe_closed"):
                try:
                    done = self.gw.get("/api/duels", done="true")
                    duels.observe_closed((done or {}).get("duels") or [])
                except Exception as e:  # noqa: BLE001
                    self._err("duels.observe_closed", e)
        return out

    def step(self, sit: Situation) -> dict:
        """One full tick on an already perceived situation."""
        control = self.control()
        write = self.can_write(control)
        self.breakers(sit)
        self.track_outcomes(sit)
        ctx = self.build_ctx(sit, control)
        domains = self.active_domains(sit, control)
        actions = self.collect(sit, ctx, domains)
        actions.extend(self.scheduled_actions(sit, ctx))
        if ctx.cautious:
            dropped = [a for a in actions if _is_buy(a)]
            actions = [a for a in actions if not _is_buy(a)]
            for a in dropped:
                self._ledger("decision", a, Verdict(False, "breaker_cautious", "no buys in cautious mode"),
                             tick=sit.tick, dry_run=not write)
        if control.get("mode") == "observe":
            actions = []
        actions = self.review_big(actions, sit, ctx)
        selected = self.select(actions, sit, ctx)
        for d in domains:
            if hasattr(d, "remember"):
                try:
                    d.remember(selected)
                except Exception as e:  # noqa: BLE001
                    self._err(f"{d.name}.remember", e)
        report = self.act(selected, sit, ctx, write)
        try:
            self.budget.save()
        except OSError as e:
            self._err("budget", e)
        self.prev = sit
        self.last_tick = sit.tick
        self.last_report = {"tick": sit.tick, "at": self.now(), "write": write, "considered": len(actions),
                            "actions": report}
        self.write_status(sit, control, write, ctx)
        return self.last_report

    # ----- dashboard files -----
    def write_status(self, sit: Situation | None, control: dict, write: bool, ctx: TickContext | None = None,
                     state: str = "running"):
        spend = {}
        if self.llm is not None and hasattr(self.llm, "spend_today"):
            try:
                spend = self.llm.spend_today()
            except Exception as e:  # noqa: BLE001
                spend = {"error": str(e)[:100]}
        tick = sit.tick if sit else None
        status = {
            "updated": self.now(), "state": "stopped" if config.STOP_FILE.exists() else state,
            "mode": self.mode, "armed": bool(control.get("armed")), "write": write,
            "allow_real": config.ALLOW_REAL, "control": control, "tick": tick,
            "doors": sit.doors if sit else None, "paused": sit.paused if sit else None,
            "tick_seconds": sit.tick_seconds if sit else None, "t_hours": sit.t_hours if sit else None,
            "day": sit.day if sit else None,
            "cash": sit.cash if sit else None, "score": sit.score if sit else None,
            "domains": self.dom_status, "last_errors": list(self.errors)[-10:], "spend": spend,
            "budget": ctx.budget if ctx else {},
            "breakers": {"cautious_until": self.cautious_until, "flood_until": self.flood_until,
                         "paused_until": self.paused_until, "refusals": self.refusals,
                         "cautious": bool(sit and sit.tick <= self.cautious_until)},
            "perceive": {"requests": sit.requests, "errors": sit.errors} if sit else {},
        }
        try:
            _write_json(self.live / "status.json", status)
            if sit is not None and state == "running":
                _write_json(self.live / "tick_latest.json", {
                    **self.last_report, "deadline": sit.deadline, "tick_start": sit.tick_start,
                    "cash": sit.cash, "score": sit.score, "novelty": sit.novelty,
                    "duels": sit.duels, "threads": [{k: t.get(k) for k in ("id", "with", "status", "topic")}
                                                    for t in sit.threads],
                    "my_offers": len(sit.my_offers), "feed_new": len(sit.feed_new)})
                exact: dict = {}                    # /api/me/value answers the domains hold, for the dashboard
                for d in self.domains:
                    for ref, ex in (getattr(d, "_exact", None) or {}).items():
                        if isinstance(ex, dict) and ex.get("at", 0) >= (exact.get(ref) or {}).get("at", 0):
                            exact[ref] = ex
                if exact:
                    try:                            # keep what earlier runs learned (a restart empties the caches)
                        old = json.loads((self.live / "exact_values.json").read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        old = {}
                    for ref, ex in (old or {}).items():
                        if isinstance(ex, dict) and ex.get("at", 0) > (exact.get(ref) or {}).get("at", 0):
                            exact[ref] = ex
                    _write_json(self.live / "exact_values.json", exact)
        except OSError as e:
            self._err("status", e)

    # ----- the loop -----
    def wait_for_tick(self) -> tuple[dict | None, bool]:
        """Returns (clock, open). Sleeps until a new tick or, while closed, for WAIT_POLL_S."""
        while True:
            try:
                clock = self.gw.get("/api/clock")
                if not isinstance(clock, dict):
                    raise ValueError(f"clock is {type(clock).__name__}")
            except Exception as e:  # noqa: BLE001
                self._err("clock", e)
                try:                                          # keep the heartbeat fresh: waiting, not hung
                    c = self.control()
                    self.write_status(self.prev, c, self.can_write(c), state="gateway_down")
                except Exception as e2:  # noqa: BLE001
                    self._err("status", e2)
                time.sleep(GATEWAY_RETRY_S)
                continue
            if clock.get("paused") or clock.get("doors") != "open":
                return clock, False
            if clock.get("tick") != self.last_tick:
                return clock, True
            try:
                nti = float(clock.get("next_tick_in"))
                if not math.isfinite(nti):
                    raise ValueError
            except (TypeError, ValueError):
                nti = 1.0
            time.sleep(min(5.0, max(0.2, nti + 0.15)))

    def loop(self, once: bool = False):
        last_record = 0.0
        while True:
            clock, is_open = self.wait_for_tick()
            control = self.control()
            if not is_open:
                if time.time() - last_record >= WAIT_POLL_S or self.prev is None:
                    try:
                        self.prev = perceive(self.gw, self.prev, live=self.live, clock=clock)
                    except Exception as e:  # noqa: BLE001
                        self._err("perceive", e)
                    last_record = time.time()
                self.write_status(self.prev, control, self.can_write(control), state="waiting")
                if once:
                    return
                time.sleep(min(WAIT_POLL_S, 10.0))
                continue
            try:
                sit = perceive(self.gw, self.prev, live=self.live, clock=clock)
            except Exception as e:  # noqa: BLE001
                self._err("perceive", e)
                time.sleep(2)
                continue
            try:
                rep = self.step(sit)
                n_sent = sum(1 for a in rep["actions"] if a["status"] in ("sent", "deal"))
                print(f"tick {sit.tick}: {len(rep['actions'])} actions, {n_sent} sent, "
                      f"write={rep['write']} requests={sit.requests}", flush=True)
            except Exception as e:  # noqa: BLE001 - the loop must survive anything
                self._err("step", e)
                traceback.print_exc()
                self.last_tick = sit.tick
            if once:
                return


# --------------------------------------------------------------------------- CLI

def build(mode: str, only: list[str] | None = None) -> Runner:
    from .gateway import Gateway
    rails = _import("bazaar.core.rails")
    executor = _import("bazaar.core.executor")
    arbiter = _import("bazaar.core.arbiter")
    llm = _import("bazaar.llm.client")
    try:
        from .core.ledger import Ledger
    except ImportError:
        Ledger = None
    lessons = None
    store = _import("bazaar.lab.store")
    if store is not None:
        try:
            lessons = store.LessonStore()
        except Exception as e:  # noqa: BLE001
            log.warning("lesson store: %s", e)
    council_mod = _import("bazaar.brain.council")
    if mode == "sim":
        url, token = f"http://127.0.0.1:{config.SIM_PORT}", "sim"
        live = config.DATA / "sim_run"
        defaults = {**DEFAULT_CONTROL, "armed": True}
    else:
        url, token = config.GATEWAY_URL, config.GATEWAY_TOKEN
        live = config.LIVE
        defaults = DEFAULT_CONTROL
    live.mkdir(parents=True, exist_ok=True)
    gw = Gateway(url=url, token=token, real=False)
    make_write = (lambda: Gateway(url=url, token=token, real=True))
    if mode == "live" and not config.ALLOW_REAL:
        make_write = None
    ledger = Ledger(live) if Ledger else None
    if llm is not None and hasattr(llm, "set_ledger") and mode == "sim":
        try:
            llm.set_ledger(ledger)
        except Exception:  # noqa: BLE001
            pass
    return Runner(gw, domains=load_domains(only, gw=gw), mode=mode, live=live, make_write_gw=make_write,
                  ledger=ledger, lessons=lessons, llm=llm, rails=rails, executor=executor, arbiter=arbiter,
                  council=getattr(council_mod, "review", None), control_defaults=defaults)


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(prog="python -m bazaar.run")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sim", action="store_true", help=f"play the simulated Bazaar on :{config.SIM_PORT}")
    g.add_argument("--live", action="store_true", help="the real game (writes need BAZAAR_ALLOW_REAL=1 + armed)")
    ap.add_argument("--only", default="", help="comma-separated domains (duels,dealers,market)")
    ap.add_argument("--once", action="store_true", help="one tick, then exit")
    args = ap.parse_args(argv)
    if args.live:
        from .supervise import AlreadyRunning, singleton
        try:
            singleton("run-live")                   # one live bot at a time (a second would double every write)
        except AlreadyRunning as e:
            print(f"bazaar.run: {e}", file=sys.stderr, flush=True)
            sys.exit(2)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    runner = build("sim" if args.sim else "live", [s for s in args.only.split(",") if s] or None)
    c = runner.control()
    print(f"bazaar.run {runner.mode}: domains {[d.name for d in runner.domains]} · "
          f"writes {'possible' if runner.make_write_gw else 'OFF (dry run)'} · armed={c.get('armed')} · "
          f"live dir {runner.live}", flush=True)
    try:
        runner.loop(once=args.once)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
