"""Evaluate the code duel policy on Sunday's format against a zoo of rivals. Never talks to the game.

    python -m bazaar.duels.sunday_eval                  # Sunday: 12 ticks, decay 0.10, price + days
    python -m bazaar.duels.sunday_eval --ticks 16 --decay 0.08     # Saturday's format, for comparison
    python -m bazaar.duels.sunday_eval --variants       # the parameter variants, one line each

Scenarios are the 34 that Duels II played (cost, value, seller's and buyer's weight per day), jittered.
The duel dict is the one the server sends: a positive `your_days_weight` and the `days_meaning` text
(the seller gains with every day, the buyer pays), so the sign reading is exercised too.
Rivals: those of simulator.py plus slow, silent, absurd, splitter and a mirror that plays our own policy.
"""
from __future__ import annotations

import argparse
import random
import tempfile
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

from .domain import DuelsDomain
from .model import DAYS_MAX, surplus
from .opponent import OpponentMemory
from .policy import PARAMS
from .simulator import DuelResult, Eager, Fixed, Injector, Mute, Rival, Scenario, Stepped, Tough

# (cost, value, seller's weight per day, buyer's weight per day): Duels II, 3 Oct, both legs of each item.
SCENARIOS = [
    (41, 54, 6.86, 2.14), (100, 145, 3.9, 4.98), (140, 147, 2.34, 3.26), (39, 122, 1.07, 2.38),
    (100, 140, 1.28, 2.01), (68, 130, 2.34, 4.95), (84, 89, 2.52, 5.84), (64, 175, 2.51, 3.34),
    (72, 104, 3.99, 1.36), (36, 175, 1.38, 1.66), (63, 116, 6.45, 1.97), (78, 109, 5.15, 4.49),
    (31, 123, 3.21, 3.64), (45, 133, 2.44, 4.38), (123, 144, 2.66, 7.99), (117, 105, 1.14, 5.99),
    (55, 146, 5.28, 7.6), (65, 59, 1.86, 4.22), (79, 90, 2.24, 2.8), (96, 99, 1.78, 6.46),
    (42, 159, 1.84, 2.45), (63, 124, 1.47, 6.76), (125, 148, 1.89, 8.22), (109, 107, 3.22, 7.64),
    (46, 143, 2.59, 7.55), (79, 118, 0.73, 1.38), (88, 125, 6.0, 1.31), (130, 194, 0.62, 1.13),
    (80, 94, 5.62, 1.54), (66, 174, 1.26, 1.17), (57, 92, 1.49, 3.04), (81, 104, 5.44, 4.31),
    (25, 94, 3.92, 2.42), (67, 114, 2.25, 4.19),
]
# Six pairs came out with value <= cost: legs of one item are not always one scenario, so those are dropped.
FEASIBLE = [s for s in SCENARIOS if s[1] - s[0] >= 5]
SELLER_DAYS = "each delivery day adds this much cash to your side"
BUYER_DAYS = "each delivery day costs you this much cash"


def scenario(rng: random.Random, role: str, decay: float) -> Scenario:
    cost, value, ws, wb = rng.choice(FEASIBLE)
    j = rng.uniform(0.85, 1.15)
    cost, value = int(round(cost * j)), int(round(value * j))
    ws, wb = round(ws * rng.uniform(0.8, 1.2), 2), round(wb * rng.uniform(0.8, 1.2), 2)
    w_us, w_rival = (ws, -wb) if role == "seller" else (-wb, ws)
    return Scenario(value=value, cost=cost, our_role=role, w_us=w_us, w_rival=w_rival, uses_days=True,
                    decay=decay, item=f"Item {rng.randint(1, 10 ** 6)}")


def total_pie(sc: Scenario) -> float:
    """Everything the two sides can share: the price gap plus the days, when the seller values them more."""
    return sc.pie + DAYS_MAX * max(0.0, sc.w_us + sc.w_rival)


# --- extra rivals ---------------------------------------------------------------------------------------
class DaysAware(Rival):
    """Base for the extra rivals: with a non-positive price gap the pie is in the days."""

    def __init__(self, sc, rng):
        super().__init__(sc, rng)
        self.pie = max(1.0, total_pie(sc))


class Slow(Stepped):
    """A stepper that only wakes up every third tick (a bot with a slow loop)."""
    kind = "slow"

    def act(self, k, ours, theirs):
        if ours and self.u(ours[-1][0], ours[-1][1]) >= self.accept_level(theirs) and k % 3 == self.start % 3:
            return ("accept",)
        return super().act(k, ours, theirs) if k % 3 == self.start % 3 else None


class Silent(Rival):
    """Never answers and never accepts (a bot that is down): nothing we do can score."""
    kind = "silent"

    def act(self, k, ours, theirs):
        return None


class Absurd(Stepped):
    """Opens far outside the pie and comes in with big steps."""
    kind = "absurd"

    def __init__(self, sc, rng):
        super().__init__(sc, rng)
        self.cur = rng.uniform(2.5, 4.0) * self.pie
        self.step = rng.uniform(0.3, 0.6) * self.pie
        self.floor = rng.uniform(0.2, 0.4) * self.pie


class Splitter(Rival):
    """An LLM-like haggler: opens high, closes 15-35 % of the gap to our last ask each time we answer, and
    takes any ask that leaves it a fair share or beats its own next offer after one more round."""
    kind = "splitter"

    def __init__(self, sc, rng):
        super().__init__(sc, rng)
        self.pie = max(1.0, total_pie(sc))
        self.cur = rng.uniform(0.7, 1.1) * self.pie
        self.rate = rng.uniform(0.15, 0.35)
        self.fair = rng.uniform(0.3, 0.5) * self.pie
        self.floor = rng.uniform(0.1, 0.3) * self.pie

    def offer(self):
        d = self.days()
        s = self.cur - (self.sc.w_rival * (d or 0))
        return ("offer", self.price_for(s), d, self.text(self.price_for(s)))

    def act(self, k, ours, theirs):
        if ours:
            u = self.u(ours[-1][0], ours[-1][1])
            nxt = max(self.floor, self.cur - self.rate * max(0.0, self.cur - u))
            if u >= self.fair or u >= nxt * (1 - self.sc.decay) or (k >= self.ticks - 2 and u >= 1):
                return ("accept",)
        if k < self.start:
            return None
        if not theirs:
            return self.offer()
        if ours and ours[-1][2] >= theirs[-1][2]:
            self.cur = max(self.floor, self.cur - self.rate * max(0.0, self.cur - self.u(ours[-1][0], ours[-1][1])))
            return self.offer()
        return None

    ticks = 12


class Mirror(Rival):
    """Our own code policy on the other side of the table, with its own memory."""
    kind = "mirror"

    def __init__(self, sc, rng):
        super().__init__(sc, rng)
        tmp = Path(tempfile.mkdtemp(prefix="mirror")) / "duel_memory.json"
        self.dom = DuelsDomain(memory=OpponentMemory(tmp, autosave=False), use_llm=False)
        self.env = {}

    def act(self, k, ours, theirs):
        e, sc = self.env, self.sc
        tick = e["start"] + k
        msgs = sorted([{"tick": e["start"] + t, "from": "you", "text": "", "price": p, "days": d} for p, d, t in theirs]
                      + [{"tick": e["start"] + t, "from": "them", "text": "", "price": p, "days": d} for p, d, t in ours],
                      key=lambda m: m["tick"])
        duel = {
            "duel": e["id"] + 500_000, "session": 4, "status": "live", "role": self.role, "item": sc.item,
            "issues": ["price", "days"], "your_days_weight": abs(sc.w_rival),
            "days_meaning": SELLER_DAYS if self.role == "seller" else BUYER_DAYS,
            "your_limit": self.limit, "rival": "them", "deadline_tick": e["start"] + e["ticks"],
            "decay_per_round": sc.decay, "rounds": min(len(ours), len(theirs)),
            "your_offer": {"id": 1, "price": theirs[-1][0], "tick": e["start"] + theirs[-1][2],
                           "days": theirs[-1][1] or 0} if theirs else None,
            "rival_offer": {"id": 2, "price": ours[-1][0], "tick": e["start"] + ours[-1][2],
                            "days": ours[-1][1] or 0} if ours else None,
            "messages": msgs[-6:], "result": None, "price": None, "days": None,
        }
        ctx = SimpleNamespace(tick=tick, deadline=None, budget={}, lessons=None, llm=None, llm_ok=True)
        for a in self.dom.fallback(SimpleNamespace(tick=tick, duels=[duel]), ctx):
            if a.kind == "duel_accept" and ours:
                return ("accept",)
            if a.kind == "duel_message":
                return ("offer", a.params["price"], a.params.get("days"), a.params["text"])
        return None


RIVALS = {c.kind: c for c in (Fixed, Stepped, Eager, Tough, Mute, Injector, Slow, Silent, Absurd, Splitter, Mirror)}
# Rough mix of what Duels II showed: 10 of 68 rivals never spoke, 18 made a single offer, the rest haggled.
MIX = {"silent": 0.10, "mute": 0.05, "fixed": 0.25, "stepped": 0.12, "eager": 0.08, "tough": 0.08,
       "slow": 0.07, "absurd": 0.05, "splitter": 0.15, "mirror": 0.05}


def run_duel(domain, sc: Scenario, rival: Rival, duel_id: int, alias: str, ticks: int, start_tick: int) -> DuelResult:
    """One duel, the server's payload for price + days. The rival moves first within a tick, as in simulator.py."""
    deadline = start_tick + ticks
    msgs: list[dict] = []
    ours: list = []
    theirs: list = []
    if isinstance(rival, Mirror):
        rival.env = {"start": start_tick, "id": duel_id, "ticks": ticks}
    if isinstance(rival, Splitter):
        rival.ticks = ticks

    def rounds():
        return min(len(ours), len(theirs))

    def close(by, price, days, k):
        s = surplus(sc.our_role, sc.our_limit, price)
        u = s + sc.w_us * (days or 0)
        return DuelResult(alias, True, price, days, rounds(), u * (1 - sc.decay) ** rounds(), total_pie(sc), k + 1,
                          by, s < 0, msgs)

    for k in range(ticks):
        tick = start_tick + k
        act = rival.act(k, ours, theirs)
        if act and act[0] == "accept" and ours:
            return close("rival", ours[-1][0], ours[-1][1], k)
        if act and act[0] == "offer":
            theirs.append((act[1], act[2], k))
            msgs.append({"tick": tick, "from": alias, "text": act[3], "price": act[1], "days": act[2]})
        duel = {
            "duel": duel_id, "session": 4, "status": "live", "role": sc.our_role, "item": sc.item,
            "issues": ["price", "days"], "your_days_weight": abs(sc.w_us),
            "days_meaning": SELLER_DAYS if sc.our_role == "seller" else BUYER_DAYS,
            "your_limit": sc.our_limit,
            "limit_meaning": "never sell below your cost" if sc.our_role == "seller" else "never pay above your value",
            "rival": alias, "deadline_tick": deadline, "decay_per_round": sc.decay, "rounds": rounds(),
            "your_offer": {"id": len(msgs), "price": ours[-1][0], "tick": start_tick + ours[-1][2],
                           "days": ours[-1][1] or 0} if ours else None,
            "rival_offer": {"id": 10_000 + len(theirs), "price": theirs[-1][0], "tick": start_tick + theirs[-1][2],
                            "days": theirs[-1][1] or 0} if theirs else None,
            "messages": list(msgs[-6:]), "result": None, "price": None, "days": None,
        }
        ctx = SimpleNamespace(tick=tick, deadline=None, budget={}, lessons=None, llm=None, llm_ok=True)
        for a in domain.fallback(SimpleNamespace(tick=tick, duels=[duel]), ctx):
            if a.kind == "duel_accept" and theirs:
                return close("us", theirs[-1][0], theirs[-1][1], k)
            if a.kind == "duel_message":
                ours.append((a.params["price"], a.params.get("days"), k))
                msgs.append({"tick": tick, "from": "you", "text": a.params["text"], "price": a.params["price"],
                             "days": a.params.get("days")})
    return DuelResult(alias, False, None, None, rounds(), 0.0, total_pie(sc), ticks, "", False, msgs)


def play(n: int, seed: int, ticks: int, decay: float, kinds: list[str]) -> dict:
    """n duels per rival kind (both roles); per kind: points, deal rate, rounds, share of the pie, illegal."""
    out = {}
    for kind in kinds:
        rng = random.Random(f"{seed}-{kind}")
        tmp = Path(tempfile.mkdtemp(prefix="suneval")) / "duel_memory.json"
        dom = DuelsDomain(memory=OpponentMemory(tmp, autosave=False), use_llm=False)
        rs = []
        for i in range(n):
            sc = scenario(rng, "seller" if i % 2 == 0 else "buyer", decay)
            r = run_duel(dom, sc, RIVALS[kind](sc, random.Random(rng.random())), i + 1, f"Rival {kind}{i}", ticks,
                         1000 + 20 * i)
            dom.memory.record_result(i + 1, "deal" if r.deal else "no_deal", price=r.price, rounds=r.rounds,
                                     days=r.days, accepted_by=r.accepted_by or None)
            r.role = sc.our_role
            rs.append(r)
        deals = [r for r in rs if r.deal]
        out[kind] = {
            "n": len(rs), "points": sum(r.points for r in rs) / len(rs), "deal_rate": len(deals) / len(rs),
            "rounds": sum(r.rounds for r in deals) / max(1, len(deals)),
            "share": sum(r.points for r in rs) / max(1.0, sum(max(0.0, r.pie) for r in rs)),
            "illegal": sum(1 for r in rs if r.illegal),
            "seller_points": sum(r.points for r in rs if r.role == "seller") / max(1, len(rs) // 2),
            "buyer_points": sum(r.points for r in rs if r.role == "buyer") / max(1, len(rs) // 2),
            "ticks": sum(r.ticks for r in deals) / max(1, len(deals)),
        }
    return out


def mixed(res: dict, key: str = "points") -> float:
    return sum(MIX[k] * res[k][key] for k in MIX if k in res) / sum(MIX[k] for k in MIX if k in res)


def table(title: str, res: dict) -> None:
    print(f"\n{title}")
    print(f"  {'rival':9} {'pts':>6} {'deal%':>6} {'rounds':>6} {'ticks':>6} {'share':>6} {'seller':>7} {'buyer':>6} {'illegal':>7}")
    for k, r in res.items():
        print(f"  {k:9} {r['points']:6.1f} {100 * r['deal_rate']:6.0f} {r['rounds']:6.1f} {r['ticks']:6.1f} "
              f"{r['share']:6.2f} {r['seller_points']:7.1f} {r['buyer_points']:6.1f} {r['illegal']:7d}")
    print(f"  {'MIX':9} {mixed(res):6.1f} {100 * mixed(res, 'deal_rate'):6.0f} {mixed(res, 'rounds'):6.1f} "
          f"{mixed(res, 'ticks'):6.1f} {mixed(res, 'share'):6.2f}")


VARIANTS = {
    "baseline": {},
    "OPEN 0.8": {"OPEN": 0.8}, "OPEN 1.0": {"OPEN": 1.0},
    "OPEN_BUYER 0.7": {"OPEN_BUYER": 0.7}, "OPEN_BUYER 0.9": {"OPEN_BUYER": 0.9},
    "ACCEPT_SHARE 0.5": {"ACCEPT_SHARE": 0.5}, "ACCEPT_SHARE 0.7": {"ACCEPT_SHARE": 0.7},
    "LAST_TICKS 3": {"LAST_TICKS": 3}, "LAST_TICKS 1": {"LAST_TICKS": 1},
    "BETA 1.5": {"BETA": 1.5}, "BETA 3": {"BETA": 3.0},
    "MIRROR 0.5": {"MIRROR": 0.5}, "MIRROR 0.15": {"MIRROR": 0.15},
    "PROBE_UNTIL 6": {"PROBE_UNTIL": 6}, "no probe": {"PROBE_UNTIL": 99},
    "FINAL_TICKS 4": {"FINAL_TICKS": 4, "FINAL_STEPS": {4: 0.5, 3: 0.40, 2: 0.28, 1: 0.17}},
    "END 0.2": {"END": 0.2},
}


def with_params(over: dict, fn):
    """Run fn() with PARAMS overridden in place (plan() and the hold rules read that same dict)."""
    old = {k: PARAMS[k] for k in over}
    PARAMS.update(over)
    try:
        return fn()
    finally:
        PARAMS.update(old)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", type=int, default=400, help="duels per rival kind")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--ticks", type=int, default=12)
    ap.add_argument("--decay", type=float, default=0.10)
    ap.add_argument("--kinds", default=",".join(RIVALS))
    ap.add_argument("--variants", action="store_true", help="one line per parameter variant (mixed rivals)")
    ap.add_argument("--replay", action="store_true", help="play back the recorded rivals of Duels II instead")
    a = ap.parse_args(argv)
    if a.replay:
        return replay_main(a.ticks, a.decay)
    kinds = a.kinds.split(",")
    base = play(a.n, a.seed, a.ticks, a.decay, kinds)
    table(f"CODE POLICY, {a.ticks} ticks, decay {a.decay}, price + days, {a.n} duels per rival", base)
    if a.variants:
        print(f"\n  {'variant':18} {'mix pts':>8} {'deal%':>6} {'rounds':>6}   delta   worst rival delta")
        b = mixed(base)
        for name, over in VARIANTS.items():
            res = with_params(over, lambda: play(a.n, a.seed, a.ticks, a.decay, kinds))
            worst = min(((res[k]["points"] - base[k]["points"], k) for k in MIX if k in res), default=(0, ""))
            print(f"  {name:18} {mixed(res):8.2f} {100 * mixed(res, 'deal_rate'):6.0f} {mixed(res, 'rounds'):6.1f} "
                  f"{mixed(res) - b:+7.2f}   {worst[1]} {worst[0]:+.2f}")



# --- replay of the real rivals of Duels II ------------------------------------------------------------------
def load_traces(record_dir: Path | str | None = None, session: int = 3, memory: Path | str | None = None) -> list[dict]:
    """One row per recorded duel of a session: our role, limit and day weight, the rival's priced offers by
    tick offset, and how it ended. Read from the recorder's files (data/record/duels) and our duel memory."""
    import json
    from .. import config
    d = Path(record_dir or config.DATA / "record" / "duels")
    try:
        mem = json.loads(Path(memory or config.LIVE / "duel_memory.json").read_text()).get("duels", {})
    except (OSError, ValueError):
        mem = {}
    final, msgs = {}, defaultdict(list)
    for f in d.glob("*.json"):
        try:
            x = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(x, dict) and x.get("session") == session:
            final[x["duel"]] = x
    for f in sorted(d.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("duel") in final:
                msgs[e["duel"]] += e.get("messages_new") or []
    rows = []
    for i, x in sorted(final.items()):
        length = int((mem.get(str(i)) or {}).get("deadline", x["deadline_tick"]) - (mem.get(str(i)) or {}).get(
            "first_seen", x["deadline_tick"] - 16)) or 16
        start = x["deadline_tick"] - length
        seen = sorted({(m["tick"], m["from"], m.get("price"), m.get("days")) for m in msgs[i] if m.get("price") is not None})
        rows.append({
            "duel": i, "role": x["role"], "limit": x["your_limit"], "w": float(x.get("your_days_weight") or 0.0),
            "length": length, "status": x["status"], "price": x.get("price"), "days": x.get("days"),
            "accepted_by": (mem.get(str(i)) or {}).get("accepted_by"), "result": float(x.get("result") or 0.0),
            "rounds": x.get("rounds"),
            "rival": [(t - start, p, dd or 0) for t, who, p, dd in seen if str(who).lower() not in ("you", "us", "me")],
            "ours": [(t - start, p, dd or 0) for t, who, p, dd in seen if str(who).lower() in ("you", "us", "me")],
        })
    return rows


class Replay(Rival):
    """A rival that plays back what a real team did in Duels II, on the new clock: its own offers at the same
    point of the duel, and it accepts terms at least as good for it, on price and on days, as terms it is
    known to take (its own offers so far, and our offer if it accepted one). Not reactive: a lower bound."""
    kind = "replay"

    def __init__(self, sc, rng, row: dict, ticks: int):
        super().__init__(sc, rng)
        scale = (ticks - 1) / max(1, row["length"] - 1)
        self.plan = sorted({(int(round(t * scale)), p, d) for t, p, d in row["rival"]})
        self.takes: list[tuple] = []                       # (from tick, price, days) it accepts
        if row["status"] == "deal" and row["accepted_by"] == "rival" and row["ours"]:
            t = max(0, int(round(row["ours"][-1][0] * scale)))
            self.takes.append((t, row["price"], row["days"] or 0))
        self.sent = 0

    def better(self, price, days, ref_price, ref_days) -> bool:
        if self.role == "seller":
            return price >= ref_price and (days or 0) >= ref_days
        return price <= ref_price and (days or 0) <= ref_days

    def act(self, k, ours, theirs):
        if ours:
            p, d = ours[-1][0], ours[-1][1]
            refs = [(rp, rd) for t, rp, rd in self.takes if t <= k] + [(rp, rd) for rp, rd, _ in theirs]
            if any(self.better(p, d, rp, rd) for rp, rd in refs):
                return ("accept",)
        due = [x for x in self.plan if x[0] <= k]
        if len(due) > self.sent:
            t, p, d = due[self.sent]
            self.sent += 1
            if not theirs or (p, d) != (theirs[-1][0], theirs[-1][1]):
                return ("offer", p, d, self.text(p))
        return None


def replay(rows: list[dict], ticks: int, decay: float) -> dict:
    """Our code policy against every recorded rival, on the given clock. Points as the server scores them."""
    tmp = Path(tempfile.mkdtemp(prefix="replay")) / "duel_memory.json"
    dom = DuelsDomain(memory=OpponentMemory(tmp, autosave=False), use_llm=False)
    pts, deals, rounds, illegal, by_role = 0.0, 0, 0, 0, defaultdict(float)
    for n, row in enumerate(rows):
        role, w = row["role"], abs(row["w"])
        # only our side is known: the rival's limit and weight are never read by Replay
        sc = Scenario(value=row["limit"], cost=row["limit"], our_role=role, w_us=w if role == "seller" else -w,
                      w_rival=0.0, uses_days=True, decay=decay, item=f"Replay {row['duel']}")
        r = run_duel(dom, sc, Replay(sc, random.Random(n), row, ticks), n + 1, f"Rival {row['duel']}", ticks,
                     5000 + 20 * n)
        dom.memory.record_result(n + 1, "deal" if r.deal else "no_deal", price=r.price, rounds=r.rounds, days=r.days,
                                 accepted_by=r.accepted_by or None)
        pts += r.points
        deals += r.deal
        rounds += r.rounds if r.deal else 0
        illegal += r.illegal
        by_role[role] += r.points
    n = max(1, len(rows))
    return {"n": len(rows), "points": pts, "avg": pts / n, "deal_rate": deals / n, "rounds": rounds / max(1, deals),
            "illegal": illegal, "seller": by_role["seller"], "buyer": by_role["buyer"]}


def replay_main(ticks: int, decay: float) -> None:
    rows = load_traces()
    if not rows:
        print("no recorded duels found")
        return
    real = sum(r["result"] for r in rows)
    print(f"\nREPLAY of {len(rows)} recorded Duels II rivals (real result that day: {real:.0f} points, "
          f"{sum(1 for r in rows if r['status'] == 'deal')} deals, with Claude deciding)")
    print(f"  {'clock':22} {'variant':18} {'points':>7} {'deal%':>6} {'rounds':>6} {'seller':>7} {'buyer':>6} {'illegal':>7}")
    for label, t, dec in (("16 ticks, decay 0.08", 16, 0.08), (f"{ticks} ticks, decay {decay}", ticks, decay)):
        base = None
        for name, over in VARIANTS.items():
            r = with_params(over, lambda: replay(rows, t, dec))
            base = base if base is not None else r["points"]
            print(f"  {label:22} {name:18} {r['points']:7.0f} {100 * r['deal_rate']:6.0f} {r['rounds']:6.1f} "
                  f"{r['seller']:7.0f} {r['buyer']:6.0f} {r['illegal']:7d}   {r['points'] - base:+.0f}")


if __name__ == "__main__":
    main()
