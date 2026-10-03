"""The board protocol most teams follow: want-to-buy bids and card-for-card swaps with long expiry.

A bid gives cash and wants any copy of a card (`want: {"cards": ["LAV-07"]}`); a swap gives one of our
cards and wants one card, no cash. The side that ACCEPTS pays the venue fee, so as makers we pay nothing
and we post where the taker pays least (team board venues without a per-card fee beat El Rastro).

Everything here is pure code over our private values (`dealers.values.Values`):
- page bonus: completing a page (a set's commons, uncommons and rares) adds `page_bonus` x the page's
  value to us; breaking a complete page loses it. `/api/me/value` does not include it, so we add it;
- bid and swap candidates that gain >= max(3 P, 25 %) at our values, ranked best first;
- which of our own open offers went stale (no longer gain) and should be cancelled;
- the public pitch our broker can announce for our own venue (we cannot trade there ourselves, but
  value created between other teams on it scores for us).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..dealers.values import Values

MIN_GAIN_P, MIN_GAIN_FRAC = 3.0, 0.25
PAGE_RARITIES = {"common", "uncommon", "rare"}
PAGE_BONUS = 0.25                 # catalog values.page_bonus (share of the page's value), used if missing
CORE_SETS = ("LAV", "MAL", "RET")  # the pages we most want to complete (our highest affinities)
BID_EXPIRES = 120                  # ticks
SWAP_EXPIRES = 120
MAX_OWN_BIDS = 2                   # open bids at once (round-4 strategy: standing bids rarely fill and lock cash)
MAX_OWN_SWAPS = 6                  # open swaps at once
MAX_OWN_OPEN = 22                  # all our market offers at once (team cap 30: room for dealers)
MAX_BID_P = 60                     # never commit more than this to one bid (council threshold)
BID_COMMIT_MAX = 40                # cash committed to open bids at once (round-4 strategy)
BID_BOOK_MIN, BID_BOOK_DEFAULT, BID_BOOK_MAX = 0.3, 0.7, 1.0   # bid price as a share of book
SWAP_BOOK_MIN = 0.8                # what we give must look fair to the taker: book >= 0.8 x book wanted
PREFERRED_VENUES = ("v03",)        # t13's protocol venue (no per-card fee): tie-break only
# Alliance 2026-10-03: Team 5 lists on our v07 (its trades there score market-making for us) and we list on its
# v10. Allied venues are trusted at their posted fee (no worst-case fee rise) and get our asks from ALLIED_MIN_ASK up:
# the taker saves El Rastro's 5 % + 1 P there, so the same ask fills more easily and we keep the full price.
ALLIED_VENUES = {"v10": "t05"}     # venue -> owner team
ALLIED_MIN_ASK = 12                # cheaper asks stay on El Rastro, where the traffic is
FAIR_MAX_PER_HOUR = 4


def min_gain(cost: float) -> float:
    return max(MIN_GAIN_P, MIN_GAIN_FRAC * cost)


def venue_id(v: dict | None) -> str | None:
    if not isinstance(v, dict):
        return str(v) if v else None
    return v.get("venue") or v.get("id")


MAX_FEE_BPS, MAX_FEE_PER_CARD = 1000.0, 5.0     # RULES: fees are capped at 10 % and 5 P per card


def is_allied(v: dict | None) -> bool:
    """An allied team's venue (by id, and by owner when the venue says who owns it)."""
    vid = venue_id(v)
    if vid not in ALLIED_VENUES:
        return False
    owner = (v or {}).get("owner") if isinstance(v, dict) else None
    return owner in (None, ALLIED_VENUES[vid])


def _fee_parts(v: dict | None) -> tuple[float, float]:
    """(bps, per card) a taker pays: the worse of the fee in force and any announced change."""
    v = v or {}
    house = venue_id(v) in (None, "rastro")
    bps = float(v.get("fee_bps", 500 if house else 0) or 0)
    per = float(v.get("fee_per_card", 1 if house else 0) or 0)
    pend = v.get("pending_fee") or {}
    if isinstance(pend, dict):
        bps = max(bps, float(pend.get("fee_bps") or 0))
        per = max(per, float(pend.get("fee_per_card") or 0))
    if not house and not is_allied(v):
        # A team venue may announce a fee rise that applies after we accept (red team: -226 P), and the API may
        # not show it: price every team venue at the legal maximum, 10 % + 5 P per card.
        bps, per = max(bps, MAX_FEE_BPS), max(per, MAX_FEE_PER_CARD)
    return bps, per


def taker_fee(v: dict | None, cash: int, cards: int) -> int:
    bps, per = _fee_parts(v)
    return int(math.ceil(cash * bps / 10000.0 + per * cards))


def tradable_venues(venues: list[dict], my_id: str | None, my_venue: str | None) -> list[dict]:
    """Open venues we may trade on: El Rastro plus other teams' venues (never ours)."""
    out = []
    for v in venues or []:
        vid = venue_id(v)
        if not vid or vid == my_venue or (my_id and v.get("owner") in (my_id,)) or v.get("team") == my_id:
            continue
        if v.get("status", "open") not in ("open", "active"):
            continue
        out.append(v)
    if not any(venue_id(v) == "rastro" for v in out):
        out.append({"venue": "rastro", "fee_bps": 500, "fee_per_card": 1, "house": True})
    return out


def choose_venue(venues: list[dict], cash: int, cards: int) -> str:
    """Where to post a maker offer: lowest fee for the taker on a board (or house) venue."""
    # Team decision 2026-10-03: post only on El Rastro (a trade on a rival's venue scores for its owner), except our
    # allies' venues: asks from ALLIED_MIN_ASK go there when the taker pays less than on El Rastro.
    allied = [v for v in venues if is_allied(v) and v.get("status", "open") in ("open", "active")]
    if allied and cash >= ALLIED_MIN_ASK:
        rastro = next((v for v in venues if venue_id(v) == "rastro"), {"venue": "rastro", "fee_bps": 500,
                                                                         "fee_per_card": 1, "house": True})
        best_ally = min(allied, key=lambda v: taker_fee(v, cash, cards))
        if taker_fee(best_ally, cash, cards) < taker_fee(rastro, cash, cards):
            return str(venue_id(best_ally))
    cands = [v for v in venues if v.get("house") or venue_id(v) == "rastro"]
    if not cands:
        return "rastro"
    best = min(cands, key=lambda v: (taker_fee(v, cash, cards), venue_id(v) not in PREFERRED_VENUES,
                                     -int(v.get("trades") or 0)))
    return str(venue_id(best))


# --- pages ------------------------------------------------------------------------------
def page_refs(values: Values, s: str) -> list[str]:
    refs = [r for r, c in values.cards.items() if c.get("set") == s and not c.get("hidden")
            and (bool(c["page"]) if "page" in c else c.get("rarity") in PAGE_RARITIES)]
    return refs or [f"{s}-{i:02d}" for i in range(1, 11)]


def page_bonus(values: Values, s: str) -> float:
    frac = float((values.catalog.get("values") or {}).get("page_bonus", PAGE_BONUS) or 0)
    return frac * values.affinity.get(s, 1.0) * sum(values.book(r) for r in page_refs(values, s))


def page_delta(values: Values, counts: dict, refs_in: list[str], refs_out: list[str]) -> float:
    """Page bonus won (+) or lost (-) if we receive refs_in and give refs_out."""
    after = dict(counts)
    for r in refs_in:
        after[r] = after.get(r, 0) + 1
    for r in refs_out:
        after[r] = after.get(r, 0) - 1
    delta = 0.0
    for s in {Values.set_of(r) for r in [*refs_in, *refs_out]}:
        refs = page_refs(values, s)
        before = all(counts.get(r, 0) > 0 for r in refs)
        now = all(after.get(r, 0) > 0 for r in refs)
        if before != now:
            delta += page_bonus(values, s) * (1 if now else -1)
    return delta


def page_progress(values: Values, counts: dict, s: str) -> float:
    refs = page_refs(values, s)
    return sum(1 for r in refs if counts.get(r, 0) > 0) / max(1, len(refs))


# --- candidates ---------------------------------------------------------------------------
@dataclass
class BidCand:
    id: str
    ref: str
    value: float                  # next copy + page bonus share if it completes the page
    min_price: int
    max_price: int
    price: int
    venue: str
    score: float
    to: str | None = None


@dataclass
class SwapCand:
    id: str
    asset: dict                   # what we give
    loss: float                   # its value to us (+ page bonus lost)
    want: str                     # the card we want
    value: float                  # its value to us (+ page bonus won)
    gain: float
    venue: str
    to: str | None = None
    fans: list[str] = field(default_factory=list)


def want_refs(values: Values, counts: dict, exclude: set[str]) -> list[tuple[str, float]]:
    """Cards we lack, with their value to us (+ page bonus if they complete a page), best first.

    Pages of our core sets come first (by how close the page is to complete), then anything else
    that is worth at least book to us."""
    sets = sorted({c.get("set") for c in values.cards.values() if c.get("set")} or set(values.affinity),
                  key=lambda s: -values.affinity.get(s, 1.0))
    out = []
    for s in sets:
        aff = values.affinity.get(s, 1.0)
        for ref in page_refs(values, s):
            c = values.cards.get(ref) or {}
            if counts.get(ref, 0) > 0 or ref in exclude or (c and not c.get("released", True)):
                continue
            if s not in CORE_SETS and aff < 1.0:
                continue
            v = values.next_copy(ref) + max(0.0, page_delta(values, counts, [ref], []))
            prio = v * (1.0 + (page_progress(values, counts, s) if s in CORE_SETS else 0.0))
            out.append((ref, round(v, 2), prio))
    out.sort(key=lambda x: -x[2])
    return [(r, v) for r, v, _ in out]


def bid_candidates(values: Values, counts: dict, venues: list[dict], cash_room: float, exclude: set[str],
                   limit: int) -> list[BidCand]:
    """Want-to-buy bids priced below our value with the min-gain margin, inside the cash we may commit."""
    out: list[BidCand] = []
    room = cash_room
    for ref, v in want_refs(values, counts, exclude):
        if len(out) >= limit:
            break
        book = values.book(ref)
        max_price = int(math.floor(min(v / (1 + MIN_GAIN_FRAC), v - MIN_GAIN_P, book * BID_BOOK_MAX, MAX_BID_P)))
        min_price = max(1, int(math.ceil(book * BID_BOOK_MIN)))
        if max_price < min_price or min_price > room:
            continue
        price = max(min_price, min(max_price, int(round(book * BID_BOOK_DEFAULT)), int(room)))
        room -= price
        out.append(BidCand(id=f"b{len(out) + 1}", ref=ref, value=v, min_price=min_price, max_price=max_price,
                           price=price, venue=choose_venue(venues, price, 1), score=round(v - price, 2)))
    return out


def swap_candidates(values: Values, counts: dict, give_pool: list[dict], venues: list[dict], exclude: set[str],
                    fans_of, limit: int) -> list[SwapCand]:
    """Our duplicates / low-affinity cards for cards we lack, same book or better for the taker."""
    pool = []
    for a in give_pool:
        ref = a.get("ref")
        s = values.set_of(ref)
        dup = counts.get(ref, 0) > 1
        if not (dup or values.affinity.get(s, 1.0) < 1.0):
            continue                                   # never swap away a single copy of a set we value
        loss = values.asset_value(a.get("id")) - min(0.0, page_delta(values, counts, [], [ref]))
        pool.append((0 if dup else 1, loss, a))
    pool.sort(key=lambda x: (x[0], x[1]))              # duplicates first, then cheapest to us
    used: set = set()
    out: list[SwapCand] = []
    venue = choose_venue(venues, 0, 2)
    for want, v in want_refs(values, counts, exclude):
        if len(out) >= limit:
            break
        wbook = values.book(want)
        for _, loss, a in pool:
            if a.get("id") in used or values.book(a.get("ref")) < SWAP_BOOK_MIN * wbook:
                continue
            gain = v - loss
            if gain < min_gain(loss):
                continue
            used.add(a.get("id"))
            fans = list(fans_of(values.set_of(a.get("ref"))))
            out.append(SwapCand(id=f"s{len(out) + 1}", asset=a, loss=round(loss, 2), want=want, value=v,
                                gain=round(gain, 2), venue=venue, to=fans[0] if fans else None, fans=fans[:3]))
            break
    return out


def offer_kind(o: dict) -> str:
    give, want = o.get("give") or {}, o.get("want") or {}
    wants_card = bool(want_cards(o))
    gives_card = bool(give.get("assets")) or bool(give.get("types"))
    if wants_card and int(give.get("cash") or 0) > 0 and not gives_card:
        return "bid"
    if wants_card and gives_card and not int(give.get("cash") or 0) and not int(want.get("cash") or 0):
        return "swap"
    if gives_card and int(want.get("cash") or 0) > 0 and not wants_card:
        return "ask"
    return "other"


def want_cards(o: dict) -> list[str]:
    want = o.get("want") or {}
    return list(want.get("cards") or []) + [str(t)[5:] for t in want.get("types") or [] if str(t).startswith("card:")]


def stale_offers(own: list[dict], values: Values, counts: dict, limit: int) -> list[tuple[dict, str]]:
    """Our open market offers that no longer gain at our values (we got the card, value moved)."""
    out = []
    for o in own:
        kind = offer_kind(o)
        give = o.get("give") or {}
        why = None
        if kind == "bid":
            refs = want_cards(o)
            cash = int(give.get("cash") or 0)
            if any(counts.get(r, 0) > 0 for r in refs):
                why = "we already hold the card"
            else:
                v = sum(values.next_copy(r) for r in refs) + max(0.0, page_delta(values, counts, refs, []))
                if v - cash < 1:
                    why = f"bid {cash} no longer below our value {v:.1f}"
        elif kind == "swap":
            refs = want_cards(o)
            ids = [a.get("id") if isinstance(a, dict) else a for a in give.get("assets") or []]
            if any(counts.get(r, 0) > 0 for r in refs):
                why = "we already hold the card"
            elif ids and all(i in values.assets for i in ids):
                gave = [values.assets[i].get("ref") for i in ids]
                loss = sum(values.asset_value(i) for i in ids) - min(0.0, page_delta(values, counts, [], gave))
                v = sum(values.next_copy(r) for r in refs) + max(0.0, page_delta(values, counts, refs, []))
                if v - loss < 1:
                    why = f"swap no longer gains ({v:.1f} for {loss:.1f})"
        elif kind == "ask":
            ids = [a.get("id") if isinstance(a, dict) else a for a in give.get("assets") or []]
            if ids and all(i in values.assets for i in ids):
                gave = [values.assets[i].get("ref") for i in ids]
                loss = sum(values.asset_value(i) for i in ids) - min(0.0, page_delta(values, counts, [], gave))
                price = int((o.get("want") or {}).get("cash") or 0)
                if price - loss < 1:
                    why = f"ask {price} now below our value {loss:.1f}"
        if why:
            out.append((o, why))
        if len(out) >= limit:
            break
    return out


# --- our venue ------------------------------------------------------------------------------
def broker_pitch(venue: dict | str | None) -> str | None:
    """Public text for broker_announce: invite the protocol's bids and swaps to our venue.

    We cannot trade on our own venue, but value created between other teams there scores for us
    (Market-making). Returns None while we have no open venue. Plain facts only, no instructions."""
    vid = venue_id(venue) if venue else None
    if not vid:
        return None
    v = venue if isinstance(venue, dict) else {}
    bps, per = float(v.get("fee_bps") or 0), float(v.get("fee_per_card") or 0)    # our own listed fee
    fee = "no fee" if not bps and not per else f"fee {bps / 100:g} % + {per:g} P per card"
    return (f"Team 10 venue {vid}: {fee}, board market with a broker pairing crossing offers every tick. "
            f"Want-to-buy bids (give cash, want {{\"cards\": [...]}}) and card-for-card swaps welcome here, "
            f"long expiry fine; the accepting side pays {('nothing' if not bps and not per else 'only this fee')}.")
