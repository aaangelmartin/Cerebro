"""Simulate: does a lesson's policy do at least as well as the baseline against the simulated Bazaar?

Uses the calibrated behaviour models in ``bazaar.sim.models`` (no HTTP, seeded, fast). Only lessons whose
prediction maps to a policy knob are simulated; the rest return ``{"applicable": False}``, which the gate
treats as neutral.

- duels: baseline = open wide, concede linearly, AC_next acceptance (Friday's operator, roughly);
  the lesson changes one knob (close by round k, accept a good first offer, take a fixed rival, offer
  mute rivals a fair split early). Score = duel points (margin * (1 - decay) ** rounds; no deal = 0).
- dealers: baseline = bid 40% of the dealer's price, step 22% of the gap, take a final; the lesson adds a
  walk-away / take-it threshold from its price range. Score = ladder capture, 0 when no deal.
"""
from __future__ import annotations

import random
import statistics as st
from typing import Any

TOL = 0.25            # points (duels) or capture*10 (dealers) the lesson may lose and still be "not worse"
EPISODES = 300


def _duel_episode(rng: random.Random, knobs: dict, kind_force: str | None = None) -> float:
    from bazaar.sim.models import DuelRival, duel_points, make_duel_scenario
    sc = make_duel_scenario(rng)
    kind = kind_force or sc["kind"]
    role, lim = sc["our_role"], sc["our_limit"]
    decay = knobs.get("decay", 0.06)
    rival = DuelRival(kind, role, lim, sc["rival_limit"], rng, decay=decay)
    sign = 1 if role == "seller" else -1          # seller wants higher prices
    ticks = 12
    open_m = 0.40 * lim                           # our opening margin
    end_m = knobs.get("end_margin_frac", 0.08) * lim
    close_by = knobs.get("close_by", ticks)

    def margin(p):
        return sign * (p - lim)

    def planned(r):
        frac = min(1.0, r / max(1, min(close_by, ticks) - 1))
        return open_m + (end_m - open_m) * frac

    offer = rival.opening()
    seen: list[int] = []
    for r in range(ticks):
        if offer is not None and offer.get("price") is not None:
            p = offer["price"]
            seen.append(p)
            m = margin(p)
            take = False
            if m > 0:
                if m >= planned(r) * (1 - decay) ** 2:
                    take = True                                                    # AC_next
                if knobs.get("accept_first_frac") is not None and len(seen) == 1 and m >= knobs["accept_first_frac"] * lim:
                    take = True
                if knobs.get("take_fixed") and len(seen) >= 2 and seen[-1] == seen[-2]:
                    take = True
                if r >= close_by:
                    take = True
                if r >= ticks - 2:
                    take = True
            if take:
                return duel_points(role, lim, p, r, decay)
        target = planned(r)
        if kind == "mute" and knobs.get("mute_fair_by") is not None and r >= knobs["mute_fair_by"]:
            target = min(target, knobs.get("mute_margin_frac", 0.15) * lim)
        our_p = round(lim + sign * target)
        res = rival.respond(our_p)
        if res["accept"]:
            return duel_points(role, lim, our_p, r + 1, decay)
        offer = {"price": res["price"]} if res.get("price") is not None else None
    return 0.0


def _dealer_episode(rng: random.Random, dealer: str, side: str, rarity: str, knobs: dict) -> float:
    from bazaar.sim.models import DealerThread
    t = DealerThread(dealer, side, rarity, rng)
    team_buys = side == "sell"
    ours = round(t.price * 0.4) if team_buys else round(t.price * 2.2)
    walk = knobs.get("take_at")                   # take the dealer's price once it is this good
    cap = knobs.get("never_past")                 # never bid past this
    for _ in range(14):
        if walk is not None and ((team_buys and t.price <= walk) or (not team_buys and t.price >= walk)):
            t.accept_standing()
            break
        if t.final:
            t.accept_standing()
            break
        gap = t.price - ours
        ours = ours + max(1, round(gap * 0.22)) if team_buys else ours - max(1, round(-gap * 0.22))
        if cap is not None:
            ours = min(ours, cap) if team_buys else max(ours, cap)
        res = t.respond(ours)
        if res["closed"]:
            break
    return t.capture()


def knobs_for(pred: dict) -> tuple[str, dict] | None:
    k = pred.get("kind")
    if k == "duel_fast":
        return "duel", {"close_by": int(pred.get("max_rounds", 3))}
    if k == "duel_accept_first":
        return "duel", {"accept_first_frac": float(pred.get("min_margin_frac", 0.15))}
    if k == "rival_rate" and pred.get("rival_kind") == "fixed" and pred.get("outcome") == "deal":
        return "duel", {"take_fixed": True}
    if k == "rival_rate" and pred.get("rival_kind") == "mute":
        return "duel", {"mute_fair_by": 2, "mute_margin_frac": 0.15}
    if k == "dealer_price" and pred.get("stage") in ("final", "deal", "last"):
        lo, hi = float(pred["lo"]), float(pred["hi"])
        side = pred.get("side")
        # Hold out for the good end of the range, never concede past the bad end.
        knobs = {"take_at": lo, "never_past": hi} if side == "sell" else {"take_at": hi, "never_past": lo}
        return "dealer", {**knobs, "dealer": pred.get("dealer"), "side": side, "item": pred.get("item")}
    return None


def simulate(pred: dict | None, episodes: int = EPISODES, seed: int = 7) -> dict[str, Any]:
    if not isinstance(pred, dict):
        return {"applicable": False}
    m = knobs_for(pred)
    if m is None:
        return {"applicable": False}
    domain, knobs = m
    base, test = [], []
    try:
        if domain == "duel":
            force = pred.get("rival_kind") if pred.get("kind") == "rival_rate" else None
            for i in range(episodes):
                base.append(_duel_episode(random.Random(seed * 1000 + i), {}, force))
                test.append(_duel_episode(random.Random(seed * 1000 + i), knobs, force))
            scale = 1.0
        else:
            item = knobs.pop("item") or "uncommon"
            dealer, side = knobs.pop("dealer"), knobs.pop("side")
            for i in range(episodes):
                base.append(_dealer_episode(random.Random(seed * 1000 + i), dealer, side, item, {}))
                test.append(_dealer_episode(random.Random(seed * 1000 + i), dealer, side, item, knobs))
            scale = 10.0
    except (ValueError, KeyError, ImportError) as e:
        return {"applicable": False, "note": repr(e)[:160]}
    b, t = st.mean(base), st.mean(test)
    delta = round((t - b) * scale, 3)
    return {"applicable": True, "domain": domain, "episodes": episodes, "baseline": round(b, 3),
            "lesson": round(t, 3), "delta": delta, "not_worse": delta >= -TOL}
