"""Pairs of other teams that should trade on our venue: a sale, a card-for-card swap, a three-way swap.

We are never a party (a team cannot trade on its own venue) and a giveaway is never proposed: a trade that destroys
value costs the venue points. Every match carries the exact request each agent sends."""
from __future__ import annotations

VENUE = "v07"
HOST = "t10"
FLOOR = {"common": 4, "uncommon": 12, "rare": 40, "epic": 110, "legendary": 300}   # below this a sale is a giveaway
BOOK = {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}
RARITY_SCORE = {"common": 0.0, "uncommon": 0.5, "rare": 1.5, "epic": 2.5, "legendary": 3.0}
MAX_MATCHES = 400


def rastro_fee(price: float) -> int:
    """What El Rastro charges the taker: 5 % plus 1 P per card."""
    return int(round(price * 0.05 + 1)) if price > 0 else 0


def _have(sheet: dict) -> dict[str, dict]:
    """ref -> the entry a team can part with: a card for sale (maybe priced) or a declared spare."""
    out: dict[str, dict] = {}
    for e in sheet.get("spares") or []:
        out[e["ref"]] = {**e, "as": "spare"}
    for e in sheet.get("for_sale") or []:
        out[e["ref"]] = {**e, "as": "for_sale"}
    return out


def _want(sheet: dict) -> dict[str, dict]:
    return {e["ref"]: e for e in sheet.get("wants") or []}


def last_of_page(sheet: dict, ref: str) -> bool:
    """Probably the last card of a page: the only page card of its set the team still looks for."""
    if int(ref[4:]) > 10:
        return False
    same = [e["ref"] for e in sheet.get("wants") or [] if e["ref"][:3] == ref[:3] and int(e["ref"][4:]) <= 10]
    return same == [ref]


def price_for(have: dict, want: dict, rarity: str | None) -> int | None:
    ask, bid = have.get("price"), want.get("bid")
    if ask and bid:
        price = round((ask + bid) / 2) if bid >= ask else None      # they do not cross: no forced price
        if price is None:
            return int(ask) if ask - bid <= max(2, 0.15 * ask) else None
    elif ask:
        price = ask
    elif bid:
        price = bid
    else:
        price = round(BOOK.get(rarity or "", 0) * 0.9)
    return int(price) if price and price >= FLOOR.get(rarity or "", 1) else None


def recipe(seller: str, buyer: str, ref: str, price: int, venue: str = VENUE) -> dict:
    """The two requests that close a sale on our venue: the buyer's addressed bid, the seller's accept."""
    return {
        "buyer": {"method": "POST", "path": "/api/offers",
                  "body": {"venue": venue, "give": {"cash": price}, "want": {"cards": [ref]}, "to": seller}},
        "seller": {"method": "POST", "path": "/api/offers/<id of that offer>/accept",
                   "body": {"assets": [f"<your asset id of {ref}>"]}},
        "note": f"0 fee on {venue}; on El Rastro the taker pays {rastro_fee(price)} P",
    }


def swap_recipe(a: str, b: str, x: str, y: str, venue: str = VENUE) -> dict:
    return {
        "first": {"team": a, "method": "POST", "path": "/api/offers",
                  "body": {"venue": venue, "give": {"assets": [f"<your asset id of {x}>"]},
                           "want": {"cards": [y]}, "to": b}},
        "second": {"team": b, "method": "POST", "path": "/api/offers/<id of that offer>/accept",
                   "body": {"assets": [f"<your asset id of {y}>"]}},
        "note": f"card for card on {venue}: no cash, no fee",
    }


def find(sheets: dict[str, dict], cat: dict[str, dict], host: str = HOST, venue: str = VENUE) -> list[dict]:
    """Every match among the teams' sheets, best first."""
    teams = {t: s for t, s in sheets.items() if t != host and not s.get("host")}
    have = {t: _have(s) for t, s in teams.items()}
    want = {t: _want(s) for t, s in teams.items()}
    out: list[dict] = []
    for b in teams:
        for ref, w in want[b].items():
            card = cat.get(ref) or {}
            rarity = card.get("rarity")
            for a in teams:
                if a == b or ref not in have[a]:
                    continue
                h = have[a][ref]
                price = price_for(h, w, rarity)
                if price is None:
                    continue
                last = last_of_page(teams[b], ref)
                declared = h.get("source") == "agent" and w.get("source") == "agent"
                score = 1.0 + RARITY_SCORE.get(rarity or "", 0.0) + (3.0 if last else 0.0) \
                    + (2.0 if declared else 0.0) + (1.0 if h.get("price") and w.get("bid") else 0.0) \
                    + min(2.0, rastro_fee(price) / 5)
                out.append({"kind": "sale", "seller": a, "buyer": b, "ref": ref, "name": card.get("name"),
                            "rarity": rarity, "price": price, "saves": rastro_fee(price), "last_of_page": last,
                            "confidence": "declared" if declared else "probable", "score": round(score, 2),
                            "why": f"{a} can part with {ref}; {b} looks for it" + (" (probably the last card of its page)" if last else ""),
                            "recipe": recipe(a, b, ref, price, venue)})
    seen = set()
    for a in teams:                                            # mutual swap: same rarity, both gain, no cash
        for b in teams:
            if a >= b:
                continue
            for x in have[a]:
                if x not in want[b]:
                    continue
                for y in have[b]:
                    if y == x or y not in want[a]:
                        continue
                    rx, ry = (cat.get(x) or {}).get("rarity"), (cat.get(y) or {}).get("rarity")
                    if rx != ry or (a, b, x, y) in seen:
                        continue
                    seen.add((a, b, x, y))
                    out.append({"kind": "swap", "teams": [a, b], "seller": a, "buyer": b, "ref": x, "ref_back": y,
                                "rarity": rx, "price": 0, "saves": 2 * rastro_fee(BOOK.get(rx or "", 0)),
                                "last_of_page": last_of_page(teams[b], x) or last_of_page(teams[a], y),
                                "confidence": "probable", "score": round(5.0 + RARITY_SCORE.get(rx or "", 0.0), 2),
                                "why": f"{a} has {x} and wants {y}; {b} has {y} and wants {x}",
                                "recipe": swap_recipe(a, b, x, y, venue)})
    tri = set()
    order = sorted(teams)
    for a in order:                                            # three-way: a gives x to b, b gives y to c, c gives z to a
        for x in have[a]:
            for b in order:
                if b == a or x not in want[b]:
                    continue
                for y in have[b]:
                    if y == x:
                        continue
                    for c in order:
                        if c in (a, b) or y not in want[c]:
                            continue
                        for z in have[c]:
                            if z in (x, y) or z not in want[a]:
                                continue
                            rar = {(cat.get(r) or {}).get("rarity") for r in (x, y, z)}
                            key = tuple(sorted([(a, x), (b, y), (c, z)]))
                            if len(rar) != 1 or key in tri:
                                continue
                            tri.add(key)
                            r = next(iter(rar))
                            out.append({"kind": "triangle", "teams": [a, b, c], "seller": a, "buyer": b, "ref": x,
                                        "legs": [{"from": a, "to": b, "ref": x}, {"from": b, "to": c, "ref": y},
                                                 {"from": c, "to": a, "ref": z}],
                                        "rarity": r, "price": 0, "saves": 3 * rastro_fee(BOOK.get(r or "", 0)),
                                        "last_of_page": False, "confidence": "probable",
                                        "score": round(4.0 + RARITY_SCORE.get(r or "", 0.0), 2),
                                        "why": f"{a} gives {x} to {b}, {b} gives {y} to {c}, {c} gives {z} to {a}",
                                        "recipe": {"note": f"three card-for-card offers on {venue}, each addressed to "
                                                           "the next team; no cash, no fee"}})
    out.sort(key=lambda m: (-m["score"], m["kind"], m["ref"], m["seller"], m["buyer"]))
    best: dict[tuple, dict] = {}
    for m in out:                                              # one proposal per (buyer, card, kind): the best seller
        best.setdefault((m["buyer"], m["ref"], m["kind"], m.get("ref_back")), m)
    return list(best.values())[:MAX_MATCHES]


def for_team(matches: list[dict], team: str) -> list[dict]:
    return [m for m in matches if team in (m.get("teams") or [m["seller"], m["buyer"]])]
