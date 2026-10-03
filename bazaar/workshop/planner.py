"""The Workshop: POST /api/taller {"assets": [a, b, c]}.

Official rule (GET /api/levels, taller): "three spare copies of one rarity (you keep at least one of each card)
become one card of the next rarity. The pull is luck, shown and never scored."

Pure functions, no I/O except reading the recorded catalog. The rails re-check everything (core.rails.rail_taller).
A copy is usable only if, after the three leave, we still hold one copy of its card that is NOT promised in an open
offer or a dealer sell thread. What we give is valued at the game's `your_value` of each copy (or the brain's
minimum ask for that card, if higher); what we get is the mean value to us of one more copy of a released card of
the next rarity. The pull itself is luck, so the gain is an expectation, never a certainty.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from bazaar import config
from bazaar.core.types import Action

NEXT_RARITY = {"common": "uncommon", "uncommon": "rare", "rare": "epic", "epic": "legendary"}
MIN_GAIN_P = 3.0            # expected value gained by one craft, at our private values
BACKOFF_TICKS = 20          # after a refusal (unknown server limits), wait before trying again


def _g(obj, name, default=None):
    if obj is None:
        return default
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def load_values(me: dict):
    """dealers.values.Values on the recorded catalog (None if it cannot be read)."""
    try:
        from bazaar.dealers.values import Values
        cat = json.loads((config.DATA / "record" / "latest" / "catalog.json").read_text())
        cat = cat.get("data", cat) if isinstance(cat, dict) else cat
        exact = {}
        try:
            exact = json.loads((config.LIVE / "exact_values.json").read_text())
        except (OSError, ValueError, AttributeError):
            exact = {}
        return Values(me or {}, cat, exact if isinstance(exact, dict) else {})
    except Exception:  # noqa: BLE001
        return None


def expected_value(values, rarity: str) -> float | None:
    """Mean value to us of one more copy of a released card of `rarity` (what a random pull is worth)."""
    if values is None or not rarity:
        return None
    try:
        refs = values.released_refs(rarity)
        if not refs:
            return None
        return round(sum(float(values.next_copy(r)) for r in refs) / len(refs), 2)
    except Exception:  # noqa: BLE001
        return None


def ev_table(values) -> dict[str, float | None]:
    return {r: expected_value(values, r) for r in ("common", "uncommon", "rare", "epic", "legendary")}


def promised_ids(sit) -> set:
    """Asset ids of ours already promised: open offers that give assets and open dealer sell threads."""
    ids: set = set()
    me_id = (_g(sit, "me") or {}).get("id")
    for o in _g(sit, "my_offers") or []:
        if isinstance(o, dict) and o.get("maker") in (None, me_id) and o.get("status", "open") == "open":
            for a in (o.get("give") or {}).get("assets") or []:
                ids.add(a.get("id") if isinstance(a, dict) else a)
    for t in _g(sit, "threads") or []:
        if isinstance(t, dict) and (t.get("status") or "open") == "open":
            sell = (t.get("topic") or {}).get("sell") or {}
            ids.update(sell.get("assets") or ([sell["asset"]] if "asset" in sell else []))
    return ids


def spare_pool(sit, control: dict | None = None) -> dict[str, list[dict]]:
    """rarity -> usable spare copies [{id, ref, value}], cheapest first. For every card we keep one copy that is not
    promised elsewhere; protected cards and copies inside open offers/threads are never usable."""
    me = _g(sit, "me") or {}
    control = control or {}
    protected = {str(x) for x in control.get("protected") or []}
    floors = {str(k).upper(): float(v) for k, v in (control.get("min_asks") or {}).items()
              if isinstance(v, (int, float))}
    promised = promised_ids(sit)
    by_ref: dict[str, list[dict]] = {}
    for a in me.get("assets") or []:
        if isinstance(a, dict) and a.get("kind", "card") == "card" and a.get("ref"):
            by_ref.setdefault(a["ref"], []).append(a)
    pool: dict[str, list[dict]] = {}
    for ref, copies in by_ref.items():
        if str(ref) in protected:
            continue
        free = [a for a in copies if a.get("id") not in promised and str(a.get("id")) not in protected]
        n_promised = len(copies) - len([a for a in copies if a.get("id") not in promised])
        usable = min(len(free), len(copies) - n_promised - 1)       # one unpromised copy always stays
        if usable <= 0:
            continue
        free.sort(key=lambda a: (float(a.get("your_value") or 0), a.get("id") or 0))
        for a in free:                                              # any free copy may go, at most `usable` per card
            if a.get("your_value") is None or a.get("rarity") not in NEXT_RARITY:
                continue
            v = max(float(a["your_value"]), floors.get(str(ref).upper(), 0.0))
            pool.setdefault(a["rarity"], []).append({"id": a["id"], "ref": ref, "value": round(v, 2),
                                                     "usable": usable})
    for lst in pool.values():
        lst.sort(key=lambda x: (x["value"], x["id"]))
    return pool


def within_usable(items: list[dict]) -> bool:
    """No card gives more copies than it can spare."""
    n: dict[str, int] = {}
    for x in items:
        n[x["ref"]] = n.get(x["ref"], 0) + 1
        if n[x["ref"]] > int(x.get("usable") or 0):
            return False
    return True


def cheapest_triple(lst: list[dict]) -> list[dict] | None:
    out: list[dict] = []
    for x in lst:                                                # already sorted by value
        if within_usable(out + [x]):
            out.append(x)
        if len(out) == 3:
            return out
    return None


def triple_value(triple: list[dict]) -> float:
    return round(sum(float(x["value"]) for x in triple), 2)


def _action(triple: list[dict], rarity: str, ev: float, source: str, why: str = "") -> Action:
    give = triple_value(triple)
    nxt = NEXT_RARITY[rarity]
    refs = ", ".join(x["ref"] for x in triple)
    return Action(kind="taller", params={"assets": [x["id"] for x in triple]}, domain="workshop", source=source,
                  reason=why or f"Workshop: 3 spare {rarity}s ({refs}, worth {give} P to us) for one {nxt} "
                                f"(a random one is worth {ev} P to us on average): expected +{round(ev - give, 1)} P.",
                  expected={"value_give": give, "value_get": ev, "value_gain": round(ev - give, 2), "points": 0.0,
                            "rarity_in": rarity, "rarity_out": nxt, "refs": [x["ref"] for x in triple]})


def plan(sit, control: dict | None = None, orders: Any = "auto", values=None, min_gain: float = MIN_GAIN_P) -> Action | None:
    """One Workshop action for this tick, or None. `orders`: "auto" (default), "off", or a list of triples of
    asset ids the brain wants (still checked for spares and value by the rails)."""
    if orders == "off":
        return None
    me = _g(sit, "me") or {}
    values = values if values is not None else load_values(me)
    pool = spare_pool(sit, control)
    if isinstance(orders, list) and orders:
        by_id = {x["id"]: (r, x) for r, lst in pool.items() for x in lst}
        for tri in orders:
            ids = list(tri) if isinstance(tri, (list, tuple)) else []
            if len(ids) == 3 and len(set(ids)) == 3 and all(i in by_id for i in ids):
                rar = {by_id[i][0] for i in ids}
                if len(rar) == 1 and within_usable([by_id[i][1] for i in ids]):
                    r = rar.pop()
                    ev = expected_value(values, NEXT_RARITY[r])
                    if ev is not None and ev - triple_value([by_id[i][1] for i in ids]) >= 1.0:
                        return _action([by_id[i][1] for i in ids], r, ev, "opus", "")
        return None
    best = None
    for rarity, lst in pool.items():
        triple = cheapest_triple(lst)                            # the three cheapest spares of this rarity
        if triple is None:
            continue
        ev = expected_value(values, NEXT_RARITY[rarity])
        if ev is None:
            continue
        gain = ev - triple_value(triple)
        if gain >= min_gain and (best is None or gain > best[0]):
            best = (gain, triple, rarity, ev)
    if best is None:
        return None
    return _action(best[1], best[2], best[3], "code")


CANCEL_MAX_GAIN_P = 4.0     # only cheap asks are withdrawn to craft: an ask that would gain more than this stays
ASK_FILL_PROB = 0.3         # a cheap ask on a flooded market rarely fills: weight of the gain we give up


def plan_actions(sit, control: dict | None = None, orders: Any = "auto", values=None) -> list[Action]:
    """The craft for this tick, or - when our spares are tied up in cheap open asks and crafting them is worth more -
    the cancels that free them (the craft follows next tick). Never touches swaps, addressed-card wants or asks
    that would gain more than CANCEL_MAX_GAIN_P."""
    if orders == "off":
        return []
    me = _g(sit, "me") or {}
    values = values if values is not None else load_values(me)
    a = plan(sit, control, orders, values)
    if a is not None:
        return [a]
    if isinstance(orders, list) and orders:
        return _free_ordered(sit, control, orders, values)
    held = {x.get("id"): x for x in me.get("assets") or [] if isinstance(x, dict)}
    counts: dict[str, int] = {}
    for x in held.values():
        if x.get("kind", "card") == "card":
            counts[x.get("ref")] = counts.get(x.get("ref"), 0) + 1
    cands = []
    for o in _g(sit, "my_offers") or []:
        if not isinstance(o, dict) or o.get("maker") not in (None, me.get("id")) or o.get("status", "open") != "open":
            continue
        give, want = o.get("give") or {}, o.get("want") or {}
        assets = give.get("assets") or []
        if len(assets) != 1 or give.get("cash") or want.get("types") or want.get("cards") or want.get("assets") \
                or o.get("thread") is not None:
            continue
        aid = assets[0].get("id") if isinstance(assets[0], dict) else assets[0]
        card = held.get(aid)
        if not card or counts.get(card.get("ref"), 0) < 2 or card.get("your_value") is None:
            continue
        forgone = float(want.get("cash") or 0) - float(card["your_value"])
        if forgone <= CANCEL_MAX_GAIN_P:
            cands.append((forgone, o))
    cands.sort(key=lambda t: t[0])
    offers = list(_g(sit, "my_offers") or [])
    dropped, lost = [], 0.0
    for forgone, o in cands:
        dropped.append(o)
        lost += max(0.0, forgone) * ASK_FILL_PROB
        sit2 = {"me": me, "threads": _g(sit, "threads") or [],
                "my_offers": [x for x in offers if x not in dropped]}
        a = plan(sit2, control, "auto", values, min_gain=MIN_GAIN_P + lost)
        if a is not None:
            refs = set(a.expected.get("refs") or [])

            def _ref(x):
                first = ((x.get("give") or {}).get("assets") or [{}])[0]
                return (held.get(first.get("id") if isinstance(first, dict) else first) or {}).get("ref")
            need = [x for x in dropped if _ref(x) in refs]       # only the asks on cards the craft will use
            return [Action(kind="cancel_offer", params={"offer": x.get("id")}, domain="workshop", source="code",
                           reason=f"Free a spare for the Workshop: crafting 3 spares is worth about "
                                  f"+{a.expected.get('value_gain')} P, more than this cheap ask is likely to bring.")
                    for x in (need or dropped)]
    return []


def _free_ordered(sit, control, orders: list, values) -> list[Action]:
    """The brain ordered a craft but its copies sit inside open offers of ours (the market's code listed them
    first): withdraw those offers when the craft would then run (it follows next tick). Thread offers stay."""
    me = _g(sit, "me") or {}
    wanted = {i for tri in orders if isinstance(tri, (list, tuple)) for i in tri}
    offers = [o for o in _g(sit, "my_offers") or [] if isinstance(o, dict)]
    holding = [o for o in offers if o.get("maker") in (None, me.get("id")) and o.get("status", "open") == "open"
               and o.get("thread") is None
               and any((a.get("id") if isinstance(a, dict) else a) in wanted
                       for a in (o.get("give") or {}).get("assets") or [])]
    if not holding:
        return []
    sit2 = {"me": me, "threads": _g(sit, "threads") or [], "my_offers": [o for o in offers if o not in holding]}
    if plan(sit2, control, orders, values) is None:
        return []
    return [Action(kind="cancel_offer", params={"offer": o.get("id")}, domain="workshop", source="code",
                   reason="Free a copy the brain ordered crafted at The Workshop: it sits in an open offer of ours.")
            for o in holding]


# ---- results and facts for the brain ---------------------------------------------------------
def results_path(live: Path | None = None) -> Path:
    return (live or config.LIVE) / "workshop.jsonl"


def record_result(action: Action, outcome, tick=None, live: Path | None = None) -> dict:
    resp = _g(outcome, "response") or {}
    card = None
    for k in ("card", "asset", "result", "pull", "got"):
        if isinstance(resp.get(k), dict):
            card = resp[k]
            break
    row = {"ts": time.time(), "tick": tick, "status": _g(outcome, "status"), "assets": (action.params or {}).get("assets"),
           "refs": (action.expected or {}).get("refs"), "value_give": (action.expected or {}).get("value_give"),
           "ev": (action.expected or {}).get("value_get"),
           "got": ({k: card.get(k) for k in ("id", "ref", "name", "rarity", "set", "serial")} if card else None),
           "error": resp.get("error"), "message": resp.get("message"),
           "response": {k: v for k, v in resp.items() if k not in ("latency_s",)} if not card else None}
    try:
        p = results_path(live)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass
    return row


def results(live: Path | None = None, n: int = 10) -> list[dict]:
    try:
        lines = results_path(live).read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(x) for x in lines if x.strip()]
    except (OSError, ValueError):
        return []


def _spare_summary(lst: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for x in lst:
        seen.setdefault(x["ref"], {"ref": x["ref"], "copies_we_can_spare": x["usable"], "value_each": x["value"]})
    return list(seen.values())[:10]


def facts(sit, control: dict | None = None, cheapest_ask: dict | None = None, live: Path | None = None) -> dict:
    """What the brain needs to reason about the Workshop. `cheapest_ask`: {rarity: lowest ask seen for a card we
    already hold} (all-in cost on El Rastro adds 5 % + 1 P)."""
    me = _g(sit, "me") or {}
    values = load_values(me)
    pool = spare_pool(sit, control)
    evs = ev_table(values)
    out: dict[str, Any] = {
        "rule": "POST /api/taller {assets:[a,b,c]}: 3 spare copies of one rarity (keep one of each card) -> 1 card of "
                "the next rarity; the pull is luck and is never scored (it only changes what we hold).",
        "expected_value_of_a_pull": {NEXT_RARITY[r]: evs.get(NEXT_RARITY[r]) for r in NEXT_RARITY},
        "our_usable_spares": {r: _spare_summary(lst) for r, lst in pool.items()},
        "next_craft": None, "buy_to_craft": {}, "results": results(live, 6)}
    a = plan(sit, control, "auto", values)
    if a is not None:
        out["next_craft"] = {"refs": a.expected.get("refs"), "give": a.expected.get("value_give"),
                             "expected_get": a.expected.get("value_get"), "expected_gain": a.expected.get("value_gain")}
    for rarity, ask in (cheapest_ask or {}).items():
        nxt = NEXT_RARITY.get(rarity)
        ev = evs.get(nxt) if nxt else None
        if ev is None or ask is None:
            continue
        cost = round(3 * (float(ask) * 1.05 + 1), 1)             # three copies bought on El Rastro, fee included
        out["buy_to_craft"][rarity] = {"cheapest_ask": ask, "cost_of_three_all_in": cost, "expected_get": ev,
                                       "expected_gain": round(ev - cost, 1),
                                       "verdict": "worth it" if ev - cost >= MIN_GAIN_P else "not worth it"}
    return out
