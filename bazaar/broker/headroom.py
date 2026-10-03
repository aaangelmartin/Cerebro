"""How much a broker can gain over the free stall on the Market Test, and where the lost share goes.

    python -m bazaar.broker.headroom --seeds 300        # bounds per trader model
    python -m bazaar.broker.headroom --real             # the recorded sessions, on estimated limits

Three upper bounds per session, all on the TRUE limits (the simulator knows them):

* all        every trader, whenever it was in the book: the classic sorted pairing.
* copresent  only pairs that were in the book at the same tick.
* cross      only pairs whose quotes crossed at some tick while both were there. Under the "quotes" rule this is
             the most a broker with perfect foresight could realise.

And three brokers with information no real broker has, to see which information is worth anything:

* oracle_now        knows every true limit, nothing about the future: best pairing of this tick's crossing pairs.
* oracle_lookahead  also knows the future quotes and the leaving tick of every trader in the book now.
* oracle_reserve    knows the limits and who leaves next tick, and holds an intramarginal trader back from an
                    extramarginal partner against a fixed reserve price.

Saturday's finding (see IMPROVEMENT_NOTES.md): when traders arrive one by one, as in every recorded session, the
first two do not beat the stall and the third gains 1 to 2 points with twice as many wins as losses. What is lost
is lost to traders that never met a crossing partner while they were in the book, which only knowing the arrivals
to come would fix.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path
from typing import Callable

from .engine import Match, hungarian_max, midpoint_price
from .sim_book import HARD, NORMAL, REAL, Planner, SimSession, SimTrader, engine_planner, play, stall_planner

# Shape of the real Saturday sessions b7, b25, b43, b60: 20 traders arriving one by one over ticks 0-11. Most shade
# hard and relax in equal steps to their limit, then leave (the sellers that ran their course ended at 0.79 to 0.82
# of their first ask, six cases; buyers started at about 0.70 of their last bid); a quarter leave earlier; the rest
# shade little and move slowly, or never move.
STRUCTURED = {
    "traders": 20, "ticks": 16, "arrive": (0, 11), "buyer_value": (30, 125), "seller_cost": (18, 105),
    "relax_p": 0.60, "slow_p": 0.25, "early_p": 0.25, "buy_shade": 0.30, "sell_shade": 0.25, "shade_noise": 0.04,
    "relax_steps": (2, 5), "slow_shade": (0.05, 0.20), "slow_steps": (4, 8), "slow_life": (2, 6),
    "firm_shade": (0.0, 0.10), "firm_life": (1, 6),
}


def structured_session(seed: int, params: dict | None = None, run: str = "b1") -> SimSession:
    """A session with the structure seen in the recordings (STRUCTURED). Checked against them with the stall:
    5.5 pairs matched (real 5.0), 37 % of traders seen for one tick (real 45 %), unmatched ones visible 3.6 ticks
    (real 3.3)."""
    p = {**STRUCTURED, **(params or {})}
    rng = random.Random(seed)
    n = p["traders"]
    n_buy = n // 2 + rng.choice([-1, 0, 0, 1])
    out = []
    for i in range(n):
        side = "buy" if i < n_buy else "sell"
        lim = rng.randint(*p["buyer_value"]) if side == "buy" else rng.randint(*p["seller_cost"])
        u, arrive, firm = rng.random(), rng.randint(*p["arrive"]), False
        if u < p["relax_p"]:
            sh = (p["buy_shade"] if side == "buy" else p["sell_shade"]) + rng.uniform(-p["shade_noise"], p["shade_noise"])
            steps = rng.randint(*p["relax_steps"])
            life = steps + 1
            if rng.random() < p["early_p"]:
                life = rng.randint(1, steps)
        elif u < p["relax_p"] + p["slow_p"]:
            sh, steps, life = rng.uniform(*p["slow_shade"]), rng.randint(*p["slow_steps"]), rng.randint(*p["slow_life"])
        else:
            sh, steps, life, firm = rng.uniform(*p["firm_shade"]), 1, rng.randint(*p["firm_life"]), True
        q0 = lim * (1 + sh) if side == "sell" else lim * (1 - sh)
        q0 = int(math.ceil(q0)) if side == "sell" else max(1, int(math.floor(q0)))
        leave = max(arrive + 1, min(p["ticks"], arrive + life))
        out.append(SimTrader(id=f"{run}-{i}", side=side, limit=lim, q0=q0, firm=firm, patience=0, mode="lin",
                             rate=0.3, step=abs(q0 - lim) / steps, arrive=arrive, leave=leave))
    rng.shuffle(out)
    return SimSession(out, p["ticks"], run)


FAMILIES: dict[str, Callable[[int], SimSession]] = {
    "normal": lambda seed: SimSession.generate(seed, None, False),
    "hard": lambda seed: SimSession.generate(seed, None, True),
    "real": lambda seed: SimSession.generate(seed, REAL, False),
    "structured": structured_session,
}


# --------------------------------------------------------------------------- upper bounds

def best_gain(sess: SimSession, feasible: str = "cross") -> float:
    """Most gain between true limits over pairs that are feasible: "all" | "copresent" | "cross"."""
    buyers = [t for t in sess.traders if t.side == "buy"]
    sellers = [t for t in sess.traders if t.side == "sell"]
    if not buyers or not sellers:
        return 0.0
    weights = []
    for s in sellers:
        row = []
        for b in buyers:
            if feasible == "all":
                ok = True
            elif feasible == "copresent":
                ok = max(s.arrive, b.arrive) < min(s.leave, b.leave)
            else:
                ok = any(b.quote(t) >= s.quote(t) for t in range(max(s.arrive, b.arrive), min(s.leave, b.leave)))
            row.append(float(max(0, b.limit - s.limit)) if ok else 0.0)
        weights.append(row)
    return sum(weights[i][j] for i, j in hungarian_max(weights))


# --------------------------------------------------------------------------- brokers that know too much

def _split(sess: SimSession, book: list[dict]) -> tuple[list[SimTrader], list[SimTrader]]:
    by = {t.id: t for t in sess.traders}
    live = [by[o["id"]] for o in book]
    return [t for t in live if t.side == "buy"], [t for t in live if t.side == "sell"]


def _matches(sess: SimSession, t: int, buyers: list[SimTrader], sellers: list[SimTrader],
             weights: list[list[float]]) -> list[Match]:
    return [Match(sellers[i].id, buyers[j].id, midpoint_price(sellers[i].quote(t), buyers[j].quote(t)), sess.run)
            for i, j in hungarian_max(weights) if weights[i][j] > 0]


def oracle_now(sess: SimSession) -> Planner:
    def plan(t: int, book: list[dict]) -> list[Match]:
        buyers, sellers = _split(sess, book)
        if not buyers or not sellers:
            return []
        w = [[b.limit - s.limit + 0.001 if b.quote(t) >= s.quote(t) else 0.0 for b in buyers] for s in sellers]
        return _matches(sess, t, buyers, sellers, w)
    return plan


def oracle_lookahead(sess: SimSession) -> Planner:
    def plan(t: int, book: list[dict]) -> list[Match]:
        buyers, sellers = _split(sess, book)
        if not buyers or not sellers:
            return []
        weights, now = [], {}
        for i, s in enumerate(sellers):
            row = []
            for j, b in enumerate(buyers):
                first = next((u for u in range(t, min(s.leave, b.leave)) if b.quote(u) >= s.quote(u)), None)
                ok = first is not None and b.limit > s.limit
                row.append(b.limit - s.limit + (0.001 if first == t else 0.0) if ok else 0.0)
                now[(i, j)] = first == t
            weights.append(row)
        return [Match(sellers[i].id, buyers[j].id, midpoint_price(sellers[i].quote(t), buyers[j].quote(t)), sess.run)
                for i, j in hungarian_max(weights) if weights[i][j] > 0 and now[(i, j)]]   # the rest wait their tick
    return plan


def oracle_reserve(reserve: float) -> Callable[[SimSession], Planner]:
    def make(sess: SimSession) -> Planner:
        def plan(t: int, book: list[dict]) -> list[Match]:
            buyers, sellers = _split(sess, book)
            if not buyers or not sellers:
                return []
            weights = []
            for s in sellers:
                row = []
                for b in buyers:
                    w = 0.0
                    if b.quote(t) >= s.quote(t):
                        if b.limit >= reserve and s.limit <= reserve:
                            w = b.limit - s.limit + 100.0
                        elif b.leave == t + 1 or s.leave == t + 1:
                            w = b.limit - s.limit + 0.001
                    row.append(w)
                weights.append(row)
            return _matches(sess, t, buyers, sellers, weights)
        return plan
    return make


def compare(seeds: int = 300, families: dict[str, Callable[[int], SimSession]] | None = None, policy: dict | None = None,
            reserve: float = 60.0) -> list[dict]:
    """Per family: the stall, the engine with `policy`, the three oracles (mean efficiency, wins and losses against
    the stall) and the stall's share of each upper bound."""
    out = []
    for name, make in (families or FAMILIES).items():
        ok = [seed for seed in range(seeds) if make(seed).max_gain() > 0]
        brokers = {
            "stall": lambda s: (stall_planner(), None),
            "engine": lambda s: engine_planner(policy),
            "oracle_now": lambda s: (oracle_now(s), None),
            "oracle_lookahead": lambda s: (oracle_lookahead(s), None),
            "oracle_reserve": lambda s: (oracle_reserve(reserve)(s), None),
        }
        effs: dict[str, list[float]] = {}
        gain = 0.0
        for label, broker in brokers.items():
            effs[label] = []
            for seed in ok:
                sess = make(seed)
                planner, eng = broker(sess)
                effs[label].append(play(sess, planner, eng))
                if label == "stall":
                    gain += sess.realised
        bounds = {f: sum(best_gain(make(seed), f) for seed in ok) for f in ("all", "copresent", "cross")}
        row = {"family": name, "sessions": len(ok),
               "stall_share_of": {f: round(gain / b, 4) if b else None for f, b in bounds.items()}}
        base = effs["stall"]
        for label, e in effs.items():
            row[label] = {"mean": round(statistics.mean(e), 4),
                          "wins": sum(x > y + 1e-9 for x, y in zip(e, base)),
                          "losses": sum(x < y - 1e-9 for x, y in zip(e, base))}
        out.append(row)
    return out


# --------------------------------------------------------------------------- the recorded sessions

def guess_limit(side: str, prices: list[int], left_early: bool) -> float:
    """A rough limit for a recorded trader, from the pattern in STRUCTURED: one that ran its course and left ended
    at its limit; one still moving has about one more step; a fresh quote sits 25 % (sellers) or 30 % (buyers) away."""
    q, q0 = prices[-1], prices[0]
    if len(prices) >= 3 and len(set(prices[-3:])) == 1:
        return float(q)
    if len(prices) >= 3:
        step = abs(prices[-1] - prices[-2])
        return float(q) if left_early else float(q + step if side == "buy" else q - step)
    return max(float(q), q0 / 0.70) if side == "buy" else min(float(q), q0 * 0.80)


def real_session(rows: list[dict]) -> dict:
    """Where a recorded session's gains went, on guessed limits: realised, lost to pairs that never crossed while
    both were in the book, and lost to traders that were never in the book together. A trader we matched is taken
    as gone from that tick on, so the bounds are what the book showed, not what a longer stay would have allowed."""
    ticks = [r for r in rows if r.get("type") == "tick"]
    if not ticks:
        return {}
    t0, last = ticks[0]["tick"], ticks[-1]["tick"]
    quotes: dict[str, dict[int, int]] = {}
    side: dict[str, str] = {}
    pairs = []
    for r in ticks:
        for o in r.get("bench") or []:
            buy = bool((o.get("give") or {}).get("cash"))
            side[o["id"]] = "buy" if buy else "sell"
            quotes.setdefault(o["id"], {})[r["tick"]] = int(o["give"]["cash"] if buy else o["want"]["cash"])
        pairs += [(x["sell"], x["buy"]) for x in r.get("results") or [] if x.get("status") == "ok"]
    matched = {k for pair in pairs for k in pair}
    lim = {k: guess_limit(side[k], [q[t] for t in sorted(q)], k not in matched and max(q) < last)
           for k, q in quotes.items()}
    buyers = [k for k in quotes if side[k] == "buy"]
    sellers = [k for k in quotes if side[k] == "sell"]

    def best(feasible: str) -> float:
        weights = []
        for s in sellers:
            row = []
            for b in buyers:
                both = set(quotes[s]) & set(quotes[b])
                ok = feasible == "all" or (both and (feasible == "copresent" or any(quotes[b][t] >= quotes[s][t] for t in both)))
                row.append(max(0.0, lim[b] - lim[s]) if ok else 0.0)
            weights.append(row)
        return sum(weights[i][j] for i, j in hungarian_max(weights)) if weights and weights[0] else 0.0

    realised = sum(max(0.0, lim[b] - lim[s]) for s, b in pairs if s in lim and b in lim)
    stall_pairs, used = 0, set()
    for r in ticks:                                   # what the stall would have paired, on the same books
        offers = [o for o in r.get("bench") or [] if o["id"] not in used]
        asks = sorted((quotes[o["id"]][r["tick"]], o["id"]) for o in offers if side[o["id"]] == "sell")
        bids = sorted(((quotes[o["id"]][r["tick"]], o["id"]) for o in offers if side[o["id"]] == "buy"), reverse=True)
        for (ask, s), (bid, b) in zip(asks, bids):
            if bid < ask:
                break
            used.update((s, b))
            stall_pairs += 1
    out = {"traders": len(quotes), "ticks": last - t0 + 1, "pairs": len(pairs), "stall_pairs": stall_pairs,
           "same_as_stall": {k for p in pairs for k in p} == used,
           "realised": round(realised, 1)}
    for f in ("all", "copresent", "cross"):
        b = best(f)
        out[f"best_{f}"] = round(b, 1)
        out[f"share_{f}"] = round(realised / b, 3) if b else None
    return out


def real_sessions(bench_dir: Path | None = None) -> dict[str, dict]:
    if bench_dir is None:
        from .. import config
        bench_dir = config.LIVE / "bench"
    out = {}
    for path in sorted(Path(bench_dir).glob("*-b*.jsonl")):
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        res = real_session(rows)
        if res:
            out[path.stem] = res
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=300)
    ap.add_argument("--real", action="store_true", help="the recorded sessions instead of the simulator")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = real_sessions() if a.real else compare(a.seeds)
    if a.json:
        print(json.dumps(res, indent=1, default=str))
    elif a.real:
        for name, r in res.items():
            print(f"{name}: {r['pairs']} pairs (stall {r['stall_pairs']}, same traders: {r['same_as_stall']})  "
                  f"share of all {r['share_all']}, of copresent {r['share_copresent']}, of crossing {r['share_cross']}")
    else:
        for r in res:
            line = f"{r['family']:10s} n={r['sessions']}  stall share of all/copresent/cross " \
                   f"{r['stall_share_of']['all']}/{r['stall_share_of']['copresent']}/{r['stall_share_of']['cross']}"
            for label in ("stall", "engine", "oracle_now", "oracle_lookahead", "oracle_reserve"):
                line += f" | {label} {r[label]['mean']:.4f} (+{r[label]['wins']}/-{r[label]['losses']})"
            print(line)


if __name__ == "__main__":
    main()
