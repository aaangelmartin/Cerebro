"""Seed the Lab: Friday's 20 curated lessons plus our own extra analysis -> lessons.jsonl; rules.json.

    python -m bazaar.lab.seed            # writes config.LAB/lessons.jsonl (only if absent) and rules.json
    python -m bazaar.lab.seed --force    # rewrites lessons.jsonl from scratch

Status policy: confidence >= 0.8 and a backtest that does not contradict it -> active, weight
0.6..0.8 by confidence; 0.7..0.8 -> canary (0.3); weaker -> proposed. A backtest with enough cases
and negative lift demotes one step.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from bazaar import config
from bazaar.core.types import Lesson
from bazaar.lab.backtest import backtest_lesson
from bazaar.lab.common import read_json, write_json
from bazaar.lab.ingest import Corpus, build_features, load_friday
from bazaar.lab.store import LessonStore, write_notice

SEED_PATH = config.FRIDAY / "analysis" / "seed_lessons.json"
SIM_DATA = config.ROOT / "sim" / "data"

SCOPE = {"duels": "duel", "scoring": "global", "ladder": "global", "packs": "dealer", "market": "market",
         "rivals": "market", "ops": "global", "dealers": "dealer", "market_test": "broker"}

# Structured params + falsifiable predictions for the seeds (ids from seed_lessons.json).
SEED_PARAMS: dict[str, dict] = {
    "L01": {"decay": {"Duels I": 0.06, "Duels II": 0.08, "Duels III": 0.10}, "min_gain_per_round": "decay",
            "prediction": {"kind": "duel_fast", "max_rounds": 3}},
    "L02": {"accept_first_if_margin_frac": 0.15,
            "prediction": {"kind": "duel_accept_first", "min_margin_frac": 0.15}},
    "L03": {"archetypes": ["fixed", "stepped", "tough", "mute"],
            "prediction": {"kind": "rival_rate", "rival_kind": "fixed", "outcome": "deal", "lo": 0.8, "hi": 1.0}},
    "L04": {"open_margin_frac_vs_silent": 0.15,
            "prediction": {"kind": "rival_rate", "rival_kind": "mute", "outcome": "no_deal", "lo": 0.5, "hi": 1.0}},
    "L05": {},
    "L06": {"buys_common": [5, 6], "buys_uncommon": [12, 14], "max_messages": 3,
            "prediction": {"kind": "dealer_price", "dealer": "abuela", "side": "buy", "item": "common",
                           "stage": "last", "lo": 5, "hi": 6}},
    "L07": {"sells_uncommon_final": [21, 24], "sells_common_final": [9, 10], "pack_final": [19, 21],
            "prediction": {"kind": "dealer_price", "dealer": "abuela", "side": "sell", "item": "uncommon",
                           "stage": "final", "lo": 21, "hi": 24}},
    "L08": {"buys_uncommon_max": 16, "sticky_open": 13,
            "prediction": {"kind": "dealer_price", "dealer": "chato", "side": "buy", "item": "uncommon",
                           "stage": "last", "lo": 13, "hi": 16}},
    "L09": {"sells_rare_open": 97, "sells_rare_seen": [82, 93], "sobre_plata": "trap",
            "prediction": {"kind": "mirror_ratio", "dealer": "chato", "side": "sell", "item": "rare",
                           "lo": 0.3, "hi": 0.8}},
    "L10": {"prediction": {"kind": "score_delta", "class_prefix": "dealer_buy:pack:sobre_plata", "sign": -1}},
    "L11": {"prediction": {"kind": "score_delta", "class_prefix": "team_buy", "sign": 1}},
    "L12": {},
    "L13": {"first_price_deal_ladder": 0},
    "L14": {"pack_ev_book": 44, "sobre_barrio_fair": [19, 21]},
    "L15": {"rastro_common": [5, 9], "rastro_uncommon_ask": [25, 40], "rare_bid": [50, 70],
            "prediction": {"kind": "settlement_price", "where": "rastro", "item": "common", "lo": 5, "hi": 9}},
    "L16": {"prediction": {"kind": "listing_price", "side": "bid", "item": "rare", "lo": 50, "hi": 70}},
    "L17": {}, "L18": {}, "L19": {"abuela_deals_per_hour": 8, "chato_deals_per_hour": 6}, "L20": {},
}

# Our own extra analysis of Friday's data (feed ticks 143-159, leaderboard attribution, duel results).
EXTRA: list[dict] = [
    {"id": "X01", "scope": "global", "conf": 0.8,
     "rule": "Selling single cards to a dealer below book value moved the seller's score by about 0 or slightly "
             "down (clean leaderboard windows, 6 teams). Sell to dealers only near-zero-value duplicates, and "
             "never spend a scarce dealer slot on it when a buy with real concessions is available.",
     "params": {"prediction": {"kind": "score_delta", "class_prefix": "dealer_sell", "sign": -1}}},
    {"id": "X02", "scope": "duel", "conf": 0.85,
     "rule": "A rival that repeats the same price ('fixed') will not move: if that price leaves us any margin, "
             "accept it now; every extra round only burns 6-10% of the pie (3/3 fixed rivals closed, mean 28 pts).",
     "params": {"prediction": {"kind": "rival_rate", "rival_kind": "fixed", "outcome": "deal", "lo": 0.8, "hi": 1.0}}},
    {"id": "X03", "scope": "dealer:abuela", "conf": 0.85,
     "rule": "Abuela's sobre_barrio opens at 30 (list 26) and settles at 19-21 after 4-6 small steps; never "
             "pay more than 21 for it.",
     "params": {"pack_final": [19, 21],
                "prediction": {"kind": "dealer_price", "dealer": "abuela", "side": "sell",
                               "item": "pack:sobre_barrio", "stage": "deal", "lo": 19, "hi": 21}}},
    {"id": "X04", "scope": "market", "conf": 0.75,
     "rule": "On El Rastro, common cards are listed at 6-12 P (mode 9) and actually settle at 5-9: a common "
             "listed above 12 rarely sells; buying a missing common at <= 9 is fair.",
     "params": {"prediction": {"kind": "listing_price", "side": "ask", "item": "common", "lo": 6, "hi": 12}}},
    {"id": "X05", "scope": "dealer:chato", "conf": 0.75,
     "rule": "El Chato mirrors our steps only partly when he sells (about half of our concession comes back): "
             "bigger steps from us earn bigger steps from him, but a repeated price earns nothing.",
     "params": {"mirror_ratio": [0.3, 0.8],
                "prediction": {"kind": "mirror_ratio", "dealer": "chato", "side": "sell", "item": "*",
                               "lo": 0.3, "hi": 0.8}}},
]


def _status_for(conf: float) -> tuple[str, float]:
    if conf >= 0.8:
        return "active", round(0.6 + 0.2 * min(1.0, (conf - 0.8) / 0.15), 3)
    if conf >= 0.7:
        return "canary", 0.3
    return "proposed", 0.0


def _evidence_ids(raw: dict) -> list[str]:
    ev = raw.get("evidence") or {}
    out: list[str] = []
    for k, v in ev.items():
        if isinstance(v, list):
            for x in v:
                if isinstance(x, int):
                    out.append(f"{'duel' if raw.get('applies_to') == 'duels' else 'thr'}:friday:{x}")
                elif isinstance(x, str):
                    out.append(f"note:{x}")
        elif isinstance(v, dict):
            out.append(f"note:{k}")
        else:
            out.append(f"note:{k}={v}")
    return out[:30]


def build_seed_lessons(corpus: Corpus) -> list[Lesson]:
    raw = read_json(SEED_PATH, {}) or {}
    lessons: list[Lesson] = []
    rows = [{"id": r["id"], "scope": _seed_scope(r), "conf": float(r.get("confidence", 0.5)), "rule": r["claim"],
             "params": SEED_PARAMS.get(r["id"], {}), "evidence": _evidence_ids(r)} for r in raw.get("lessons", [])]
    rows += [{**x, "evidence": []} for x in EXTRA]
    for r in rows:
        status, weight = _status_for(r["conf"])
        l = Lesson(id=r["id"], scope=r["scope"], rule=r["rule"], params=dict(r["params"]),
                   evidence=list(r["evidence"]), status=status, weight=weight, created_by="seed")
        bt = backtest_lesson(l, corpus)
        if bt.get("ok"):
            l.evidence = list(dict.fromkeys(l.evidence + bt["cases"]))[:40]
            l.n, l.sources = bt["n"], bt["sources"]
            if bt.get("lift") is not None and bt["lift"] < 0:
                status, weight = {"active": ("canary", 0.3), "canary": ("proposed", 0.0)}.get(status, (status, weight))
                l.status, l.weight = status, weight
        else:
            l.n = len(l.evidence)
            l.sources = 0
        l.backtest = {**bt, "confidence": r["conf"], "seeded": time.time(),
                      "live": {"prior": l.weight, "s": 0, "f": 0}}
        lessons.append(l)
    return lessons


def _seed_scope(r: dict) -> str:
    a = r.get("applies_to", "global")
    if a.startswith("dealer:"):
        return a
    return SCOPE.get(a, "global")


def build_rules(corpus: Corpus) -> dict:
    dealers = read_json(SIM_DATA / "dealers.json", {}) or {}
    schedule = read_json(SIM_DATA / "schedule.json", {}) or {}
    catalog = read_json(SIM_DATA / "catalog.json", {}) or {}
    levels = read_json(SIM_DATA / "levels.json", {}) or {}
    feats = build_features(corpus)
    return {
        "updated": time.time(),
        "sources": ["sdk/bazaar-kit/RULES.md", "docs/LOG.md", "public API snapshot 2026-10-03 01:50",
                    "data/friday"],
        "limits": {"accepts_per_team_per_tick": 1, "messages_per_side_per_tick": 1, "max_open_threads_per_team": 6,
                   "max_open_offers_per_team": 30, "offers_per_team_per_tick": 12,
                   "rate_limit_rps": 5, "rate_burst": 20, "streams_per_key": 6},
        "clock": {"days": {"fri": {"open": "19:00", "close": "23:00", "tick_s": 60},
                           "sat": {"open": "09:00", "close": "23:00", "tick_s": 30},
                           "sun": {"open": "09:00", "close": "15:00", "tick_s": 15}},
                  "tick_s_range": [5, 60]},
        "scoring": {"negotiating": 30, "market": 30, "judges": 40,
                    "duel_points": "margin * (1 - decay) ** rounds; no deal = 0; outside limit is negative",
                    "ladder": "share of the dealer's price range captured; best 3 deals per level; deal at opening price = 0",
                    "relative": "negotiating score is relative to the leader (leader = 30)",
                    "never_counts": ["number of trades", "fees", "pack luck", "gifts", "easter eggs", "grants"],
                    "round_weights": {"fri": 0.5, "sat": 1, "sun": 1}},
        "values": catalog.get("values", {}),
        "rarities": catalog.get("rarities", {}),
        "packs": catalog.get("packs", []),
        "fees": {"rastro": {"bps": 500, "per_card": 1}, "venue_cap": {"bps": 1000, "per_card": 5},
                 "venue_bond": 250, "venue_cost": 20, "venue_min_level": 2},
        "dealers": {p["id"]: {"level": p.get("level"), "menu": p.get("menu"), "traits": p.get("traits"),
                              "unlock": p.get("unlock")} for p in dealers.get("personas", [])},
        "levels": levels.get("levels", []),
        "schedule": [e for e in schedule.get("upcoming", []) if e.get("action") in ("duels", "bench", "grant_all",
                                                                                    "set_release", "round", "persona")],
        "duel_sessions": {e["params"].get("name", e["action"]): e["params"]
                          for e in schedule.get("upcoming", []) if e.get("action") == "duels"},
        "known": {"dealers": sorted(corpus.seen["dealers"]), "event_types": sorted(corpus.seen["event_types"]),
                  "decays": sorted(corpus.seen["decays"] | {0.06, 0.08, 0.1}), "venues": sorted(corpus.seen["venues"])},
        "observed": {"public_duel_deal_rate": feats["duels"]["public"]["deal_rate"],
                     "our_duel_deal_rate": feats["duels"]["ours"]["deal_rate"]},
        "changes": [],
    }


def seed(force: bool = False, lab: Path | None = None) -> dict:
    lab = Path(lab or config.LAB)
    corpus = load_friday(Corpus())
    path = lab / "lessons.jsonl"
    written = 0
    if force and path.exists():
        path.unlink()
    store = LessonStore(path)
    if not store.all():
        lessons = build_seed_lessons(corpus)
        store.upsert_many(lessons)
        written = len(lessons)
        write_notice("seed", f"Laboratorio sembrado con {written} lecciones del viernes.",
                     path=lab / "notices.jsonl", count=written)
    rules = build_rules(corpus)
    old = read_json(lab / "rules.json", {}) or {}
    rules["changes"] = old.get("changes", [])
    write_json(lab / "rules.json", rules)
    by = {}
    for l in store.all():
        by[l.status] = by.get(l.status, 0) + 1
    return {"written": written, "by_status": by, "lessons": len(store.all())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    print(json.dumps(seed(force=args.force), indent=1))


if __name__ == "__main__":
    main()
