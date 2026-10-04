"""This morning's real situations (Saturday 3 Oct 2026), each with what el cerebro must notice and decide.

det(ctx)  -> [(check, ok, detail)]   code side: the picture/detectors contain the facts (no API call)
llm(plan, ctx) -> [(check, ok, detail)]  the plan Opus returns for that picture does the right thing
ctx = {"pic": picture dict, "text": picture JSON lowercased, "events": [event dicts], "tick": int}
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

Check = tuple[str, bool, str]


def _r(pic: dict, *path, default=None):
    cur = pic
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return default if cur is None else cur


def plan_text(plan: dict) -> str:
    return json.dumps(plan or {}, ensure_ascii=False, default=str).lower()


def _ids(xs) -> set[int]:
    out = set()
    for x in xs or []:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out


@dataclass
class Scenario:
    id: str
    title: str
    tick: int
    expect: str
    det: Callable[[dict], list[Check]]
    llm: Callable[[dict, dict], list[Check]]
    control: dict = field(default_factory=dict)
    events_from_tick: int | None = None       # build the game events (EventDetector diff) since this tick


# --------------------------------------------------------------------------- 1. key B
def det_key_b(ctx):
    h = _r(ctx["pic"], "research", "llm_health", default={})
    b = (h.get("by_key_30min") or {}).get("B") or {}
    anomalies = " ".join(h.get("anomalies") or []).lower()
    causes = " ".join(_r(ctx["pic"], "research", "our_bot", "likely_causes", default=[])).lower()
    return [("llm_health counts key B errors", sum((b.get("errors") or {}).values()) > 0, json.dumps(b)[:160]),
            ("anomaly names key B", "key b" in anomalies, anomalies[:160]),
            ("idle cause: decisions from code fallback", "fallback" in causes, causes[:160])]


def llm_key_b(plan, ctx):
    t = plan_text(plan)
    return [("plan flags key B failing", bool(re.search(r"(key|clave)\s*b\b", t)) and
             bool(re.search(r"400|workspace|fail|error|dead|broken|rechaz", t)), ""),
            ("plan notes the code fallback", "fallback" in t or "code" in t and "claude" in t, "")]


# --------------------------------------------------------------------------- 2. cash locked in bids
def det_locked(ctx):
    bot = _r(ctx["pic"], "research", "our_bot", default={})
    out = _r(ctx["pic"], "research", "our_offer_outliers", "outliers", default=[])
    mal = [o for o in out if o.get("kind") == "bid" and o.get("card") == "MAL-09"]
    return [("cash locked in bids >= 40 P", (bot.get("cash_locked_in_bids") or 0) >= 40,
             f"locked {bot.get('cash_locked_in_bids')} of cash {bot.get('cash')}"),
            ("idle cause names the locked cash", "locked" in " ".join(bot.get("likely_causes") or []), ""),
            ("outlier: our MAL-09 bid is outbid", bool(mal), json.dumps(mal)[:200])]


def llm_locked(plan, ctx):
    ours = set(_r(ctx["pic"], "our_open_offer_ids", default=[]))
    bids = {o.get("offer") for o in _r(ctx["pic"], "research", "our_offer_outliers", "outliers", default=[])
            if o.get("kind") == "bid"}
    cancel = _ids(plan.get("cancel_offers"))
    return [("cancels the outbid cash bid(s)", bool(bids & cancel) or bool(cancel & ours and "bid" in plan_text(plan)),
             f"cancel {sorted(cancel)} outbid {sorted(bids)}"),
            ("explains cash is parked/locked", bool(re.search(r"lock|parked|bloque|free (the )?cash|liberar", plan_text(plan))), "")]


# --------------------------------------------------------------------------- 3. broker announcement refused
def det_announce(ctx):
    ref = _r(ctx["pic"], "research", "our_bot", "refusals", default={})
    n = sum(v for k, v in ref.items() if k.startswith("broker_announce"))
    return [("refusals count broker_announce 429s", n >= 3, json.dumps(ref)[:200]),
            ("recent_refusals show the rate-limit text", "one announcement per venue" in ctx["text"], "")]


def llm_announce(plan, ctx):
    t = plan_text(plan)
    return [("plan addresses the refused announcement", "announc" in t or "anunci" in t, ""),
            ("plan respects the 20-tick limit / backs off", bool(re.search(r"20 ticks|every 20|rate.?limit|429|back.?off|wait|espera", t)), "")]


# --------------------------------------------------------------------------- 4. goal mode freezing trades
def det_freeze(ctx):
    bot = _r(ctx["pic"], "research", "our_bot", default={})
    return [("ticks without actions >= 10 of last 20", (bot.get("ticks_without_actions_last_20") or 0) >= 10,
             str(bot.get("ticks_without_actions_last_20"))),
            ("idle cause names the goal saving", "goal" in " ".join(bot.get("likely_causes") or []), ""),
            ("goals in force are MAL-09/MAL-10", set(_r(ctx["pic"], "goals_in_force", default={})) >= {"MAL-09", "MAL-10"},
             json.dumps(_r(ctx["pic"], "goals_in_force", default={})))]


def llm_freeze(plan, ctx):
    cp = plan.get("cash_policy") or {}
    t = plan_text(plan)
    return [("allows small value deals while saving", (cp.get("max_small_deal") or 0) > 0
             or bool(re.search(r"small (value )?(deal|buy)|tratos? peque", t)), json.dumps(cp)),
            ("names the idle bot", bool(re.search(r"idle|no action|0 action|frozen|freez|parad|sin hacer", t)), "")]


# --------------------------------------------------------------------------- 5. Team 5 bid for our only RET-01
def det_team5(ctx):
    to_us = _r(ctx["pic"], "research", "offers_to_us", default=[])
    o = next((x for x in to_us if x.get("offer") == 4167), None)
    return [("offers_to_us lists #4167", o is not None, json.dumps(o)[:220]),
            ("#4167 gains value (~+9 P)", bool(o) and (o.get("value_gain_cash_only") or 0) >= 5, ""),
            ("#4167 marked last copy + ally", bool(o) and o.get("last_copy") and o.get("ally"), "")]


def llm_team5(plan, ctx):
    return [("accept_offers includes #4167", 4167 in _ids(plan.get("accept_offers")),
             str(plan.get("accept_offers")))]


# --------------------------------------------------------------------------- 6. outlier asks on v10
def det_outliers(ctx):
    out = {o.get("offer") for o in _r(ctx["pic"], "research", "our_offer_outliers", "outliers", default=[])}
    unk = {o.get("offer") for o in _r(ctx["pic"], "research", "offers_not_posted_by_our_bot", default=[])}
    return [("outlier detector flags #4117 (RET-06 at 55 P, value 27.5)", 4117 in out, str(sorted(out))),
            ("outlier detector flags #4144 (RET-01 at 40 P, value 11)", 4144 in out, ""),
            ("unknown-actor detector lists #4117 and #4144", {4117, 4144} <= unk, str(sorted(unk)))]


def llm_outliers(plan, ctx):
    cancel = _ids(plan.get("cancel_offers"))
    t = plan_text(plan)
    return [("cancels #4117 and #4144", {4117, 4144} <= cancel, str(sorted(cancel))),
            ("flags offers not posted by our bot", bool(re.search(r"unknown|not (posted|made) by (our|the) bot|someone else|our key|outside", t)), "")]


# --------------------------------------------------------------------------- 7. RET buys don't add score
def det_ret(ctx):
    bi = _r(ctx["pic"], "research", "our_buys_by_set_last_3h", default={})
    ret = bi.get("RET") or {}
    return [("buy impact has RET buys", (ret.get("buys") or 0) >= 1, json.dumps(ret)[:200]),
            ("RET marked low_impact", bool(ret.get("low_impact")), "")]


def llm_ret(plan, ctx):
    return [("avoid_buy_sets includes RET", "RET" in (plan.get("avoid_buy_sets") or []),
             str(plan.get("avoid_buy_sets")))]


# --------------------------------------------------------------------------- 8. MAL-09/10 goals
def det_mal(ctx):
    autos = _r(ctx["pic"], "automatic_goals", default={})
    miss = {m["ref"]: m.get("value_to_us") for m in _r(ctx["pic"], "sets", "MAL", "missing", default=[])}
    return [("automatic goals MAL-09/10", {"MAL-09", "MAL-10"} <= set(autos), json.dumps(autos)),
            ("goal prices below value (<= 90)", all(0 < autos.get(r, 0) <= 90 for r in ("MAL-09", "MAL-10")), ""),
            ("picture shows MAL-09/10 worth ~91", all((miss.get(r) or 0) >= 80 for r in ("MAL-09", "MAL-10")),
             json.dumps(miss))]


def llm_mal(plan, ctx):
    g = plan.get("goal_buys") or {}
    keep = all((r not in g) or (0 < int(g[r]) <= 90) for r in ("MAL-09", "MAL-10"))
    named = "mal-09" in plan_text(plan) or "malasa" in plan_text(plan)
    return [("keeps MAL-09/10 as goals at <= 90 P", keep and named, json.dumps(g)),
            ("no goal at or above value", all(int(p) < 91 for r, p in g.items() if r.startswith("MAL")), "")]


# --------------------------------------------------------------------------- 9. Team 12 via Carmen
def det_t12(ctx):
    t12 = _r(ctx["pic"], "research", "rivals_last_2h", "teams", "t12", default={})
    return [("rival research covers t12", bool(t12), json.dumps({k: t12.get(k) for k in ('buys', 'sets_bought', 'partners')})[:200]),
            ("t12 RET buys seen", (t12.get("sets_bought") or {}).get("RET", 0) >= 3, ""),
            ("t12 partner is abuela", "abuela" in json.dumps(t12.get("partners") or {}), "")]


def llm_t12(plan, ctx):
    t = plan_text(plan)
    return [("rival finding on Team 12", bool(re.search(r"t12|team 12", t)), ""),
            ("explains Carmen/abuela buys below value", bool(re.search(r"abuela|carmen", t)), "")]


# --------------------------------------------------------------------------- 10. new dealer (Doña Pilar)
def det_pilar(ctx):
    evs = " ".join(e.get("text", "") for e in ctx.get("events") or []).lower()
    dealers = [d.get("id") for d in _r(ctx["pic"], "dealers", default=[])]
    return [("event detector reports the new dealer pilar", "pilar" in evs, evs[:200]),
            ("picture lists pilar with unlock rules", "pilar" in dealers, str(dealers))]


def llm_pilar(plan, ctx):
    t = plan_text(plan)
    return [("plan reacts to Pilar", "pilar" in t, ""),
            ("plan says what unlocking/levels need", bool(re.search(r"unlock|level|nivel|desbloq", t)), "")]


# --------------------------------------------------------------------------- 11. broker probe refused
def det_probe(ctx):
    return [("picture shows the Market Test probe refusal", "price must sit between" in ctx["text"], ""),
            ("picture carries the broker's Market Test status", "efficiency_estimate" in ctx["text"]
             or "session_stats" in ctx["text"] or "broker_status" in ctx["text"], "")]


def llm_probe(plan, ctx):
    t = plan_text(plan)
    return [("finding on the broker probe bug", bool(re.search(r"probe|between the ask|bad_match", t)), "")]


NO_GUARD = {"avoid_buy_sets": [], "goal_buys": {}}

SCENARIOS: list[Scenario] = [
    Scenario("key_b", "Key B answers every call with 400 (no workspace); bot falls back to code", 197,
             "finding on key B + fallback", det_key_b, llm_key_b, NO_GUARD),
    Scenario("cash_locked", "51 P parked in cash bids (MAL-09 40 P outbid by 70 P, RET-06 11 P): 0 P dealer budget", 232,
             "cancel the outbid bids, free the cash", det_locked, llm_locked, NO_GUARD),
    Scenario("announce_429", "Broker announcement refused every tick (one per venue per 20 ticks)", 215,
             "back off / announce at most every 20 ticks", det_announce, llm_announce, NO_GUARD),
    Scenario("goal_freeze", "Goal mode froze every trade (ticks 224-240 with 0 actions)", 240,
             "allow small value deals while saving", det_freeze, llm_freeze, NO_GUARD),
    Scenario("team5_ret01", "Team 5 (ally) bids 20 P for our only RET-01 (worth 11 P)", 273,
             "accept #4167", det_team5, llm_team5, NO_GUARD),
    Scenario("outlier_asks", "Our asks RET-06 55 P / RET-01 40 P on v10, posted by an unknown actor", 268,
             "cancel #4117/#4144 and flag the unknown actor", det_outliers, llm_outliers, NO_GUARD),
    Scenario("ret_no_score", "El Retiro buys do not move our score", 300,
             "avoid_buy_sets RET", det_ret, llm_ret, NO_GUARD),
    Scenario("mal_goals", "MAL-09/MAL-10 worth 91 P complete Malasaña", 230,
             "goals MAL-09/10 at <= 90 P", det_mal, llm_mal, NO_GUARD),
    Scenario("t12_carmen", "Team 12 scores buying El Retiro from Carmen below value", 230,
             "rival analysis of Team 12", det_t12, llm_t12, NO_GUARD),
    Scenario("new_dealer", "A new dealer (Doña Pilar, L3) is announced and goes active", 263,
             "re-plan for Pilar: unlock path", det_pilar, llm_pilar, NO_GUARD, events_from_tick=250),
    Scenario("probe_refused", "Market Test probe refused: price must sit between the ask and the bid", 212,
             "finding on the broker probe bug", det_probe, llm_probe, NO_GUARD),
]
