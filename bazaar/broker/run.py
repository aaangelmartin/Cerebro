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
After each session it reads /api/me score.bench_efficiency and the public bench.finished events and logs them.
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

STOP_CODES = {"wait_for_tick", "rate_limited", "too_many_matches", "match_limit", "limit_reached", "bad_broker_key",
              "auto_venue", "not_board"}
GONE_HINTS = ("gone", "not_found", "closed", "taken", "unknown")


# --------------------------------------------------------------------------- clients

class LiveClient:
    """The broker side of the gateway. The key stays in memory and in broker.json, never in logs."""

    def __init__(self, gw: Gateway, key: str | None):
        self.gw, self._key = gw, key

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
    if ctl.get("armed") is False:
        return False, "control.json armed=false"
    return True, ""


# --------------------------------------------------------------------------- the loop

class BrokerLoop:
    def __init__(self, client, out_dir: Path, policy: dict | None = None,
                 writes_allowed: Callable[[], tuple[bool, str]] = lambda: (True, ""),
                 control_file: Path | None = None, status_file: Path | None = None, day: str | None = None):
        self.client = client
        self.out = out_dir
        self.out.mkdir(parents=True, exist_ok=True)
        self.policy = policy or load_policy()
        self.engine = BenchEngine(self.policy)
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

    # ---- helpers
    def control(self) -> dict:
        d = _read_json(self.control_file) if self.control_file else {}
        return {"enabled": d.get("enabled", True), "mode": d.get("mode", "smart")}

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

    # ---- one poll
    def poll(self) -> None:
        try:
            clock = self.client.clock()
        except Exception as e:  # noqa: BLE001
            self._err(None, "clock", e)
            self.heartbeat(None)
            return
        tick = clock.get("tick")
        self.t_hours = float(clock.get("t_hours") or 0.0)
        if not isinstance(tick, int) or tick == self.last_tick:
            return
        self.last_tick = tick
        self._refresh_schedule(tick)
        self.on_tick(tick, clock)

    def on_tick(self, tick: int, clock: dict) -> None:
        ctl = self.control()
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
        for run in runs - self.active_runs:            # a session starts
            hard = any(abs(self.t_hours - h) < 0.25 for h in self.hard_hours)
            if hard:
                self.engine.run_profile[run] = "hard"
            self.stats[run] = {"start_tick": tick, "matches": 0, "refused": 0, "fallback": 0, "probes": 0,
                               "est_surplus": 0.0, "profile": "hard" if hard else "auto"}
            self._append(self.session_name(run), {"type": "start", "tick": tick, "t_hours": self.t_hours,
                                                  "profile": self.stats[run]["profile"], "policy": self.policy})
        for run in self.active_runs - runs:            # a session ended: read our score in two ticks
            self.pending_results[run] = tick + 2
            self._append(self.session_name(run), {"type": "end", "tick": tick,
                                                  "est_efficiency": self.engine.efficiency_estimate(run),
                                                  "stats": self.stats.get(run), "traders": self.engine.snapshot(run)})
        self.active_runs = runs

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
            pplan = public_plan(book, int(self.policy.get("max_public_matches_per_tick", 10)))
            if pplan:
                presults = self._send(tick, pplan, send, bench=False)
                self._append(f"public-{self.day}", {"type": "tick", "tick": tick, "t": round(time.time(), 2),
                                                    "sent": send, "offers": book.get("offers"),
                                                    "plan": [m.to_dict() for m in pplan], "results": presults})
        self._read_results(tick)
        self.engine.forget_before(tick - 40)
        self.heartbeat(tick)

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
                    self.engine.note_refused(m, e.code)
                    st = self.stats.get(run_of(m.sell))
                    if st:
                        st["refused"] += 1
                        st["probes"] += m.kind == "probe"
                out.append(rec)
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
            rec = {"type": "result", "tick": tick, "run": run, "session": self.session_name(run), "score": res,
                   "est_efficiency": self.engine.efficiency_estimate(run), "stats": self.stats.get(run),
                   "bench_events": others[-40:]}
            self._append(self.session_name(run), rec)
            self._append("results", rec)
            self.last_result = rec

    def heartbeat(self, tick: int | None) -> None:
        run = sorted(self.active_runs)[-1] if self.active_runs else None
        st = {
            "updated": time.time(), "tick": tick, "t_hours": self.t_hours,
            "session": self.session_name(run) if run else None, "active_runs": sorted(self.active_runs),
            "mode": self.control()["mode"], "writes": self.writes_allowed()[0], "rule": self.engine.rule,
            "has_key": getattr(self.client, "has_key", True),
            "efficiency_estimate": self.engine.efficiency_estimate(run) if run else None,
            "session_stats": self.stats.get(run) if run else None,
            "matches_total": self.matches_total, "public_matches_total": self.public_total,
            "last_result": ({k: self.last_result.get(k) for k in ("session", "score", "est_efficiency")}
                            if self.last_result else None),
            "errors": self.errors[-10:],
        }
        tmp = self.status_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, default=str))
        tmp.replace(self.status_file)


# --------------------------------------------------------------------------- entry points

def run_sim(hard: bool = False, sessions: int = 3, seed: int = 0, cross_rule: str = "quotes",
            out_dir: Path | None = None) -> dict:
    """Drive BrokerLoop against in-process synthetic sessions; compare with the stall on the same seeds."""
    from .sim_book import SimClient, SimSession, play, stall_planner
    out_dir = out_dir or (config.LAB / "broker" / "sim_run" / "bench")
    if out_dir.exists():                             # each sim run starts clean
        for f in out_dir.glob("*.jsonl"):
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
    ap.add_argument("--poll", type=float, default=1.0, help="seconds between clock reads")
    a = ap.parse_args(argv)

    if a.sim:
        print(json.dumps(run_sim(a.hard, a.sessions, a.seed, a.cross_rule), indent=1))
        return

    against_sim = bool(a.url) and ("127.0.0.1" in a.url or "localhost" in a.url) and a.url != config.GATEWAY_URL
    gw = Gateway(url=a.url or config.GATEWAY_URL, token=a.token or config.GATEWAY_TOKEN,
                 real=True if against_sim else config.ALLOW_REAL)
    key = a.key or venue.load_key()
    client = LiveClient(gw, key)
    out = (config.LAB / "broker" / "fake_run" / "bench") if against_sim else (config.LIVE / "bench")
    writes = (lambda: (True, "")) if against_sim else live_writes_allowed
    loop = BrokerLoop(client, out, load_policy(), writes_allowed=writes,
                      control_file=config.LIVE / "broker_control.json",
                      status_file=out.parent / "broker_status.json")
    print(f"broker: {'fake bazaar' if against_sim else 'live'} | key {'present' if key else 'MISSING'} | "
          f"writes {'on' if writes()[0] else 'off (' + writes()[1] + ')'} | out {out}", flush=True)
    while True:
        if not client.has_key:
            key = venue.load_key()                    # the venue may open while we run
            if key:
                client._key = key
                print("broker: key found, matching on", flush=True)
        started = time.time()
        try:
            if client.has_key:
                loop.poll()
            else:
                loop.heartbeat(loop.last_tick)
        except Exception as e:  # noqa: BLE001 - the process must not die
            loop._err(loop.last_tick, "loop", e)
        time.sleep(max(0.05, a.poll - (time.time() - started)))


if __name__ == "__main__":
    main()
