"""Closing on v07 with nothing to connect: the exact game call for an offer, and the pairs that would cross today.

Only what the game shows everyone is read here: public offers (never one addressed to a team) from the price board.
Nothing of the market's own (sheets, limits, matches, threads) is used, and Team 10 is never one of the two teams.
The body is the game's own `POST /api/offers`, run by the team with its own key; the market sends nothing."""
from __future__ import annotations

import re

from .store import PlazaError

VENUE = "v07"
HOST = "t10"
REF = re.compile(r"[A-Z]{3}-\d{2}")
QUICK = re.compile(r"/plaza/api/quick/([A-Z]{3}-\d{2})")
DOC = "/plaza/api/quick"
OPPS = "/plaza/api/opportunities"
FLOOR = {"common": 4, "uncommon": 12, "rare": 40, "epic": 110, "legendary": 300}   # under this a sale is a giveaway
MAX_PRICE = 2000
KEPT = 40
ASSET = "<your asset id of {ref}: the id of that card in GET /api/me>"

MD = """# v07 in one call (Team 10's market, 0 % fee)

No connection, no account, nothing to install. To trade any card on venue `v07`, post your normal offer to the game
with `"venue": "v07"`, using your own team key; the other team accepts it.

Sell a card for P:
`POST $GAME/api/offers {"venue":"v07","give":{"assets":[<your asset id>]},"want":{"cash":P}}`

Buy a card for P:
`POST $GAME/api/offers {"venue":"v07","give":{"cash":P},"want":{"cards":["SAL-10"]}}`

Take an offer that is already on v07 (id N):
`POST $GAME/api/offers/N/accept` (a seller adds `{"assets":[<your asset id>]}`)

That is how every deal on v07 has closed: one team posts, the other accepts, it settles within a tick or two and
nobody pays a fee (El Rastro: 5 % + 1 P for the side that accepts). Is your bid or ask sitting on El Rastro?
Post the same one on v07 and the other side saves the fee by taking it here.

Ready-made bodies and today's pairs:
- `GET {base}/api/quick/SAL-10?side=sell&price=60` (or `side=buy`): the body for that card and price.
- `GET {base}/api/opportunities`: public bids and asks worth moving to v07, with the call for each side.
- `GET {base}/board.json`: every card's best public ask and bid on every venue.

Your game key goes to the game only. Team 10 is never a party on v07.
"""


def body(ref: str, side: str, price: int) -> dict:
    if side == "sell":
        return {"venue": VENUE, "give": {"assets": [ASSET.format(ref=ref)]}, "want": {"cash": price}}
    return {"venue": VENUE, "give": {"cash": price}, "want": {"cards": [ref]}}


def accept(offer, ref: str, selling: bool) -> dict:
    """Taking an offer that already sits on v07."""
    return {"venue": VENUE, "method": "POST", "path": f"/api/offers/{offer}/accept", "ref": ref,
            "body": {"assets": [ASSET.format(ref=ref)]} if selling else {},
            "note": "Accept it with your own team key: it is on v07, so nobody pays a fee."}


def call(ref: str, side: str, price: int) -> dict:
    return {"venue": VENUE, "method": "POST", "path": "/api/offers", "side": side, "ref": ref, "price": price,
            "body": body(ref, side, price),
            "note": ("Send it to the game with your own team key. The other team accepts it on v07: 0 % fee."
                     + (" Replace the asset id with your copy's id from GET /api/me." if side == "sell" else ""))}


def _card(snap: dict, ref: str) -> dict | None:
    for c in ((snap.get("board") or {}).get("cards") or []):
        if c.get("ref") == ref:
            return c
    return None


def quick(snap: dict, ref: str, side: str, price) -> dict:
    cat = snap.get("cat") or {}
    if ref not in cat:
        raise PlazaError(404, "not_found", f"no such card: {ref}")
    if side not in ("sell", "buy"):
        raise PlazaError(400, "bad_request", "side is sell or buy")
    card = _card(snap, ref) or {}
    best = (card.get("bid") if side == "sell" else card.get("ask")) or {}
    if price in (None, ""):
        price = best.get("price")
        if price is None:
            raise PlazaError(400, "bad_request", "give a price: nobody quotes this card in public right now")
    try:
        price = int(price)
    except (TypeError, ValueError):
        raise PlazaError(400, "bad_request", "price is a whole number") from None
    if not 1 <= price <= MAX_PRICE:
        raise PlazaError(400, "bad_request", f"price is between 1 and {MAX_PRICE}")
    out = call(ref, side, price)
    out.update(name=(cat.get(ref) or {}).get("name"), tick=snap.get("tick"),
               best_public={"side": "bid" if side == "sell" else "ask", "price": best.get("price"),
                            "venue": best.get("venue"), "team": best.get("team")} if best else None)
    return out


def opportunities(snap: dict) -> dict:
    """Public bids and asks of other teams worth closing on v07, each with the steps: its maker posts it on v07 (or
    it is there already) and the other side accepts. `cross` when a public ask is already under the bid."""
    out = []
    for c in ((snap.get("board") or {}).get("cards") or []):
        ask, bid = c.get("ask") or {}, c.get("bid") or {}
        seller, buyer = ask.get("team"), bid.get("team")
        if HOST in (seller, buyer) or (seller and seller == buyer):
            continue
        ref, floor = c["ref"], FLOOR.get(c.get("rarity") or "", 0)
        row = {"ref": ref, "name": c.get("name"), "rarity": c.get("rarity"), "page": bool(c.get("page"))}
        taker = seller if seller and buyer and bid["price"] >= ask["price"] else None
        if buyer and bid["price"] >= floor:
            # a public bid: on v07 a holder accepts it; elsewhere its maker posts it here first
            on = bid.get("venue") == VENUE
            row.update(kind="cross" if taker else "wanted", buyer=buyer, seller=taker, bid=bid["price"],
                       price=bid["price"], bid_venue=bid.get("venue"), offer=bid.get("offer") if on else None,
                       saves=bid.get("saves_on_v07") or 0,
                       steps=([] if on else [{"team": buyer, "do": "post your bid on v07 too",
                                              **call(ref, "buy", bid["price"])}])
                       + [{"team": taker or "holder", "do": "accept it on v07",
                           **(accept(bid["offer"], ref, True) if on else
                              {"path": "/api/offers/<its id on v07>/accept", "method": "POST", "venue": VENUE,
                               "body": {"assets": [ASSET.format(ref=ref)]}})}])
        elif seller and ask["price"] >= floor and (c.get("seekers") or c.get("bids")):
            on = ask.get("venue") == VENUE
            row.update(kind="for_sale", seller=seller, ask=ask["price"], price=ask["price"],
                       ask_venue=ask.get("venue"), offer=ask.get("offer") if on else None,
                       saves=ask.get("saves_on_v07") or 0,
                       steps=([] if on else [{"team": seller, "do": "post your ask on v07 too",
                                              **call(ref, "sell", ask["price"])}])
                       + [{"team": "buyer", "do": "accept it on v07",
                           **(accept(ask["offer"], ref, False) if on else
                              {"path": "/api/offers/<its id on v07>/accept", "method": "POST", "venue": VENUE,
                               "body": {}})}])
        else:
            continue
        row["score"] = ({"cross": 3, "wanted": 1.5, "for_sale": 1}[row["kind"]]
                        + {"rare": 1.5, "epic": 2.5, "legendary": 3}.get(c.get("rarity") or "", 0))
        out.append(row)
    out.sort(key=lambda r: (-r["score"], -r["price"], r["ref"]))
    return {"tick": snap.get("tick"), "venue": VENUE, "fee": 0,
            "how": "One team posts its public offer on v07 with its own key; the other accepts it. 0 % fee for both.",
            "source": "public offers of the game only", "opportunities": out[:KEPT], "total": len(out)}


def get(h, path: str, q: dict, snap: dict) -> bool:
    if path == DOC:
        h.route = "quick"
        from .server import public_url
        base = public_url(h.board.live) or "/plaza"
        h._send(200, MD.replace("{base}", base).encode(), "text/markdown; charset=utf-8", cors=True)
        return True
    if path == OPPS:
        h.route = "quick"
        h._json(200, opportunities(snap), cors=True)
        return True
    m = QUICK.fullmatch(path)
    if m:
        h.route = "quick"
        h._json(200, quick(snap, m.group(1), q.get("side") or "sell", q.get("price")), cors=True)
        return True
    return False


def write(h, method: str, path: str, body) -> bool:
    return False
