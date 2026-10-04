"""Synthetic Market Test: traders with hidden limits, shaded quotes that relax with impatience, firm traders, early
leavers. Evaluates a broker policy by efficiency = realised gains between true limits / max possible gains.

    python -m bazaar.broker.sim_book --seeds 300            # engine vs auto stall, normal and hard
    python -m bazaar.broker.sim_book --seeds 300 --json

The generator is a guess at the real bench, deliberately wide: geometric and linear relaxation, patience before
relaxing, late arrivals, integer quotes. `params` can be refitted from recorded sessions (see tune.py).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable

from .engine import BenchEngine, Match, merge_policy, midpoint_price, stall_plan

NORMAL = {
    "traders": 10, "ticks": 16,
    "buyer_value": (20, 100), "seller_cost": (20, 100),
    "shade": (0.02, 0.40),
    "firm_p": 0.20,
    "patience": (0, 5),           # ticks before an impatient trader starts relaxing
    "geo_rate": (0.15, 0.45),     # share of the remaining gap closed per tick
    "linear_p": 0.30,             # share of relaxing traders that move in fixed steps instead
    "linear_steps": (3, 8),       # steps to reach the limit
    "leave_p": 0.30,              # share that leaves before the end
    "leave_at": (3, 12),
    "late_p": 0.20,               # share arriving after the start
    "late_at": (1, 6),
}
HARD = {**NORMAL, "traders": 12, "firm_p": 0.35, "shade": (0.10, 0.45), "patience": (0, 2),
        "geo_rate": (0.25, 0.60), "leave_p": 0.55, "leave_at": (2, 8), "late_at": (1, 4)}
# Fitted to the real Saturday sessions b7 and b25 (stall 0.892 and 0.931 there; this profile gives 0.915):
# 20 traders arriving one by one over the session, quotes close to the limits that relax a few primas per tick,
# traders with a chance at the going price (about 68) stay 8-14 ticks, the others give up after 1-5. Checked
# against the recordings: ~9.5 traders matched (real 8-10), 38 % seen for a single tick (real 45 %), unmatched
# traders visible 3.2 ticks (real 3.2).
REAL = {**NORMAL, "traders": 20, "ticks": 14, "buyer_value": (20, 110), "seller_cost": (20, 130),
        "shade": (0.0, 0.20), "firm_p": 0.15, "patience": (0, 1), "linear_steps": (2, 5),
        "late_p": 1.0, "late_at": (0, 11), "life": (8, 14), "life_short_p": 0.0, "life_out": (1, 5), "mid": 68}


@dataclass
class SimTrader:
    id: str
    side: str
    limit: int
    q0: int
    firm: bool
    patience: int
    mode: str            # geo | lin
    rate: float
    step: float
    arrive: int
    leave: int           # present while arrive <= t < leave
    matched: bool = False

    def quote(self, t: int) -> int:
        age = t - self.arrive
        gap = self.q0 - self.limit                       # >0 for sellers, <0 for buyers
        if not self.firm and age > self.patience:
            k = age - self.patience
            gap = gap * (1 - self.rate) ** k if self.mode == "geo" else math.copysign(max(0.0, abs(gap) - self.step * k), gap)
        q = self.limit + gap
        return int(math.ceil(q - 1e-9)) if self.side == "sell" else int(math.floor(q + 1e-9))

    def present(self, t: int) -> bool:
        return self.arrive <= t < self.leave and not self.matched


@dataclass
class SimSession:
    traders: list[SimTrader]
    ticks: int
    run: str = "b1"
    realised: float = 0.0
    matches: list[dict] = field(default_factory=list)
    refused: int = 0
    cross_rule: str = "quotes"       # quotes: price inside [ask, bid]; limits: price inside the hidden limits

    @classmethod
    def generate(cls, seed: int, params: dict | None = None, hard: bool = False, run: str = "b1",
                 cross_rule: str = "quotes") -> "SimSession":
        p = {**(HARD if hard else NORMAL), **(params or {})}
        rng = random.Random(seed)
        n = p["traders"]
        n_buy = n // 2 + rng.choice([-1, 0, 0, 1]) if n >= 6 else n // 2
        out = []
        for i in range(n):
            side = "buy" if i < n_buy else "sell"
            lim = rng.randint(*p["buyer_value"]) if side == "buy" else rng.randint(*p["seller_cost"])
            sh = rng.uniform(*p["shade"])
            q0 = lim * (1 + sh) if side == "sell" else lim * (1 - sh)
            q0 = int(math.ceil(q0)) if side == "sell" else max(1, int(math.floor(q0)))
            mode = "lin" if rng.random() < p["linear_p"] else "geo"
            arrive = rng.randint(*p["late_at"]) if rng.random() < p["late_p"] else 0
            leave = rng.randint(*p["leave_at"]) if rng.random() < p["leave_p"] else p["ticks"]
            if "life" in p:                                     # real sessions: short stays after arriving
                life = 1 if rng.random() < p.get("life_short_p", 0.0) else rng.randint(*p["life"])
                # traders with no chance at the going price (cheap buyers, dear sellers) give up sooner
                out_of_market = (lim < p["mid"]) if side == "buy" else (lim > p["mid"])
                if "life_out" in p and "mid" in p and out_of_market:
                    life = min(life, rng.randint(*p["life_out"]))
                leave = min(p["ticks"], arrive + life)
            leave = max(leave, arrive + 1)
            out.append(SimTrader(
                id=f"{run}-{i}", side=side, limit=lim, q0=q0, firm=rng.random() < p["firm_p"],
                patience=rng.randint(*p["patience"]), mode=mode, rate=rng.uniform(*p["geo_rate"]),
                step=abs(q0 - lim) / rng.randint(*p["linear_steps"]), arrive=arrive, leave=leave))
        rng.shuffle(out)
        return cls(out, p["ticks"], run, cross_rule=cross_rule)

    def max_gain(self) -> float:
        v = sorted((t.limit for t in self.traders if t.side == "buy"), reverse=True)
        c = sorted(t.limit for t in self.traders if t.side == "sell")
        return float(sum(max(0, a - b) for a, b in zip(v, c)))

    def book(self, t: int) -> list[dict]:
        out = []
        for tr in self.traders:
            if not tr.present(t):
                continue
            q = tr.quote(t)
            if tr.side == "sell":
                out.append({"id": tr.id, "give": {"cash": 0, "assets": [], "types": ["card:SIM-01"]},
                            "want": {"cash": q, "assets": [], "types": []}, "created_tick": tr.arrive})
            else:
                out.append({"id": tr.id, "give": {"cash": q, "assets": [], "types": []},
                            "want": {"cash": 0, "assets": [], "types": ["card:SIM-01"]}, "created_tick": tr.arrive})
        return out

    def match(self, t: int, sell: str, buy: str, price: int) -> dict:
        by = {tr.id: tr for tr in self.traders}
        s, b = by.get(sell), by.get(buy)
        if not s or not b or s.side != "sell" or b.side != "buy" or not s.present(t) or not b.present(t):
            self.refused += 1
            return {"error": "offer_gone"}
        lo, hi = (s.quote(t), b.quote(t)) if self.cross_rule == "quotes" else (s.limit, b.limit)
        if not (lo <= price <= hi):
            self.refused += 1
            return {"error": "price_outside"}
        s.matched = b.matched = True
        gain = b.limit - s.limit
        self.realised += gain
        self.matches.append({"t": t, "sell": sell, "buy": buy, "price": price, "gain": gain})
        return {"ok": True}

    def efficiency(self) -> float:
        m = self.max_gain()
        return 1.0 if m <= 0 else self.realised / m


# --------------------------------------------------------------------------- policies under test

Planner = Callable[[int, list[dict]], list[Match]]


def stall_planner() -> Planner:
    return lambda t, book: stall_plan(book)


def engine_planner(policy: dict | None = None, profile: str | None = None) -> tuple[Planner, BenchEngine]:
    eng = BenchEngine(policy, profile)

    def plan(t: int, book: list[dict]) -> list[Match]:
        eng.observe(t, book)
        return eng.plan(t)
    return plan, eng


def oracle_planner(sess: SimSession) -> Planner:
    """Knows the true limits but not who leaves when: matches the true intramarginal set greedily."""
    def plan(t: int, book: list[dict]) -> list[Match]:
        by = {tr.id: tr for tr in sess.traders}
        live = [by[o["id"]] for o in book]
        b = sorted((x for x in live if x.side == "buy"), key=lambda x: -x.limit)
        s = sorted((x for x in live if x.side == "sell"), key=lambda x: x.limit)
        out = []
        for x in b:
            for y in s:
                if not y.matched and x.quote(t) >= y.quote(t) and x.limit > y.limit and y not in [o[1] for o in out]:
                    out.append((x, y))
                    break
        return [Match(y.id, x.id, midpoint_price(y.quote(t), x.quote(t)), "b1") for x, y in out]
    return plan


def play(sess: SimSession, planner: Planner, engine: BenchEngine | None = None) -> float:
    for t in range(sess.ticks):
        book = sess.book(t)
        for m in planner(t, book):
            r = sess.match(t, m.sell, m.buy, m.price)
            if engine is not None:
                if r.get("ok"):
                    engine.note_matched(m.sell, m.buy, m.est_surplus, m.kind)
                else:
                    engine.note_refused(m, r.get("error", ""))
    return sess.efficiency()


def benchmark(seeds: int = 200, hard: bool = False, policy: dict | None = None, params: dict | None = None,
              start: int = 0, oracle: bool = False, cross_rule: str = "quotes") -> dict:
    eff_s, eff_e, eff_o = [], [], []
    for seed in range(start, start + seeds):
        if SimSession.generate(seed, params, hard).max_gain() <= 0:
            continue
        eff_s.append(play(SimSession.generate(seed, params, hard, cross_rule=cross_rule), stall_planner()))
        plan, eng = engine_planner(policy)
        eff_e.append(play(SimSession.generate(seed, params, hard, cross_rule=cross_rule), plan, eng))
        if oracle:
            s = SimSession.generate(seed, params, hard)
            eff_o.append(play(s, oracle_planner(s)))
    out = {
        "mode": "hard" if hard else "normal", "cross_rule": cross_rule, "sessions": len(eff_s),
        "stall": round(statistics.mean(eff_s), 4), "engine": round(statistics.mean(eff_e), 4),
        "engine_wins": sum(e > s + 1e-9 for e, s in zip(eff_e, eff_s)),
        "engine_losses": sum(e < s - 1e-9 for e, s in zip(eff_e, eff_s)),
        "engine_p10": round(sorted(eff_e)[len(eff_e) // 10], 4),
        "stall_p10": round(sorted(eff_s)[len(eff_s) // 10], 4),
    }
    if oracle:
        out["oracle"] = round(statistics.mean(eff_o), 4)
    return out


# --------------------------------------------------------------------------- a fake broker endpoint for run.py --sim

class SimClient:
    """Implements the broker client interface of run.py against a stream of simulated sessions (fast clock)."""

    def __init__(self, seed: int = 0, hard: bool = False, sessions: int = 2, gap_ticks: int = 3, params: dict | None = None):
        self.tick = 0
        self.sessions: list[tuple[int, SimSession]] = []
        t = 2
        for k in range(sessions):
            s = SimSession.generate(seed + k, params, hard, run=f"b{k + 1}")
            self.sessions.append((t, s))
            t += s.ticks + gap_ticks
        self.end_tick = t
        self.announced: list[str] = []

    def _local(self) -> list[tuple[int, SimSession]]:
        return [(t0, s) for t0, s in self.sessions if t0 <= self.tick < t0 + s.ticks]

    def advance(self) -> None:
        self.tick += 1

    def clock(self) -> dict:
        return {"tick": self.tick, "t_hours": 5 + self.tick / 120, "tick_seconds": 0.05, "paused": False}

    def book(self) -> dict:
        offers = []
        for t0, s in self._local():
            for o in s.book(self.tick - t0):
                o = dict(o)
                o["created_tick"] = o["created_tick"] + t0
                offers.append(o)
        return {"venue": "vsim", "fee_bps": 0, "fee_per_card": 0, "offers": [], "bench_offers": offers}

    def match(self, sell: Any, buy: Any, price: int) -> dict:
        for t0, s in self._local():
            if str(sell).startswith(s.run + "-"):
                r = s.match(self.tick - t0, sell, buy, price)
                if r.get("error"):
                    from ..gateway import GameError
                    raise GameError(r["error"], "sim refused", 409, r)
                return r
        from ..gateway import GameError
        raise GameError("offer_gone", "no such run", 404)

    def announce(self, text: str) -> dict:
        self.announced.append(text)
        return {"ok": True}

    def me(self) -> dict:
        done = [s for t0, s in self.sessions if self.tick >= t0 + s.ticks]
        eff = done[-1].efficiency() if done else None
        return {"id": "t10", "venue": {"venue": "vsim"}, "score": {"bench_efficiency": eff, "bench_venue": "vsim"}}

    def schedule(self) -> dict:
        return {"upcoming": []}

    def feed(self) -> dict:
        return {"events": []}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=300)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--oracle", action="store_true")
    ap.add_argument("--policy", help="policy.json to test (default: built-in defaults merged with LAB policy)")
    a = ap.parse_args(argv)
    from .engine import load_policy
    pol = load_policy(a.policy) if a.policy else merge_policy(None)
    res = [benchmark(a.seeds, False, pol, oracle=a.oracle), benchmark(a.seeds, True, pol, oracle=a.oracle)]
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        for r in res:
            print(f"{r['mode']:6s} n={r['sessions']}  stall {r['stall']:.3f}  engine {r['engine']:.3f}"
                  + (f"  oracle {r['oracle']:.3f}" if "oracle" in r else "")
                  + f"  wins {r['engine_wins']} losses {r['engine_losses']}  p10 {r['engine_p10']:.3f} vs {r['stall_p10']:.3f}")


if __name__ == "__main__":
    main()
