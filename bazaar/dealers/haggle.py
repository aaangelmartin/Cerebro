"""Pure haggling: limits, guards and the code-only fallback tactic. No I/O, no clock.

The guards are what the code guarantees whatever Claude says:
- never accept the dealer's opening price (a deal there scores 0 on the ladder and does not unlock);
- never repeat our own price (dealers give nothing for it and some call it spam) and never go backwards;
- buy at most our private value minus a margin; sell at least our value plus a margin;
- never offer past the dealer's current price (meeting it is an accept, not a message).

The fallback tactic (measured against Friday's dealers): anchor below the dealer's estimated limit,
concede a fraction of the gap per step, drop to 1 P steps when the dealer stalls (it is at its limit),
and take the final offer if it is inside our limit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .threads import ThreadView, offer_matches

BUY_MARGIN_P, BUY_MARGIN_FRAC = 3.0, 0.10     # buy max = value - max(3, 10 %)
SELL_MARGIN_P, SELL_MARGIN_FRAC = 1.0, 0.10   # sell min = value + max(1, 10 %)
ANCHOR_K = 1.2           # first price sits this many (opening - limit) spans beyond the estimated limit
STEP_FRAC = 0.22         # share of the gap we concede per step
STALL_STEP = 1           # once the dealer stops moving, 1 P steps
WAIT_REPLY_TICKS = 3     # ticks we wait for a dealer reply before nudging again
LADDER_WEIGHT_P = 10.0   # P-equivalent of one full capture unit at level 1 (higher levels weigh more). Raised on
# Saturday: /api/me shows the ladder is its own score component (ladder_points), dealer deals add nothing to
# neg_points, and an empty slot counts as zero, so filling a slot matters more than the P gained in the deal.
MAX_PRICE = 10_000_000


def buy_max(value: float) -> int:
    return int(math.floor(value - max(BUY_MARGIN_P, BUY_MARGIN_FRAC * value)))


def sell_min(value: float) -> int:
    return int(math.ceil(value + max(SELL_MARGIN_P, SELL_MARGIN_FRAC * value)))


@dataclass
class Move:
    kind: str                 # "price" | "accept" | "close" | "wait"
    price: int | None = None
    why: str = ""


def allowed_range(v: ThreadView, limit: int) -> tuple[int, int] | None:
    """The legal prices for our next message, or None if there is none."""
    theirs = v.last_theirs
    if v.buying:
        lo = (v.last_ours + 1) if v.last_ours is not None else 1
        hi = limit
        if theirs is not None:
            hi = min(hi, theirs - 1)
        if v.opening is not None:
            hi = min(hi, v.opening - 1)
    else:
        lo = max(limit, 1)
        if theirs is not None:
            lo = max(lo, theirs + 1)
        if v.opening is not None:
            lo = max(lo, v.opening + 1)
        hi = (v.last_ours - 1) if v.last_ours is not None else MAX_PRICE
    return (lo, hi) if lo <= hi else None


def guard_price(v: ThreadView, price: int | float | None, limit: int) -> int | None:
    """Clamp a proposed price into the legal range; None if no legal price exists."""
    rng = allowed_range(v, limit)
    if rng is None or price is None:
        return None
    try:
        p = int(round(float(price)))
    except (TypeError, ValueError):
        return None
    return max(rng[0], min(rng[1], p))


def acceptable(v: ThreadView, limit: int) -> tuple[bool, str]:
    """Can we take the dealer's standing offer? Structure, our limit, and never the opening price."""
    if not v.standing or v.standing_price is None:
        return False, "no standing offer"
    ok, why = offer_matches(v, v.standing)
    if not ok:
        return False, why
    p = v.standing_price
    if v.opening is None:
        return False, "opening unknown"
    if v.buying:
        if p > limit:
            return False, f"{p} above our max {limit}"
        if p >= v.opening:
            return False, "that is the dealer's opening price"
    else:
        if p < limit:
            return False, f"{p} below our min {limit}"
        if p <= v.opening:
            return False, "that is the dealer's opening price"
    return True, "ok"


def stalled(v: ThreadView) -> int:
    """How many of the dealer's last answers to our concessions did not move.

    The dealer's answer to our first (anchor) price is not counted: it has nothing to mirror yet.
    """
    if len(v.ours) < 2:
        return 0
    n = 0
    for c in reversed(v.their_concessions()[1:][-3:]):
        if c > 0:
            break
        n += 1
    return n


def plan_next(v: ThreadView, limit: int, limit_est: float, patience: float = 6.0) -> int | None:
    """Our next price under the fallback tactic (already guarded), or None if no legal price.

    Time-based schedule (Faratin-style): anchor beyond the dealer's estimated limit by at least one P per
    expected message of its patience, then walk towards that limit so we reach it about when its patience
    runs out (its final offer then lands near its limit). 1 P steps once it stalls.
    """
    rng = allowed_range(v, limit)
    if rng is None:
        return None
    o = v.opening if v.opening is not None else v.last_theirs
    theirs = v.last_theirs
    if o is None or theirs is None:
        return None
    pat = max(2.0, float(patience or 6.0))
    if v.last_ours is None:
        room = max(ANCHOR_K * max(1.0, abs(o - limit_est)), pat)
        target = limit_est - room if v.buying else limit_est + room
        return guard_price(v, target, limit)
    st = stalled(v)
    left = max(1.0, pat - len(v.ours))
    dist = (limit_est - v.last_ours) if v.buying else (v.last_ours - limit_est)
    step = STALL_STEP if st >= 1 else max(1, round(max(dist, 0) / left), round(STEP_FRAC * 0.5 * abs(theirs - v.last_ours)) if dist > 0 else 1)
    nxt = v.last_ours + step if v.buying else v.last_ours - step
    if st < 2 and dist > 0:
        # keep on our side of its estimated limit until it stalls, so its final lands there
        nxt = min(nxt, math.floor(limit_est)) if v.buying else max(nxt, math.ceil(limit_est))
    if (v.buying and nxt <= v.last_ours) or (not v.buying and nxt >= v.last_ours):
        nxt = v.last_ours + 1 if v.buying else v.last_ours - 1
    return guard_price(v, nxt, limit)


QUICK_GAP = 2                # P: on small deals, settle or close when the dealer is this close to our limit
SMALL_DEAL_P = 10            # ...only for cards worth this little (5-8 P commons); bigger haggles keep their range


def fallback_move(v: ThreadView, limit: int, limit_est: float, tick: int, patience: float = 6.0) -> Move:
    """Code-only decision for one thread."""
    ok, why = acceptable(v, limit)
    theirs = v.last_theirs
    if v.final:
        return Move("accept", theirs, "final offer inside our limit") if ok else Move("close", None, f"final offer: {why}")
    if theirs is None:
        return Move("wait", None, "waiting for the dealer's opening")
    if v.last_sender == "us":
        last_tick = v.our_ticks[-1] if v.our_ticks else tick
        if tick - last_tick < WAIT_REPLY_TICKS:
            return Move("wait", None, "waiting for the dealer's answer")
    nxt = plan_next(v, limit, limit_est, patience)
    # Team decision 2026-10-03: small haggles are not worth the dealer's only slot. Within QUICK_GAP of our
    # limit, take the offer if it is acceptable, otherwise close.
    if limit <= SMALL_DEAL_P and abs(theirs - limit) <= QUICK_GAP:
        if ok:
            return Move("accept", theirs, f"within {QUICK_GAP} P of our limit: settle now")
        if stalled(v) >= 1:                    # it stopped conceding just outside our limit: free the slot
            return Move("close", None, f"dealer stalled within {QUICK_GAP} P outside our limit")
    if ok:
        # AC_next: their price is no worse than what we would offer next; or already at/below its estimated limit.
        at_limit = theirs <= limit_est if v.buying else theirs >= limit_est
        if nxt is None or at_limit or (v.buying and theirs <= nxt) or (not v.buying and theirs >= nxt) or stalled(v) >= 2:
            return Move("accept", theirs, "standing offer is as good as our next step")
    if nxt is None:
        return Move("close", None, "no legal price left inside our limit")
    # Our limit is beyond where this dealer stops and it has stopped moving: free its only slot (Friday L08).
    hopeless = (limit < limit_est - 1) if v.buying else (limit > limit_est + 1)
    if hopeless and not ok and stalled(v) >= 2:
        return Move("close", None, "dealer stuck far from our limit")
    return Move("price", nxt, "walk towards its estimated limit" if stalled(v) == 0 else "dealer stalled: 1 P step")


def expected_points(value_gain: float, level: int, ladder_gain: float) -> float:
    """What a deal is worth to the score, in P-equivalents (value at private values + ladder share)."""
    return round(value_gain + LADDER_WEIGHT_P * max(1, level) * ladder_gain, 2)


# --- words -------------------------------------------------------------------------------
KIND_LINES = [
    "Gracias, {name}. {item} would make my day; could you do {p} P, por favor?",
    "{name}, your stall is the heart of El Rastro. I can stretch to {p} P for {item}, de corazón.",
    "Ay, {name}, you are very kind. {p} P is what my pockets allow for {item}. ¿Le parece?",
    "Mil gracias for your patience, {name}. Could we meet at {p} P for {item}?",
]
STRAIGHT_LINES = [
    "{p} P for {item}. Fair and straight.",
    "I can do {p} P for {item}.",
    "{p} P. That is a serious price for {item}.",
    "Moving to {p} P for {item}. Straight deal.",
]


def line(dealer_name: str, item: str, price: int, kind: bool, n: int) -> str:
    pool = KIND_LINES if kind else STRAIGHT_LINES
    return pool[n % len(pool)].format(name=dealer_name, item=item, p=price)
