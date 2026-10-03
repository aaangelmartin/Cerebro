"""Pure-code duel policy: the instant fallback, the economics table Claude reads, and the guard that
turns any proposed move (Claude's or ours) into a safe one.

Words never enter here: every input is a number from the structured offer fields.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import DAYS_MAX, MIN_SURPLUS, DuelView, points, price_for

PARAMS = {
    "OPEN": 0.9,           # opening ask, as a share of the estimated pie
    "OPEN_BUYER": 0.8,     # as buyer open a little closer: 2.2 rounds per deal against 1.7 as seller in Duels II
    "END": 0.12,           # last-tick ask against a silent rival (rounds do not grow while they are mute)
    "BETA": 2.0,           # >1: hold early, concede late
    "ACCEPT_SHARE": 0.6,   # accept any rival offer that already gives us this share of the pie
    "MIRROR": 0.3,         # after a rival counter, concede this share of their last step (min 1 P)
    "STEP_PRIOR": 4.0,     # Friday steppers moved ~4 P per step
    "PROBE_UNTIL": 9,      # leave one rival offer unanswered for a tick while more ticks than this remain
    "LAST_TICKS": 2,       # in the last ticks take any offer inside our limit
    "TOUGH_TAKE": 1.0,     # tough rival: take their offer when it is worth >= TOUGH_TAKE x q x the midpoint
    # Rival silent since our offer: hold in silence, then a short finish in the last FINAL_TICKS ticks, one
    # step per tick, down to these shares of the estimated pie (by ticks left). Saturday's silent rivals
    # accepted at 26 %, 17 % and 29 % of the pie (duels 2328, 2329, 2354), so the steps end at 17 %.
    "FINAL_TICKS": 3,
    "FINAL_STEPS": {3: 0.40, 2: 0.28, 1: 0.17},
}


@dataclass
class Move:
    action: str                          # "accept" | "offer" | "wait"
    price: int | None = None
    days: int | None = None
    text: str = ""
    reason: str = ""
    expected_points: float = 0.0
    source: str = "fallback"
    econ: dict = field(default_factory=dict)
    lesson_ids: list = field(default_factory=list)     # lessons Claude cited (validated in the domain)


TEMPLATES = [
    "I can do {p} P{d}. Every round costs us both, so let's close.",
    "{p} P{d} works for me and we can close now.",
    "Meeting you closer: {p} P{d}.",
    "A real step from me: {p} P{d}.",
]


def template_text(v: DuelView, price: int, days: int | None) -> str:
    d = f" with delivery in {days} days" if (v.uses_days and days is not None) else ""
    return TEMPLATES[len(v.our_msgs()) % len(TEMPLATES)].format(p=price, d=d)


# --- days (Duels II) --------------------------------------------------------------------------------
def days_weight(v: DuelView) -> float:
    """Value to us of one delivery day, in points: the ONE signed weight (model.days_interpretation)."""
    return v.days_w


def rival_days_weight(v: DuelView, w: float) -> float:
    """Rough rival weight per day: the sign from the days they ask for, the size from how they move."""
    ds = [o.days for o in v.rival_offers() if o.days is not None]
    if not ds:
        return 0.0
    m = sum(ds) / len(ds)
    if abs(m - DAYS_MAX / 2) < 0.5:
        return 0.0
    sign = 1.0 if m > DAYS_MAX / 2 else -1.0
    size = abs(w) or 1.0
    if len(ds) >= 2 and abs(ds[-1] - ds[0]) >= 3:
        size *= 0.5           # they give ground on days: they care less than about price
    elif len(ds) >= 3 and len(set(ds)) == 1:
        size *= 1.5           # they never move on days: they care
    return sign * size


AMBIGUOUS_PAD_SHARE = 0.25   # sign unknown: give the rival its days only if the safety padding is < 25 % of pie
COST_DAYS_GOODWILL = 0.10    # days cost us: match the rival's own lowest days only while that costs < 10 % of pie


def _days_when_they_cost(v: DuelView, w: float, pie: float | None) -> int:
    """Days cost us |w| per day: offer 0. The old joint-weight rule guessed the rival's weight from our own
    |w| and the days it asks for, so a rival that simply asked 10 days got 10 days at our cost (sim duel
    1168: 23 of 34 P burned, no deal). A rival's day count is not evidence that it pays for days, and every
    price we ask already charges the days we give (utility-based asks), so days only go out as cheap
    goodwill: the rival's own lowest days when that costs < COST_DAYS_GOODWILL of the pie."""
    rival_days = [o.days for o in v.rival_offers() if o.days is not None]
    if rival_days and pie is not None:
        low = min(rival_days)
        if 0 < low and abs(w) * low < COST_DAYS_GOODWILL * pie:
            return low
    return 0


DAY_PRIOR_RATIO = 1.25   # the rival must care this much more than we do: the prior is a median of other duels
DAY_PRIOR_GAP = 0.5      # and by at least this many points a day


def rival_cares_more(v: DuelView) -> bool:
    """True when a delivery day is worth clearly more to the rival than to us (opponent.rival_day_prior).
    The seller gains with every later day and the buyer loses, so the day belongs to whoever has the larger
    weight: Duels II left about 7.6 points of pie per deal on the table by always asking for our own day."""
    r, w = v.rival_w_prior, abs(days_weight(v))
    return r is not None and not v.days_ambiguous and r >= DAY_PRIOR_RATIO * w and r - w >= DAY_PRIOR_GAP


def joint_days_bonus(v: DuelView, days: int | None) -> float:
    """Pie added by giving the rival `days` that cost us less than they are worth to it."""
    if not days or not rival_cares_more(v) or days_weight(v) >= 0:
        return 0.0
    return (v.rival_w_prior - abs(days_weight(v))) * days


def choose_days(v: DuelView, pie: float | None = None) -> int | None:
    if not v.uses_days:
        return None
    w = days_weight(v)
    if rival_cares_more(v):
        # Give the day to whoever cares more and charge it in the price (utility-based asks do that):
        # days cost us -> the rival's gain is larger, so deliver late; days pay us -> its loss is larger,
        # so deliver at once and ask for more money instead.
        return DAYS_MAX if w < 0 else 0
    if v.days_ambiguous:
        # We do not know if days help or hurt us, so every offer is priced safe under both readings: the
        # padding is |w| x days. Give the rival its own last days only while that padding is small.
        last = next((o.days for o in reversed(v.rival_offers()) if o.days is not None), None)
        if last is not None and pie is not None and abs(w) * last < AMBIGUOUS_PAD_SHARE * pie:
            return last
        return 0
    if w < 0:
        return _days_when_they_cost(v, w, pie)
    wr = rival_days_weight(v, w)
    joint = w + wr
    if abs(joint) < 1e-9:
        last = next((o.days for o in reversed(v.rival_offers()) if o.days is not None), None)
        if last is not None:
            return last
        return DAYS_MAX if w > 0 else 0 if w < 0 else DAYS_MAX // 2
    return DAYS_MAX if joint > 0 else 0


# --- economics ----------------------------------------------------------------------------------------
def economics(v: DuelView, opp: dict, ask: tuple[int, int | None] | None = None) -> dict:
    """Points now vs after one more round, for the prompt and for the expected points we attach."""
    out: dict = {"rounds_now": v.rounds, "decay": v.decay, "ticks_left": v.ticks_left,
                 "rounds_if_we_send": v.rounds_if_we_send()}
    r = v.rival_offer
    if r is not None:
        u = v.utility(r.price, r.days)
        out["accept_now"] = {"price": r.price, "days": r.days, "margin": round(u, 1),
                             "points": round(points(u, v.decay, v.rounds), 2),
                             "inside_limit": v.surplus(r.price) >= MIN_SURPLUS}
        if v.days_ambiguous:
            out["accept_now"]["margin_if_days_sign_is_reversed"] = round(v.safe_utility(r.price, r.days), 1)
            out["accept_now"]["acceptable"] = v.safe_utility(r.price, r.days) >= MIN_SURPLUS
    if ask is not None:
        u = v.utility(*ask)
        out["our_ask_if_accepted"] = {"price": ask[0], "days": ask[1], "margin": round(u, 1),
                                      "points": round(points(u, v.decay, v.rounds_if_we_send()), 2)}
    nxt = opp.get("next_rival_surplus_estimate")
    if nxt is not None:
        out["their_next_offer_if_we_counter"] = {
            "margin_est": nxt, "points_est": round(points(nxt, v.decay, v.rounds + 1), 2)}
    pie = opp.get("pie_estimate") or 0
    out["break_even_after_one_round"] = (
        round(out["accept_now"]["margin"] / (1 - v.decay), 1) if "accept_now" in out else None)
    out["pie_estimate"] = pie
    return out


# --- the fallback ---------------------------------------------------------------------------------------
def _target_share(v: DuelView, p=PARAMS) -> float:
    T = max(2, v.total_ticks)
    x = min(1.0, v.elapsed / (T - 1))
    top = p.get("OPEN_BUYER", p["OPEN"]) if v.role == "buyer" else p["OPEN"]
    return top - (top - p["END"]) * (x ** p["BETA"])


def _their_steps(v: DuelView) -> list[float]:
    """Their concessions so far, as the change of our surplus between consecutive rival offers."""
    s = [v.utility(o.price, o.days) for o in v.rival_offers()]
    return [b - a for a, b in zip(s, s[1:])]


def expected_step(v: DuelView, opp: dict, p=PARAMS) -> float:
    """How much better we expect their next offer to be (0 for a rival that stopped moving)."""
    steps = _their_steps(v)
    if steps:
        if steps[-1] <= 0.5:                       # they repeated their price: that is their floor (for now)
            return 0.0
        recent = [x for x in steps[-2:] if x > 0]
        return sum(recent) / len(recent) * (REMAINING_DECAY if len(steps) >= 2 and steps[-1] < steps[-2] else 1.0)
    if opp.get("type") == "fixed":
        return 0.0
    return float(opp.get("avg_step") or p["STEP_PRIOR"])


REMAINING_DECAY = 0.8


def _probed(v: DuelView) -> bool:
    """We already left one of their offers unanswered for a tick (so we know if they move alone)."""
    priced = [m for m in v.messages if m.price is not None]
    for a, b in zip(priced, priced[1:]):
        if not a.ours and b.ours and b.tick > a.tick:
            return True
        if not a.ours and not b.ours:
            return True
    return False


def plan(v: DuelView, opp: dict, p=PARAMS) -> Move:
    """One tick of one duel, decided by code only (instant).

    Optimal stopping on the rival's offers: keep going only while their next concession is worth more
    than the decay of one more round (q x (u + step) > u). Against a rival who moves only when answered we
    answer with small concessions (they come to us); against one who moves on their own ("free steps")
    we wait; against a silent rival a time schedule lowers our ask to a near-limit last offer, which costs
    no decay because rounds only count when both sides have offered."""
    pie = max(2.0, float(opp.get("pie_estimate") or 2.0))
    w = days_weight(v)
    d_off = choose_days(v, pie)
    last_ticks = last_ticks_for(opp, p)
    days_bonus = (w * d_off) if (v.uses_days and d_off is not None and not v.days_ambiguous) else 0.0
    pie_u = pie + max(0.0, days_bonus) + joint_days_bonus(v, d_off)
    q = 1.0 - v.decay
    share = _target_share(v, p)
    u_target = max(MIN_SURPLUS, share * pie_u)

    our_prev = v.our_offer or (v.our_offers()[-1] if v.our_offers() else None)
    u_prev = v.utility(our_prev.price, our_prev.days) if our_prev else None

    r = v.rival_offer or (v.rival_offers()[-1] if v.rival_offers() else None)
    usable = r is not None and v.surplus(r.price) >= MIN_SURPLUS and (not v.uses_days or r.days is not None) \
        and v.safe_utility(r.price, r.days) >= MIN_SURPLUS
    step = expected_step(v, opp, p) if r is not None else None
    if usable:
        u_r = v.safe_utility(r.price, r.days)
        why = None
        if u_r >= q * (u_r + step):
            why = f"their next step (~{step:.1f}) is worth less than a round of decay on {u_r:.0f}"
        elif u_prev is not None and u_r >= u_prev * q:
            why = f"rival gives {u_r:.0f}, our own ask {u_prev:.0f} is worth no more after a round"
        elif u_r >= p["ACCEPT_SHARE"] * pie_u:
            why = f"rival gives {u_r:.0f} >= {p['ACCEPT_SHARE']:.0%} of pie ~{pie_u:.0f}"
        elif v.ticks_left <= last_ticks:
            why = f"{v.ticks_left} ticks left: take {u_r:.0f}"
        elif u_r >= u_target:
            why = f"rival gives {u_r:.0f} >= this tick's target {u_target:.0f}"
        if why:
            return Move("accept", r.price, r.days, reason=why,
                        expected_points=round(points(u_r, v.decay, v.rounds), 2))
    else:
        u_r = None

    free = opp.get("free_steps_here", 0) > 0 or (opp.get("history") or {}).get("free_step_rate", 0) >= 0.5
    if usable and u_prev is not None and opp.get("tough_now") and v.unanswered_rival_offer():
        # Tough rival (< 2 P per offer after 3 offers) whose offer is inside our limit: haggling only buys
        # decay. Take their offer when the midpoint is not worth a round, else jump to the midpoint.
        u_mid = (u_prev + u_r) / 2.0
        if u_r >= q * u_mid * p["TOUGH_TAKE"]:
            return Move("accept", r.price, r.days, reason=f"tough rival (steps < 2 P): take {u_r:.0f} now",
                        expected_points=round(points(u_r, v.decay, v.rounds), 2))
        if u_mid < u_prev - 1:
            price = price_for(v.role, v.limit, max(MIN_SURPLUS, u_mid - days_bonus))
            return Move("offer", price, d_off, reason=f"tough rival (steps < 2 P): jump to the midpoint {u_mid:.0f}")
    if r is not None and u_prev is not None and v.unanswered_rival_offer():
        if free and step and v.ticks_left > last_ticks + 2:
            return Move("wait", reason=f"rival concedes on its own (~{step:.1f}/tick): let them come for free")
        if not free and not _probed(v) and r.tick == v.tick and v.ticks_left > p["PROBE_UNTIL"]:
            return Move("wait", reason="probe: one tick of silence shows whether they move without us (free)")
        # They answered us: concede a little so they keep stepping, a lot only when time runs out.
        floor_u = max(u_r if u_r is not None else MIN_SURPLUS, MIN_SURPLUS)
        conc = max(1.0, p["MIRROR"] * (step or 0.0))
        u_ask = min(u_prev - conc, max(u_target, floor_u + 1))
    elif u_prev is None:
        u_ask = u_target
    else:
        u_ask = min(u_prev, u_target)      # waiting on them: only the time schedule moves us
    if u_r is not None:
        u_ask = max(u_ask, u_r + 1)

    s_ask = u_ask - days_bonus
    price = price_for(v.role, v.limit, s_ask)
    return Move("offer", price, d_off,
                reason=f"ask {v.utility(price, d_off):.0f} of pie ~{pie_u:.0f} ({share:.0%} schedule)")


def final_u(v: DuelView, opp: dict, p=PARAMS) -> float:
    """The margin this tick's finish step keeps: a share of the pie, never below MIN_SURPLUS (so never
    past our limit)."""
    pie = max(2.0, float(opp.get("pie_estimate") or 2.0))
    steps = p["FINAL_STEPS"]
    share = steps.get(int(v.ticks_left), steps[min(steps)] if v.ticks_left < min(steps) else steps[max(steps)])
    return max(float(MIN_SURPLUS), share * pie)


def hold_rule(v: DuelView, mv: Move, opp: dict, p=PARAMS) -> tuple[Move, list[str]]:
    """Never bid against ourselves. While the rival owes us an answer (it has said nothing since our last
    priced offer, or nothing at all), our standing offer stays and we send NOTHING: no repeated messages,
    no lower prices tick after tick. We speak again when the rival moves (normal haggling), or in the last
    FINAL_TICKS ticks with a short finish: one step per tick down the FINAL_STEPS shares of the pie, the
    prices a silent rival has accepted before. Applies to Claude's moves and to the code fallback,
    price-only duels and Duels II alike."""
    if mv.action == "accept" or (v.our_offer is None and not v.our_offers()):
        return mv, []                               # accept / our opening offer: nothing to hold
    if v.unanswered_rival_offer():
        return mv, []                               # the rival moved: answering is the normal game
    prev = v.our_offer or v.our_offers()[-1]
    u_prev = v.utility(prev.price, prev.days)
    keep = dict(source=mv.source, econ=mv.econ, lesson_ids=list(mv.lesson_ids))
    if v.ticks_left > p["FINAL_TICKS"]:
        if mv.action == "wait":
            return mv, []
        return Move("wait", reason="hold: the rival has not answered our offer; no message, no concession",
                    **keep), ["hold: rival silent since our offer"]
    floor = final_u(v, opp, p)
    if u_prev <= floor + 0.5:
        return Move("wait", reason="hold: this tick's finish step is already on the table", **keep), \
            ["hold: finish step already sent"]
    days = (mv.days if mv.action == "offer" else None)
    if v.uses_days and days is None:
        days = prev.days if prev.days is not None else 0
    price = price_for(v.role, v.limit, max(float(MIN_SURPLUS), floor - u_days(v, days)))
    if v.surplus(price) < MIN_SURPLUS:
        price = price_for(v.role, v.limit, MIN_SURPLUS)
    if price == prev.price and days == prev.days:
        return Move("wait", reason="hold: this tick's finish step is already on the table", **keep), []
    d = f" with delivery in {days} days" if v.uses_days and days is not None else ""
    last = v.ticks_left <= 1
    text = (f"My final offer: {price} P{d}. Happy to close now." if last
            else f"I can do {price} P{d} to close today.")
    return Move("offer", price, days, text=text,
                reason=f"finish vs a silent rival: {v.ticks_left} ticks left, keep {floor:.0f} of the pie",
                expected_points=round(points(v.utility(price, days), v.decay, v.rounds_if_we_send()), 2),
                **keep), [f"finish step to margin {floor:.0f}"]


def rival_unchanged(v: DuelView) -> bool:
    """The rival answered our last priced offer with the very terms it already had on the table."""
    ro = v.rival_offers()
    last_ours = max((m.tick for m in v.messages if m.ours and m.price is not None), default=None)
    if len(ro) < 2 or last_ours is None:
        return False
    before = [o for o in ro if o.tick is not None and o.tick <= last_ours]
    return bool(before) and (ro[-1].price, ro[-1].days) == (before[-1].price, before[-1].days)


def hold_vs_unmoved_rival(v: DuelView, mv: Move, p=PARAMS) -> tuple[Move, list[str]]:
    """Claude's moves too: a rival that repeats its exact terms after our step has not paid for another
    one. A new offer from us would only add a round of decay and bid against ourselves (duel 2420: the
    rival sat on one price five times while we walked from 18 to 1). Wait instead; accepting stays free,
    and the last FINAL_TICKS ticks are left to the normal finish."""
    if mv.action != "offer" or v.ticks_left <= p["FINAL_TICKS"] or not v.our_offers():
        return mv, []
    if not rival_unchanged(v):
        return mv, []
    return Move("wait", reason="hold: the rival repeated its price since our last offer; no new step",
                source=mv.source, econ=mv.econ, lesson_ids=list(mv.lesson_ids)), ["hold: rival price unchanged"]


def hold_if_rival_unchanged(v: DuelView, mv: Move, p=PARAMS) -> tuple[Move, list[str]]:
    """Code fallback only: if the rival's price has not changed since our last offer (it repeated the same
    terms), stepping again is bidding against ourselves. Hold until it moves or the last ticks."""
    if mv.action != "offer" or v.ticks_left <= p["FINAL_TICKS"] or not v.our_offers():
        return mv, []
    ro = v.rival_offers()
    last_ours = max((m.tick for m in v.messages if m.ours and m.price is not None), default=None)
    if len(ro) < 2 or last_ours is None:
        return mv, []
    if rival_unchanged(v):
        return Move("wait", reason="hold: the rival repeated its price since our last offer; no new step",
                    source=mv.source), ["hold: rival price unchanged"]
    # the rival moved: concede at most half of its last move (min 1 P), never the whole time schedule
    steps = _their_steps(v)
    prev = v.our_offer or v.our_offers()[-1]
    u_prev = v.utility(prev.price, prev.days)
    cap = max(1.0, 0.5 * max(0.0, steps[-1])) if steps else None
    if cap is not None:
        try:
            u = v.utility(float(mv.price), mv.days)
        except (TypeError, ValueError):
            return mv, []
        if u < u_prev - cap:
            price = price_for(v.role, v.limit, max(float(MIN_SURPLUS), u_prev - cap - u_days(v, mv.days)))
            d = f" with delivery in {mv.days} days" if v.uses_days and mv.days is not None else ""
            return Move("offer", price, mv.days, text=f"Meeting you closer: {price} P{d}.",
                        reason=f"{mv.reason} [step capped at half the rival's move: {cap:.0f} P]",
                        source=mv.source), [f"step capped to {cap:.0f} P"]
    return mv, []


def u_days(v: DuelView, days) -> float:
    """The part of our utility that comes from the delivery days (0 in price-only duels)."""
    if not v.uses_days or days is None:
        return 0.0
    return v.utility(v.limit, days) - v.utility(v.limit, 0)


def last_ticks_for(opp: dict, p=PARAMS) -> int:
    """Take-anything window: one accept per tick for the whole team, so with N duels waiting to accept the
    last one only gets its turn N ticks later (opp["accept_queue"], set by the domain each tick)."""
    return max(int(p["LAST_TICKS"]), min(6, int(opp.get("accept_queue") or 0)))


# --- the guard -------------------------------------------------------------------------------------------
def guard(v: DuelView, mv: Move, fallback: Move | None = None) -> tuple[Move, list[str]]:
    """Make any move safe: inside the limit, days 0-10, accept only a real rival offer, never resend the
    same price/days, text that carries the exact price. Returns the safe move and the notes."""
    notes: list[str] = []
    if mv.action not in ("accept", "offer", "wait"):
        notes.append(f"unknown action {mv.action!r}")
        return (fallback or Move("wait", reason="invalid move")), notes

    if mv.action == "accept":
        r = v.rival_offer
        if r is None:
            notes.append("accept without a rival offer")
            return (guard(v, fallback)[0] if fallback and fallback.action != "accept" else Move("wait")), notes
        if v.surplus(r.price) < MIN_SURPLUS:
            notes.append(f"rival offer {r.price} is outside our limit")
            return (guard(v, fallback)[0] if fallback and fallback.action != "accept" else Move("wait")), notes
        if v.uses_days and r.days is None:
            notes.append("rival offer has no days")
            return Move("wait"), notes
        if v.safe_utility(r.price, r.days) < MIN_SURPLUS:
            notes.append("rival package is worth less than nothing to us once days count"
                         + (" (worse sign reading)" if v.days_ambiguous else ""))
            return (guard(v, fallback)[0] if fallback and fallback.action != "accept" else Move("wait")), notes
        mv.price, mv.days = r.price, r.days
        mv.expected_points = round(points(v.utility(r.price, r.days), v.decay, v.rounds), 2)
        return mv, notes

    if mv.action == "wait":
        return mv, notes

    # offer
    try:
        price = int(round(float(mv.price)))
    except (TypeError, ValueError):
        notes.append("offer without a price")
        return (fallback or Move("wait")), notes
    if v.surplus(price) < MIN_SURPLUS:
        notes.append(f"price {price} outside limit {v.limit}: clamped")
        price = price_for(v.role, v.limit, MIN_SURPLUS)
    days = None
    if v.uses_days:
        try:
            days = int(mv.days) if mv.days is not None else choose_days(v)
        except (TypeError, ValueError):
            days = choose_days(v)
        if days is None:
            days = 0
        days = max(0, min(DAYS_MAX, days))
    if v.days_ambiguous and days is not None and v.safe_utility(price, days) < MIN_SURPLUS:
        notes.append("days sign ambiguous: price raised so the offer is safe under both readings")
        price = price_for(v.role, v.limit, MIN_SURPLUS + abs(v.days_w) * days)
    mv.price, mv.days = price, days

    # If the rival already offers at least this, accepting is strictly better than asking for less.
    r = v.rival_offer
    if r is not None and v.surplus(r.price) >= MIN_SURPLUS and (not v.uses_days or r.days is not None) \
            and v.safe_utility(r.price, r.days) >= MIN_SURPLUS:
        if v.utility(r.price, r.days) >= v.utility(price, days):
            notes.append("rival already offers at least our ask: accept instead")
            return guard(v, Move("accept", reason=mv.reason + " (rival already there)", source=mv.source))[0], notes

    # Only send if something changes.
    standing = v.our_offer or (v.our_offers()[-1] if v.our_offers() else None)
    if standing is not None and standing.price == price and (not v.uses_days or standing.days == days):
        if not (v.ticks_left <= 1 and v.unanswered_rival_offer()):
            notes.append("same offer already standing: wait")
            return Move("wait", reason="our offer stands", source=mv.source), notes

    text = (mv.text or "").replace("\n", " ").strip()
    if not text or not re.search(rf"(?<!\d){price}(?!\d)", text) or len(text) > 280 or \
            re.findall(r"\d+", text).count(str(price)) == 0 or _other_prices(text, price, days):
        if text:
            notes.append("text did not carry the exact price: template")
        text = template_text(v, price, days)
    mv.text = text
    # Code-side estimate: the points if the rival takes this offer (Claude's own guess goes in the reason).
    mv.expected_points = round(points(v.utility(price, days), v.decay, v.rounds_if_we_send()), 2)
    return mv, notes


def _other_prices(text: str, price: int, days: int | None) -> bool:
    """True when the text names a different P amount than the structured price (would confuse them)."""
    for m in re.finditer(r"(\d+)\s*(P\b|primas)", text):
        if int(m.group(1)) != price:
            return True
    return False


# --- how much weight Claude's move gets (control duel_claude_mode) ------------------------------------------
CLAUDE_MODES = ("bounded", "full", "code")
BOUND_TOL_P = 2.0            # bounded: Claude may ask up to max(2 P, 10 % of the pie) less than code
BOUND_TOL_SHARE = 0.10
BOUND_ECON_PTS = 1.0         # bounded: Claude's wait/accept must agree with the economics table within 1 pt


def claude_mode(ctx) -> str:
    ctl = (getattr(ctx, "control", None) if ctx is not None else None) or {}
    m = str(ctl.get("duel_claude_mode") or "bounded").lower() if isinstance(ctl, dict) else "bounded"
    return m if m in CLAUDE_MODES else "bounded"


def claude_full_weight(v: DuelView, opp: dict) -> bool:
    """Where code has no better model than Claude: Duels II packages and rivals we cannot classify."""
    return v.uses_days or (opp.get("type") or "unknown") == "unknown"


def _code_ask_u(v: DuelView, base: Move) -> float | None:
    if base.action == "offer" and base.price is not None:
        return v.utility(base.price, base.days)
    standing = v.our_offer or (v.our_offers()[-1] if v.our_offers() else None)
    if standing is not None:
        return v.utility(standing.price, standing.days)
    if base.action == "accept" and v.rival_offer is not None:
        return v.utility(v.rival_offer.price, v.rival_offer.days)
    return None


def bound_claude(v: DuelView, mv: Move, base: Move, opp: dict, econ: dict | None,
                 mode: str = "bounded") -> tuple[Move, list[str]]:
    """Claude proposes, code bounds (mode "bounded"): its price only down to code's ask minus
    max(2 P, 10 % of the pie); its wait/accept only when the economics table agrees within 1 pt. Full weight
    on Duels II, unknown archetypes and the text. "full" returns Claude's move as is (the guard runs after)."""
    if mode != "bounded" or claude_full_weight(v, opp):
        return mv, []
    econ = econ or {}
    acc = (econ.get("accept_now") or {}).get("points")
    cont = (econ.get("their_next_offer_if_we_counter") or {}).get("points_est")
    pie = float(opp.get("pie_estimate") or 0.0)
    if mv.action == "offer":
        ref = _code_ask_u(v, base)
        try:
            u = v.utility(float(mv.price), mv.days)
        except (TypeError, ValueError):
            return mv, []
        if ref is None:
            return mv, []
        floor_u = ref - max(BOUND_TOL_P, BOUND_TOL_SHARE * pie)
        if u < floor_u:
            price = price_for(v.role, v.limit, max(float(MIN_SURPLUS), floor_u))
            note = f"bounded: claude asked {u:.0f}, code {ref:.0f}: raised to {floor_u:.0f} (price {price})"
            return Move("offer", price, mv.days, text=mv.text, reason=f"{mv.reason} [{note}]", source=mv.source,
                        econ=mv.econ, lesson_ids=list(mv.lesson_ids)), [note]
        return mv, []
    if mv.action == "accept":
        if base.action == "accept" or acc is None or cont is None or acc >= cont - BOUND_ECON_PTS:
            return mv, []
        note = f"bounded: accept now {acc:.1f} pts < next offer ~{cont:.1f}: code's move"
        return base, [note]
    if mv.action == "wait":
        if base.action == "accept":
            if acc is not None and cont is not None and cont >= acc - BOUND_ECON_PTS:
                return mv, []
            note = f"bounded: claude waits but accepting now ({acc} pts) beats the next offer ({cont}): accept"
            return base, [note]
        if base.action == "offer" and v.ticks_left <= last_ticks_for(opp):
            return base, [f"bounded: {v.ticks_left} ticks left, code's offer instead of waiting"]
    return mv, []
