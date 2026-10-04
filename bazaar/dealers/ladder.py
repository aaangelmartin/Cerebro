"""The dealer ladder as the game scores it, for the brain and the dashboard.

Rules (RULES.md, Scoring): "the dealer ladder (share of each dealer's price range you captured: your best three
deals per level count, a missing one as zero, higher levels weigh more)". GET /api/me exposes the live
components of Negotiating: `neg_points` (value gained in trades with other teams, in P), `duel_points` and
`ladder_points`. Measured on Saturday: three good Abuela deals took ladder_points 0 -> 0.056 (~0.019 each), which
fits weights level/15 over five levels with three slots each (a full level 1 = 0.067, level 2 = 0.133,
level 3 = 0.2). Dealer deals did not move neg_points: with a dealer only the share of its range counts.
A deal closed by hand counts in the game like any other: MAL-09 bought from Los Pícaros at 57 (opening 73) in
a hand-run thread took ladder_points 0.149 -> 0.196 at tick 967 (+0.047, about half of a level 4 slot of 0.089).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SLOTS = 3
LEVELS_ASSUMED = 5          # "haggles with five card dealers"; weights assumed level / (1+2+3+4+5)


def _read(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def slot_value(level: int) -> float:
    """ladder_points one full-capture slot is worth at this level (estimate from the measured level 1)."""
    return round(level / sum(range(1, LEVELS_ASSUMED + 1)) / SLOTS, 4)


def dealer_prices(feed: list[dict], since_tick: int = 0) -> dict[str, dict[str, Any]]:
    """What each dealer opened at and the best price it reached, per side, from every team's public threads."""
    threads: dict[Any, dict] = {}
    for r in feed:
        p = r.get("payload") or {}
        if r.get("type") not in ("thread.opened", "thread.message") or p.get("kind") != "persona":
            continue
        if (r.get("tick") or 0) < since_tick:
            continue
        t = threads.setdefault(p.get("thread"), {"dealer": p.get("with"), "side": None, "prices": [], "final": False})
        topic = p.get("topic") if r.get("type") == "thread.opened" else None
        if isinstance(topic, dict):
            t["side"] = "team_sells" if topic.get("sell") else "team_buys" if topic.get("buy") else t["side"]
        o = p.get("offer")
        if isinstance(o, dict) and p.get("sender") == p.get("with"):
            want, give = (o.get("want") or {}).get("cash") or 0, (o.get("give") or {}).get("cash") or 0
            if t["side"] is None:
                t["side"] = "team_buys" if want else "team_sells"
            t["prices"].append(want or give)
            t["final"] = t["final"] or bool(o.get("final"))
    out: dict[str, dict[str, Any]] = {}
    for t in threads.values():
        if not t["prices"] or not t["dealer"] or not t["side"]:
            continue
        opening = t["prices"][0]
        best = min(t["prices"]) if t["side"] == "team_buys" else max(t["prices"])
        row = out.setdefault(t["dealer"], {}).setdefault(t["side"], {})
        b = row.setdefault(str(opening), {"threads": 0, "best": best, "finals": []})
        b["threads"] += 1
        b["best"] = min(b["best"], best) if t["side"] == "team_buys" else max(b["best"], best)
        if t["final"]:
            b["finals"] = (b["finals"] + [t["prices"][-1]])[-6:]
    return out


def report(live: Path, me: dict | None = None, dealers: list[dict] | None = None,
           feed: list[dict] | None = None, since_tick: int = 0) -> dict[str, Any]:
    """Our ladder slot by slot, what is at stake, and the prices the dealers showed today."""
    mem = _read(Path(live) / "dealer_memory.json", {})
    deals = [d for d in mem.get("deals") or [] if d.get("negotiated")]
    score = (me or {}).get("score") if isinstance((me or {}).get("score"), dict) else {}
    by_level: dict[int, list[dict]] = {}
    for p in dealers or []:
        menu = p.get("menu") or {}
        if p.get("level") and (p.get("kind", "dealer") in ("dealer", "persona") or menu.get("buys") or menu.get("sells")):
            by_level.setdefault(int(p["level"]), []).append(p)
    unlocked = set((me or {}).get("unlocked") or [])
    levels = {}
    at_stake = 0.0
    for lvl in sorted(by_level):
        ours = sorted((d for d in deals if d.get("level") == lvl), key=lambda d: -float(d.get("capture") or 0))[:SLOTS]
        caps = [round(float(d.get("capture") or 0), 2) for d in ours] + [0.0] * (SLOTS - len(ours))
        missing = round(sum(1.0 - c for c in caps) * slot_value(lvl), 3)
        at_stake += missing
        levels[str(lvl)] = {
            "dealers": [{"id": p.get("id"), "open_to_us": bool(p.get("id") in unlocked or p.get("open_to_all"))}
                        for p in by_level[lvl]],
            "best3_capture_est": caps, "empty_slots": SLOTS - len(ours),
            "slot_worth_ladder_points": slot_value(lvl), "ladder_points_missing": missing,
            "deals": [{"item": d.get("item"), "side": d.get("side"), "opening": d.get("opening"),
                       "price": d.get("price"), "capture": d.get("capture")} for d in ours]}
    return {
        "score_components_now": {k: score.get(k) for k in ("negotiating", "neg_points", "duel_points", "ladder_points")},
        "how_it_scores": "ladder_points: best 3 negotiated deals per dealer level, each = share of the dealer's range "
                         "(opening -> its limit) we captured; an empty slot is 0; higher levels weigh more. A deal at "
                         "the opening price scores 0. Dealer deals do NOT add to neg_points (only trades with teams "
                         "do); the size of the deal does not matter, the share captured does. Captures here are our "
                         "estimates; the game's ladder_points is the truth (a hand-closed deal counts too).",
        "levels": levels, "ladder_points_missing_total": round(at_stake, 3),
        "dealer_prices_seen_today": dealer_prices(feed or [], since_tick),
    }
