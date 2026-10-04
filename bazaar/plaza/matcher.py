"""Pairs of other teams that should trade on our venue: a sale, a card-for-card swap, a three-way swap.

We are never a party (a team cannot trade on its own venue). The game scores a venue by the value its trades create
(the buyer's private value minus the seller's), so a trade that destroys value costs us points. The gate:

    a sale is proposed only when (a) both sides gave a limit and the limits overlap (private limits, asked blindly,
    or a public ask and bid that cross), or (b) the card is a duplicate the seller's agent declared and a want the
    buyer's agent declared; and, when both gave a private value, only when the buyer's is the higher one.
    A swap or a three-way swap is proposed only between cards the agents themselves declared.

The price is never the midpoint of two private limits (a team that knows its own limit would read the other's):
it is the public reference price of the card, pulled inside the overlap with a margin drawn in secret per match
(`rule_price`). Every match carries the exact request each agent sends, always on our venue."""
from __future__ import annotations

import hashlib
import time

VENUE = "v07"
HOST = "t10"
FLOOR = {"common": 4, "uncommon": 12, "rare": 40, "epic": 110, "legendary": 300}   # below this a sale is a giveaway
BOOK = {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}
RARITY_SCORE = {"common": 0.0, "uncommon": 0.5, "rare": 1.5, "epic": 2.5, "legendary": 3.0}
RARITY_RANK = {"legendary": 0, "epic": 1, "rare": 2, "uncommon": 3, "common": 4}   # dear cards first: they move the score
MAX_CANDIDATES = 1500
MAX_SWAPS = 600                 # card-for-card candidates kept; the search stops there
MAX_TRIANGLES = 200
MAX_STEPS = 150000              # inner steps the swap and three-way searches may take, together
BUDGET_S = 0.4                  # and the time they may take: the board is never held up by one big sheet
MAX_MARGIN = 0.25               # the secret margin is at most this share of the overlap, on each side


def grid(price: float) -> int:
    """Prices are whole P under 20 and multiples of 5 above."""
    return int(round(price)) if price < 20 else int(round(price / 5.0)) * 5


def step(price: float) -> int:
    """The size of one grid step at this price."""
    return 1 if price < 20 else 5


def inside(lo: int, hi: int, ref_price: float, margin: int = 1) -> int | None:
    """A grid price strictly inside [lo, hi]: at least `margin` and one grid step away from each end, as near the
    reference as that allows, rounded towards the inside and never onto an end. When the overlap is too narrow for
    the 5 P grid the price is a whole P; when it has no inside at all (narrower than 2 P): None."""
    lo, hi = int(lo), int(hi)
    for unit in (5, 1):
        low, high = lo + max(margin, unit), hi - max(margin, unit)
        if unit == 5:
            if hi < 20 + unit:                                 # the 5 P grid starts at 20
                continue
            low, high = -(-low // 5) * 5, (high // 5) * 5      # up to the grid from below, down to it from above
        else:
            low, high = lo + max(1, min(margin, (hi - lo) // 2)), hi - max(1, min(margin, (hi - lo) // 2))
        if low > high:
            continue
        price = min(max(float(ref_price or 0), low), high)
        out = int(round(price / unit)) * unit
        return min(max(out, low), high)
    return None


def rule_price(lo: int, hi: int, ref_price: float, floor: int = 1, share: float = 0.0) -> int | None:
    """The price inside the overlap [lo, hi]: the reference price, kept `share` of the overlap away from each end.

    A price equal to the reference says nothing about either limit. A price pulled in says only that a limit lies
    on the far side of it, within `MAX_MARGIN / (1 - MAX_MARGIN)` of the distance to one's own limit: accepting any
    price reveals as much. No overlap: None, and no reason is given."""
    lo = max(int(lo), int(floor))
    hi = int(hi)
    if hi < lo:
        return None
    d = int((hi - lo) * min(max(share, 0.0), MAX_MARGIN))
    price = min(max(float(ref_price or 0), lo + d), hi - d)
    out = grid(price)
    if not lo <= out <= hi:                                    # the grid stepped out of a narrow overlap
        out = int(round(price))
    return min(max(out, lo), hi)


def public_quote(seller: str, buyer: str, ref: str, ref_price: float, floor: int = 1, salt: str = "",
                 ask=None, bid=None) -> dict:
    """The quote when nobody keeps private limits: only what both teams published (an ask, a bid)."""
    if ask and bid:
        price = rule_price(ask, bid, ref_price, floor)
        return {"price": price, "overlap": price is not None, "value": None, "basis": "public" if price else None}
    price = max(int(floor), grid(ref_price or 0))
    if (ask and price < ask) or (bid and price > bid):
        price = int(ask or bid)                                # a public price, shown as it was published
        if price < floor:
            return {"price": None, "overlap": False, "value": None, "basis": None}
    return {"price": price or None, "overlap": None, "value": None, "basis": None}


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
    """1 the last card of a page, 2 a legendary or an epic, 3 a rare, 4 the rest: by the value a trade creates."""
    if last:
        return 1
    if rarity in ("legendary", "epic"):
        return 2
    return 3 if rarity == "rare" else 4


def order_key(m: dict):
    """Dear cards first; among equals a swap before a sale (both sides gain a card), then a pair that has not yet
    traded on our venue, then what the agents declared."""
    return (m["priority"], RARITY_RANK.get(m.get("rarity") or "", 5), m["kind"] == "sale", bool(m.get("pair_traded")),
            m["confidence"] != "declared", -m["score"], m["kind"], m["ref"], m["seller"], m["buyer"])


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


def _quoter(gate, quote):
    """The blind question about two teams' limits, whichever form the caller has."""
    if quote is not None:
        return quote
    owner = getattr(gate, "__self__", None)
    if owner is not None and callable(getattr(owner, "quote", None)):
        return owner.quote
    if owner is not None and hasattr(owner, "key") and hasattr(owner, "data"):
        from .quotes import Quoter                             # a vault's gate: the same rules as everywhere else
        if getattr(owner, "_quoter", None) is None:
            owner._quoter = Quoter(owner)
        return owner._quoter.quote
    if gate is None:
        return public_quote

    def old(seller, buyer, ref, ref_price, floor=1, salt="", ask=None, bid=None):
        base = public_quote(seller, buyer, ref, ref_price, floor, salt, ask, bid)
        if base["price"] is None:
            return base
        gated, overlap = gate(seller, buyer, ref, base["price"], floor)
        if gated is None:
            return {"price": None, "overlap": False, "value": None, "basis": None}
        return {"price": gated, "overlap": base["overlap"] or overlap, "value": None, "basis": base["basis"]}
    return old


def find(sheets: dict[str, dict], cat: dict[str, dict], host: str = HOST, venue: str = VENUE, gate=None, *,
         quote=None, refprice: dict[str, int] | None = None, traded=frozenset(), paused=frozenset(),
         strict: bool = True, prefers=None, budget_s: float = BUDGET_S, clock=time.monotonic) -> list[dict]:
    """Every candidate among the teams' sheets, dear cards first. `assign` then keeps one per card and team.

    `quote(seller, buyer, ref, ref_price, floor, salt, ask, bid)` answers blindly about the two teams' limits;
    `refprice` is the public reference price per card (median of its sales between teams); `traded` the pairs that
    already closed on our venue; `paused` the teams that asked for no new matches. `strict=False` also proposes
    what is only deduced from the public feed (never used by the server: such a trade may cost the venue points).
    `prefers(team, get, give)` says whether a team values the card it gets above the one it gives (None: it did not
    say); a swap in which a team said it loses is not proposed. The swap and three-way searches stop at a count, a
    number of steps and `budget_s`: they return what they found, dear cards first, never everything at any cost."""
    teams = {t: s for t, s in sheets.items() if t != host and not s.get("host") and t not in paused}
    have = {t: _have(s) for t, s in teams.items()}
    want = {t: _want(s) for t, s in teams.items()}
    ask_quote = _quoter(gate, quote)
    refprice = refprice or {}
    agent = lambda *entries: all(e.get("source") == "agent" for e in entries)   # noqa: E731
    out: list[dict] = []
    for b in teams:
        for ref, w in want[b].items():
            card = cat.get(ref) or {}
            rarity = card.get("rarity")
            floor = FLOOR.get(rarity or "", 1)
            for a in teams:
                if a == b or ref not in have[a]:
                    continue
                h = have[a][ref]
                base, basis = price_for(h, w, rarity, card.get("book"))
                if refprice.get(ref):
                    base, basis = refprice[ref], "reference"
                if base is None:
                    continue
                q = ask_quote(a, b, ref, base, floor, f"{a}|{b}|{ref}", h.get("price"), w.get("bid"))
                price = q.get("price")
                if price is None or q.get("overlap") is False or q.get("value") is False:
                    continue                                   # the limits do not meet, or the trade destroys value
                declared = agent(h, w)
                duplicate = declared and h.get("as") == "spare"
                if strict and not (q.get("overlap") or duplicate):
                    continue                                   # nothing says that both sides gain: not proposed
                if q.get("basis"):
                    basis = q["basis"]
                elif price == floor and base < floor:
                    basis = "floor"
                last = last_of_page(teams[b], ref)
                pair = frozenset((a, b)) in traded
                score = 1.0 + RARITY_SCORE.get(rarity or "", 0.0) + (3.0 if last else 0.0) \
                    + (2.0 if declared else 0.0) + (1.0 if q.get("overlap") else 0.0) \
                    + (0.0 if pair else 0.5) + min(2.0, rastro_fee(price) / 5)
                why = f"{a} can part with {ref}; {b} looks for it" + (" (probably the last card of its page)" if last else "")
                out.append({"kind": "sale", "seller": a, "buyer": b, "ref": ref, "name": card.get("name"),
                            "rarity": rarity, "price": price, "basis": basis, "saves": rastro_fee(price),
                            "last_of_page": last, "priority": priority("sale", rarity, last),
                            "confidence": "declared" if declared else "probable", "score": round(score, 2),
                            "pair_traded": pair, "why": why, "recipe": recipe(a, b, ref, price, venue)})
    if prefers is None:
        prefers = getattr(getattr(ask_quote, "__self__", None), "prefers", None) or (lambda team, get, give: None)
    rar = lambda r: (cat.get(r) or {}).get("rarity")           # noqa: E731
    declared = lambda e: e.get("source") == "agent"            # noqa: E731
    # what each team can give and wants, by rarity; in strict mode only what its agent declared takes part
    give: dict[str, dict] = {t: {} for t in teams}
    for t in teams:
        for r, e in have[t].items():
            if not strict or declared(e):
                give[t].setdefault(rar(r), []).append(r)
    wanters: dict[str, list[str]] = {}
    for t in sorted(teams):
        for r, e in want[t].items():
            if not strict or declared(e):
                wanters.setdefault(r, []).append(t)
    seeks = {t: {r for r, e in want[t].items() if not strict or declared(e)} for t in teams}
    rank = lambda r: RARITY_RANK.get(r or "", 5)               # noqa: E731
    deadline, steps = clock() + max(0.0, budget_s), [0]

    def spent() -> bool:
        steps[0] += 1
        return steps[0] > MAX_STEPS or (steps[0] % 512 == 0 and clock() > deadline)

    def gains(*moves) -> bool:
        """No team of the swap said it values what it gets below what it gives."""
        return all(prefers(t, get, giv) is not False for t, get, giv in moves)

    order = sorted(teams)
    swaps, stop = 0, False
    for rarity in sorted({r for t in teams for r in give[t]}, key=rank):   # dear cards first
        if stop:
            break
        for a in order:                                        # mutual swap: same rarity, both gain, no cash
            if stop:
                break
            for x in give[a].get(rarity, ()):
                if stop:
                    break
                for b in wanters.get(x, ()):
                    if b <= a:
                        continue
                    for y in give[b].get(rarity, ()):
                        if spent() or swaps >= MAX_SWAPS:
                            stop = True
                            break
                        if y == x or y not in seeks[a]:
                            continue
                        if not gains((a, y, x), (b, x, y)):
                            continue
                        both = agent(have[a][x], have[b][y], want[a][y], want[b][x])
                        last = last_of_page(teams[b], x) or last_of_page(teams[a], y)
                        pair = frozenset((a, b)) in traded
                        swaps += 1
                        out.append({"kind": "swap", "teams": [a, b], "seller": a, "buyer": b, "ref": x, "ref_back": y,
                                    "name": (cat.get(x) or {}).get("name"),
                                    "rarity": rarity, "price": 0, "basis": "swap",
                                    "saves": 2 * rastro_fee(BOOK.get(rarity or "", 0)),
                                    "last_of_page": last, "priority": priority("swap", rarity, last),
                                    "confidence": "declared" if both else "probable",
                                    "score": round(5.0 + RARITY_SCORE.get(rarity or "", 0.0) + (2.0 if both else 0.0), 2),
                                    "pair_traded": pair,
                                    "why": f"{a} has {x} and wants {y}; {b} has {y} and wants {x}",
                                    "recipe": swap_recipe(a, b, x, y, venue)})
                    if stop:
                        break
    tri: set = set()
    stop = False
    for rarity in sorted({r for t in teams for r in give[t]}, key=rank):
        if stop:
            break
        for a in order:                                        # three-way: a gives x to b, b gives y to c, c gives z to a
            if stop:
                break
            mine = [z for z in seeks[a] if rar(z) == rarity]   # what a could get back, of this rarity
            if not mine:
                continue
            for x in give[a].get(rarity, ()):
                if stop:
                    break
                for b in wanters.get(x, ()):
                    if b == a or stop:
                        continue
                    for y in give[b].get(rarity, ()):
                        if stop:
                            break
                        if y == x:
                            continue
                        for c in wanters.get(y, ()):
                            if spent() or len(tri) >= MAX_TRIANGLES:
                                stop = True
                                break
                            if c in (a, b):
                                continue
                            for z in mine:
                                if spent() or len(tri) >= MAX_TRIANGLES:
                                    stop = True
                                    break
                                if z in (x, y) or z not in have[c] or (strict and not declared(have[c][z])):
                                    continue
                                key = tuple(sorted([(a, x), (b, y), (c, z)]))
                                if key in tri or not gains((a, z, x), (b, x, y), (c, y, z)):
                                    continue
                                all_declared = agent(have[a][x], have[b][y], have[c][z], want[b][x], want[c][y], want[a][z])
                                tri.add(key)
                                out.append({"kind": "triangle", "teams": [a, b, c], "seller": a, "buyer": b, "ref": x,
                                            "legs": [{"from": a, "to": b, "ref": x}, {"from": b, "to": c, "ref": y},
                                                     {"from": c, "to": a, "ref": z}],
                                            "name": (cat.get(x) or {}).get("name"),
                                            "rarity": rarity, "price": 0, "basis": "swap",
                                            "saves": 3 * rastro_fee(BOOK.get(rarity or "", 0)),
                                            "last_of_page": False, "priority": priority("triangle", rarity, False),
                                            "confidence": "declared" if all_declared else "probable",
                                            "score": round(4.0 + RARITY_SCORE.get(rarity or "", 0.0), 2),
                                            "pair_traded": False,
                                            "why": f"{a} gives {x} to {b}, {b} gives {y} to {c}, {c} gives {z} to {a}",
                                            "recipe": {"note": f"three card-for-card offers on {venue}, each addressed to "
                                                               "the next team; no cash, no fee"}})
                            if stop:
                                break
    for m in out:
        m["id"] = match_id(m)
    out.sort(key=order_key)
    return out[:MAX_CANDIDATES]


def for_team(matches: list[dict], team: str) -> list[dict]:
    return [m for m in matches if team in (m.get("teams") or [m["seller"], m["buyer"]])]
