"""Goal buys: cards the bot saves cash for.

The bot finds them by itself: a page with only one or two cards missing, where a missing card is worth a lot to
us (finishing the page also adds the page bonus), becomes a goal, priced a little below its value to us.
control["goal_buys"] = {ref: max price} can add or override goals by hand.

While a goal card is still missing, the bot stops spending cash on anything else (dealer buys, packs and
market bids for other cards), cancels its other cash bids so the cash is free, keeps selling what it values
little, and buys the goal card up to its max price. When every goal card is held, normal play resumes.
"""
from __future__ import annotations


def _g(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def goal_buys(control) -> dict[str, int]:
    out = {}
    for ref, price in ((control or {}).get("goal_buys") or {}).items():
        try:
            out[str(ref).upper()] = int(price)
        except (TypeError, ValueError):
            continue
    return out


AUTO_MAX_MISSING = 2        # a page this close to complete is worth finishing
AUTO_MIN_VALUE = 30.0       # only cards worth this much to us justify saving cash
AUTO_MARGIN_FRAC = 0.03     # max price = value - max(1, 3 %): every buy still creates value


def auto_goals(values) -> dict[str, int]:
    """Missing cards of nearly complete pages, worth a lot to us, with the max price we would pay."""
    if values is None:
        return {}
    try:
        by_set: dict[str, list[str]] = {}
        cards = getattr(values, "cards", {}) or {}
        for ref in values.released_refs():
            if (cards.get(ref) or {}).get("page") is False:
                continue                          # epic/legendary extras: not part of the page
            by_set.setdefault(values.set_of(ref), []).append(ref)
        out = {}
        for refs in by_set.values():
            missing = [r for r in refs if values.count(r) == 0]
            if not missing or len(missing) > AUTO_MAX_MISSING or len(refs) - len(missing) < 5:
                continue
            for r in missing:
                v = float(values.next_copy(r))
                if v >= AUTO_MIN_VALUE:
                    out[r] = int(v - max(1.0, AUTO_MARGIN_FRAC * v))
        return out
    except Exception:  # noqa: BLE001 - a goal is a hint, never a reason to crash a tick
        return {}


def avoid_sets(control) -> set[str]:
    """Sets we do not buy (control.avoid_buy_sets; the brain's choice is merged in by brain.strategy.overlay)."""
    return {str(x).upper()[:3] for x in (control or {}).get("avoid_buy_sets") or [] if str(x).strip()}


def avoided(ref, control) -> bool:
    sets = avoid_sets(control)
    return bool(sets) and str(ref or "").upper()[:3] in sets


def strategy_goals(values=None) -> dict[str, int]:
    """The strategist's goal cards, each capped one point below its value to us (never pay above value)."""
    try:
        from bazaar.brain.strategy import goal_buys as _sg
        goals = _sg()
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for ref, p in goals.items():
        if values is not None and p > 0:
            try:
                p = min(p, int(values.next_copy(ref)) - 1)
            except Exception:  # noqa: BLE001
                pass
        out[ref] = p
    return out


def pending(sit, control, values=None) -> dict[str, int]:
    """Goal cards we do not hold yet, with their max price: automatic goals < the strategist's < the
    operator's (control.goal_buys). A price of 0 or less drops the goal."""
    goals = {**auto_goals(values), **strategy_goals(values), **goal_buys(control)}
    goals = {r: p for r, p in goals.items() if p > 0 and not avoided(r, control)}
    if not goals:
        return {}
    held = {str(a.get("ref")).upper() for a in (_g(sit, "me") or {}).get("assets") or []
            if isinstance(a, dict) and a.get("kind", "card") == "card"}
    return {r: p for r, p in goals.items() if r not in held}
