"""The price board: every card with its best public ask and bid on any venue, what it really costs, and its history.

Built from what the game shows everyone and the recorder already keeps: public offers (never one addressed to a
team), sales between two teams, the catalog and each venue's fee. Nothing private of the market is read here: no
limit, no match, no thread. Built with the board, in its own thread; a request only hands the last one out."""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

VENUE = "v07"
TEAM = re.compile(r"t\d{2}")
SPARK = 12                  # prices drawn in the little chart
DEALS_KEPT = 60             # deals per card in the history
MIN_FOR_RANGE = 3           # sales a card needs before it has a usual range
HOT = 0.8                   # an ask this far under the low end of the usual range is marked
FLAT = 0.05                 # a move smaller than this is no trend
LIVE_TICKS = 2              # live.json carries what changed in this many ticks
LIVE_KEPT = 600


def quantile(sorted_values: list[int], q: float) -> int:
    if not sorted_values:
        return 0
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return int(round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)))


def team_deals(sales) -> dict[str, list[dict]]:
    """ref -> its sales between two teams for cash, oldest first. A trade of several cards has no price per card."""
    out: dict[str, list[dict]] = {}
    for s in sales:
        if s.get("dealer") or not s.get("price") or (s.get("n") or 1) != 1:
            continue
        seller, buyer = str(s.get("from") or ""), str(s.get("to") or "")
        if not (TEAM.fullmatch(seller) and TEAM.fullmatch(buyer)):
            continue
        out.setdefault(s["ref"], []).append({"tick": s.get("tick"), "price": int(s["price"]), "venue": s.get("venue"),
                                             "seller": seller, "buyer": buyer})
    return out


def stats(deals: list[dict]) -> dict:
    """Last price, the usual range (the middle half of its sales) and where it is heading."""
    prices = [d["price"] for d in deals]
    if not prices:
        return {"n": 0, "last": None, "last_tick": None, "low": None, "median": None, "high": None, "min": None,
                "max": None, "trend": None}
    ordered = sorted(prices)
    ranged = len(prices) >= MIN_FOR_RANGE
    trend = None
    if len(prices) >= 2:
        recent = prices[-3:] if len(prices) >= 4 else prices[-1:]
        before = prices[-6:-3] if len(prices) >= 4 else prices[-2:-1]
        a, b = sum(recent) / len(recent), sum(before) / len(before)
        trend = "up" if a > b * (1 + FLAT) else "down" if a < b * (1 - FLAT) else "flat"
    return {"n": len(prices), "last": prices[-1], "last_tick": deals[-1].get("tick"),
            "low": quantile(ordered, 0.25) if ranged else None, "median": quantile(ordered, 0.5),
            "high": quantile(ordered, 0.75) if ranged else None, "min": ordered[0], "max": ordered[-1], "trend": trend}


def unreleased(record: Path) -> list[dict]:
    """Sets the game's catalog names but has not released yet."""
    try:
        cat = json.loads((Path(record) / "latest" / "catalog.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cat = cat.get("data", cat) if isinstance(cat, dict) else {}
    return [{"id": s.get("id"), "name": s.get("name"), "color": s.get("color")}
            for s in cat.get("sets") or [] if isinstance(s, dict) and s.get("id") and not s.get("released", True)]


def supply(record: Path | None) -> dict[str, dict]:
    """ref -> {minted, print_run}: how many copies the game has handed out and how many it will ever print."""
    if not record:
        return {}
    try:
        cat = json.loads((Path(record) / "latest" / "catalog.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cat = cat.get("data", cat) if isinstance(cat, dict) else {}
    out = {}
    for s in cat.get("sets") or []:
        if not isinstance(s, dict) or not s.get("released", True):
            continue
        for c in s.get("cards") or []:
            if isinstance(c, dict) and c.get("id") and not c.get("hidden"):
                out[c["id"]] = {"minted": c.get("minted"), "print_run": c.get("print_run")}
    return out


def _side(o: dict, fees: dict) -> dict:
    v = fees.get(o.get("venue")) or {}
    return {"price": o["price"], "fee": o.get("fee") or 0, "venue": o.get("venue"),
            "venue_name": v.get("name") or o.get("venue"), "team": o.get("maker"), "offer": o.get("id"),
            "expires_tick": o.get("expires_tick"), "on_v07": o.get("venue") == VENUE}


def build(cat: dict, offers: list[dict], sales, sheets: dict, fees: dict, tick, record: Path | None = None,
          art: set | None = None) -> tuple[dict, dict]:
    """(the live board, the history). `offers` are the open ones with their fee; addressed offers are left out."""
    public = [o for o in offers or [] if not o.get("to") and o.get("side") in ("ask", "bid")
              and TEAM.fullmatch(str(o.get("maker") or ""))]
    asks: dict[str, list[dict]] = {}
    bids: dict[str, list[dict]] = {}
    for o in public:
        (asks if o["side"] == "ask" else bids).setdefault(o["ref"], []).append(o)
    holders: dict[str, set] = {}
    seekers: dict[str, set] = {}
    for team, s in (sheets or {}).items():
        if s.get("host"):
            continue
        for e in list(s.get("spares") or []) + list(s.get("for_sale") or []):
            holders.setdefault(e["ref"], set()).add(team)
        for e in s.get("wants") or []:
            seekers.setdefault(e["ref"], set()).add(team)
    for o in public:
        (holders if o["side"] == "ask" else seekers).setdefault(o["ref"], set()).add(o["maker"])
    deals = team_deals(sales)
    moved: dict[str, int] = {}
    for s in sales:
        moved[s["ref"]] = moved.get(s["ref"], 0) + 1
    copies = supply(record)
    cards, history, sets = [], {}, {}
    for ref in sorted(cat):
        c = cat[ref]
        sets.setdefault(c.get("set") or ref[:3], {"id": c.get("set") or ref[:3], "name": c.get("set_name"),
                                                 "color": c.get("color")})
        mine = deals.get(ref, [])
        st = stats(mine)
        a = sorted(asks.get(ref, []), key=lambda o: (o["price"] + (o.get("fee") or 0), o.get("id") or 0))
        b = sorted(bids.get(ref, []), key=lambda o: (-(o["price"] - (o.get("fee") or 0)), o.get("id") or 0))
        ask = bid = None
        if a:
            ask = {**_side(a[0], fees), "cost": a[0]["price"] + (a[0].get("fee") or 0)}
            ask["saves_on_v07"] = ask["fee"] if not ask["on_v07"] else 0     # the same price here costs no fee
        if b:
            bid = {**_side(b[0], fees), "nets": b[0]["price"] - (b[0].get("fee") or 0)}
            bid["saves_on_v07"] = bid["fee"] if not bid["on_v07"] else 0
        hot = bool(ask and st["low"] and ask["cost"] <= HOT * st["low"])
        made = copies.get(ref) or {}
        seen = bool(mine or moved.get(ref) or holders.get(ref) or a or made.get("minted"))
        cards.append({
            "ref": ref, "name": c.get("name") or ref, "rarity": c.get("rarity"), "set": c.get("set") or ref[:3],
            "set_name": c.get("set_name"), "color": c.get("color"), "book": c.get("book"),
            "page": bool(c.get("page", True)), "minted": made.get("minted"), "print_run": made.get("print_run"),
            "art": f"/plaza/art/{ref}.svg" if art and ref in art else None,
            "ask": ask, "bid": bid, "asks": len(a), "bids": len(b),
            "last": st["last"], "last_tick": st["last_tick"], "low": st["low"], "median": st["median"],
            "high": st["high"], "deals": st["n"], "trend": st["trend"], "hot": hot,
            "spark": [d["price"] for d in mine[-SPARK:]],
            "holders": sorted(holders.get(ref, ())), "seekers": sorted(seekers.get(ref, ())),
            "moved": moved.get(ref, 0), "state": "in_play" if seen else "not_seen",
        })
        history[ref] = {"name": c.get("name") or ref, "rarity": c.get("rarity"), "set": c.get("set") or ref[:3],
                        "stats": st, "deals": mine[-DEALS_KEPT:]}
    venues = {k: {"name": v.get("name") or k, "fee_bps": v.get("bps") or 0, "fee_per_card": v.get("per_card") or 0,
                  "status": v.get("status")} for k, v in (fees or {}).items()}
    head = {"tick": tick, "venue": VENUE, "unreleased_sets": unreleased(record) if record else []}
    live = {**head, "sets": list(sets.values()), "venues": venues, "cards": cards, "total": len(cards),
            "offers": len(public)}
    return live, {**head, "cards": history}


class Live:
    """What changed since the last look: public offers that appeared or went, and sales between teams. Small and
    cheap to poll every tick; the first build only sets the baseline."""

    def __init__(self):
        self.offers: dict | None = None
        self.sold: set = set()
        self.events: collections.deque = collections.deque(maxlen=LIVE_KEPT)

    def update(self, offers: list[dict], sales, fees: dict, tick) -> dict:
        now = {o["id"]: o for o in offers or [] if not o.get("to") and o.get("side") in ("ask", "bid")
               and TEAM.fullmatch(str(o.get("maker") or ""))}
        deals = [(ref, d) for ref, rows in team_deals(sales).items() for d in rows]
        keys = {(ref, d["tick"], d["seller"], d["buyer"], d["price"]) for ref, d in deals}
        if self.offers is not None:
            for oid, o in now.items():
                if oid not in self.offers:
                    self.events.append({"tick": tick, "what": "listed", "side": o["side"], "ref": o["ref"],
                                        "price": o["price"], "fee": o.get("fee") or 0, "venue": o.get("venue"),
                                        "team": o.get("maker"), "offer": oid})
            for oid, o in self.offers.items():
                if oid not in now:
                    self.events.append({"tick": tick, "what": "gone", "side": o["side"], "ref": o["ref"],
                                        "price": o["price"], "venue": o.get("venue"), "team": o.get("maker"),
                                        "offer": oid})
            for ref, d in sorted(deals, key=lambda x: x[1]["tick"] or 0):
                if (ref, d["tick"], d["seller"], d["buyer"], d["price"]) not in self.sold:
                    self.events.append({"tick": d["tick"], "what": "sold", "ref": ref, "price": d["price"],
                                        "venue": d["venue"], "seller": d["seller"], "buyer": d["buyer"]})
        self.offers, self.sold = now, keys
        since = (tick or 0) - LIVE_TICKS + 1
        return {"tick": tick, "venue": VENUE, "since_tick": since, "stream": "/plaza/api/floor/stream",
                "events": [e for e in self.events if (e.get("tick") or 0) >= since]}


def by_set(live: dict, sheets: dict) -> dict:
    """The board by set: each card's supply, price and demand, the scarcest and the most wanted of the set, and
    what the game shows of every team's album. Demand is a count; whose page a card would finish is never said."""
    by: dict[str, list[dict]] = {}
    for c in live.get("cards") or []:
        by.setdefault(c["set"], []).append({
            "ref": c["ref"], "name": c["name"], "rarity": c["rarity"], "color": c.get("color"), "art": c.get("art"),
            "page": c.get("page"), "minted": c.get("minted"), "print_run": c.get("print_run"), "state": c["state"],
            "ask": (c.get("ask") or {}).get("cost"), "bid": (c.get("bid") or {}).get("nets"), "last": c.get("last"),
            "can_sell": len(c.get("holders") or []), "wanted_by": len(c.get("seekers") or [])})
    sets = []
    for s in live.get("sets") or []:
        cards = by.get(s["id"], [])
        known = [c for c in cards if isinstance(c.get("minted"), int)]
        sets.append({**s, "released": True, "cards": cards, "total": len(cards),
                     "in_play": sum(1 for c in cards if c["state"] == "in_play"),
                     "scarcest": [c["ref"] for c in sorted(known, key=lambda c: (c["minted"], c["ref"]))[:3]],
                     "most_wanted": [c["ref"] for c in sorted(cards, key=lambda c: (-c["wanted_by"], c["ref"]))[:3]
                                     if c["wanted_by"]]})
    teams = [{"team": t, "name": s.get("name"), "album": s.get("album"), "pages": s.get("pages")}
             for t, s in sorted((sheets or {}).items()) if not s.get("host") and (s.get("album") or s.get("pages") is not None)]
    return {"tick": live.get("tick"), "venue": VENUE, "sets": sets,
            "unreleased_sets": live.get("unreleased_sets") or [], "teams": teams}
