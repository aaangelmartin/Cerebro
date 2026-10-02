"""Negotiation tactics: small, pure helpers the strategies can call (see docs/NEGOTIATION.md).

Nothing here talks to the Bazaar or keeps state: every function takes numbers and returns numbers
(or a short label), so each one is unit-tested in bot/tests/test_tactics.py and tuned in the simulator.

Conventions:
* Prices are whole primas. `buying=True` means we buy (we want the price low, the counterpart sells);
  `buying=False` means we sell.
* "Utility" (u) is our surplus over our limit, plus `weight * days` when the deal has delivery days.
* Time `t` is the share of the negotiation already played, from 0 (start) to 1 (deadline).

Sources (details and evidence in docs/NEGOTIATION.md): Faratin, Sierra & Jennings 1998 (time-dependent
tactics, Boulware vs conceder, behaviour-dependent tit-for-tat); Baarslag, Hindriks & Jonker 2013
(acceptance conditions AC_next / AC_combi); Rubinstein 1982 (alternating offers with discounting);
Galinsky & Mussweiler 2001 (first offers as anchors); Roth et al. 1988 (deadline effect);
Medvec et al. (MESOs); Van Kleef et al. 2004 (emotion and concessions).
"""

from __future__ import annotations

import math
from statistics import median

# Faratin exponents: e < 1 holds firm and concedes late (Boulware), e = 1 is linear, e > 1 concedes early.
CURVES = {"hardheaded": 0.1, "boulware": 0.3, "linear": 1.0, "conceder": 3.0}


# --- concession curves (time-dependent tactics) -------------------------------------------------
def faratin_alpha(t: float, e: float = CURVES["boulware"], k: float = 0.0) -> float:
    """Share of the way from our opening to our reservation we have conceded at time t.

    alpha(t) = k + (1 - k) * t^(1/e)  (Faratin, Sierra & Jennings 1998), clamped to [0, 1]."""
    if e <= 0:
        raise ValueError("e must be > 0")
    t = min(1.0, max(0.0, t))
    k = min(1.0, max(0.0, k))
    return k + (1 - k) * t ** (1.0 / e)


def concession_target(start: float, reserve: float, t: float, e: float = CURVES["boulware"], k: float = 0.0) -> float:
    """Where the curve puts our offer at time t: from `start` (t=0) to `reserve` (t=1).

    Works in either direction (a buyer's start is below its reserve, a seller's above)."""
    return start + faratin_alpha(t, e, k) * (reserve - start)


def utility_target(u_open: float, u_floor: float, t: float, e: float = CURVES["boulware"]) -> float:
    """The same curve in utility: what we still ask for at time t (u_open at t=0, u_floor at t=1)."""
    return concession_target(u_open, u_floor, t, e)


# --- reading the counterpart --------------------------------------------------------------------
def concessions(prices: list, they_sell: bool) -> list:
    """Size of each step the counterpart made towards us (negative = they went backwards).

    `they_sell`: their price falling is a concession; otherwise their price rising is."""
    out = []
    for a, b in zip(prices, prices[1:]):
        out.append((a - b) if they_sell else (b - a))
    return out


def mirror_ratio(our_steps: list, their_steps: list, last: int = 3):
    """How much of our step the counterpart gives back (median of their_step / our_step over the
    last `last` exchanges where we moved). None when we have not moved yet.

    A dealer that 'concedes only when we concede' answers with a stable ratio; when the ratio
    collapses towards 0 it has hit its secret limit."""
    pairs = [(o, t) for o, t in zip(our_steps, their_steps) if o > 0][-last:]
    if not pairs:
        return None
    return median(t / o for o, t in pairs)


def estimate_reservation(prices: list, they_sell: bool, q_cap: float = 0.75, stall: int = 2) -> dict:
    """Guess the counterpart's limit from its offer history (most recent last).

    Their steps usually shrink geometrically as they near their limit (Boulware-like). With the
    last two steps c1, c2 the ratio q = c2 / c1 (capped at q_cap) extrapolates what is left:
    c2 * q / (1 - q). If they did not move for `stall` consecutive offers, their last price is the
    limit. Returns {"estimate", "stalled", "q", "remaining", "n"}; estimate is None with no offers.
    """
    if not prices:
        return {"estimate": None, "stalled": False, "q": None, "remaining": None, "n": 0}
    last = prices[-1]
    steps = concessions(prices, they_sell)
    sign = -1 if they_sell else 1
    if len(steps) >= stall and all(s <= 0 for s in steps[-stall:]):
        return {"estimate": float(last), "stalled": True, "q": 0.0, "remaining": 0.0, "n": len(prices)}
    pos = [s for s in steps if s > 0]
    if not pos:
        return {"estimate": None, "stalled": False, "q": None, "remaining": None, "n": len(prices)}
    if len(pos) >= 2 and pos[-2] > 0:
        q = min(q_cap, pos[-1] / pos[-2])
    else:
        q = q_cap
    remaining = pos[-1] * q / (1 - q)
    return {"estimate": last + sign * remaining, "stalled": False, "q": q, "remaining": remaining,
            "n": len(prices)}


# --- our next step (behaviour-dependent: reciprocity) -------------------------------------------
def reciprocal_step(their_step: float | None, gap: float, ratio: float = 1.0, min_step: int = 1,
                    cap_frac: float = 0.35) -> int:
    """How far we move this round, matching the counterpart (tit-for-tat on concession size).

    * They moved `their_step`: we move ratio * their_step (ratio < 1 keeps us ahead of the split).
    * They did not move (None or <= 0): we move only `min_step`, never zero (a repeated price
      earns nothing and some dealers call it spam), never a big unilateral step.
    * Never more than cap_frac of the remaining gap, never less than min_step."""
    if gap <= 0:
        return 0
    want = ratio * their_step if (their_step is not None and their_step > 0) else min_step
    cap = max(min_step, math.floor(cap_frac * gap))
    return int(max(min_step, min(cap, round(want))))


def next_offer(ours: int | None, theirs: int, limit: int, buying: bool, step: int) -> int | None:
    """Our next price after a step of `step` towards them, never past their price or our limit and
    never repeating our last price. None when we cannot move (we are at our limit or at their price):
    then we wait for their final offer instead of repeating ourselves."""
    if ours is None:
        raise ValueError("next_offer needs our previous price; use anchor() for the first one")
    if buying:
        nxt = min(ours + max(1, step), theirs, limit)
        return nxt if nxt > ours else None
    nxt = max(ours - max(1, step), theirs, limit)
    return nxt if nxt < ours else None


def anchor(their_price: int, limit: int, buying: bool, ambition: float) -> int:
    """First offer: an ambitious anchor relative to their opening price, but on our side of our limit.

    Buying: ambition is the share of their ask we bid (e.g. 0.40). Selling: ambition is the multiple
    of their bid we ask (e.g. 2.2). Extreme anchors risk an insult/impasse (Schweinsberg et al. 2012),
    so keep ambition in a sane band: [0.25, 0.7] buying, [1.3, 3.0] selling."""
    if buying:
        a = min(0.7, max(0.25, ambition))
        return int(max(1, min(limit, round(their_price * a))))
    a = min(3.0, max(1.3, ambition))
    return int(max(limit, round(their_price * a)))


def blended_step(ours: int, theirs: int, limit: int, buying: bool, t: float, start: int,
                 their_step: float | None, e: float = CURVES["boulware"], w_time: float = 0.5,
                 ratio: float = 1.0, cap_frac: float = 0.35) -> int:
    """Faratin-style mix of a time tactic and a reciprocity tactic: the step is a weighted average of
    (a) the step that puts us on the concession curve from `start` to `limit` at time t and
    (b) the reciprocal step. Always at least 1 (never repeat)."""
    gap = (theirs - ours) if buying else (ours - theirs)
    target = concession_target(start, limit, t, e)
    time_step = max(0.0, (target - ours) if buying else (ours - target))
    rec = reciprocal_step(their_step, gap, ratio=ratio, cap_frac=cap_frac)
    step = w_time * time_step + (1 - w_time) * rec
    cap = max(1, math.floor(cap_frac * gap))
    return int(max(1, min(cap, round(step))))


# --- acceptance (deadline-aware) ----------------------------------------------------------------
def discounted(u: float, decay: float, rounds: float) -> float:
    """What utility u is worth if it arrives `rounds` rounds later and the pie shrinks by `decay`."""
    return u * (1 - decay) ** max(0.0, rounds)


def should_accept(offered_u: float, planned_u: float, decay: float = 0.0, lookahead: float = 1.0,
                  ticks_left: float | None = None, last_ticks: int = 1, reservation_u: float = 0.0,
                  best_seen_u: float | None = None, late_frac: float | None = None, t: float | None = None,
                  final: bool = False) -> tuple:
    """Accept the counterpart's offer now? Returns (bool, reason).

    * Never below our reservation (outside our limit loses points).
    * final offer inside our limit: take it (the alternative is a walk-out, worth 0).
    * AC_next with discount: accept if their offer >= our planned next offer, discounted by the decay
      of the `lookahead` rounds it would take them to accept ours.
    * AC_time: with `last_ticks` or fewer ticks left, anything inside our limit beats no deal.
    * AC_combi (Baarslag et al. 2013): late in the game (t >= late_frac) accept an offer at least
      as good as the best one they made so far (it will probably not get better)."""
    if offered_u < reservation_u:
        return False, f"below reservation ({offered_u:.1f} < {reservation_u:.1f})"
    if final:
        return True, "final offer inside our limit"
    nxt = discounted(planned_u, decay, lookahead)
    if offered_u >= nxt:
        return True, f"AC_next: {offered_u:.1f} >= our next {planned_u:.1f} discounted to {nxt:.1f}"
    if ticks_left is not None and ticks_left <= last_ticks:
        return True, f"AC_time: {ticks_left} ticks left"
    if late_frac is not None and t is not None and t >= late_frac and best_seen_u is not None \
            and offered_u >= best_seen_u:
        return True, f"AC_combi: late and {offered_u:.1f} >= best seen {best_seen_u:.1f}"
    return False, f"hold: {offered_u:.1f} < {nxt:.1f}"


def rubinstein_share(decay: float) -> float:
    """Share of the pie the first proposer gets in Rubinstein's alternating-offers equilibrium with a
    common per-round discount delta = 1 - decay: 1 / (1 + delta). A sanity target for duels: with
    decay 0.06 it is ~0.515, so asking much more than half late in a duel only burns pie."""
    delta = 1 - decay
    return 1.0 / (1.0 + delta)


# --- two issues: logrolling and equivalent packages ---------------------------------------------
def joint_day(w_ours: float, w_rival: float, days_max: int = 10) -> int:
    """The delivery day that maximises the joint pie when utility is linear in days: an extreme,
    chosen by the sign of the summed weights (the side that cares more wins the issue)."""
    joint = w_ours + w_rival
    if abs(joint) < 1e-9:
        return days_max // 2
    return days_max if joint > 0 else 0


def equivalent_packages(role: str, limit: float, u: float, w: float, days_options=(0, 5, 10),
                        min_surplus: float = 1.0) -> list:
    """MESO: several (price, days) packages worth the same utility u to us (surplus + w * days).

    Sending a different one each round costs us nothing and the rival's reaction (which day they
    counter with) reveals the sign and size of their own day weight."""
    out = []
    for d in days_options:
        s = max(min_surplus, u - w * d)
        price = limit + s if role == "seller" else limit - s
        price = int(round(price))
        if price >= 1:
            out.append((price, int(d)))
    return out


# --- words: the tone of our next message --------------------------------------------------------
TONES = ("warm", "firm", "closing")

TONE_HINTS = {
    "warm": "Friendly and appreciative; thank them, build rapport, show genuine interest in the card.",
    "firm": "Still polite, but calm and steady: our price reflects real value and we have moved as far as is "
            "fair for now; no apologies, no pressure, no threats.",
    "closing": "Warm and decisive: signal this is a good point to shake hands now, and that we are glad to close.",
}


def tone(t: float, their_step: float | None = None, final: bool = False, gap: float | None = None,
         our_step: float | None = None, kind_counterpart: bool = False, close_at: float = 0.8) -> str:
    """Pick the tone of our next message: "warm", "firm" or "closing".

    * closing: their final offer is on the table, we are late (t >= close_at), or the gap is about
      one more step (deadline effect: agreements cluster at the end; say we are ready).
    * firm: they did not move last round (don't reward a stall with warmth AND a big step).
      Never with a counterpart that rewards kindness (Abuela): there "firm" becomes "warm".
    * warm: otherwise (rapport helps integrative deals and keeps dealers from cooling us off)."""
    if final or t >= close_at or (gap is not None and our_step is not None and gap <= max(1, 2 * our_step)):
        return "closing"
    if their_step is not None and their_step <= 0 and not kind_counterpart:
        return "firm"
    return "warm"
