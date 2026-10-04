"""Pure matching logic for our `board` venue: the Market Test bench and the public offers. No I/O here.

The bench: every venue gets the same synthetic traders. Sellers ask cash for a card, buyers bid cash for it. Each one
quotes away from a hidden limit (a seller's cost, a buyer's value); most relax toward it when impatient, firm ones
never move, some leave early. Efficiency counts the gains between the TRUE limits of the pairs we match, so:

* every matched pair is worth v - c (> 0 whenever the quotes cross), whatever the price;
* how pairs are formed does not change the total, WHICH traders get matched does: matching an extramarginal trader
  (a buyer whose value is below the clearing price, a seller whose cost is above it) can displace a better one.

So each tick we (1) track every quote trajectory and estimate each trader's hidden limit (geometric extrapolation of
the relaxation, a learned shading prior otherwise), (2) find the intramarginal set T and a clearing price p* on the
estimates, (3) run a max-weight bipartite matching over the pairs whose quotes cross now, where the weight of a pair
is its estimated surplus minus what each side would still be worth if we waited (scaled by the risk of losing it).
Intramarginal pairs match at once; an extramarginal partner is used only when the other side is about to be lost.
In the last ticks every crossing pair is matched. `stall_plan` reproduces the free auto stall and is the safety net.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- policy

GONE_CODES = ("gone", "not_found", "notfound", "unknown", "closed", "taken", "no_offer", "expired", "missing")

DEFAULT_POLICY: dict[str, Any] = {
    "session_ticks": 16,          # bench session length (schedule params.ticks)
    "max_bench_matches_per_tick": 10,
    "max_public_matches_per_tick": 10,
    "hard_traders": 12,           # a session with at least this many traders uses the hard profile
    "matcher": "engine",          # engine | stall. "stall" pairs exactly as the free stall does (highest bid against
                                  # lowest ask); it can never score below it. See broker/headroom.py for why the
                                  # estimate-driven engine has no edge on one-by-one arrivals.
    "cross_rule": "quotes",       # quotes | limits | probe. The server said it on Saturday ("price must sit between
                                  # the ask and the bid"): quotes. Probing cost a little in every sim profile.
    "max_probes": 2,              # non-crossing tries per session while the rule is unknown
    "probe_after": 2,             # ticks into a session before the first probe (estimates need a few quotes)
    "probe_refusals": 3,          # refused probes that settle the rule as "quotes" ...
    "probe_refusal_runs": 2,      # ... and they must come from at least this many distinct sessions
    "probes_when_quotes": 1,      # once settled as "quotes", keep this many probes per session (refusals are free)
    "carry_max_weight": 24.0,     # cap on the pseudo-observations carried across sessions for the shading prior
    "profiles": {
        "normal": {
            "prior_shade": 0.15,      # initial quote distance from the limit, as a share of the limit
            "prior_weight": 3.0,      # pseudo-observations behind prior_shade when learning it in-session
            "max_shade": 0.60,        # never estimate a limit further than this share from the quote
            "hazard": 0.12,           # prior per-tick probability that a trader leaves
            "hazard_weight": 30.0,    # pseudo trader-ticks behind the hazard prior
            "wait_ticks": 2.0,        # expected ticks until a better counterpart crosses
            "geo_max_ratio": 0.9,     # successive move ratio below this = geometric relaxation
            "lin_steps": 2.0,         # linear relaxation: assume this many more steps beyond the quote
            "stop_ticks": 2,          # unchanged this many ticks after moving = reached its limit
            "firm_ticks": 4,          # never moved for this many ticks = treat as firm at its quote
            "endgame_ticks": 2,       # last ticks: match every crossing pair
            "tt_bonus": 1.0,          # tie-break so intramarginal pairs always match at once
            "min_weight": 0.0,
            "limit_margin": 0.05,     # non-crossing pairs need an estimated surplus of this share of p* ...
            "limit_margin_abs": 3,    # ... and at least this many primas
            "limit_conf": 1.0,        # discount on the estimated surplus of a non-crossing pair
        },
        "hard": {
            "prior_shade": 0.20, "prior_weight": 3.0, "max_shade": 0.60,
            "hazard": 0.20, "hazard_weight": 30.0, "wait_ticks": 2.0,
            "geo_max_ratio": 0.9, "lin_steps": 2.0, "stop_ticks": 2, "firm_ticks": 3,
            "endgame_ticks": 3, "tt_bonus": 1.0, "min_weight": 0.0,
            "limit_margin": 0.05, "limit_margin_abs": 3, "limit_conf": 1.0,
        },
    },
}


def merge_policy(over: dict | None) -> dict:
    pol = json.loads(json.dumps(DEFAULT_POLICY))
    for k, v in (over or {}).items():
        if k == "profiles" and isinstance(v, dict):
            for name, prof in v.items():
                pol["profiles"].setdefault(name, {}).update(prof or {})
        else:
            pol[k] = v
    return pol


def load_policy(path: Path | None = None) -> dict:
    if path is None:
        from .. import config
        path = config.LAB / "broker" / "policy.json"
    try:
        return merge_policy(json.loads(Path(path).read_text()))
    except (OSError, ValueError):
        return merge_policy(None)


# --------------------------------------------------------------------------- offer parsing

def run_of(offer_id: Any) -> str:
    """Bench offers look like "b12-7": run "b12". Only a sell and a buy of the same run can match."""
    s = str(offer_id)
    return s.rsplit("-", 1)[0] if "-" in s else s


def bench_side(o: dict) -> tuple[str, int] | None:
    """('sell', ask) or ('buy', bid) for a bench offer, None if the shape is unknown."""
    give, want = o.get("give") or {}, o.get("want") or {}
    if (want.get("cash") or 0) > 0:
        return "sell", int(want["cash"])
    if (give.get("cash") or 0) > 0:
        return "buy", int(give["cash"])
    return None


def trader_key(o: dict) -> str:
    """Stable identity of a bench trader across ticks: an explicit trader field if the book gives one, else the id."""
    for k in ("trader", "trader_id", "bench_trader"):
        if o.get(k) is not None:
            return f"{run_of(o['id'])}:{o[k]}"
    return str(o["id"])


# --------------------------------------------------------------------------- trader tracking

@dataclass
class Trader:
    key: str
    run: str
    side: str                         # "sell" | "buy"
    offer_id: Any
    quotes: list[tuple[int, int]] = field(default_factory=list)   # (tick, price), one per tick seen
    first_tick: int = 0
    last_tick: int = 0
    deadline: int | None = None       # expires_tick when the book gives one
    gone: bool = False                # vanished without us matching it (left)
    matched: bool = False
    est: float = 0.0
    status: str = "new"               # new | static | firm | early | geo | lin | stopped

    @property
    def quote(self) -> int:
        return self.quotes[-1][1]

    @property
    def active(self) -> bool:
        return not self.gone and not self.matched

    def prices(self) -> list[int]:
        return [p for _, p in self.quotes]


def estimate_limit(side: str, prices: list[int], prior_shade: float, prof: dict) -> tuple[float, str]:
    """Estimate a trader's hidden limit from its quote history. Returns (limit, status).
    Seller limit <= current ask, buyer limit >= current bid, never beyond max_shade."""
    q, q0 = prices[-1], prices[0]
    sgn = -1 if side == "sell" else 1                  # direction of relaxation
    prior = q0 / (1 + prior_shade) if side == "sell" else q0 / max(1e-6, 1 - prior_shade)
    moves = [(prices[i] - prices[i - 1]) * sgn for i in range(1, len(prices))]

    def further(a: float, b: float) -> float:          # the one further from the quote in the limit's direction
        return min(a, b) if side == "sell" else max(a, b)

    if not any(m > 0 for m in moves):
        static_for = len(moves)
        status = "firm" if static_for >= prof["firm_ticks"] else "static"
        est = prior
    else:
        last = max(i for i, m in enumerate(moves) if m > 0)
        stalled = len(moves) - 1 - last
        recent = moves[: last + 1]
        if stalled >= prof["stop_ticks"]:
            est, status = float(q), "stopped"
        else:
            run: list[int] = []
            for m in reversed(recent):                 # trailing consecutive positive moves
                if m > 0:
                    run.append(m)
                else:
                    break
            run.reverse()
            if len(run) >= 2:
                if len(run) >= 3:
                    rho = (run[-1] + run[-2]) / (run[-2] + run[-3])
                else:
                    rho = run[-1] / run[-2]
                if rho < prof["geo_max_ratio"]:
                    rest = run[-1] * rho / (1 - rho)
                    est, status = q + sgn * rest, "geo"
                else:
                    est, status = further(q + sgn * run[-1] * prof["lin_steps"], prior), "lin"
            else:
                d = run[-1] if run else max(moves)
                est, status = further(prior, q + sgn * d), "early"
    lo = q * (1 - prof["max_shade"]) if side == "sell" else q
    hi = q if side == "sell" else q * (1 + prof["max_shade"])
    return min(hi, max(lo, est)), status


def realised_shade(side: str, prices: list[int], limit: float) -> float | None:
    if limit <= 0:
        return None
    return (prices[0] - limit) / limit if side == "sell" else (limit - prices[0]) / limit


def hungarian_max(weights: list[list[float]]) -> list[tuple[int, int]]:
    """Max-weight assignment on a rectangular matrix (rows x cols) of non-negative weights.
    Returns (row, col) pairs with weight > 0. O(n^3), fine for a dozen traders."""
    nr = len(weights)
    nc = len(weights[0]) if nr else 0
    if not nr or not nc:
        return []
    n = max(nr, nc)
    big = max((w for row in weights for w in row), default=0.0)
    cost = [[(big - (weights[i][j] if i < nr and j < nc else 0.0)) for j in range(n)] for i in range(n)]
    INF = float("inf")
    u, v, p, way = [0.0] * (n + 1), [0.0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [INF] * (n + 1), [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    out = []
    for j in range(1, n + 1):
        i = p[j] - 1
        if 0 <= i < nr and j - 1 < nc and weights[i][j - 1] > 0:
            out.append((i, j - 1))
    return out


def midpoint_price(ask: int, bid: int, fee_bps: int = 0, fee_per_card: int = 0) -> int | None:
    """Midpoint inside [ask, bid - fee]; None if no price lets the buyer also pay the fee."""
    def fee(p: int) -> int:
        return math.ceil(fee_bps * p / 10000) + fee_per_card
    for p in range((ask + bid) // 2, ask - 1, -1):
        if p + fee(p) <= bid:
            return p
    return None


# --------------------------------------------------------------------------- bench engine

@dataclass
class Match:
    sell: Any
    buy: Any
    price: int
    run: str = ""
    weight: float = 0.0
    est_surplus: float = 0.0
    reason: str = ""
    kind: str = "cross"               # cross (quotes cross) | limit (inside estimated limits) | probe | stall | public

    def to_dict(self) -> dict:
        return {"sell": self.sell, "buy": self.buy, "price": self.price, "run": self.run, "kind": self.kind,
                "weight": round(self.weight, 2), "est_surplus": round(self.est_surplus, 2), "reason": self.reason}


class BenchEngine:
    """Tracks the bench across ticks and plans matches. One instance per broker process; runs are kept apart.

    cross_rule (policy): "quotes" = only pairs whose quotes cross (what the stall does); "limits" = the server
    accepts any price inside both hidden limits, so non-crossing pairs with a clear estimated surplus are matched
    too; "probe" = unknown, try a few non-crossing pairs per session and learn the rule from the answer."""

    def __init__(self, policy: dict | None = None, profile: str | None = None):
        self.policy = merge_policy(policy)
        self.forced_profile = profile
        self.run_profile: dict[str, str] = {}                        # run -> "hard" | "normal" (from the schedule)
        self.traders: dict[str, Trader] = {}
        self.run_start: dict[str, int] = {}
        self.run_end: dict[str, int] = {}
        self.realised_est: dict[str, float] = {}
        self.last_tick: int | None = None
        self.rule: str = self.policy.get("cross_rule", "quotes")      # quotes | limits | probe
        self.probes: dict[str, int] = {}                              # run -> probes sent
        self.probe_refusals = 0
        self.refusal_runs: set[str] = set()                          # sessions in which a probe was refused
        self.learn_rule = self.rule == "probe"                        # the rule is learned (not forced by policy)
        self.carry: dict[str, dict[str, float]] = {}                  # profile -> {"sum", "n"}: shades of past sessions
        self.learned_runs: set[str] = set()
        self.shadow: dict[str, dict] = {}                             # run -> what the free stall would have done
        self.our_pairs: dict[str, list[tuple[str, str, int]]] = {}    # run -> (sell key, buy key, quoted gap) we matched
        self.blocked: set[tuple[Any, Any]] = set()                    # refused non-crossing pairs
        self.penalty: dict[str, int] = {}                             # trader key -> refusals it took part in

    # ---- observation
    def observe(self, tick: int, bench_offers: list[dict], ends: dict[str, int] | None = None) -> None:
        """Feed one tick of the book. `ends` maps run -> ends_tick when the book says when a session ends."""
        seen: set[str] = set()
        ticks = int(self.policy.get("session_ticks", 16))
        for o in bench_offers or []:
            side = bench_side(o)
            if side is None or "id" not in o:
                continue
            key, run = trader_key(o), run_of(o["id"])
            seen.add(key)
            tr = self.traders.get(key)
            if tr is None:
                tr = Trader(key=key, run=run, side=side[0], offer_id=o["id"], first_tick=tick)
                self.traders[key] = tr
                created = o.get("created_tick")
                start = created if isinstance(created, int) and created <= tick else tick
                self.run_start[run] = min(self.run_start.get(run, start), start)
                self.run_end[run] = self.run_start[run] + ticks - 1
            tr.offer_id = o["id"]
            if isinstance(o.get("expires_tick"), int):
                tr.deadline = o["expires_tick"]
            if not tr.quotes or tr.quotes[-1][0] != tick:
                tr.quotes.append((tick, side[1]))
            else:
                tr.quotes[-1] = (tick, side[1])
            tr.last_tick = tick
            tr.gone = False
            if ends and isinstance(ends.get(run), int):
                self.run_end[run] = ends[run] - 1      # last tick on which the run still trades
        for tr in self.traders.values():
            if tr.active and tr.key not in seen and tr.last_tick < tick:
                tr.gone = True                          # vanished without a match: it left
        self._shadow_stall(tick)
        self.last_tick = tick

    def _shadow_stall(self, tick: int) -> None:
        """Replay this tick's book through the free stall. Traders we matched are no longer in our book, so the
        shadow keeps them at their last quote (the stall would still have had them); traders that left are dropped."""
        runs: dict[str, tuple[list[Trader], list[Trader]]] = {}
        for t in self.traders.values():
            sh = self.shadow.setdefault(t.run, {"pairs": [], "used": set()})
            if t.key in sh["used"] or t.gone:
                continue
            if not (t.last_tick == tick or (t.matched and t.last_tick < tick)):
                continue
            if t.last_tick < tick and t.deadline is not None and t.deadline <= tick:
                continue                                # it would have expired from the stall's book too
            asks, bids = runs.setdefault(t.run, ([], []))
            (asks if t.side == "sell" else bids).append(t)
        for run, (asks, bids) in runs.items():
            sh = self.shadow[run]
            for s, b in zip(sorted(asks, key=lambda t: t.quote), sorted(bids, key=lambda t: -t.quote)):
                if b.quote < s.quote:
                    break
                sh["used"].update((s.key, b.key))
                sh["pairs"].append((s.key, b.key, b.quote - s.quote))

    def stall_efficiency(self, run: str) -> float | None:
        """Best estimate of what the free stall would have scored on this run, on the same estimated limits as
        efficiency_estimate (so the two compare like with like)."""
        best = self._best_gain(run)
        sh = self.shadow.get(run)
        if best is None or sh is None:
            return None
        return min(1.0, self._pairs_gain(sh["pairs"]) / best)

    def our_efficiency(self, run: str) -> float | None:
        """Our realised share on the CURRENT estimates, scored exactly like stall_efficiency."""
        best = self._best_gain(run)
        if best is None:
            return None
        return min(1.0, self._pairs_gain(self.our_pairs.get(run, [])) / best)

    def _pairs_gain(self, pairs: list) -> float:
        gain = 0.0
        for sk, bk, quoted in pairs:
            s, b = self.traders.get(sk), self.traders.get(bk)
            gain += max(float(quoted), (b.est - s.est) if (s and b) else 0.0)
        return gain

    def _by_offer(self, offer_id: Any) -> Trader | None:
        for tr in self.traders.values():
            if tr.offer_id == offer_id:
                return tr
        return None

    def note_matched(self, sell: Any, buy: Any, est_surplus: float = 0.0, kind: str = "cross") -> None:
        trs = [self._by_offer(sell), self._by_offer(buy)]
        for tr in trs:
            if tr is not None:
                tr.matched = True
        run = run_of(sell)
        if all(trs):
            self.our_pairs.setdefault(run, []).append((trs[0].key, trs[1].key, max(0, trs[1].quote - trs[0].quote)))
        self.realised_est[run] = self.realised_est.get(run, 0.0) + est_surplus
        if kind in ("limit", "probe") and (self.rule == "probe" or (self.learn_rule and self.rule == "quotes")):
            self.rule = "limits"                       # a non-crossing pair went through: limits rule

    def note_refused(self, m: "Match", code: str = "", message: str = "") -> None:
        """A planned match was refused. Gone offers are dropped; a refused non-crossing pair is blocked, both
        traders' limit estimates are pulled toward their quotes, and enough probe refusals settle the rule.
        When the server states the rule outright ("price must sit between the ask and the bid"), it is settled
        at once as "quotes" and no more probes are sent."""
        c = (code or "").lower()
        if m.kind in ("limit", "probe") and "between the ask" in (message or "").lower():
            self.rule, self.learn_rule = "quotes", False
        gone = any(w in c for w in GONE_CODES)
        if gone:
            for oid in (m.sell, m.buy):
                tr = self._by_offer(oid)
                if tr is not None and tr.active:
                    tr.gone = True
            return
        if m.kind in ("limit", "probe"):
            self.blocked.add((m.sell, m.buy))
            for oid in (m.sell, m.buy):
                tr = self._by_offer(oid)
                if tr is not None:
                    self.penalty[tr.key] = self.penalty.get(tr.key, 0) + 1
            if m.kind == "probe":
                self.probe_refusals += 1
                self.refusal_runs.add(m.run or run_of(m.sell))
                if self.rule == "probe" and self.probe_refusals >= int(self.policy.get("probe_refusals", 3)) \
                        and len(self.refusal_runs) >= int(self.policy.get("probe_refusal_runs", 2)):
                    self.rule = "quotes"               # one odd session (bad estimates) cannot settle it alone

    def apply_policy(self, policy: dict) -> None:
        """Swap in a new policy between sessions (never call it while a session runs). A changed cross_rule
        restarts what the engine learned about the rule."""
        old_rule = self.policy.get("cross_rule")
        self.policy = policy
        if policy.get("cross_rule") != old_rule:
            self.rule = policy.get("cross_rule", "quotes")
            self.learn_rule = self.rule == "probe"
            self.probe_refusals = 0
            self.refusal_runs = set()

    def probe_budget(self) -> int:
        if self.rule == "probe":
            return int(self.policy.get("max_probes", 2))
        if self.rule == "quotes" and self.learn_rule:
            return int(self.policy.get("probes_when_quotes", 1))
        return 0

    # ---- estimation
    def profile_name(self, run: str) -> str:
        name = self.forced_profile or self.run_profile.get(run)
        if name is None:
            n = sum(1 for t in self.traders.values() if t.run == run)
            name = "hard" if n >= int(self.policy.get("hard_traders", 12)) else "normal"
        return name if name in self.policy["profiles"] else "normal"

    def profile_for(self, run: str) -> dict:
        return self.policy["profiles"][self.profile_name(run)]

    def session_shades(self, run: str) -> list[float]:
        """Realised quote shading of the traders of this run whose limit we pinned down."""
        prof = self.profile_for(run)
        out = []
        for t in self.traders.values():
            if t.run == run and len(t.quotes) >= 3:
                est, st = estimate_limit(t.side, t.prices(), prof["prior_shade"], prof)
                if st in ("geo", "stopped"):
                    s = realised_shade(t.side, t.prices(), est)
                    if s is not None and 0 <= s < prof["max_shade"]:
                        out.append(s)
        return out

    def learn_session(self, run: str) -> dict | None:
        """Carry this run's shading into the prior of the next sessions (once per run). Returns the new carry."""
        if run in self.learned_runs:
            return None
        self.learned_runs.add(run)
        shades = self.session_shades(run)
        if not shades:
            return None
        c = self.carry.setdefault(self.profile_name(run), {"sum": 0.0, "n": 0.0})
        c["sum"] += sum(shades)
        c["n"] += len(shades)
        cap = float(self.policy.get("carry_max_weight", 24.0))
        if c["n"] > cap:                                # old sessions fade: keep the mean, cap the weight
            c["sum"], c["n"] = c["sum"] * cap / c["n"], cap
        return dict(c)

    def export_state(self) -> dict:
        return {"carry": self.carry, "rule": self.rule, "probe_refusals": self.probe_refusals,
                "refusal_runs": sorted(self.refusal_runs)[-20:]}

    def load_state(self, d: dict | None) -> None:
        d = d or {}
        for name, c in (d.get("carry") or {}).items():
            try:
                self.carry[str(name)] = {"sum": float(c["sum"]), "n": float(c["n"])}
            except (KeyError, TypeError, ValueError):
                continue
        if self.learn_rule and d.get("rule") in ("probe", "quotes", "limits"):
            self.rule = d["rule"]
            self.probe_refusals = int(d.get("probe_refusals") or 0)
            self.refusal_runs = set(map(str, d.get("refusal_runs") or []))

    def estimates(self, run: str) -> dict[str, float]:
        prof = self.profile_for(run)
        trs = [t for t in self.traders.values() if t.run == run]
        shades = self.session_shades(run)               # learn the shading prior from traders we have pinned down
        w = prof["prior_weight"]
        c = self.carry.get(self.profile_name(run)) if run not in self.learned_runs else None
        cs, cn = (c["sum"], c["n"]) if c else (0.0, 0.0)   # ... and from past sessions
        prior = (prof["prior_shade"] * w + cs + sum(shades)) / (w + cn + len(shades))
        out = {}
        for t in trs:
            t.est, t.status = estimate_limit(t.side, t.prices(), prior, prof)
            k = self.penalty.get(t.key, 0)
            if k:                                       # each refusal halves the distance to the quote
                t.est = t.quote + (t.est - t.quote) * 0.5 ** k
            out[t.key] = t.est
        return out

    def hazard(self, run: str) -> float:
        prof = self.profile_for(run)
        trs = [t for t in self.traders.values() if t.run == run]
        left = sum(1 for t in trs if t.gone)
        exposure = sum(max(1, t.last_tick - t.first_tick + 1) for t in trs)
        return (prof["hazard"] * prof["hazard_weight"] + left) / (prof["hazard_weight"] + exposure)

    @staticmethod
    def clearing(buyers: list[Trader], sellers: list[Trader]) -> tuple[float, set[str]]:
        """(p*, keys of the intramarginal set) on estimated limits."""
        b = sorted(buyers, key=lambda t: -t.est)
        s = sorted(sellers, key=lambda t: t.est)
        k = 0
        while k < min(len(b), len(s)) and b[k].est >= s[k].est:
            k += 1
        if k == 0:
            if b and s:
                return (b[0].est + s[0].est) / 2, set()
            return 0.0, set()
        lo = max([s[k - 1].est] + ([b[k].est] if k < len(b) else []))
        hi = min([b[k - 1].est] + ([s[k].est] if k < len(s) else []))
        if lo > hi:
            lo, hi = hi, lo
        return (lo + hi) / 2, {t.key for t in b[:k]} | {t.key for t in s[:k]}

    # ---- planning
    def plan(self, tick: int, fee_bps: int = 0, fee_per_card: int = 0) -> list[Match]:
        out: list[Match] = []
        plan_run = self._plan_run_stall if self.policy.get("matcher") == "stall" else self._plan_run
        for run in sorted({t.run for t in self.traders.values() if t.active}):
            out.extend(plan_run(run, tick, fee_bps, fee_per_card))
        out.sort(key=lambda m: -m.weight)
        return out[: int(self.policy.get("max_bench_matches_per_tick", 10))]

    def _plan_run_stall(self, run: str, tick: int, fee_bps: int, fee_per_card: int) -> list[Match]:
        """The free stall's pairing on the traders in this tick's book: highest bid against lowest ask while the
        bid covers it. Estimates are still refreshed, so the session report compares like with like."""
        self.estimates(run)
        act = [t for t in self.traders.values() if t.run == run and t.active and t.last_tick == tick]
        asks = sorted((t for t in act if t.side == "sell"), key=lambda t: t.quote)
        bids = sorted((t for t in act if t.side == "buy"), key=lambda t: -t.quote)
        out = []
        for s, b in zip(asks, bids):
            if b.quote < s.quote:
                break
            price = midpoint_price(s.quote, b.quote, fee_bps, fee_per_card)
            if price is None:
                continue
            surplus = max(b.est, b.quote) - min(s.est, s.quote)
            out.append(Match(s.offer_id, b.offer_id, price, run, surplus + 1.0, surplus,
                             f"stall pairing: bid {b.quote} >= ask {s.quote}", "cross"))
        return out

    def _plan_run(self, run: str, tick: int, fee_bps: int, fee_per_card: int) -> list[Match]:
        prof = self.profile_for(run)
        self.estimates(run)
        act = [t for t in self.traders.values() if t.run == run and t.active and t.last_tick == tick]
        buyers = [t for t in act if t.side == "buy"]
        sellers = [t for t in act if t.side == "sell"]
        if not buyers or not sellers:
            return []
        pstar, T = self.clearing(buyers, sellers)
        end = self.run_end.get(run, tick)
        endgame = tick >= end - prof["endgame_ticks"] + 1
        h = self.hazard(run)
        base_risk = 1 - (1 - h) ** prof["wait_ticks"]
        probing = self.probes.get(run, 0) < self.probe_budget() \
            and tick - self.run_start.get(run, tick) >= int(self.policy.get("probe_after", 2))
        loose = self.rule == "limits"

        def reach(t: Trader) -> float:                  # the best quote this trader may ever reach
            return float(t.quote) if t.status == "firm" else t.est

        def risk(t: Trader) -> float:
            if endgame or (t.deadline is not None and t.deadline <= tick + 1):
                return 1.0
            if t.key in T and not loose:                # can a still-open intramarginal partner ever cross it?
                partners = [p for p in (sellers if t.side == "buy" else buyers) if p.key in T]
                ok = any((reach(t) >= reach(p)) if t.side == "buy" else (reach(p) >= reach(t)) for p in partners)
                if not ok:
                    return 1.0
            return base_risk

        def value_if_wait(t: Trader) -> float:
            if t.key not in T:
                return 0.0
            return max(0.0, t.est - pstar) if t.side == "buy" else max(0.0, pstar - t.est)

        weights, info = [], {}
        probe_best: tuple[float, int, int] | None = None
        for i, s in enumerate(sellers):
            row = []
            for j, b in enumerate(buyers):
                crossing = b.quote >= s.quote and midpoint_price(s.quote, b.quote, fee_bps, fee_per_card) is not None
                v, c = max(b.est, b.quote), min(s.est, s.quote)
                surplus = v - c
                kind = "cross"
                if not crossing:
                    margin = max(float(prof.get("limit_margin_abs", 3)), prof.get("limit_margin", 0.15) * max(1.0, pstar))
                    young = tick - self.run_start.get(run, tick) < int(self.policy.get("probe_after", 2))
                    if (s.offer_id, b.offer_id) in self.blocked or surplus < margin or young:
                        row.append(0.0)
                        continue
                    if probing and s.key in T and b.key in T:
                        if probe_best is None or surplus > probe_best[0]:
                            probe_best = (surplus, i, j)
                    if not loose:
                        row.append(0.0)
                        continue
                    kind = "limit"
                    surplus *= prof.get("limit_conf", 0.7)
                if endgame:
                    w = surplus + 1.0
                else:
                    w = surplus - (1 - risk(b)) * value_if_wait(b) - (1 - risk(s)) * value_if_wait(s)
                    if b.key in T and s.key in T:
                        w += prof["tt_bonus"]
                    w = w if w > prof["min_weight"] else 0.0
                row.append(max(0.0, w))
                info[(i, j)] = (surplus, w, kind)
            weights.append(row)
        out = []
        used_s, used_b = set(), set()
        for i, j in hungarian_max(weights):
            s, b = sellers[i], buyers[j]
            surplus, w, kind = info[(i, j)]
            if kind == "cross":
                price = midpoint_price(s.quote, b.quote, fee_bps, fee_per_card)
            else:
                price = self._limit_price(s, b)
            tag = "endgame" if endgame else ("TT" if (s.key in T and b.key in T) else "risk")
            out.append(Match(s.offer_id, b.offer_id, price, run, w, surplus,
                             f"{tag} p*={pstar:.0f} est b{b.est:.0f}/s{s.est:.0f}", kind))
            used_s.add(i)
            used_b.add(j)
        if probe_best is not None and probe_best[1] not in used_s and probe_best[2] not in used_b:
            _, i, j = probe_best
            s, b = sellers[i], buyers[j]
            self.probes[run] = self.probes.get(run, 0) + 1
            out.append(Match(s.offer_id, b.offer_id, self._limit_price(s, b), run, 0.01, b.est - s.est,
                             f"probe: bid {b.quote} < ask {s.quote}, est b{b.est:.0f}/s{s.est:.0f}", "probe"))
        return out

    @staticmethod
    def _limit_price(s: Trader, b: Trader) -> int:
        """Inside both estimated limits, as close to the middle as the quotes allow."""
        p = round((s.est + b.est) / 2)
        lo, hi = min(b.quote, s.quote), max(b.quote, s.quote)
        return int(min(hi, max(lo, p)))

    # ---- reporting
    def _best_gain(self, run: str) -> float | None:
        trs = [t for t in self.traders.values() if t.run == run]
        if not trs:
            return None
        self.estimates(run)
        v = sorted((t.est for t in trs if t.side == "buy"), reverse=True)
        c = sorted(t.est for t in trs if t.side == "sell")
        best = sum(max(0.0, a - b) for a, b in zip(v, c))
        return best if best > 0 else None

    def efficiency_estimate(self, run: str) -> float | None:
        best = self._best_gain(run)
        return None if best is None else min(1.0, self.realised_est.get(run, 0.0) / best)

    def snapshot(self, run: str | None = None) -> list[dict]:
        return [{"key": t.key, "run": t.run, "side": t.side, "quote": t.quote, "est": round(t.est, 1),
                 "status": t.status, "gone": t.gone, "matched": t.matched, "n": len(t.quotes)}
                for t in self.traders.values() if run is None or t.run == run]

    def forget_before(self, tick: int) -> None:
        """Drop finished runs (keeps memory flat over a weekend)."""
        dead = {r for r, e in self.run_end.items() if e < tick - 2}
        self.traders = {k: t for k, t in self.traders.items() if t.run not in dead}
        for r in dead:
            for d in (self.run_start, self.run_end, self.run_profile, self.probes, self.realised_est, self.shadow,
                      self.our_pairs):
                d.pop(r, None)


# --------------------------------------------------------------------------- stall baseline (safety net)

def stall_plan(bench_offers: list[dict]) -> list[Match]:
    """Exactly the free auto stall: per run, highest bid against lowest ask while the bid covers it, at the midpoint."""
    runs: dict[str, tuple[list, list]] = {}
    for o in bench_offers or []:
        side = bench_side(o)
        if side is None:
            continue
        asks, bids = runs.setdefault(run_of(o["id"]), ([], []))
        (asks if side[0] == "sell" else bids).append((side[1], o["id"]))
    plan = []
    for run, (asks, bids) in runs.items():
        for (ask, sell), (bid, buy) in zip(sorted(asks, key=lambda a: a[0]), sorted(bids, key=lambda b: -b[0])):
            if bid < ask:
                break
            plan.append(Match(sell, buy, (ask + bid) // 2, run, 0.0, bid - ask, "stall", "stall"))
    return plan


# --------------------------------------------------------------------------- public offers on our venue

def _asset_ref(a: Any) -> tuple[Any, str | None]:
    """(asset id, "card:REF") for an asset entry (dict or bare id)."""
    if isinstance(a, dict):
        ref = f"{a.get('kind', 'card')}:{a['ref']}" if a.get("ref") else None
        return a.get("id"), ref
    return a, None


def public_plan(book: dict, limit: int = 10, tick: int | None = None) -> list[Match]:
    """Card by card: each single-card ask against the highest bid that wants that card (any copy via want.types, or
    that exact asset via want.assets), from another maker, covering ask + fee. Price at the midpoint, lowered until the
    buyer can also pay our fee. Asks are taken cheapest first; a bid is used once. Offers that expire at or before
    `tick` (default book["tick"]) are skipped: the server would refuse them. An offer addressed to one team (`to`)
    only meets that team's offer."""
    fee_bps, fee_card = int(book.get("fee_bps") or 0), int(book.get("fee_per_card") or 0)
    if tick is None and isinstance(book.get("tick"), int):
        tick = book["tick"]

    def alive(o: dict) -> bool:
        exp = o.get("expires_tick")
        return not (isinstance(tick, int) and isinstance(exp, int) and exp <= tick)

    offers = [o for o in (book.get("offers") or []) if o.get("status", "open") == "open" and alive(o)]
    bids = []
    for o in offers:
        g, w = o.get("give") or {}, o.get("want") or {}
        if (g.get("cash") or 0) > 0 and not g.get("assets") and not (w.get("cash") or 0):
            types, assets = list(w.get("types") or []), [_asset_ref(a)[0] for a in (w.get("assets") or [])]
            if len(types) + len(assets) == 1:
                bids.append((o, types, assets))
    bids.sort(key=lambda x: -x[0]["give"]["cash"])
    asks = []
    for o in offers:
        g, w = o.get("give") or {}, o.get("want") or {}
        if len(g.get("assets") or []) == 1 and (w.get("cash") or 0) > 0 and not (g.get("cash") or 0) \
                and not w.get("assets") and not w.get("types"):
            asks.append(o)
    asks.sort(key=lambda o: o["want"]["cash"])
    plan, used = [], set()
    for s in asks:
        ask = int(s["want"]["cash"])
        aid, ref = _asset_ref(s["give"]["assets"][0])
        for b, types, assets in bids:
            if b["id"] in used or b.get("maker") == s.get("maker"):
                continue
            if (s.get("to") and s["to"] != b.get("maker")) or (b.get("to") and b["to"] != s.get("maker")):
                continue                # an addressed offer is for that team alone: never cross it with a third one
            if not ((ref and types == [ref]) or (aid is not None and assets == [aid])):
                continue
            bid = int(b["give"]["cash"])
            price = midpoint_price(ask, bid, fee_bps, fee_card) if bid >= ask else None
            if price is None:
                continue
            used.add(b["id"])
            plan.append(Match(s["id"], b["id"], price, "public", float(bid - ask), float(bid - ask), f"card {ref or aid}", "public"))
            break
        if len(plan) >= limit:
            break
    return plan
