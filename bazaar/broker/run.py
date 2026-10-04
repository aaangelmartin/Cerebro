"""The broker process: plays the Market Test bench and our venue's public offers, once per tick.

    python -m bazaar.broker.run                 # live: reads through the gateway; writes only with BAZAAR_ALLOW_REAL=1
    python -m bazaar.broker.run --sim           # in-process synthetic sessions, fast clock, prints efficiency vs stall
    python -m bazaar.broker.run --sim --hard
    python -m bazaar.broker.run --url http://127.0.0.1:8797 --token sim --key sim-broker   # against sim/fake_bazaar

Each tick: read the book (X-Broker-Key), feed the engine, plan, POST /api/broker/matches within the per-tick limits,
record everything to data/live/bench/<session>.jsonl and write the heartbeat data/live/broker_status.json.
Safety net: any exception in the engine, or mode "stall" in data/live/broker_control.json, falls back to crossing
by quotes exactly as the free auto stall does, so we never score below half the bench points.
Writes are blocked when bazaar/STOP exists, when data/live/control.json says armed: false, when
broker_control.json says enabled: false / mode "off", and always unless BAZAAR_ALLOW_REAL=1 (live mode).
After each session it reads /api/me score.bench_efficiency and the public bench.* events and logs them, carries the
learned quote-shading prior into the next sessions (state file), and compares itself with the free stall: below it in
`stall_switch_sessions` sessions in a row, it switches broker_control.json to mode "stall" and posts a notice.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .. import config
from ..gateway import GameError, Gateway
from . import venue
from .engine import BenchEngine, Match, load_policy, public_plan, run_of, stall_plan

STOP_CODES = {"wait_for_tick", "rate_limited", "too_many_matches", "match_limit", "limit_reached", "bad_broker_key", "bad_key",
              "auto_venue", "not_board"}
GONE_HINTS = ("gone", "not_found", "closed", "taken", "unknown")
KEY_CODES = {"bad_broker_key", "bad_key", "unauthorized", "forbidden", "invalid_key"}
HEARTBEAT_EVERY = 5.0          # seconds: heartbeat on every poll at most this often, even when the tick does not move
END_AFTER_ABSENT = 2           # ticks a run must be missing from the book before its session is closed
STALL_SWITCH_SESSIONS = 2      # sessions in a row below the stall before switching to mode "stall"
STALL_MARGIN = 0.005           # server numbers are exact
REPLAY_MARGIN = 0.02           # the replay compares estimates: demand a clearer gap
WAKE_EARLY_S = 0.3             # wake this long before the next tick
MIN_SLEEP_S = 0.5
CLOSED_SLEEP_S = 15.0          # doors closed or paused: read the clock this often (10-30 s)
ERROR_SLEEP_S = 2.0
MAX_SLEEP_S = 30.0


def next_sleep(clock: dict | None, clock_at: float | None = None, now: float | None = None) -> float:
    """Seconds until the next clock read: just before the next tick, 15 s while closed/paused, 2 s after an error.
    Replaces polling /api/clock every second."""
    if not isinstance(clock, dict):
        return ERROR_SLEEP_S
    if clock.get("paused") or clock.get("doors") not in ("open", None):
        return CLOSED_SLEEP_S
    nti = clock.get("next_tick_in")
    if isinstance(nti, bool) or not isinstance(nti, (int, float)) or nti != nti:
        return 1.0
    spent = max(0.0, (now if now is not None else time.time()) - clock_at) if clock_at else 0.0
    return min(MAX_SLEEP_S, max(MIN_SLEEP_S, float(nti) - WAKE_EARLY_S - spent))


# --------------------------------------------------------------------------- clients

class LiveClient:
    """The broker side of the gateway. The key stays in memory and in broker.json, never in logs."""

    def __init__(self, gw: Gateway, key: str | None, reload: bool = True):
        self.gw, self._key, self.reload = gw, key, reload

    def reload_key(self) -> bool:
        """Re-read the stored broker key (the venue may be reopened or rotated). True when it changed."""
        if not self.reload:
            return False
        key = venue.load_key()
        if key and key != self._key:
            self._key = key
            return True
        return False

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def clock(self) -> dict:
        return self.gw.get("/api/clock")

    def book(self) -> dict:
        # Gateway.get has no broker-key argument; the gateway forwards X-Broker-Key on any method.
        try:
            return self.gw._request("GET", "/api/broker/book", None, self._key)
        except GameError as e:
            if e.code in ("rate_limited", "upstream", "network", "timeout", "server_error"):
                time.sleep(0.4)
                return self.gw._request("GET", "/api/broker/book", None, self._key)
            raise

    def match(self, sell: Any, buy: Any, price: int) -> dict:
        return self.gw.post("/api/broker/matches", {"sell": sell, "buy": buy, "price": int(price)}, broker_key=self._key)

    def announce(self, text: str) -> dict:
        return self.gw.post("/api/broker/announce", {"text": text}, broker_key=self._key)

    def me(self) -> dict:
        return self.gw.get("/api/me")

    def schedule(self) -> dict:
        return self.gw.get("/api/schedule")

    def feed(self) -> dict:
        return self.gw.get("/api/feed", limit=200)


def _read_json(p: Path) -> dict:
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def live_writes_allowed() -> tuple[bool, str]:
    if config.STOP_FILE.exists():
        return False, "STOP file"
    if not config.ALLOW_REAL:
        return False, "BAZAAR_ALLOW_REAL is not 1"
    ctl = _read_json(config.LIVE / "control.json")
    if ctl.get("armed") is not True:                           # a missing or unreadable control file is disarmed
        return False, "control.json not armed"
    return True, ""


# --------------------------------------------------------------------------- the loop

class BrokerLoop:
    def __init__(self, client, out_dir: Path, policy: dict | None = None,
                 writes_allowed: Callable[[], tuple[bool, str]] = lambda: (True, ""),
                 control_file: Path | None = None, status_file: Path | None = None, day: str | None = None,
                 state_file: Path | None = None, notices_file: Path | None = None):
        self.client = client
        self.out = out_dir
        self.out.mkdir(parents=True, exist_ok=True)
        self.policy = policy or load_policy()
        self.base_policy = json.loads(json.dumps(self.policy))     # code defaults + the tuned file, no overlay
        self.engine = BenchEngine(self.policy)
        self.overlay_file = (status_file or (out_dir.parent / "broker_status.json")).parent / "broker_policy.json"
        self.overlay: dict = {"policy": {}, "version": None, "rejected": []}
        self.writes_allowed = writes_allowed
        self.control_file = control_file
        self.status_file = status_file or (self.out.parent / "broker_status.json")
        self.day = day or datetime.now().strftime("%Y-%m-%d")
        self.last_tick: int | None = None
        self.active_runs: set[str] = set()
        self.session_of: dict[str, str] = {}
        self.pending_results: dict[str, int] = {}       # run -> tick at which to read the score
        self.stats: dict[str, dict] = {}                # run -> counters
        self.errors: list[dict] = []
        self.engine_failures: dict[str, int] = {}
        self.matches_total = 0
        self.public_total = 0
        self.last_result: dict | None = None
        self.hard_hours: list[float] = []
        self.schedule_tick: int | None = None
        self.t_hours: float = 0.0
        self.absent: dict[str, int] = {}                # run -> consecutive ticks missing from the book
        self.hb_at = 0.0
        self.last_clock: dict | None = None             # the last /api/clock read (None after an error)
        self.last_clock_at: float | None = None
        self.auto_mode: str | None = None               # "stall" after an automatic switch when there is no control file
        self.state_file = state_file or (self.out.parent / "broker_state.json")
        self.notices_file = notices_file or (self.out.parent / "notices.jsonl")
        self.watch: dict = {"below": 0, "history": [], "switched": None}
        self.matchmaker = None                          # broker.matchmaker.MatchMaker, attached for the live venue
        self.bench_hours: list[float] = []              # every scheduled Market Test, to stay quiet around it
        self._load_state()

    # ---- helpers
    def control(self) -> dict:
        d = _read_json(self.control_file) if self.control_file else {}
        mode = d.get("mode", "smart")
        if self.auto_mode and mode == "smart" and not self.control_file:
            mode = self.auto_mode
        return {"enabled": d.get("enabled", True), "mode": mode}

    # ---- state carried across sessions and restarts
    def _load_state(self) -> None:
        d = _read_json(self.state_file)
        self.engine.load_state(d.get("engine"))
        w = d.get("watch")
        if isinstance(w, dict):
            self.watch.update({k: w[k] for k in ("below", "history", "switched") if k in w})

    def _save_state(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"updated": time.time(), "engine": self.engine.export_state(),
                                       "watch": self.watch}, default=str))
            tmp.replace(self.state_file)
        except OSError as e:
            self._err(self.last_tick, "state", e)

    def _err(self, tick: int | None, where: str, e: Any) -> None:
        self.errors.append({"t": round(time.time(), 1), "tick": tick, "where": where, "error": str(e)[:300]})
        self.errors = self.errors[-20:]

    def _append(self, name: str, rec: dict) -> None:
        with open(self.out / f"{name}.jsonl", "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    def session_name(self, run: str) -> str:
        if run not in self.session_of:
            self.session_of[run] = f"{self.day}-{run}"
        return self.session_of[run]

    def _refresh_schedule(self, tick: int) -> None:
        if self.schedule_tick is not None and tick - self.schedule_tick < 60:
            return
        self.schedule_tick = tick
        try:
            sch = self.client.schedule()
        except Exception as e:  # noqa: BLE001
            self._err(tick, "schedule", e)
            return
        hard, ticks = [], None
        self.bench_hours = [float(ev.get("at_hours", -1)) for ev in sch.get("upcoming") or []
                            if ev.get("action") == "bench"]
        for ev in sch.get("upcoming") or []:
            if ev.get("action") != "bench":
                continue
            text = f"{ev.get('note', '')} {(ev.get('params') or {}).get('name', '')}".lower()
            if "hard" in text:
                hard.append(float(ev.get("at_hours", -1)))
            ticks = (ev.get("params") or {}).get("ticks") or ticks
        self.hard_hours = sorted(set(self.hard_hours) | set(hard))
        if ticks:
            self.policy["session_ticks"] = int(ticks)

    def _load_overlay(self) -> None:
        """Read data/live/broker_policy.json (validated, bounded) on top of the base policy."""
        from .policy_overlay import apply, load
        try:
            ov = load(self.overlay_file)
        except Exception as e:  # noqa: BLE001 - a bad overlay must never stop the broker
            self._err(None, "overlay", e)
            return
        ticks = self.policy.get("session_ticks")
        pol = apply(self.base_policy, ov["policy"])
        if ticks:
            pol["session_ticks"] = ticks
        self.policy = pol
        self.engine.apply_policy(pol)
        self.overlay = ov

    # ---- one poll
    def poll(self) -> None:
        try:
            clock = self.client.clock()
        except Exception as e:  # noqa: BLE001
            self.last_clock = None
            self._err(None, "clock", e)
            self.heartbeat(None)
            return
        self.last_clock, self.last_clock_at = (clock if isinstance(clock, dict) else None), time.time()
        if not isinstance(clock, dict):
            return
        tick = clock.get("tick")
        self.t_hours = float(clock.get("t_hours") or 0.0)
        if not isinstance(tick, int) or tick == self.last_tick:
            if time.time() - self.hb_at >= HEARTBEAT_EVERY:   # slow ticks: stay alive for the supervisor
                self.heartbeat(self.last_tick)
            return
        self.last_tick = tick
        self._refresh_schedule(tick)
        self.on_tick(tick, clock)

    def on_tick(self, tick: int, clock: dict) -> None:
        ctl = self.control()
        self.heartbeat(tick)                           # alive before the slow reads: a late game is not a hung broker
        try:
            book = self.client.book()
        except Exception as e:  # noqa: BLE001
            self._err(tick, "book", e)
            self.heartbeat(tick)
            return
        bench = list(book.get("bench_offers") or [])
        runs = {run_of(o.get("id")) for o in bench if o.get("id") is not None}
        ends = {}
        meta = book.get("bench")
        if isinstance(meta, dict) and meta.get("run") and isinstance(meta.get("ends_tick"), int):
            ends[str(meta["run"])] = meta["ends_tick"]
        for run in runs:
            self.absent.pop(run, None)
        if runs - self.active_runs and not self.active_runs:
            self._load_overlay()                       # only between sessions: never mid-session
        for run in runs - self.active_runs:            # a session starts
            hard = any(abs(self.t_hours - h) < 0.25 for h in self.hard_hours)
            if hard:
                self.engine.run_profile[run] = "hard"
            self.stats[run] = {"start_tick": tick, "matches": 0, "refused": 0, "fallback": 0, "probes": 0,
                               "est_surplus": 0.0, "profile": "hard" if hard else "auto",
                               "policy_version": self.overlay.get("version")}
            self._append(self.session_name(run), {"type": "start", "tick": tick, "t_hours": self.t_hours,
                                                  "profile": self.stats[run]["profile"], "policy": self.policy,
                                                  "policy_version": self.overlay.get("version"),
                                                  "overlay": self.overlay.get("policy"),
                                                  "overlay_by": self.overlay.get("by"),
                                                  "overlay_rejected": self.overlay.get("rejected")})
        still = set()
        for run in self.active_runs - runs:            # missing: ended, or a blip in the book?
            self.absent[run] = self.absent.get(run, 0) + 1
            if self.absent[run] < END_AFTER_ABSENT:
                still.add(run)
                continue
            self.absent.pop(run, None)                 # a session ended: read our score in two ticks
            self.pending_results[run] = tick + 2
            stall_eff = self.engine.stall_efficiency(run)
            if run in self.stats:
                self.stats[run]["stall_efficiency"] = stall_eff
                self.stats[run]["our_replay_efficiency"] = self.engine.our_efficiency(run)
            self._append(self.session_name(run), {"type": "end", "tick": tick,
                                                  "est_efficiency": self.engine.efficiency_estimate(run),
                                                  "stall_efficiency": stall_eff,
                                                  "stats": self.stats.get(run), "traders": self.engine.snapshot(run)})
            carry = self.engine.learn_session(run)
            if carry is not None:
                self._save_state()
        self.active_runs = runs | still

        plan: list[Match] = []
        mode = ctl["mode"]
        if bench:
            try:
                self.engine.observe(tick, bench, ends)
                if mode == "stall" or any(self.engine_failures.get(r, 0) >= 3 for r in runs):
                    plan = stall_plan(bench)
                else:
                    plan = self.engine.plan(tick, int(book.get("fee_bps") or 0), int(book.get("fee_per_card") or 0))
                    live = {o["id"] for o in bench}
                    plan = [m for m in plan if m.sell in live and m.buy in live]
            except Exception as e:  # noqa: BLE001 - the safety net: behave like the stall
                for r in runs:
                    self.engine_failures[r] = self.engine_failures.get(r, 0) + 1
                    if r in self.stats:
                        self.stats[r]["fallback"] += 1
                self._err(tick, "engine", f"{type(e).__name__}: {e} | {traceback.format_exc(limit=2)[-200:]}")
                plan = stall_plan(bench)
            plan = plan[: int(self.policy.get("max_bench_matches_per_tick", 10))]
        ok, why = self.writes_allowed()
        send = ok and ctl["enabled"] and mode != "off"
        results = self._send(tick, plan, send, bench=True) if plan else []
        for run in runs:
            self._append(self.session_name(run), {
                "type": "tick", "tick": tick, "t": round(time.time(), 2), "mode": mode, "sent": send,
                "blocked": None if send else (why or f"control enabled={ctl['enabled']} mode={mode}"),
                "bench_meta": meta, "bench": [o for o in bench if run_of(o.get("id")) == run],
                "plan": [m.to_dict() for m in plan if m.run == run or run_of(m.sell) == run],
                "results": [r for r in results if run_of(r["sell"]) == run],
                "traders": self.engine.snapshot(run), "rule": self.engine.rule})

        if book.get("offers"):
            pplan = public_plan(book, int(self.policy.get("max_public_matches_per_tick", 10)), tick)
            if pplan:
                presults = self._send(tick, pplan, send, bench=False)
                self._append(f"public-{self.day}", {"type": "tick", "tick": tick, "t": round(time.time(), 2),
                                                    "sent": send, "offers": book.get("offers"),
                                                    "plan": [m.to_dict() for m in pplan], "results": presults})
        self._read_results(tick)
        self.engine.forget_before(tick - 40)
        self.heartbeat(tick)                           # the Market Test work is done: the side job cannot age it
        self._matchmake(tick, clock, send, bool(bench))
        self.heartbeat(tick)

    def _matchmake(self, tick: int, clock: dict, send: bool, in_session: bool) -> None:
        """Invite pairs of other teams to our venue. Never during a Market Test or the 12 ticks before one."""
        from .matchmaker import EVERY_TICKS
        mm = self.matchmaker
        if mm is None or not send or in_session or self.active_runs or self.pending_results or tick % EVERY_TICKS:
            return
        per_hour = 3600.0 / float(clock.get("tick_seconds") or 30.0)       # ticks in one game hour
        if any(0 <= (h - self.t_hours) * per_hour <= 12 for h in self.bench_hours):
            return
        try:
            done = mm.step(tick, last_venue_announce=last_announce_tick(mm.venue))
            if done.get("announced") or done.get("messages"):
                self._append(f"matchmaker-{self.day}", {"tick": tick, **done})
        except Exception as e:  # noqa: BLE001 - a side job: it must never hurt the Market Test loop
            self._err(tick, "matchmaker", f"{type(e).__name__}: {e}")

    def _send(self, tick: int, plan: list[Match], send: bool, bench: bool) -> list[dict]:
        out = []
        for m in plan:
            rec = {"sell": m.sell, "buy": m.buy, "price": m.price, "kind": m.kind}
            if not send:
                rec["status"] = "dry"
                out.append(rec)
                continue
            try:
                resp = self.client.match(m.sell, m.buy, m.price)
                rec.update(status="ok", response=venue.redact(resp))
                if bench:
                    self.engine.note_matched(m.sell, m.buy, m.est_surplus, m.kind)
                    st = self.stats.get(run_of(m.sell))
                    if st:
                        st["matches"] += 1
                        st["est_surplus"] += m.est_surplus
                        st["probes"] += m.kind == "probe"
                    self.matches_total += 1
                else:
                    self.public_total += 1
            except GameError as e:
                rec.update(status="refused", error=e.code, message=e.message[:200])
                if bench:
                    self.engine.note_refused(m, e.code, getattr(e, "message", "") or "")
                    st = self.stats.get(run_of(m.sell))
                    if st:
                        st["refused"] += 1
                        st["probes"] += m.kind == "probe"
                out.append(rec)
                if e.code in KEY_CODES and hasattr(self.client, "reload_key"):
                    if self.client.reload_key():
                        self._err(tick, "match", f"{e.code}: broker key reloaded")
                if e.code in STOP_CODES:
                    self._err(tick, "match", f"{e.code}: stopping this tick")
                    break
                continue
            except Exception as e:  # noqa: BLE001
                rec.update(status="error", error=f"{type(e).__name__}: {e}"[:200])
                self._err(tick, "match", e)
            out.append(rec)
        return out

    def _read_results(self, tick: int) -> None:
        due = [r for r, at in self.pending_results.items() if tick >= at]
        if not due:
            return
        try:
            me = self.client.me()
        except Exception as e:  # noqa: BLE001
            self._err(tick, "me", e)
            return
        score = me.get("score") or {}
        res = {k: score.get(k) for k in ("bench_efficiency", "bench_points", "bench_venue", "market", "mm_points")}
        others = []
        try:
            feed = self.client.feed()
            for ev in feed.get("events") or feed.get("items") or []:
                if str(ev.get("type", "")).startswith("bench."):
                    others.append(ev)
        except Exception as e:  # noqa: BLE001
            self._err(tick, "feed", e)
        for run in due:
            self.pending_results.pop(run, None)
            est = self.engine.efficiency_estimate(run)
            ours_cmp = (self.stats.get(run) or {}).get("our_replay_efficiency")
            if ours_cmp is None:
                ours_cmp = self.engine.our_efficiency(run)
            stall_est = (self.stats.get(run) or {}).get("stall_efficiency")
            if stall_est is None:
                stall_est = self.engine.stall_efficiency(run)
            rec = {"type": "result", "tick": tick, "run": run, "session": self.session_name(run), "score": res,
                   "est_efficiency": est, "stall_efficiency": stall_est, "stats": self.stats.get(run),
                   "bench_events": others[-40:]}
            rec["vs_stall"] = self._compare_with_stall(run, res.get("bench_efficiency"), ours_cmp, stall_est, others)
            self._append(self.session_name(run), rec)
            self._append("results", rec)
            self.last_result = rec

    def _compare_with_stall(self, run: str, ours_server: Any, ours_est: float | None, stall_est: float | None,
                            events: list[dict]) -> dict:
        """Are we below the free stall this session? Like with like: the server's efficiency against a stall
        efficiency published in the bench.* events when there is one, else our estimate against the stall replayed on
        our own recorded book. Below in STALL_SWITCH_SESSIONS sessions in a row -> mode "stall" + a notice."""
        stall_srv = stall_from_events(events, run)
        if isinstance(ours_server, (int, float)) and stall_srv is not None:
            ours, stall, basis = float(ours_server), stall_srv, "server"
        elif ours_est is not None and stall_est is not None:
            ours, stall, basis = ours_est, stall_est, "replay"
        else:
            return {"basis": None}
        below = ours < stall - (STALL_MARGIN if basis == "server" else REPLAY_MARGIN)
        self.watch["below"] = self.watch.get("below", 0) + 1 if below else 0
        self.watch["history"] = (list(self.watch.get("history") or []) + [
            {"run": run, "ours": round(ours, 4), "stall": round(stall, 4), "basis": basis, "below": below}])[-10:]
        out = {"basis": basis, "ours": ours, "stall": stall, "below": below, "below_in_a_row": self.watch["below"]}
        if self.watch["below"] >= STALL_SWITCH_SESSIONS and self.control()["mode"] == "smart":
            out["switched"] = self._switch_to_stall(ours, stall, basis)
        self._save_state()
        return out

    def _switch_to_stall(self, ours: float, stall: float, basis: str) -> bool:
        n = self.watch["below"]
        if self.control_file:
            d = _read_json(self.control_file)
            d.update(mode="stall", auto=True, reason=f"below the stall {n} sessions in a row", switched_at=time.time())
            try:
                tmp = self.control_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(d))
                tmp.replace(self.control_file)
            except OSError as e:
                self._err(self.last_tick, "control", e)
                return False
        else:
            self.auto_mode = "stall"
        self.watch["switched"] = time.time()
        self.watch["below"] = 0
        try:
            from ..lab.store import write_notice
            write_notice("broker", f"Broker: por debajo de la tienda gratis {n} sesiones seguidas "
                         f"({ours:.1%} frente a {stall:.1%}, base {basis}). Paso a modo «stall» (cruzar por "
                         f"cotizaciones). Para volver: mode «smart» en broker_control.json.",
                         path=self.notices_file, mode="stall", ours=round(ours, 4), stall=round(stall, 4), basis=basis)
        except Exception as e:  # noqa: BLE001
            self._err(self.last_tick, "notice", e)
        return True

    def heartbeat(self, tick: int | None) -> None:
        self.hb_at = time.time()
        run = sorted(self.active_runs)[-1] if self.active_runs else None
        st = {
            "updated": time.time(), "tick": tick, "t_hours": self.t_hours,
            "session": self.session_name(run) if run else None, "active_runs": sorted(self.active_runs),
            "mode": self.control()["mode"], "writes": self.writes_allowed()[0], "rule": self.engine.rule,
            "has_key": getattr(self.client, "has_key", True),
            "efficiency_estimate": self.engine.efficiency_estimate(run) if run else None,
            "stall_efficiency": (self.engine.stall_efficiency(run) if run else
                                 (self.last_result or {}).get("stall_efficiency")),
            "vs_stall": {"below_in_a_row": self.watch.get("below", 0), "switched": self.watch.get("switched"),
                         "history": (self.watch.get("history") or [])[-3:]},
            "prior_carry": self.engine.carry,
            "session_stats": self.stats.get(run) if run else None,
            "matches_total": self.matches_total, "public_matches_total": self.public_total,
            "last_result": ({k: self.last_result.get(k) for k in ("session", "score", "est_efficiency",
                                                                  "stall_efficiency", "vs_stall")}
                            if self.last_result else None),
            "errors": self.errors[-10:],
            "policy_version": self.overlay.get("version"), "overlay": self.overlay.get("policy"),
            "overlay_rejected": self.overlay.get("rejected"),
        }
        tmp = self.status_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, default=str))
        tmp.replace(self.status_file)


def last_announce_tick(venue_id: str, live: Path | None = None, tail_bytes: int = 400_000) -> int | None:
    """The tick of the last announcement on a venue, from the recorded feed (ours or the bot's)."""
    path = (live or config.LIVE) / "events.jsonl"
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail_bytes))
            rows = f.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return None
    for line in reversed(rows):
        if '"venue.announcement"' not in line or f'"{venue_id}"' not in line:
            continue
        try:
            return int(json.loads(line).get("tick"))
        except (ValueError, TypeError):
            continue
    return None


def team_message(gw: Gateway, venue_id: str) -> Callable[[str, str], Any]:
    """Open a thread with a team on El Rastro, leave one message and close it (frees the thread slot)."""
    def send(team: str, text: str) -> Any:
        # the game refuses a thread on our own venue (self_venue): the note travels on the house market
        t = gw.post("/api/threads", {"with": team, "venue": "rastro"})
        tid = t.get("id") or (t.get("thread") or {}).get("id")
        try:
            return gw.post(f"/api/threads/{int(tid)}/messages", {"text": text[:600]})
        finally:
            try:
                gw.post(f"/api/threads/{int(tid)}/close")
            except Exception:  # noqa: BLE001
                pass
    return send


def plaza_helpers(control_fn: Callable[[], dict] | None = None) -> tuple[Callable[[], Any] | None,
                                                                         Callable[[], Any] | None]:
    """The plaza's two helpers for the matchmaker (its public address, the pairs agents declared), or
    (None, None) when the plaza package does not even import. The broker plays the Market Test: it must
    start and run whatever state the market board's code is in.

    The address goes into the venue's announcements, which every team reads, only once a human has switched
    the market on by hand: control.json `plaza: "on"` (POST /control {"plaza": "on"}). With the key absent
    the market still runs, but its address is not announced."""
    try:
        from ..plaza import server as plaza
    except Exception as e:  # noqa: BLE001 - any failure of that package, a syntax error included
        print(f"broker: plaza not available ({type(e).__name__}: {e}); announcements go without its page", flush=True)
        return None, None
    control = control_fn or (lambda: _read_json(config.LIVE / "control.json"))

    def page() -> str | None:
        if str((control() or {}).get("plaza") or "").lower() != "on":
            return None
        return plaza.public_url(config.LIVE, config.DATA)

    return page, lambda: plaza.declared_pairs(config.LIVE, config.DATA / "record")


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    x = float(x)
    return x / 100 if 1 < x <= 100 else x          # a percentage


def stall_from_events(events: list[dict], run: str | None = None) -> float | None:
    """The free stall's efficiency for a session, if the public bench.* events publish it: an explicit
    stall/baseline field, or the mean efficiency of the starter (auto) venues in a per-venue list."""
    vals: list[float] = []
    for ev in events or []:
        if not str(ev.get("type", "")).startswith("bench."):
            continue
        evrun = ev.get("run") or (ev.get("data") or {}).get("run")
        if run and evrun and str(evrun) != str(run):
            continue
        body = {**(ev.get("data") or {}), **ev} if isinstance(ev.get("data"), dict) else ev
        for k in ("stall_efficiency", "stall", "baseline_efficiency", "baseline", "auto_efficiency"):
            v = body.get(k)
            v = _num(v.get("efficiency") if isinstance(v, dict) else v)
            if v is not None:
                vals.append(v)
                break
        else:
            rows = body.get("venues") or body.get("results") or []
            if isinstance(rows, dict):
                rows = [{"venue": k, **(r if isinstance(r, dict) else {"efficiency": r})} for k, r in rows.items()]
            st = [_num(r.get("efficiency")) for r in rows if isinstance(r, dict)
                  and (r.get("starter") or (r.get("rules") or {}).get("mechanism") == "auto" or r.get("mechanism") == "auto")]
            st = [v for v in st if v is not None]
            if st:
                vals.append(sum(st) / len(st))
    return vals[-1] if vals else None


# --------------------------------------------------------------------------- entry points

def run_sim(hard: bool = False, sessions: int = 3, seed: int = 0, cross_rule: str = "quotes",
            out_dir: Path | None = None) -> dict:
    """Drive BrokerLoop against in-process synthetic sessions; compare with the stall on the same seeds."""
    from .sim_book import SimClient, SimSession, play, stall_planner
    out_dir = out_dir or (config.LAB / "broker" / "sim_run" / "bench")
    if out_dir.exists():                             # each sim run starts clean
        for f in out_dir.glob("*.jsonl"):
            f.unlink()
    for f in (out_dir.parent / "broker_state.json",):
        if f.exists():
            f.unlink()
    client = SimClient(seed=seed, hard=hard, sessions=sessions)
    for _, s in client.sessions:
        s.cross_rule = cross_rule
    loop = BrokerLoop(client, out_dir, load_policy(), status_file=out_dir.parent / "broker_status.json")
    while client.tick < client.end_tick + 3:
        loop.poll()
        client.advance()
    eng = [s.efficiency() for _, s in client.sessions]
    stall = []
    for k, (_, s) in enumerate(client.sessions):
        ref = SimSession.generate(seed + k, None, hard, run=s.run, cross_rule=cross_rule)
        stall.append(play(ref, stall_planner()))
    return {"engine": [round(x, 3) for x in eng], "stall": [round(x, 3) for x in stall], "out": str(out_dir),
            "errors": loop.errors}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Team 10 broker: Market Test + public offers on our board venue")
    ap.add_argument("--sim", action="store_true", help="in-process synthetic sessions (no network)")
    ap.add_argument("--hard", action="store_true")
    ap.add_argument("--sessions", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cross-rule", default="quotes", choices=["quotes", "limits"], help="--sim server rule")
    ap.add_argument("--url", help="gateway or fake_bazaar URL (default config.GATEWAY_URL)")
    ap.add_argument("--token", help="gateway token (default config.GATEWAY_TOKEN)")
    ap.add_argument("--key", help="broker key (default: data/live/broker.json); never printed")
    ap.add_argument("--poll", type=float, default=1.0, help="seconds between key checks while there is no key")
    a = ap.parse_args(argv)

    if a.sim:
        print(json.dumps(run_sim(a.hard, a.sessions, a.seed, a.cross_rule), indent=1))
        return

    against_sim = bool(a.url) and ("127.0.0.1" in a.url or "localhost" in a.url) and a.url != config.GATEWAY_URL
    if not against_sim:
        from ..supervise import singleton
        singleton("broker")                        # a second live broker exits here with a clear message
    gw = Gateway(url=a.url or config.GATEWAY_URL, token=a.token or config.GATEWAY_TOKEN,
                 real=True if against_sim else config.ALLOW_REAL)
    key = a.key or venue.load_key()
    client = LiveClient(gw, key, reload=not a.key)
    out = (config.LAB / "broker" / "fake_run" / "bench") if against_sim else (config.LIVE / "bench")
    writes = (lambda: (True, "")) if against_sim else live_writes_allowed
    loop = BrokerLoop(client, out, load_policy(), writes_allowed=writes,
                      control_file=config.LIVE / "broker_control.json",
                      status_file=out.parent / "broker_status.json",
                      state_file=(out.parent / "broker_state.json") if against_sim else (config.LAB / "broker" / "state.json"),
                      notices_file=(out.parent / "notices.jsonl") if against_sim else (config.LAB / "notices.jsonl"))
    if not against_sim:
        from ..intel.needs import needs_report
        from .matchmaker import VENUE, MatchMaker
        page_fn, declared_fn = plaza_helpers()
        loop.matchmaker = MatchMaker(config.LIVE / "matchmaker.json", needs_report,
                                     lambda: _read_json(config.LIVE / "control.json"),
                                     announce=client.announce, message=team_message(gw, VENUE),
                                     page_fn=page_fn, declared_fn=declared_fn)
    print(f"broker: {'fake bazaar' if against_sim else 'live'} | key {'present' if key else 'MISSING'} | "
          f"writes {'on' if writes()[0] else 'off (' + writes()[1] + ')'} | out {out}", flush=True)
    while True:
        had = client.has_key
        try:
            if client.reload_key():                   # the venue may open (or be reopened) while we run
                print("broker: key " + ("changed" if had else "found, matching on"), flush=True)
        except Exception as e:  # noqa: BLE001
            loop._err(loop.last_tick, "key", e)
        started = time.time()
        polled = False
        try:
            if client.has_key:
                polled = True
                loop.poll()
            else:
                loop.heartbeat(loop.last_tick)
        except Exception as e:  # noqa: BLE001 - the process must not die
            loop._err(loop.last_tick, "loop", e)
        if polled:
            time.sleep(next_sleep(loop.last_clock, loop.last_clock_at))
        else:
            time.sleep(max(0.05, a.poll - (time.time() - started)))


if __name__ == "__main__":
    main()
