"""Pairs of other teams that should trade on our venue: a sale, a card-for-card swap, a three-way swap.

We are never a party (a team cannot trade on its own venue) and a giveaway is never proposed: a trade that destroys
value costs the venue points. Every match carries the exact request each agent sends."""
from __future__ import annotations

import hashlib

VENUE = "v07"
HOST = "t10"
FLOOR = {"common": 4, "uncommon": 12, "rare": 40, "epic": 110, "legendary": 300}   # below this a sale is a giveaway
BOOK = {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}
RARITY_SCORE = {"common": 0.0, "uncommon": 0.5, "rare": 1.5, "epic": 2.5, "legendary": 3.0}
MAX_CANDIDATES = 1500


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


def price_for(have: dict, want: dict, rarity: str | None, book: float | None = None) -> tuple[int | None, str | None]:
    """The suggested price and where it comes from: the midpoint when there is an ask and a bid, else the price
    one side declared, else the book of the rarity; never below the floor of the rarity."""
    ask, bid = have.get("price"), want.get("bid")
    if ask and bid:
        price, basis = round((ask + bid) / 2), "midpoint"
    elif ask or bid:
        price, basis = ask or bid, "declared"
    else:
        price, basis = round(book or BOOK.get(rarity or "", 0)), "book"
    if not price or price <= 0:
        return None, None
    floor = FLOOR.get(rarity or "", 1)
    if price < floor:
        price, basis = floor, "floor"
    return int(price), basis


def priority(kind: str, rarity: str | None, last: bool) -> int:
    """1 the last card of a page, 2 a swap both sides gain from, 3 an epic or rare card, 4 the rest."""
    if last:
        return 1
    if kind in ("swap", "triangle"):
        return 2
    return 3 if rarity in ("rare", "epic", "legendary") else 4


def match_id(m: dict) -> str:
    legs = "|".join(f"{leg['from']}>{leg['to']}:{leg['ref']}" for leg in m.get("legs") or [])
    key = f"{m['kind']}|{m['seller']}|{m['buyer']}|{m['ref']}|{m.get('ref_back') or ''}|{legs}"
    return "m-" + hashlib.sha1(key.encode()).hexdigest()[:10]


def slots(m: dict) -> list[tuple]:
    """What a match takes: a card a team gives and a card a team gets. One active match per slot."""
    if m["kind"] == "triangle":
        return [x for leg in m["legs"] for x in (("give", leg["from"], leg["ref"]), ("get", leg["to"], leg["ref"]))]
    out = [("give", m["seller"], m["ref"]), ("get", m["buyer"], m["ref"])]
    if m["kind"] == "swap":
        out += [("give", m["buyer"], m["ref_back"]), ("get", m["seller"], m["ref_back"])]
    return out


def brief(m: dict) -> dict:
    return {"id": m["id"], "kind": m["kind"], "seller": m["seller"], "buyer": m["buyer"], "ref": m["ref"],
            "price": m["price"], **({"ref_back": m["ref_back"]} if m.get("ref_back") else {})}


def assign(cands: list[dict], skip=frozenset(), max_alternatives: int = 4) -> list[dict]:
    """One active match per card and team, in the order given. A candidate whose card or team slot is taken
    becomes an alternative of the match that holds it, so the same card is never proposed to three teams at once."""
    used: dict[tuple, dict] = {}
    active: list[dict] = []
    for m in cands:
        if m["id"] in skip:
            continue
        holders = [used[s] for s in slots(m) if s in used]
        if holders:
            alt = holders[0]["alternatives"]
            if len(alt) < max_alternatives and all(a["id"] != m["id"] for a in alt):
                alt.append(brief(m))
            continue
        m = {**m, "alternatives": []}
        for s in slots(m):
            used[s] = m
        active.append(m)
    return active


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


def find(sheets: dict[str, dict], cat: dict[str, dict], host: str = HOST, venue: str = VENUE, gate=None) -> list[dict]:
    """Every candidate among the teams' sheets, by priority. `assign` then keeps one per card and team."""
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
                price, basis = price_for(h, w, rarity, card.get("book"))
                if price is None:
                    continue
                if gate is not None:                           # private limits, asked blindly: pass, move or drop
                    gated, overlap = gate(a, b, ref, price, FLOOR.get(rarity or "", 1))
                    if gated is None:
                        continue
                    if overlap and gated != price:
                        price, basis = gated, "limits"
                last = last_of_page(teams[b], ref)
                declared = h.get("source") == "agent" and w.get("source") == "agent"
                score = 1.0 + RARITY_SCORE.get(rarity or "", 0.0) + (3.0 if last else 0.0) \
                    + (2.0 if declared else 0.0) + (1.0 if h.get("price") and w.get("bid") else 0.0) \
                    + min(2.0, rastro_fee(price) / 5)
                out.append({"kind": "sale", "seller": a, "buyer": b, "ref": ref, "name": card.get("name"),
                            "rarity": rarity, "price": price, "basis": basis, "saves": rastro_fee(price),
                            "last_of_page": last, "priority": priority("sale", rarity, last),
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
                    last = last_of_page(teams[b], x) or last_of_page(teams[a], y)
                    both = all(e.get("source") == "agent" for e in (have[a][x], have[b][y], want[a][y], want[b][x]))
                    out.append({"kind": "swap", "teams": [a, b], "seller": a, "buyer": b, "ref": x, "ref_back": y,
                                "name": (cat.get(x) or {}).get("name"),
                                "rarity": rx, "price": 0, "basis": "swap", "saves": 2 * rastro_fee(BOOK.get(rx or "", 0)),
                                "last_of_page": last, "priority": priority("swap", rx, last),
                                "confidence": "declared" if both else "probable",
                                "score": round(5.0 + RARITY_SCORE.get(rx or "", 0.0) + (2.0 if both else 0.0), 2),
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
                                        "name": (cat.get(x) or {}).get("name"),
                                        "rarity": r, "price": 0, "basis": "swap",
                                        "saves": 3 * rastro_fee(BOOK.get(r or "", 0)),
                                        "last_of_page": False, "priority": priority("triangle", r, False),
                                        "confidence": "probable",
                                        "score": round(4.0 + RARITY_SCORE.get(r or "", 0.0), 2),
                                        "why": f"{a} gives {x} to {b}, {b} gives {y} to {c}, {c} gives {z} to {a}",
                                        "recipe": {"note": f"three card-for-card offers on {venue}, each addressed to "
                                                           "the next team; no cash, no fee"}})
    for m in out:
        m["id"] = match_id(m)
    out.sort(key=lambda m: (m["priority"], m["confidence"] != "declared", -m["score"], m["kind"], m["ref"],
                            m["seller"], m["buyer"]))
    return out[:MAX_CANDIDATES]


def for_team(matches: list[dict], team: str) -> list[dict]:
    return [m for m in matches if team in (m.get("teams") or [m["seller"], m["buyer"]])]
