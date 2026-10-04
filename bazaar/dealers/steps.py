"""Step ladders per dealer: the haggle that worked by hand on Saturday, as code. Pure: no I/O, no clock.

Measured on Saturday evening (our own threads 1600-1703 and every team's public threads):

- Los Pícaros sell a rare: open 73. Bids 32, 36, 40, 44, 47, 49 brought 66, 62, 58 and a final of 55; a first
  bid of 48 with two messages closed at 54-59. Five or six small steps, then take their final.
- Doña Pilar buys a rare she loves: opens 70. Asks 105, 102, 99, 96, 93, 90 brought 72, 75, 78, 81 and a final
  of 84. An ask of 108 made her steps smaller (final 77). A counter-offer sent AFTER her final closed the
  thread: after a final there is only accept or close.
- El Chato mirrors steps of 2-4 P and calls 1 P steps games: seven or eight messages, never a 1 P step.
- Abuela buys an uncommon: opens 18. Asks 24, 21, 20 brought 19: steps of 1-3 P down to her price.

The rules the code guarantees for a thread under a ladder (whatever Claude says):
- one message per dealer answer, never two in a row, never the same price twice;
- after the dealer's final offer: accept it inside our limit, or close; never a counter-offer;
- never past our limit; when cash caps the next bid, wait a couple of ticks, then close and free the thread.
"""
from __future__ import annotations

from dataclasses import dataclass

from .haggle import Move, allowed_range
from .threads import ThreadView

WAIT_CASH_TICKS = 2          # ticks a cash-capped bid waits for cash before the thread is closed
MIN_OPENING = 12             # below this opening (5 P commons) the quick small-deal rule of haggle.py stays


@dataclass(frozen=True)
class StepProfile:
    first: float             # first price as a multiple of the dealer's opening (buy < 1, sell > 1)
    step_max: int            # largest step, at an opening of `ref_open`
    step_min: int            # smallest step ever sent (Chato: 2)
    gap_div: float           # step = gap between the two prices / gap_div, clamped to [step_min, step cap]
    max_messages: int        # our priced messages before the ladder ends
    ref_open: int            # the opening the steps were measured at; they scale with the real one


PROFILES: dict[tuple[str, str], StepProfile] = {
    ("picaros", "buy"): StepProfile(first=0.44, step_max=4, step_min=2, gap_div=6.0, max_messages=7, ref_open=73),
    ("pilar", "sell"): StepProfile(first=1.50, step_max=3, step_min=1, gap_div=1.0, max_messages=8, ref_open=70),
    ("chato", "buy"): StepProfile(first=0.62, step_max=4, step_min=2, gap_div=4.0, max_messages=8, ref_open=97),
    ("chato", "sell"): StepProfile(first=1.45, step_max=2, step_min=2, gap_div=1.0, max_messages=7, ref_open=13),
    ("abuela", "sell"): StepProfile(first=1.33, step_max=3, step_min=1, gap_div=2.0, max_messages=6, ref_open=18),
}


def profile_for(dealer: str, side: str) -> StepProfile | None:
    return PROFILES.get((str(dealer), str(side)))


def messages_for(prof: StepProfile, order: dict | None) -> int:
    """Our priced messages for this thread. A brain order of 1-2 messages means "close fast" and is kept;
    anything longer never cuts the ladder short (the dealer's final comes at the end of it)."""
    om = int((order or {}).get("max_messages") or 0)
    if om and om <= 2:
        return om
    return max(om, prof.max_messages)


def _step_cap(prof: StepProfile, opening: float) -> int:
    return max(prof.step_min, int(round(prof.step_max * float(opening or prof.ref_open) / prof.ref_open)))


def first_price(prof: StepProfile, buying: bool, opening: float, limit: int, open_hint: int | None = None) -> int:
    """Our first price: the brain's `open` if it gave one, else the profile's share of the dealer's opening,
    with room left for the ladder on our side of the limit."""
    cap = _step_cap(prof, opening)
    if open_hint:
        p = int(open_hint)
    else:
        p = int(round(prof.first * float(opening)))
        room = cap * 2
        p = min(p, limit - room) if buying else max(p, limit + room)
    return max(1, min(p, limit)) if buying else max(p, limit)


def next_price(v: ThreadView, prof: StepProfile, limit: int) -> int | None:
    """The price after our last one (not yet checked against the legal range)."""
    theirs, ours = v.last_theirs, v.last_ours
    if theirs is None or ours is None:
        return None
    gap = (theirs - ours) if v.buying else (ours - theirs)
    step = max(prof.step_min, min(_step_cap(prof, v.opening or theirs), int(gap / prof.gap_div + 0.5)))
    return ours + step if v.buying else ours - step


def next_move(v: ThreadView, limit: int, tick: int, prof: StepProfile, ok: bool, why: str = "",
              open_hint: int | None = None, max_messages: int | None = None, budget_bound: bool = False) -> Move:
    """The ladder's move for one thread. `ok`: the dealer's standing offer is acceptable (haggle.acceptable)."""
    theirs = v.last_theirs
    if v.final:
        return Move("accept", theirs, "final offer inside our limit: take it") if ok else \
            Move("close", None, f"final offer: {why}")
    if theirs is None:
        return Move("wait", None, "waiting for the dealer's opening")
    if v.last_sender == "us":
        return Move("wait", None, "one message per answer: waiting for the dealer")
    rng = allowed_range(v, limit)
    msgs = int(max_messages or prof.max_messages)
    if v.last_ours is None:
        if rng is None:
            return Move("close", None, "no legal price inside our limit")
        p = first_price(prof, v.buying, v.opening or theirs, limit, open_hint)
        return Move("price", max(rng[0], min(rng[1], p)), f"ladder: open at {max(rng[0], min(rng[1], p))}")
    nxt = next_price(v, prof, limit)
    crossed = nxt is not None and ((theirs <= nxt) if v.buying else (theirs >= nxt))
    if ok and crossed:
        return Move("accept", theirs, "its offer is as good as our next step")
    if len(v.ours) >= msgs:
        return Move("accept", theirs, "ladder used: its offer is inside our limit") if ok else \
            Move("close", None, f"ladder used: {len(v.ours)} messages without an offer inside our limit")
    if rng is not None and nxt is not None:
        p = max(rng[0], min(rng[1], nxt))
        if abs(p - v.last_ours) >= prof.step_min:
            return Move("price", p, f"ladder: step to {p}")
    if ok:
        return Move("accept", theirs, "no step left: its offer is inside our limit")
    if budget_bound:
        waited = tick - int(v.last_dealer_tick or tick)
        if waited < WAIT_CASH_TICKS:
            return Move("wait", None, "cash caps our next bid: waiting for cash")
        return Move("close", None, "cash caps our next bid: close and free the thread")
    return Move("close", None, "no step left inside our limit")
