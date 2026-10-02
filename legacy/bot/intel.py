"""The bot's view of the world, written every tick to <data>/intel.json for the dashboard.

Per card: our private value, book, the role the bot gives it (target/buy/sell/keep/ignore), the
price bounds it would trade at, live listings and dealer threads, and a short reason. Plus the plan
(budget), the strategy knobs, per-dealer haggle state and duel estimates. Built only from data the
strategies already fetched this tick, so it costs no extra requests.
"""

from __future__ import annotations

import json
import time

from .core import Ctx

RESERVE = 120  # keep in step with market.py's cash reserve


def _market_book(boards: dict) -> dict:
    book: dict[str, dict] = {}
    for offers in boards.values():
        for o in offers:
            give, want = o.get("give") or {}, o.get("want") or {}
            for a in give.get("assets") or []:
                if isinstance(a, dict) and want.get("cash"):
                    b = book.setdefault(a.get("ref"), {"best_ask": None, "asks": 0, "best_bid": None, "bids": 0})
                    b["asks"] += 1
                    b["best_ask"] = want["cash"] if b["best_ask"] is None else min(b["best_ask"], want["cash"])
            for t in want.get("types") or []:
                if t.startswith("card:") and give.get("cash"):
                    b = book.setdefault(t[5:], {"best_ask": None, "asks": 0, "best_bid": None, "bids": 0})
                    b["bids"] += 1
                    b["best_bid"] = give["cash"] if b["best_bid"] is None else max(b["best_bid"], give["cash"])
    return book


def build(ctx: Ctx, memory: dict) -> dict:
    v = ctx.values
    dealer_mem, market_mem = memory.get("dealer", {}), memory.get("market", {})
    book = _market_book(ctx.shared.get("boards", {}))
    reserved = set(ctx.shared.get("reserved", []))

    listed = {}
    for oid, l in (market_mem.get("listings") or {}).items():
        listed[l.get("ref")] = {"ask": l.get("price"), "floor": l.get("floor"), "offer_id": oid}
    threads = {}
    for tid, t in (dealer_mem.get("threads") or {}).items():
        if t.get("status") == "open":
            ref = (t.get("topic", {}).get("buy") or {}).get("card") or t.get("item")
            threads[ref] = {"thread": int(tid), "dealer": t.get("dealer"), "goal": t.get("goal"), "first": t.get("first"),
                            "ours": t.get("ours"), "theirs": t.get("theirs"), "limit": t.get("limit"),
                            "said": t.get("said", []), "leak": t.get("leak"), "final": t.get("final")}

    cards = {}
    for ref, c in v.cards.items():
        held = v.count(ref)
        aff = v.affinity.get(c["set"], 1.0)
        nxt = round(v.next_copy(ref), 2)
        spare_loss = round(v.spare_value(ref), 2) if held else None
        if held > 1:
            role, why = "sell", f"{held} copies: the extra one is worth only {spare_loss} P to us"
        elif held == 1 and aff < 1.0:
            role, why = "sell", f"set multiplier {aff} < 1: worth {spare_loss} P to us, {c['book']} P book"
        elif held == 1:
            role, why = "keep", f"our only copy, set multiplier {aff}"
        elif not c.get("released"):
            role, why = "ignore", "set not released yet"
        elif nxt >= c["book"]:
            role, why = "target", f"worth {nxt} P to us vs {c['book']} P book (multiplier {aff})"
        elif nxt > 0.6 * c["book"]:
            role, why = "buy", f"worth {nxt} P to us; buy below that"
        else:
            role, why = "ignore", f"worth only {nxt} P to us"
        entry = {"name": c.get("name"), "set": c["set"], "rarity": c["rarity"], "book": c["book"], "held": held,
                 "value": nxt, "spare_loss": spare_loss, "role": role, "why": why,
                 "max_buy": round(nxt * 0.85) if role in ("target", "buy") else None,
                 "min_sell": max(round((spare_loss or 0) + 3), round(0.4 * c["book"])) if role == "sell" else None,
                 "market": book.get(ref), "reserved": False}
        if ref in listed:
            entry.update(listed[ref])
        if ref in threads:
            entry["dealer"] = threads[ref]
        cards[ref] = entry
    for a in ctx.me.get("assets", []):
        if a.get("id") in reserved and a.get("ref") in cards:
            cards[a["ref"]]["reserved"] = True
    priority = sorted((r for r, e in cards.items() if e["role"] == "target"), key=lambda r: -cards[r]["value"])
    for i, r in enumerate(priority, 1):
        cards[r]["priority"] = i

    cash = ctx.me.get("cash", 0)
    duels = memory.get("duels", {})
    return {
        "tick": ctx.clock.get("tick"), "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "affinity": v.affinity,
        "cards": cards,
        "plan": {"budget": {"cash": cash, "reserved": RESERVE, "free": max(0, cash - RESERVE)},
                 "targets": priority[:10],
                 "sell": [r for r, e in cards.items() if e["role"] == "sell"],
                 "open_dealer_threads": list(threads.values())},
        "dealer": {"deals": (dealer_mem.get("deals") or [])[-20:], "probe_stats": dealer_mem.get("probe_stats", {}),
                   "cooloff_until": dealer_mem.get("cooloff_until")},
        "duels": {k: v for k, v in duels.items() if k in ("duels", "estimates", "history")} or duels,
        "params": {k: v for k, v in ctx.env.items() if k.startswith("BOT_DEALER_")},
    }


def write(ctx: Ctx, memory: dict, path):
    try:
        data = build(ctx, memory)
    except Exception as e:  # noqa: BLE001 - the snapshot must never stop the bot
        ctx.journal.error("intel", e)
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=str))
    tmp.replace(path)
