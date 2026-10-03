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


def pending(sit, control, values=None) -> dict[str, int]:
    """Goal cards we do not hold yet, with their max price (automatic goals, then the manual ones on top)."""
    goals = {**auto_goals(values), **goal_buys(control)}
    if not goals:
        return {}
    held = {str(a.get("ref")).upper() for a in (_g(sit, "me") or {}).get("assets") or []
            if isinstance(a, dict) and a.get("kind", "card") == "card"}
    return {r: p for r, p in goals.items() if r not in held}
