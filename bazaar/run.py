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
COUNCIL_SHARE = 0.80             # the council may run until this share of the tick
COUNCIL_MIN_S = 4.0              # ...and only if at least this many seconds remain
DROP_PCT = 0.05                  # breaker: score or portfolio down 5 % ...
DROP_WINDOW = 10                 # ...within 10 ticks -> cautious (no buys) for CAUTIOUS_TICKS
VENUE_BOND = 250
CAUTIOUS_TICKS = 10
REFUSALS_TO_PAUSE = 3            # consecutive refusals of one domain -> pause it PAUSE_TICKS
PAUSE_TICKS = 10
INJECTION_FLOOD = 4              # flagged texts from others in one tick -> code-only for FLOOD_TICKS
FLOOD_TICKS = 5
ATTRIBUTE_TICKS = 3              # score deltas go to actions sent in the last N ticks


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


def load_domains(only: list[str] | None = None) -> list:
    out = []
    for name, mod, cls in DOMAINS:
        if only and name not in only:
            continue
        m = _import(mod)
        if m is not None and hasattr(m, cls):
            try:
                out.append(getattr(m, cls)())
            except Exception as e:  # noqa: BLE001
                log.error("domain %s failed to start: %s", name, e)
    return out


def _is_buy(a: Action) -> bool:
    if a.domain == "duels":
        return False
    if _cash_out(a) > 0:
        return True
    p = a.params or {}
    topic = p.get("topic") or {}
    return a.kind == "open_thread" and isinstance(topic, dict) and "buy" in topic


def _texts_from_others(sit: Situation) -> list[str]:
    me = (sit.me or {}).get("id")
    out = []
    for t in sit.threads:
        for m in t.get("messages") or []:
            if m.get("tick") == sit.tick and m.get("sender") != me:
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
        if a.kind in ACCEPT_KINDS:
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
        return load_control(self.live, self.control_defaults)

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
            if not ctx.llm_ok or (busy is not None and not busy.done()):
                continue                                      # code only, or still thinking last tick
            futs[d.name] = self.running[d.name] = self.pools[d.name].submit(d.decide, sit, ctx)
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

    def review_big(self, actions: list[Action], sit: Situation, ctx: TickContext) -> list[Action]:
        council = self.council
        if council is None or not ctx.llm_ok:
            return actions
        cdead = sit.tick_start + COUNCIL_SHARE * sit.tick_seconds
        out = []
        for a in actions:
            if not a.big or cdead - self.now() < COUNCIL_MIN_S:
                out.append(a)
                continue
            try:
                r = council(a, sit, ctx.with_deadline(cdead))
            except Exception as e:  # noqa: BLE001
                self._err("council", e)
                r = a
            if r is None:
                self._ledger("decision", a, Verdict(False, "council", "vetoed by the council"),
                             tick=sit.tick, dry_run=False)
                self._observe(a, Outcome(a.id, sit.tick, "vetoed", {"by": "council"}))
            else:
                out.append(r)
        return out

    def select(self, actions: list[Action], sit: Situation, ctx: TickContext) -> list[Action]:
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
        for a in actions:
            t0 = self.now()
            if self.rails is not None:
                try:
                    verdict = self.rails.check(a, sit, ctx)
                except Exception as e:  # noqa: BLE001 - a crashing rail is a veto
                    self._err("rails", e)
                    verdict = Verdict(False, "rails_error", str(e)[:200])
            else:
                verdict = Verdict(False, "rails_missing", "core/rails.py not importable")
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
                except Exception as e:  # noqa: BLE001
                    self._err("executor", e)
                    outcome = Outcome(a.id, sit.tick, "error", {"error": getattr(e, "code", type(e).__name__),
                                                                "message": str(e)[:200]})
            self._ledger("decision", a, verdict, source=a.source, latency_s=round(self.now() - t0, 3),
                         tick=sit.tick, dry_run=not write)
            status = outcome.status if outcome else "dry_run"
            if outcome is not None:
                self._ledger("outcome", outcome, a)
                self._observe(a, outcome)
                self.budget.record(a, outcome.status, self.now())
                ctx.budget = self.budget.for_tick(sit.tick, sit.limits, self.now())   # rails see it at once
                self._count_refusal(a.domain, outcome.status, sit.tick)
                if outcome.status in ("sent", "deal"):
                    self.recent.append((sit.tick, a, outcome.status))
            report.append({"id": a.id, "domain": a.domain, "kind": a.kind, "params": a.params, "source": a.source,
                           "reason": a.reason, "verdict": {"ok": verdict.ok, "rail": verdict.rail,
                                                           "detail": verdict.detail}, "status": status})
        return report

    def _count_refusal(self, domain: str, status: str, tick: int):
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
                     + (VENUE_BOND if me.get("venue") else 0))
        if self.history and self.history[-1][0] == sit.tick:
            self.history.pop()
        self.history.append((sit.tick, sit.score, portfolio))
        window = [h for h in self.history if sit.tick - h[0] <= DROP_WINDOW]
        for i, label in ((1, "score"), (2, "portfolio")):
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
        except OSError as e:
            self._err("status", e)

    # ----- the loop -----
    def wait_for_tick(self) -> tuple[dict | None, bool]:
        """Returns (clock, open). Sleeps until a new tick or, while closed, for WAIT_POLL_S."""
        while True:
            try:
                clock = self.gw.get("/api/clock")
            except Exception as e:  # noqa: BLE001
                self._err("clock", e)
                time.sleep(3)
                continue
            if clock.get("paused") or clock.get("doors") != "open":
                return clock, False
            if clock.get("tick") != self.last_tick:
                return clock, True
            nti = float(clock.get("next_tick_in") or 1.0)
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
    return Runner(gw, domains=load_domains(only), mode=mode, live=live, make_write_gw=make_write,
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
