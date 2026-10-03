"""Quick evaluation of the dealer negotiator against the Friday-calibrated fake dealers.

    python -m bazaar.dealers.evaluate                 # code fallback only, 200 threads per scenario
    python -m bazaar.dealers.evaluate --n 50 --seed 3
    python -m bazaar.dealers.evaluate --llm --calls 30   # Claude decides (<= 30 calls, well under 2 $)

Reports, per scenario: deal rate, share of the dealer's price range captured (true secret limit of the
simulator), value gained at our private values, messages per thread, and two safety counters that must
stay at 0: deals outside our limit and deals at the dealer's opening price.
"""
from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from .domain import DealersDomain
from .profiles import ProfileStore
from .simulator import TEAM, DealerWorld

AFFINITY = {"LAV": 1.6, "MAL": 1.3, "RET": 1.1, "SAL": 0.9, "CHA": 0.7, "LAT": 0.5}
RARITY_BOOK = {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}


def make_catalog(sets=("LAV", "MAL", "SAL", "LAT", "RET")) -> dict:
    rar = ["common"] * 5 + ["uncommon"] * 3 + ["rare"] * 2 + ["epic", "legendary"]
    return {
        "rarities": {r: {"book": b} for r, b in RARITY_BOOK.items()},
        "values": {"copy_marginals": [1.0, 0.25, 0.1]},
        "packs": [{"id": "sobre_barrio", "slots": [{"common": 1.0}, {"common": 1.0}, {"common": 0.75, "uncommon": 0.25}]},
                  {"id": "sobre_plata", "slots": [{"common": 1.0}, {"common": 1.0}, {"uncommon": 1.0}, {"uncommon": 1.0},
                                                  {"rare": 0.86, "epic": 0.12, "legendary": 0.02}]}],
        "sets": [{"id": s, "released": True, "cards": [
            {"id": f"{s}-{i + 1:02d}", "name": f"{s} card {i + 1}", "rarity": r, "book": RARITY_BOOK[r],
             "hidden": r == "legendary"} for i, r in enumerate(rar)]} for s in sets],
    }


FRIDAY_PERSONAS = [
    {"id": "abuela", "name": "Abuela Carmen", "status": "active", "level": 1, "kind": "dealer", "open_to_all": True,
     "traits": {"patience": 0.85, "generosity": 0.8, "shrewdness": 0.2, "memory": 0.15, "strictness": 0.1},
     "menu": {"sells": [{"pack": "sobre_barrio", "list_price": 26, "opening_ask": 30, "per_team_per_hour": 3},
                        {"rarity": "common", "sets": "released", "list_price": 10},
                        {"rarity": "uncommon", "sets": "released", "list_price": 25}],
              "buys": [{"rarity": "common", "sets": "released"}, {"rarity": "uncommon", "sets": "released"}],
              "deals_per_team_per_hour": 8}},
    {"id": "chato", "name": "El Chato", "status": "active", "level": 2, "kind": "dealer", "open_to_all": True,
     "traits": {"patience": 0.35, "generosity": 0.25, "shrewdness": 0.85, "memory": 0.9, "strictness": 0.85},
     "menu": {"sells": [{"pack": "sobre_plata", "list_price": 150, "opening_ask": 188, "per_team_per_hour": 2},
                        {"rarity": "uncommon", "sets": "released", "list_price": 26},
                        {"rarity": "rare", "sets": "released", "list_price": 77}],
              "buys": [{"rarity": "uncommon", "sets": "released"}, {"rarity": "rare", "sets": "released"}],
              "deals_per_team_per_hour": 6}},
]


@dataclass
class Scenario:
    name: str
    dealer: str
    kind: str
    topic: dict
    item_type: str = ""
    asset: dict | None = None          # the card we sell (with your_value)
    value: float = 0.0                 # our private value of the item (for reporting)


SCENARIOS = [
    Scenario("abuela buys LAV uncommon from her", "abuela", "buy:uncommon", {"buy": {"card": "LAV-07"}}, "card:LAV-07", value=40),
    Scenario("abuela LAV common", "abuela", "buy:common", {"buy": {"card": "LAV-04"}}, "card:LAV-04", value=16),
    Scenario("abuela sobre_barrio", "abuela", "buy:pack", {"buy": {"pack": "sobre_barrio"}}, "pack:sobre_barrio"),
    Scenario("chato LAV rare", "chato", "buy:rare", {"buy": {"card": "LAV-10"}}, "card:LAV-10", value=112),
    Scenario("chato buys our spare SAL uncommon", "chato", "sell:uncommon", {"sell": {"assets": [901]}},
             asset={"id": 901, "kind": "card", "ref": "SAL-07", "rarity": "uncommon", "set": "SAL", "your_value": 5.6}),
    Scenario("abuela buys our spare LAT common", "abuela", "sell:common", {"sell": {"assets": [902]}},
             asset={"id": 902, "kind": "card", "ref": "LAT-02", "rarity": "common", "set": "LAT", "your_value": 1.25}),
]


class Ctx(SimpleNamespace):
    pass


def make_ctx(tick: int, seconds: float = 25.0, llm=None) -> Ctx:
    return Ctx(tick=tick, day="sat", deadline=time.time() + seconds, lessons=None, llm=llm, ledger=None,
               budget={"messages": {}, "spend_hour_left": 250}, control={}, cautious=False, llm_ok=True)


def make_sit(world: DealerWorld, scen: Scenario, cash: int = 400) -> SimpleNamespace:
    assets = [{"id": 1, "kind": "card", "ref": "LAT-01", "rarity": "common", "set": "LAT", "your_value": 5.0}]
    if scen.asset:
        assets.append(dict(scen.asset))
        dup = dict(scen.asset, id=scen.asset["id"] + 1000)
        assets.append(dup)     # a spare: we hold two copies
    return SimpleNamespace(tick=world.tick, me={"id": TEAM, "cash": cash, "affinity": AFFINITY, "assets": assets,
                                                "unlocked": ["abuela", "chato"], "level": 2},
                           threads=world.open_raw(), my_offers=[], dealers=FRIDAY_PERSONAS,
                           limits={"max_open_threads_per_team": 6}, feed_new=[], closed_threads=[])


def apply(world: DealerWorld, actions, sent: dict) -> None:
    for a in actions:
        p = a.params
        if a.kind == "thread_message":
            t = world.threads[p["thread"]]
            if t.status == "open":
                t.team_message(p["price"], p.get("text", ""))
                sent["msgs"] += 1
        elif a.kind == "accept_offer":
            for t in world.threads.values():
                if any(o["id"] == p["offer"] for o in t.offers) and t.status == "open":
                    t.accept(p["offer"])
                    sent["accepts"] += 1
        elif a.kind == "close_thread":
            t = world.threads[p["thread"]]
            if t.status == "open":
                t.close()


def run_thread(scen: Scenario, seed: int, domain: DealersDomain, use_llm: bool = False, max_ticks: int = 30,
               inject: bool = False) -> dict:
    world = DealerWorld(seed=seed, inject=inject)
    t = world.open(scen.dealer, scen.topic, scen.kind, scen.item_type,
                   asset_ids=(scen.topic.get("sell") or {}).get("assets"))
    sent = {"msgs": 0, "accepts": 0}
    for _ in range(max_ticks):
        if t.status != "open":
            break
        world.advance()
        sit = make_sit(world, scen)
        ctx = make_ctx(world.tick)
        acts = domain.decide(sit, ctx) if use_llm else domain.fallback(sit, ctx)
        apply(world, [a for a in acts if a.kind != "open_thread"], sent)
    value = scen.value
    if scen.kind == "buy:pack":
        from .values import Values, pack_value
        value = pack_value("sobre_barrio", Values({"affinity": AFFINITY, "assets": []}, make_catalog()))
    if scen.asset:
        value = scen.asset["your_value"]
    price = t.deal_price
    buying = scen.kind.startswith("buy")
    gain = 0.0 if price is None else ((value - price) if buying else (price - value))
    return {"deal": price is not None, "price": price, "opening": t.opening, "limit": t.limit,
            "capture": t.capture(), "gain": gain, "msgs": sent["msgs"],
            "at_opening": price is not None and price == t.opening, "status": t.status, "reason": t.closed_reason,
            "outside_limit": price is not None and (gain < 0)}


def evaluate(n: int = 200, seed: int = 0, use_llm: bool = False, calls: int = 30, scenarios=SCENARIOS) -> list[dict]:
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for s_i, scen in enumerate(scenarios):
            store = ProfileStore(Path(tmp) / f"mem{s_i}.json")
            dom = DealersDomain(store=store, catalog=make_catalog(), use_llm=use_llm, max_calls=calls if use_llm else 0)
            results = []
            for k in range(n):
                store.data["threads"].clear()
                if use_llm and dom.calls >= calls:
                    break
                results.append(run_thread(scen, seed * 100_000 + s_i * 1000 + k, dom, use_llm))
            if not results:
                continue
            rows.append({"scenario": scen.name, "n": len(results),
                         "deal_rate": round(sum(r["deal"] for r in results) / len(results), 3),
                         "capture": round(statistics.mean(r["capture"] for r in results), 3),
                         "value_gain": round(statistics.mean(r["gain"] for r in results), 2),
                         "msgs": round(statistics.mean(r["msgs"] for r in results), 1),
                         "at_opening": sum(r["at_opening"] for r in results),
                         "outside_limit": sum(r["outside_limit"] for r in results),
                         "llm_calls": dom.calls, "llm_usd": round(dom.cost_usd, 4)})
    return rows


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--llm", action="store_true", help="let Claude decide (costs money)")
    ap.add_argument("--calls", type=int, default=30, help="max Claude calls per scenario group (with --llm)")
    a = ap.parse_args(argv)
    if a.llm:
        a.n = min(a.n, 3)
    rows = evaluate(n=a.n, seed=a.seed, use_llm=a.llm, calls=a.calls if not a.llm else max(1, a.calls // len(SCENARIOS)))
    head = f"{'scenario':38} {'n':>4} {'deal':>6} {'capture':>8} {'gain P':>7} {'msgs':>5} {'@open':>6} {'bad':>4}"
    print(head)
    print("-" * len(head))
    for r in rows:
        print(f"{r['scenario']:38} {r['n']:>4} {r['deal_rate']:>6.2f} {r['capture']:>8.3f} {r['value_gain']:>7.2f} "
              f"{r['msgs']:>5.1f} {r['at_opening']:>6} {r['outside_limit']:>4}")
    if a.llm:
        print(f"Claude calls: {sum(r['llm_calls'] for r in rows)}, cost ${sum(r['llm_usd'] for r in rows):.3f}")


if __name__ == "__main__":
    main()
