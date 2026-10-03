"""Arbiter: from every domain's proposals, pick what this tick may really send.

- At most `accepts_per_team_per_tick` offer accepts (left in budget), by priority. Duel accepts have their
  own budget (the game limits them separately), so a duel accept never costs a trade its slot.
- One message per conversation per tick, and none where we already spoke this tick.
- Listing cap per tick and open offers/threads caps; one open thread per dealer.
- The same card is never promised twice in one tick.
- An accept that loses the single slot is not silence: if it carries `params.fallback_message` (duels: an
  offer of exactly the rival's standing terms), that message is considered in its place, under the same
  one-message-per-conversation rule.
`budget` is ctx.budget (core.context.Budget.for_tick). Returns (chosen, dropped[(action, why)]).
"""
from __future__ import annotations

from .rails import conv_key, flows
from .context import duel_accept_cap
from .types import ACCEPT_KINDS, MESSAGE_KINDS, Action

DOMAIN_RANK = {"duels": 0, "market": 1, "broker": 1, "dealers": 2, "lab": 3}


def _get(obj, name, default=None):
    if obj is None:
        return default
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _order(a: Action) -> tuple:
    """Accepts first, by priority alone; the rest by domain rank, then priority.

    Accept priority scale (set by the domains): urgent duel accept (<= 2 ticks left) >= 150 > dealer final offer 140
    (it walks away if not taken) > other duel accepts 100-130 > other accepts < 100. Team decision 2026-10-03:
    duels first, except that a dealer's final offer beats a duel accept that can still wait."""
    if a.kind in ACCEPT_KINDS:
        p = float(a.priority or 0)
        if a.kind == "duel_accept":
            p = max(p, 100.0)                                 # a duel accept never ranks below the 100 floor
        return (0, -p, a.created)
    return (1, DOMAIN_RANK.get(a.domain, 9), -float(a.priority or 0), a.created)


def _sig(a: Action) -> str:
    import json
    return a.kind + json.dumps(a.params, sort_keys=True, default=str)


ALT_KIND = {"duel_accept": "duel_message"}


def alternative(a: Action) -> Action | None:
    """The message an accept falls back to when it loses the tick's single accept (None if it has none)."""
    fm = (a.params or {}).get("fallback_message")
    kind = ALT_KIND.get(a.kind)
    if not isinstance(fm, dict) or kind is None or fm.get("price") is None:
        return None
    return Action(kind=kind, params=dict(fm), domain=a.domain, source=a.source, lesson_ids=list(a.lesson_ids),
                  priority=float(a.priority or 0), big=False,
                  reason=f"accept lost the single slot: offer their own terms instead ({a.reason})"[:300],
                  expected={**(a.expected or {}), "alt_for": a.id})


def select(actions: list[Action], sit, budget: dict | None) -> tuple[list[Action], list[tuple[Action, str]]]:
    budget = budget or {}
    lim = {**(budget.get("limits") or {}), **(_get(sit, "limits") or {})}
    accepts_left = budget.get("accepts_left")
    if accepts_left is None:
        accepts_left = int(lim.get("accepts_per_team_per_tick", 1)) - int(budget.get("accepts_used", 0))
    duel_accepts_left = budget.get("duel_accepts_left")
    if duel_accepts_left is None:
        duel_accepts_left = duel_accept_cap(lim) - int(budget.get("duel_accepts_used", 0))
    accept_cap, duel_cap = int(lim.get("accepts_per_team_per_tick", 1)), duel_accept_cap(lim)   # for the reasons
    offers_left = budget.get("offers_left", int(lim.get("offers_per_team_per_tick", 12)))
    open_offers = len(_get(sit, "my_offers") or [])
    max_offers = int(lim.get("max_open_offers_per_team", 30))
    open_threads = [t for t in _get(sit, "threads") or [] if _get(t, "status", "open") == "open"]
    max_threads = int(lim.get("max_open_threads_per_team", 6))
    talking_to = {_get(t, "with") for t in open_threads}
    spoken = {k for k, n in (budget.get("messages") or {}).items() if n}
    per_side = int(lim.get("messages_per_side_per_tick", 1))

    chosen: list[Action] = []
    dropped: list[tuple[Action, str]] = []
    seen_sigs: set[str] = set()
    promised: set[str] = set()
    closing: set[str] = set()
    queue = sorted(actions, key=_order)
    i = 0
    while i < len(queue):
        a = queue[i]
        i += 1
        p = a.params or {}
        sig = _sig(a)
        why = ""
        if a.kind == "noop":
            why = "noop"
        elif sig in seen_sigs:
            why = "duplicate"
        elif a.kind == "duel_accept" and duel_accepts_left <= 0:
            why = f"duel accepts already used this tick (cap {duel_cap})"
        elif a.kind in ACCEPT_KINDS and a.kind != "duel_accept" and accepts_left <= 0:
            why = f"accept already used this tick (cap {accept_cap} offer accept per tick; retried next tick)"
        elif a.kind in MESSAGE_KINDS and (conv_key(a) in spoken or per_side <= 0):
            why = f"already spoke in {conv_key(a)} this tick"
        elif a.kind == "thread_message" and str(p.get("thread")) in closing:
            why = "thread is being closed"
        elif a.kind == "post_offer" and (offers_left <= 0 or open_offers >= max_offers):
            why = "listing limit"
        elif a.kind == "open_thread" and (len(open_threads) >= max_threads
                                           or (p.get("with") in talking_to and not p.get("venue"))):
            why = "thread limit or already talking"
        else:
            give, _ = flows(a, sit)
            cards = {f"a{x}" for x in give["assets"]} | {f"t{x}" for x in give["types"]}
            if cards & promised:
                why = "card already promised this tick"
            else:
                promised |= cards
        if why:
            dropped.append((a, why))
            alt = alternative(a) if a.kind in ACCEPT_KINDS and "already used this tick" in why else None
            if alt is not None:                    # accepts sort first, so the rest of the queue is all non-accepts
                rest = sorted(queue[i:] + [alt], key=_order)
                queue[i:] = rest
            continue
        seen_sigs.add(sig)
        if a.kind == "duel_accept":
            duel_accepts_left -= 1
        elif a.kind in ACCEPT_KINDS:
            accepts_left -= 1
        if a.kind in MESSAGE_KINDS:
            spoken.add(conv_key(a))
        if a.kind == "close_thread":
            closing.add(str(p.get("thread")))
        if a.kind == "post_offer":
            offers_left -= 1
            open_offers += 1
        if a.kind == "open_thread":
            open_threads.append({"with": p.get("with"), "status": "open"})
            talking_to.add(p.get("with"))
        chosen.append(a)
    return chosen, dropped
