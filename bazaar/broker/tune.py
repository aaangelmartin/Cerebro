"""Tune the broker policy between sessions (run by the Lab or by hand):

    python -m bazaar.broker.tune                     # fit the bench from recorded sessions, grid-search, print
    python -m bazaar.broker.tune --write             # ... and write data/lab/broker/policy.json
    python -m bazaar.broker.tune --write --claude    # ... plus a short Claude summary (purpose "broker_policy")

Recorded sessions (data/live/bench/<session>.jsonl, written by run.py) carry every bench quote per tick, but not the
hidden limits, so a recorded session cannot be replayed counterfactually once we matched someone. Instead:
1. `fit_params` reads the quote trajectories and fits the synthetic generator (shade, firm share, patience,
   relaxation speed, linear share, leavers, trader count, limit ranges);
2. `search` grid-searches the policy thresholds on fresh synthetic sessions drawn from those fitted params, normal
   and hard, keeping only candidates that never lose to the stall on the 10th percentile;
3. `replay` re-runs the engine on each recorded book tick by tick and reports what it would plan now vs what was sent.
"""
from __future__ import annotations

import argparse
import itertools
import json
import statistics
import time
from pathlib import Path

from .. import config
from .engine import BenchEngine, bench_side, estimate_limit, load_policy, merge_policy, run_of
from .sim_book import HARD, NORMAL, benchmark

POLICY_FILE = config.LAB / "broker" / "policy.json"


def load_sessions(dirs: list[Path] | None = None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for d in dirs or [config.LIVE / "bench"]:
        for p in sorted(Path(d).glob("*.jsonl")):
            if p.name.startswith(("public-", "results")):
                continue
            rows = []
            for line in p.read_text().splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
            if any(r.get("type") == "tick" for r in rows):
                out[p.stem] = rows
    return out


def trajectories(rows: list[dict]) -> dict[str, dict]:
    """offer id -> {side, quotes [(tick, price)], matched, last_tick}."""
    tr: dict[str, dict] = {}
    matched = set()
    last_tick = None
    for r in rows:
        if r.get("type") != "tick":
            continue
        last_tick = r["tick"]
        for o in r.get("bench") or []:
            side = bench_side(o)
            if not side:
                continue
            t = tr.setdefault(str(o["id"]), {"side": side[0], "quotes": [], "matched": False})
            if not t["quotes"] or t["quotes"][-1][0] != r["tick"]:
                t["quotes"].append((r["tick"], side[1]))
        for res in r.get("results") or []:
            if res.get("status") == "ok":
                matched.update({str(res["sell"]), str(res["buy"])})
    for k, t in tr.items():
        t["matched"] = k in matched
        t["last_tick"] = t["quotes"][-1][0]
        t["session_last"] = last_tick
    return tr


def fit_params(sessions: dict[str, list[dict]], base: dict | None = None) -> dict:
    """Fit sim_book generator params from recorded quote trajectories. Falls back to `base` where data is thin."""
    base = dict(base or NORMAL)
    prof = merge_policy(None)["profiles"]["normal"]
    shades, rates, patience, firm, moved, linear, leave_age, counts, buys, sells = [], [], [], 0, 0, 0, [], [], [], []
    stayed = 0
    for rows in sessions.values():
        trs = trajectories(rows)
        if not trs:
            continue
        counts.append(len(trs))
        start = min(t["quotes"][0][0] for t in trs.values())
        for t in trs.values():
            prices = [p for _, p in t["quotes"]]
            sgn = -1 if t["side"] == "sell" else 1
            mv = [(prices[i] - prices[i - 1]) * sgn for i in range(1, len(prices))]
            est, status = estimate_limit(t["side"], prices, prof["prior_shade"], prof)
            (buys if t["side"] == "buy" else sells).append(est)
            if any(m > 0 for m in mv):
                moved += 1
                patience.append(next(i for i, m in enumerate(mv) if m > 0))
                pos = [m for m in mv if m > 0]
                if len(pos) >= 2:
                    rho = pos[1] / pos[0]
                    if rho >= 0.9:
                        linear += 1
                    else:
                        rates.append(1 - rho)
                if status in ("geo", "stopped") and est > 0:
                    shades.append(abs(prices[0] - est) / est)
            elif len(prices) >= 6:
                firm += 1
            if not t["matched"] and t["last_tick"] < (t["session_last"] or 0):
                leave_age.append(t["last_tick"] - start + 1)
            else:
                stayed += 1
    fitted = dict(base)
    n_obs = moved + firm
    if counts:
        fitted["traders"] = int(round(statistics.median(counts)))
    if len(shades) >= 4:
        fitted["shade"] = (max(0.0, _q(shades, 0.1)), min(0.8, _q(shades, 0.9)))
    if n_obs >= 6:
        fitted["firm_p"] = round(firm / n_obs, 3)
    if len(patience) >= 4:
        fitted["patience"] = (int(_q(patience, 0.1)), max(int(_q(patience, 0.9)), int(_q(patience, 0.1))))
    if len(rates) >= 4:
        fitted["geo_rate"] = (max(0.02, _q(rates, 0.1)), min(0.95, _q(rates, 0.9)))
    if moved >= 6:
        fitted["linear_p"] = round(linear / moved, 3)
    total = len(leave_age) + stayed
    if total >= 8:
        fitted["leave_p"] = round(len(leave_age) / total, 3)
        if len(leave_age) >= 3:
            fitted["leave_at"] = (max(1, int(_q(leave_age, 0.1))), max(2, int(_q(leave_age, 0.9))))
    if len(buys) >= 4 and len(sells) >= 4:
        fitted["buyer_value"] = (int(min(buys)), int(max(buys)) + 1)
        fitted["seller_cost"] = (int(min(sells)), int(max(sells)) + 1)
    fitted["_evidence"] = {"sessions": len(sessions), "traders": sum(counts), "shades": len(shades),
                           "rates": len(rates), "leavers": len(leave_age)}
    return fitted


def _q(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, int(q * (len(s) - 1))))]


GRID = {
    "hazard": [0.04, 0.08, 0.12, 0.2],
    "wait_ticks": [1.0, 2.0, 4.0],
    "prior_shade": [0.15, 0.2, 0.3],
    "endgame_ticks": [1, 2, 3],
}


def search(params_normal: dict, params_hard: dict, seeds: int = 150, base: dict | None = None,
           cross_rule: str = "quotes") -> dict:
    """Grid-search each profile on its own fitted sessions. Returns {"policy": ..., "table": ...}."""
    pol = merge_policy(base)
    table = {}
    sim_params = {"normal": {k: v for k, v in params_normal.items() if not k.startswith("_")},
                  "hard": {k: v for k, v in params_hard.items() if not k.startswith("_")}}
    for name, hard in (("normal", False), ("hard", True)):
        rows = []
        for combo in itertools.product(*GRID.values()):
            over = dict(zip(GRID.keys(), combo))
            cand = merge_policy({**pol, "profiles": {name: {**pol["profiles"][name], **over}}})
            r = benchmark(seeds, hard, cand, params=sim_params[name], start=10_000, cross_rule=cross_rule)
            rows.append({**over, **{k: r[k] for k in ("engine", "stall", "engine_p10", "stall_p10", "engine_losses")}})
        safe = [r for r in rows if r["engine_p10"] >= r["stall_p10"] - 0.01] or rows
        best = max(safe, key=lambda r: (r["engine"], -r["engine_losses"]))
        pol["profiles"][name].update({k: best[k] for k in GRID})
        table[name] = {"best": best, "top": sorted(rows, key=lambda r: -r["engine"])[:5]}
    return {"policy": pol, "table": table}


def replay(rows: list[dict], policy: dict | None = None) -> dict:
    """Re-run the engine on a recorded session: how often would it plan what was sent?"""
    eng = BenchEngine(policy or load_policy())
    same, differ, ticks = 0, 0, 0
    for r in rows:
        if r.get("type") != "tick" or not r.get("bench"):
            continue
        ticks += 1
        eng.observe(r["tick"], r["bench"])
        plan = {(m.sell, m.buy) for m in eng.plan(r["tick"])}
        sent = {(x["sell"], x["buy"]) for x in r.get("results") or []}
        same += len(plan & sent)
        differ += len(plan ^ sent)
        for x in r.get("results") or []:
            if x.get("status") == "ok":
                s_, b_ = eng._by_offer(x["sell"]), eng._by_offer(x["buy"])
                est = (b_.est - s_.est) if (s_ and b_) else 0.0
                eng.note_matched(x["sell"], x["buy"], max(0.0, est), x.get("kind", "cross"))
    runs = {run_of(t.offer_id) for t in eng.traders.values()}
    return {"ticks": ticks, "same": same, "differ": differ,
            "est_efficiency": {r: eng.efficiency_estimate(r) for r in runs}, "rule": eng.rule}


def claude_summary(report: dict) -> str | None:
    try:
        from ..llm import client
    except Exception:  # noqa: BLE001
        return None
    try:
        r = client.ask(purpose="broker_policy", max_tokens=500,
                       system="You review a market-making broker's tuning results for a trading game. Be brief, "
                              "concrete, in Spanish, max 8 bullet points: what changed, risks, what to watch next.",
                       messages=[{"role": "user", "content": json.dumps(report, default=str)[:12000]}])
        return r.text
    except Exception as e:  # noqa: BLE001
        return f"(no summary: {type(e).__name__})"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Tune the broker policy from recorded bench sessions")
    ap.add_argument("--dir", action="append", help="folder(s) with <session>.jsonl (default data/live/bench)")
    ap.add_argument("--seeds", type=int, default=150)
    ap.add_argument("--write", action="store_true", help=f"write {POLICY_FILE}")
    ap.add_argument("--claude", action="store_true")
    ap.add_argument("--cross-rule", default=None, help="quotes | limits (default: what the sessions showed)")
    a = ap.parse_args(argv)
    sessions = load_sessions([Path(d) for d in a.dir] if a.dir else None)
    hard_s = {k: v for k, v in sessions.items() if any(r.get("profile") == "hard" for r in v if r.get("type") == "start")}
    norm_s = {k: v for k, v in sessions.items() if k not in hard_s}
    pn = fit_params(norm_s, NORMAL) if norm_s else dict(NORMAL)
    ph = fit_params(hard_s, HARD) if hard_s else dict(HARD)
    rules = [r.get("rule") for v in sessions.values() for r in v if r.get("type") == "tick" and r.get("rule")]
    rule = a.cross_rule or ("limits" if "limits" in rules else "quotes")
    base = load_policy()
    if "limits" in rules:
        base["cross_rule"] = "limits"                  # a probe went through: keep matching inside limits
    res = search(pn, ph, a.seeds, base, cross_rule=rule)
    report = {"tuned_at": time.strftime("%Y-%m-%d %H:%M:%S"), "sessions": sorted(sessions), "cross_rule": rule,
              "fitted_normal": pn, "fitted_hard": ph, "table": res["table"],
              "replay": {k: replay(v, res["policy"]) for k, v in list(sessions.items())[-6:]}}
    if a.claude:
        report["claude"] = claude_summary({k: report[k] for k in ("sessions", "fitted_normal", "fitted_hard", "table")})
    print(json.dumps({k: report[k] for k in ("sessions", "cross_rule", "table")}, indent=1, default=str))
    if report.get("claude"):
        print(report["claude"])
    if a.write:
        POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
        pol = res["policy"]
        pol["_tuned"] = {"at": report["tuned_at"], "sessions": len(sessions), "cross_rule": rule}
        POLICY_FILE.write_text(json.dumps(pol, indent=1))
        (POLICY_FILE.parent / "tune_report.json").write_text(json.dumps(report, indent=1, default=str))
        print(f"wrote {POLICY_FILE}")


if __name__ == "__main__":
    main()
