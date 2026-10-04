"""The Lab learns the broker: Market Test sessions in, `broker`-scope lessons out.

Each recorded session (data/live/bench/results.jsonl + the session files' start records) becomes a row with its
official efficiency, the free stall's efficiency and the policy version the broker used. After every new session
the Lab tries a small grid of policy overlays in the simulator (normal, hard and the profile fitted to the real
sessions) against the policy in use, and proposes the best one as a lesson with its predicted efficiency delta.
El cerebro reads those lessons and decides (with its council) whether to write the overlay; the broker applies it
only at a session start. Nothing here changes the broker by itself.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bazaar.broker import policy_overlay as PO
from bazaar.broker import sim_book
from bazaar.broker.engine import load_policy
from bazaar.core.types import Lesson

MIN_DELTA = 0.004           # a candidate must beat the current policy by this much on average ...
MAX_HARD_LOSS = 0.002       # ... and may not lose more than this on any profile
SEEDS = 150

# candidate overlays: one knob at a time, inside PO bounds
GRID: list[dict[str, Any]] = [
    {"profiles": {"normal": {"wait_ticks": 0.0}, "hard": {"wait_ticks": 0.0}}},
    {"profiles": {"normal": {"wait_ticks": 1.0}, "hard": {"wait_ticks": 1.0}}},
    {"profiles": {"normal": {"wait_ticks": 3.0}, "hard": {"wait_ticks": 3.0}}},
    {"profiles": {"normal": {"endgame_ticks": 1}, "hard": {"endgame_ticks": 1}}},
    {"profiles": {"normal": {"endgame_ticks": 4}, "hard": {"endgame_ticks": 4}}},
    {"profiles": {"normal": {"hazard": 0.3}, "hard": {"hazard": 0.4}}},
    {"profiles": {"normal": {"hazard": 0.05}, "hard": {"hazard": 0.1}}},
    {"profiles": {"normal": {"firm_ticks": 2}, "hard": {"firm_ticks": 2}}},
    {"profiles": {"normal": {"prior_shade": 0.25}, "hard": {"prior_shade": 0.3}}},
    {"profiles": {"normal": {"tt_bonus": 3.0}, "hard": {"tt_bonus": 3.0}}},
]


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def sessions(live: Path) -> list[dict]:
    """One row per finished Market Test session, oldest first."""
    bench = Path(live) / "bench"
    starts: dict[str, dict] = {}
    for f in sorted(bench.glob("*.jsonl")) if bench.exists() else []:
        if f.name == "results.jsonl":
            continue
        for r in _read_jsonl(f):
            if r.get("type") == "start":
                starts[f.stem] = r
                break
    rows = []
    for r in _read_jsonl(bench / "results.jsonl"):
        sc = r.get("score") or {}
        st = starts.get(str(r.get("session")), {})
        eff, stall = sc.get("bench_efficiency"), r.get("stall_efficiency")
        rows.append({"run": r.get("run"), "session": r.get("session"), "tick": r.get("tick"),
                     "efficiency": eff, "stall_efficiency": stall, "bench_points": sc.get("bench_points"),
                     "vs_stall": round(float(eff) - float(stall), 4) if eff is not None and stall is not None else None,
                     "policy_version": st.get("policy_version") or (r.get("stats") or {}).get("policy_version"),
                     "profile": (r.get("stats") or {}).get("profile"),
                     "matches": (r.get("stats") or {}).get("matches"),
                     "refused": (r.get("stats") or {}).get("refused")})
    return rows


def evaluate(policy: dict, seeds: int = SEEDS) -> dict[str, float]:
    """Mean simulated efficiency of `policy` per profile (the stall's too, for reference)."""
    out = {}
    for name, params, hard in (("normal", None, False), ("hard", None, True), ("real", sim_book.REAL, False)):
        b = sim_book.benchmark(seeds, hard=hard, params=params, policy=policy)
        out[name] = b["engine"]
        out[name + "_stall"] = b["stall"]
    return out


def best_candidate(base: dict, current_overlay: dict, seeds: int = SEEDS, grid: list[dict] | None = None) -> dict | None:
    """The grid overlay (on top of the current one) that beats the policy in use most, or None."""
    cur_policy = PO.apply(base, current_overlay)
    cur = evaluate(cur_policy, seeds)
    best = None
    for cand in grid if grid is not None else GRID:
        clean, rejected = PO.validate(cand)
        if rejected or not clean:
            continue
        merged = PO.apply(PO.apply({}, current_overlay), clean) if current_overlay else clean
        got = evaluate(PO.apply(base, merged), seeds)
        deltas = {k: round(got[k] - cur[k], 4) for k in ("normal", "hard", "real")}
        mean = round(sum(deltas.values()) / 3, 4)
        if mean >= MIN_DELTA and min(deltas.values()) >= -MAX_HARD_LOSS and (best is None or mean > best["delta"]):
            best = {"overlay": merged, "knob": clean, "delta": mean, "deltas": deltas, "sim": got, "current": cur}
    return best


def learn(store, live: Path, lab: Path, seeds: int = SEEDS, grid: list[dict] | None = None) -> dict:
    """Ingest the sessions and, when there is a new one, propose the best overlay as a broker lesson.
    Returns {"sessions": n, "new": bool, "lesson": id|None}."""
    rows = sessions(live)
    state_p = Path(lab) / "broker_sessions.json"
    try:
        prev = json.loads(state_p.read_text())
    except (OSError, ValueError):
        prev = {}
    seen = int(prev.get("n") or 0)
    out = {"sessions": len(rows), "new": len(rows) > seen, "lesson": None}
    if not out["new"]:
        return out
    cur = PO.load(Path(live) / "broker_policy.json")
    base = load_policy()
    best = best_candidate(base, cur["policy"], seeds, grid)
    doc = {"n": len(rows), "sessions": rows[-12:], "overlay_version": cur["version"],
           "mean_vs_stall": round(sum(r["vs_stall"] for r in rows if r["vs_stall"] is not None)
                                  / max(1, sum(1 for r in rows if r["vs_stall"] is not None)), 4),
           "best_candidate": best}
    if best is not None:
        lid = "BR" + PO.version_of(best["overlay"])[:6]
        rule = (f"Broker policy {json.dumps(best['knob'], sort_keys=True)} beats the policy in use by "
                f"{best['delta']:+.4f} efficiency in the simulator (normal {best['deltas']['normal']:+.4f}, hard "
                f"{best['deltas']['hard']:+.4f}, fitted to real sessions {best['deltas']['real']:+.4f}); real sessions "
                f"so far average {doc['mean_vs_stall']:+.4f} vs the free stall over {len(rows)} sessions. "
                "Apply it as broker_policy at the next session start and compare the next sessions.")
        if store.get(lid) is None:
            store.upsert(Lesson(id=lid, scope="broker", rule=rule, n=len(rows), sources=1, status="shadow",
                                weight=0.0, created_by="lab",
                                evidence=[f"bench:{r['session']}" for r in rows[-6:]],
                                params={"broker_policy": best["overlay"],
                                        "prediction": {"kind": "broker_eff", "delta": best["delta"]},
                                        "sim": best["sim"], "sim_current": best["current"]},
                                backtest={"n": seeds * 3, "lift": best["delta"]}), by="lab")
        out["lesson"] = lid
    state_p.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str))
    tmp.replace(state_p)
    return out
