"""Rails: invariants no model, lesson or bug can cross. Pure functions over (action, sit, ctx).

`sit` is core.state.Situation and `ctx` core.context.TickContext, used only by duck typing:
  sit.me (cash, assets[{id, ref, set, your_value}]), sit.duels, sit.threads, sit.my_offers, sit.limits,
  optional sit.values {ref: value of one more copy}; ctx.control, ctx.budget, ctx.ledger,
  optional ctx.value(ref) -> float.
Operator caps in ctx.control (cash_reserve, max_spend_per_deal, max_spend_per_hour, min_surplus,
value_margin, fair_max_per_hour, protected) override the defaults; lessons never reach here.
"""
from __future__ import annotations

import re
from typing import Any

from .. import config
from .types import ACCEPT_KINDS, MESSAGE_KINDS, Action, Verdict

STOP_FILE = config.STOP_FILE
MIN_SURPLUS = 1                  # duels: points of slack against our limit
VALUE_MARGIN = 1                 # dealers/market: P of slack against our private value
FAIR_MAX_PER_HOUR = 4            # deals with the same team per hour
SCARCE_SETS = {"LAV", "MAL", "RET"}
WRITE_KINDS = {"open_thread", "thread_message", "close_thread", "accept_offer", "post_offer", "cancel_offer",
               "duel_message", "duel_accept", "venue_open", "venue_patch", "broker_match", "broker_announce", "open_pack"}
VENUE_COST = 270                 # bond 250 (refundable) + 20
OK = Verdict(True)


# --- small helpers ------------------------------------------------------------------
def _get(obj, name, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _control(ctx) -> dict:
    return _get(ctx, "control") or {}


def _cap(ctx, name: str, default):
    v = _control(ctx).get(name)
    return default if v is None else type(default)(v)


def _num(x, default=0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _asset_id(a) -> Any:
    return a.get("id") if isinstance(a, dict) else a


def _held(sit) -> dict:
    """asset id -> asset dict for every card we hold."""
    me = _get(sit, "me") or {}
    return {a.get("id"): a for a in me.get("assets", []) if isinstance(a, dict)}


def _side(d: dict | None) -> dict:
    d = d or {}
    return {"cash": int(_num(d.get("cash"))), "assets": [_asset_id(a) for a in d.get("assets") or []],
            "asset_refs": {_asset_id(a): a.get("ref") for a in d.get("assets") or [] if isinstance(a, dict)},
            # `cards: ["LAV-03"]` (any copy of a card) is the same as types ["card:LAV-03"]
            "types": list(d.get("types") or []) + [f"card:{c}" for c in d.get("cards") or []]}


def _find(items, key, value):
    for it in items or []:
        if str(_get(it, key)) == str(value):
            return it
    return None


def _thread(sit, tid):
    return _find(_get(sit, "threads"), "id", tid)


def _duel(sit, did):
    return _find(_get(sit, "duels"), "duel", did) or _find(_get(sit, "duels"), "id", did)


def is_team(who) -> bool:
    return bool(who) and bool(re.fullmatch(r"t\d+|m[0-9a-f]{6,}", str(who)))


def flows(action: Action, sit=None) -> tuple[dict, dict]:
    """(what we give, what we get) as {cash, assets, types} for actions that can move value."""
    p = action.params or {}
    if "give" in p and "want" in p and action.kind != "post_offer":
        return _side(p["give"]), _side(p["want"])                # explicit override from the domain
    if action.kind == "accept_offer":
        exp = p.get("expect") or {}
        give = _side(exp.get("want"))                            # we hand over what the maker wants
        if p.get("assets"):                                      # ...as these copies of ours (sent in the body)
            give["assets"] = list(dict.fromkeys([*give["assets"], *p["assets"]]))
        return give, _side(exp.get("give"))
    if action.kind == "post_offer":
        return _side(p.get("give")), _side(p.get("want"))
    if action.kind in ("thread_message", "open_thread"):
        th = _thread(sit, p.get("thread")) if action.kind == "thread_message" else None
        topic = p.get("topic") or _get(th, "topic") or {}
        price = p.get("price")
        if isinstance(p.get("offer"), dict):
            o = p["offer"]
            return _side(o.get("give")), _side(o.get("want"))
        if "sell" in topic:
            sell = topic["sell"] or {}
            ids = sell.get("assets") or ([sell["asset"]] if "asset" in sell else [])
            types = [f"card:{sell['card']}"] if sell.get("card") else []
            return _side({"assets": ids, "types": types}), _side({"cash": price or 0})
        if "buy" in topic:
            item = _dealer_item(th)
            if item is not None:                                 # what the dealer actually puts on the table
                return _side({"cash": price or 0}), item
            buy = topic["buy"] or {}
            types = []
            if buy.get("card"):
                types.append(f"card:{buy['card']}")
            if buy.get("pack"):
                types.append(f"pack:{buy['pack']}")
            if not types:
                types.append(f"lot:{buy.get('set', '?')}:{buy.get('rarity', '?')}")
            return _side({"cash": price or 0}), _side({"types": types})
    return _side(None), _side(None)


def _dealer_item(th) -> dict | None:
    """The goods side of the counterparty's latest offer in a buy thread (None if it has not offered)."""
    for m in reversed(_get(th, "messages") or []):
        o = m.get("offer") if isinstance(m, dict) else None
        if o and o.get("maker") == _get(th, "with"):
            g = _side(o.get("give"))
            if g["assets"] or g["types"]:
                return g
    return None


def counterparty(action: Action, sit=None) -> str | None:
    p = action.params or {}
    if action.kind == "accept_offer":
        return (p.get("expect") or {}).get("maker")
    if action.kind == "post_offer":
        return p.get("to")
    if action.kind == "open_thread":
        return p.get("with")
    if action.kind == "thread_message":
        return _get(_thread(sit, p.get("thread")), "with")
    return None


# --- the eight rails ------------------------------------------------------------------
def rail_armed(action: Action, sit=None, ctx=None) -> Verdict:
    """8. STOP file or control.armed == False -> no write goes out."""
    if action.kind == "noop":
        return OK
    if STOP_FILE.exists():
        return Verdict(False, "armed", "STOP file present")
    if _control(ctx).get("armed") is False:
        return Verdict(False, "armed", "control disarmed")
    return OK


def rail_known(action: Action, sit=None, ctx=None) -> Verdict:
    """7a. Only known kinds; never automatic flags."""
    if action.kind != "noop" and action.kind not in WRITE_KINDS:
        return Verdict(False, "fair_play", f"kind {action.kind!r} is not allowed automatically")
    return OK


def rail_accept_shape(action: Action, sit=None, ctx=None) -> Verdict:
    """1. An accept must carry what we evaluated, so the executor can compare it with a fresh read."""
    if action.kind in ACCEPT_KINDS and not isinstance((action.params or {}).get("expect"), dict):
        return Verdict(False, "fresh", "accept without params.expect")
    return OK


def rail_cards(action: Action, sit=None, ctx=None) -> Verdict:
    """2. Only our cards; never the last copy of a LAV/MAL/RET card nor a protected one without a human."""
    give, _ = flows(action, sit)
    if not give["assets"] and not give["types"]:
        return OK
    held = _held(sit)
    human = bool((action.params or {}).get("human_ok"))
    protected = {str(x) for x in _control(ctx).get("protected") or []}
    counts: dict[str, int] = {}
    for a in held.values():
        counts[a.get("ref")] = counts.get(a.get("ref"), 0) + 1
    out: dict[str, int] = {}
    for aid in give["assets"]:
        a = held.get(aid) or held.get(int(aid) if str(aid).isdigit() else aid)
        if a is None:
            return Verdict(False, "cards", f"asset {aid} is not ours")
        if not human and (str(aid) in protected or str(a.get("ref")) in protected):
            return Verdict(False, "cards", f"asset {aid} ({a.get('ref')}) is protected")
        out[a.get("ref")] = out.get(a.get("ref"), 0) + 1
    for t in give["types"]:
        kind, _, ref = str(t).partition(":")
        if kind != "card":
            return Verdict(False, "cards", f"cannot give {t}")
        if counts.get(ref, 0) == 0:
            return Verdict(False, "cards", f"we hold no {ref}")
        if not human and ref in protected:
            return Verdict(False, "cards", f"{ref} is protected")
        out[ref] = out.get(ref, 0) + 1
    if not human:
        for ref, n in out.items():
            if str(ref)[:3] in SCARCE_SETS and counts.get(ref, 0) - n < 1:
                return Verdict(False, "cards", f"last copy of {ref}")
    return OK


def rail_duel(action: Action, sit=None, ctx=None) -> Verdict:
    """3. Duels: price inside our limit with MIN_SURPLUS slack; days 0..10."""
    if action.kind not in ("duel_message", "duel_accept"):
        return OK
    p = action.params or {}
    duel = _duel(sit, p.get("duel"))
    if duel is None:
        return Verdict(False, "duel", f"duel {p.get('duel')} not in view")
    if duel.get("status") not in (None, "live", "open"):
        return Verdict(False, "duel", f"duel is {duel.get('status')}")
    if action.kind == "duel_accept":
        exp = p.get("expect") or {}
        price, days = exp.get("price"), exp.get("days")
    else:
        price, days = p.get("price"), p.get("days")
    if price is None:
        return OK if action.kind == "duel_message" else Verdict(False, "duel", "accept without a price")
    limit, role = duel.get("your_limit"), duel.get("role")
    if limit is None or role not in ("seller", "buyer"):
        return Verdict(False, "duel", "unknown limit or role")
    slack = _cap(ctx, "min_surplus", MIN_SURPLUS)
    price = _num(price)
    if role == "seller" and price < limit + slack:
        return Verdict(False, "duel", f"sell at {price} < limit {limit} + {slack}")
    if role == "buyer" and price > limit - slack:
        return Verdict(False, "duel", f"buy at {price} > limit {limit} - {slack}")
    if "days" in (duel.get("issues") or []) and days is None and action.kind == "duel_message":
        return Verdict(False, "duel", "days required")
    if days is not None and not (0 <= _num(days, -1) <= 10):
        return Verdict(False, "duel", f"days {days} outside 0..10")
    return OK


def _value_of(item: str, sit, ctx, action) -> float | None:
    """Private value of one more copy of `item` ("card:LAV-03", "pack:x" or a ref)."""
    kind, _, ref = item.partition(":") if ":" in item else ("card", "", item)
    fn = _get(ctx, "value")
    if kind == "card" and callable(fn):
        try:
            v = fn(ref)
            if v is not None:
                return float(v)
        except Exception:
            pass
    values = _get(sit, "values") or {}
    for k in (item, ref):
        if k in values and values[k] is not None:
            return float(values[k])
    return None


def rail_value(action: Action, sit=None, ctx=None) -> Verdict:
    """4. Buy at most at our private value minus a margin; sell at least at our value plus a margin."""
    if action.kind not in ("accept_offer", "post_offer", "thread_message"):
        return OK
    give, get = flows(action, sit)
    if action.kind == "thread_message" and (action.params or {}).get("price") is None:
        return OK                                              # words only, nothing on the table
    if not (give["assets"] or give["types"] or get["assets"] or get["types"]):
        return OK                                              # cash for cash: nothing to value
    held = _held(sit)
    margin = _cap(ctx, "value_margin", VALUE_MARGIN)
    v_give = 0.0
    for aid in give["assets"]:
        a = held.get(aid)
        if a is None or a.get("your_value") is None:
            return Verdict(False, "value", f"no value for our asset {aid}")
        v_give += float(a["your_value"])
    for t in give["types"]:
        refs = [a for a in held.values() if f"card:{a.get('ref')}" == t and a.get("your_value") is not None]
        if not refs:
            return Verdict(False, "value", f"no value for {t}")
        v_give += max(float(a["your_value"]) for a in refs)    # worst case: they get our best copy
    v_get = 0.0
    hint = (action.expected or {}).get("value_get")
    for aid in get["assets"]:
        ref = get["asset_refs"].get(aid)
        v = _value_of(f"card:{ref}", sit, ctx, action) if ref else None
        if v is None:
            return Verdict(False, "value", f"unknown value of asset {aid}")
        v_get += v
    for t in get["types"]:
        v = _value_of(t, sit, ctx, action)
        if v is None and not str(t).startswith("card:") and hint is not None:
            v = _num(hint, None)                               # pack/lot EV comes from the domain's estimate
        if v is None:
            return Verdict(False, "value", f"unknown value of {t}")
        v_get += v
    surplus = v_get + get["cash"] - v_give - give["cash"]
    if surplus < margin:
        return Verdict(False, "value", f"surplus {surplus:.1f} < margin {margin} "
                                       f"(get {v_get:.1f}+{get['cash']}P, give {v_give:.1f}+{give['cash']}P)")
    return OK


def own_venue(sit) -> str | None:
    """Our own venue id: the free starter stall (from hour 3.0) is not ours."""
    vid = (_get(sit, "me") or {}).get("venue")
    if isinstance(vid, dict):
        vid = vid.get("venue") or vid.get("id")
    if not vid:
        return None
    for v in _get(sit, "venues") or []:
        if isinstance(v, dict) and (v.get("venue") or v.get("id")) == vid and (v.get("starter") or v.get("house")):
            return None
    return vid


GRANT_AT_HOURS, GRANT_CASH = 4.05, 150   # Saturday allowance; the bond can count on it before it arrives


def _venue_pending(sit, ctx) -> bool:
    """True while we still mean to open our own venue (decision: board venue at hour 4.05)."""
    control = _get(ctx, "control") or {}
    if control.get("venue_reserve") is False:
        return False
    return own_venue(sit) is None


def _venue_reserve(sit) -> int:
    """Cash to keep for the bond: the Saturday grant will cover part of it if it has not arrived yet."""
    t = _get(sit, "t_hours")
    before_grant = t is not None and 0 < _num(t, 0) < GRANT_AT_HOURS
    return max(0, VENUE_COST - (GRANT_CASH if before_grant else 0))


def rail_cash(action: Action, sit=None, ctx=None) -> Verdict:
    """5. Keep CASH_RESERVE; per-deal and per-hour spending caps."""
    give, _ = flows(action, sit)
    spend = give["cash"]
    if action.kind == "venue_open":
        spend = VENUE_COST
    if spend <= 0:
        return OK
    cash = _num((_get(sit, "me") or {}).get("cash"))
    reserve = _cap(ctx, "cash_reserve", config.CASH_RESERVE)
    if action.kind != "venue_open" and _venue_pending(sit, ctx):
        reserve += _venue_reserve(sit)                         # keep the bond for our venue until it is open
    if cash - spend < reserve:
        return Verdict(False, "cash", f"cash {cash:.0f} - {spend} < reserve {reserve}")
    if action.kind == "venue_open":
        return OK                                              # a refundable bond, not a purchase
    per_deal = _cap(ctx, "max_spend_per_deal", config.MAX_SPEND_PER_DEAL)
    if spend > per_deal:
        return Verdict(False, "cash", f"spend {spend} > per-deal cap {per_deal}")
    per_hour = _cap(ctx, "max_spend_per_hour", config.MAX_SPEND_PER_HOUR)
    spent = _spent_hour(ctx)
    if spent + spend > per_hour:
        return Verdict(False, "cash", f"hour spend {spent:.0f} + {spend} > cap {per_hour}")
    return OK


def _spent_hour(ctx) -> float:
    b = _get(ctx, "budget") or {}
    if "spend_hour" in b:
        return _num(b["spend_hour"])
    lg = _get(ctx, "ledger")
    if lg is not None and hasattr(lg, "spend_last_hour"):
        return _num(lg.spend_last_hour())
    if isinstance(_get(ctx, "spend_last_hour"), (int, float)):
        return float(ctx.spend_last_hour)
    return 0.0


def rail_pace(action: Action, sit=None, ctx=None) -> Verdict:
    """6. One accept per tick, one message per conversation per tick, listing and open-thread limits."""
    b = _get(ctx, "budget") or {}
    lim = {**(b.get("limits") or {}), **(_get(sit, "limits") or {})}
    p = action.params or {}
    if action.kind in ACCEPT_KINDS:
        left = b.get("accepts_left")
        if left is None:
            left = int(lim.get("accepts_per_team_per_tick", 1)) - int(b.get("accepts_used", 0))
        if left <= 0:
            return Verdict(False, "pace", "no accept left this tick")
    if action.kind in MESSAGE_KINDS:
        key = conv_key(action)
        if (b.get("messages") or {}).get(key, 0) >= int(lim.get("messages_per_side_per_tick", 1)):
            return Verdict(False, "pace", f"already spoke in {key} this tick")
    if action.kind == "post_offer":
        if b.get("offers_left", 1) <= 0:
            return Verdict(False, "pace", "no listings left this tick")
        if len(_get(sit, "my_offers") or []) >= int(lim.get("max_open_offers_per_team", 30)):
            return Verdict(False, "pace", "too many open offers")
    if action.kind == "open_thread":
        open_ = [t for t in _get(sit, "threads") or [] if _get(t, "status", "open") == "open"]
        if len(open_) >= int(lim.get("max_open_threads_per_team", 6)):
            return Verdict(False, "pace", "too many open threads")
        if any(_get(t, "with") == p.get("with") and not p.get("venue") for t in open_):
            return Verdict(False, "pace", f"already talking to {p.get('with')}")
    return OK


def rail_fair(action: Action, sit=None, ctx=None) -> Verdict:
    """7b. At most N deals per hour with the same team."""
    if action.kind not in ("accept_offer", "post_offer", "thread_message"):
        return OK
    who = counterparty(action, sit)
    if not is_team(who):
        return OK
    cap = _cap(ctx, "fair_max_per_hour", FAIR_MAX_PER_HOUR)
    b = _get(ctx, "budget") or {}
    n = (b.get("deals_by_team_hour") or {}).get(who)
    if n is None:
        lg = _get(ctx, "ledger")
        n = lg.deals_with(who, 1.0) if lg is not None and hasattr(lg, "deals_with") else 0
    if n >= cap:
        return Verdict(False, "fair_play", f"{n} deals with {who} this hour (cap {cap})")
    return OK


def rail_pack(action: Action, sit=None, ctx=None) -> Verdict:
    """Only open sealed packs we actually hold."""
    if action.kind != "open_pack":
        return OK
    aid = (action.params or {}).get("asset")
    a = _held(sit).get(aid) or _held(sit).get(int(aid) if str(aid).isdigit() else aid)
    if not a or a.get("kind") != "pack":
        return Verdict(False, "pack", f"asset {aid} is not a pack of ours")
    return OK


RAILS = [rail_armed, rail_pack, rail_known, rail_accept_shape, rail_cards, rail_duel, rail_value, rail_cash, rail_pace,
         rail_fair]


def conv_key(action: Action) -> str:
    """Budget key of the conversation an action speaks in (same as core.context.Budget)."""
    from .context import conv_key as _ck
    return _ck(action)


def check(action: Action, sit, ctx) -> Verdict:
    """First rail that vetoes, or Verdict(True)."""
    for rail in RAILS:
        try:
            v = rail(action, sit, ctx)
        except Exception as e:  # noqa: BLE001 - a broken rail vetoes, never lets through
            return Verdict(False, rail.__name__.removeprefix("rail_"), f"rail error: {type(e).__name__}: {e}")
        if not v.ok:
            return v
    return OK


# --- 1. fresh re-read before accepting ---------------------------------------------------
def _norm_side(d: dict | None) -> tuple:
    s = _side(d)
    return s["cash"], tuple(sorted(str(a) for a in s["assets"])), tuple(sorted(str(t) for t in s["types"]))


def verify_fresh(action: Action, fresh: dict | None) -> Verdict:
    """The offer (or duel) read just before accepting must be exactly what we evaluated."""
    exp = (action.params or {}).get("expect") or {}
    if not fresh:
        return Verdict(False, "fresh", "offer not found on re-read")
    if action.kind == "accept_offer":
        if str(fresh.get("id")) != str((action.params or {}).get("offer")):
            return Verdict(False, "fresh", "different offer id")
        if fresh.get("status", "open") != "open":
            return Verdict(False, "fresh", f"offer is {fresh.get('status')}")
        for side in ("give", "want"):
            if _norm_side(fresh.get(side)) != _norm_side(exp.get(side)):
                return Verdict(False, "fresh", f"{side} changed: {_norm_side(exp.get(side))} -> "
                                               f"{_norm_side(fresh.get(side))}")
        for k in ("maker", "to", "venue", "thread"):
            if k in exp and exp[k] != fresh.get(k):
                return Verdict(False, "fresh", f"{k} changed")
        return OK
    if action.kind == "duel_accept":
        if fresh.get("status") not in (None, "live", "open"):
            return Verdict(False, "fresh", f"duel is {fresh.get('status')}")
        rival = fresh.get("rival_offer")
        if not rival:
            return Verdict(False, "fresh", "no rival offer")
        for k in ("id", "price", "days"):
            if k in exp and exp[k] is not None and str(exp[k]) != str(rival.get(k)):
                return Verdict(False, "fresh", f"rival offer {k} changed: {exp[k]} -> {rival.get(k)}")
        return OK                                                # the rival's offer stands after our counters
    return Verdict(False, "fresh", f"{action.kind} is not an accept")
