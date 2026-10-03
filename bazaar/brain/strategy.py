"""The team strategy: what the strategist (bazaar.strategist.run) decided, read by every domain.

    current() -> dict | None             the accepted plan (data/live/strategy.json), cached by mtime
    sanitize(raw) -> dict                 a model's plan, clamped to safe shapes and ranges
    big_changes(old, new) -> list[str]    what in `new` needs a council vote
    merge_accepted(old, new, ok) -> dict  the plan to publish (big parts only when the council accepted)
    prompt_block(domain) -> str           text appended to a domain's Opus prompt ("" without a plan)
    goal_buys() -> {ref: max price}       the strategy's goal cards (core.goal merges them)
    cancel_offers() -> {offer id}         our own offers to cancel (the market domain does it)
    accept_offers() -> {offer id}         offers addressed to us the brain + council decided to accept
    keep_one_exception(sit, ref, offer)   may that accept give our last copy of ref (set <= 50 % held)
    overlay(control) -> control           the strategy's cash policy, duel mode and pauses under the operator's control
    council_vote(old, new, picture) -> dict   three parallel opinions; majority approves

The plan is advice. Rails stay authoritative: goal prices are capped at our value by core.goal, the
cash reserve never drops below MIN_RESERVE, and the operator's control.json always wins.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import time
from pathlib import Path
from typing import Any

from .. import config

STALE_S = 30 * 60               # a plan older than this is ignored (the strategist is down or the game paused)
BIG_GOAL_P = 40                 # a new goal (or a raise) above this needs the council
BIG_GOAL_RAISE_P = 10
MIN_RESERVE, MAX_RESERVE = 5, 80
MAX_SMALL_DEAL = 60
DOMAINS = ("market", "dealers", "duels", "broker")
PAUSABLE = ("market", "dealers")    # duels/broker/packs are never paused by the strategy
REF_RX = re.compile(r"^[A-Z]{3}-\d{2}$")
DUEL_MODES = ("bounded", "full", "code")
MIN_CHECK, MAX_CHECK, DEFAULT_CHECK = 3, 6, 4   # ticks between plans when nothing happens (events: at once)

_cache: dict[str, Any] = {"path": None, "mtime": None, "data": None}


def path(live: Path | None = None) -> Path:
    return Path(live or config.LIVE) / "strategy.json"


def history_path(live: Path | None = None) -> Path:
    return Path(live or config.LIVE) / "strategy.jsonl"


def current(live: Path | None = None, now: float | None = None) -> dict | None:
    """The accepted strategy, or None if there is none or it is stale."""
    p = path(live)
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None
    if _cache["path"] != str(p) or _cache["mtime"] != mt:
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            return None
        _cache.update(path=str(p), mtime=mt, data=data if isinstance(data, dict) else None)
    data = _cache["data"]
    if not data:
        return None
    if (now or time.time()) - float(data.get("updated") or 0) > STALE_S:
        return None
    return data


# --------------------------------------------------------------------------- shapes

def _clean(text: Any, n: int) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:n]


def _int(x, lo: int, hi: int) -> int | None:
    try:
        v = int(round(float(x)))
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, v))


def sanitize(raw: Any) -> dict:
    """Clamp a model's plan to known fields and safe ranges. Unknown fields are dropped."""
    raw = raw if isinstance(raw, dict) else {}
    goals = {}
    for ref, price in (raw.get("goal_buys") or {}).items() if isinstance(raw.get("goal_buys"), dict) else []:
        ref = str(ref).upper().strip()
        p = _int(price, 0, 300)
        if REF_RX.match(ref) and p is not None:
            goals[ref] = p                          # 0 drops an automatic goal
    cp_raw = raw.get("cash_policy") if isinstance(raw.get("cash_policy"), dict) else {}
    cash = {}
    r = _int(cp_raw.get("reserve"), MIN_RESERVE, MAX_RESERVE)
    if r is not None:
        cash["reserve"] = r
    m = _int(cp_raw.get("max_small_deal"), 0, MAX_SMALL_DEAL)
    if m is not None:
        cash["max_small_deal"] = m
    guidance_raw = raw.get("guidance") if isinstance(raw.get("guidance"), dict) else {}
    guidance = {d: _clean(guidance_raw.get(d), 700) for d in DOMAINS if guidance_raw.get(d)}
    pauses = sorted({str(d) for d in raw.get("pause_domains") or [] if str(d) in PAUSABLE}) \
        if isinstance(raw.get("pause_domains"), list) else []
    nxt = _int(raw.get("next_check_in_ticks"), MIN_CHECK, MAX_CHECK) or DEFAULT_CHECK
    findings = []
    for x in (raw.get("findings") or [])[:8] if isinstance(raw.get("findings"), list) else []:
        if isinstance(x, dict) and _clean(x.get("finding"), 400):
            findings.append({"topic": _clean(x.get("topic"), 40) or "general", "finding": _clean(x.get("finding"), 400),
                             "evidence": _clean(x.get("evidence"), 300)})
        elif isinstance(x, str) and _clean(x, 400):
            findings.append({"topic": "general", "finding": _clean(x, 400), "evidence": ""})
    duel_mode = str(raw.get("duel_claude_mode") or "").lower()
    accepts = []
    for x in (raw.get("accept_offers") or [])[:5] if isinstance(raw.get("accept_offers"), list) else []:
        v = _int(x.get("offer") if isinstance(x, dict) else x, 1, 10**9)
        if v is not None:
            accepts.append(v)
    avoid = sorted({str(x).upper().strip()[:3] for x in raw.get("avoid_buy_sets") or []
                    if re.match(r"^[A-Za-z]{3}$", str(x).strip())}) if isinstance(raw.get("avoid_buy_sets"), list) else None
    cancels = []
    for x in (raw.get("cancel_offers") or [])[:10] if isinstance(raw.get("cancel_offers"), list) else []:
        v = _int(x, 1, 10**9)
        if v is not None:
            cancels.append(v)
    min_asks = {}
    for ref, price in list((raw.get("min_asks") or {}).items())[:40] if isinstance(raw.get("min_asks"), dict) else []:
        ref = str(ref).upper().strip()
        p = _int(price, 1, 500)
        if REF_RX.match(ref) and p is not None:
            min_asks[ref] = p
    return {
        **({"min_asks": min_asks} if isinstance(raw.get("min_asks"), dict) else {}),
        **({"venue_announcement": _clean(raw.get("venue_announcement"), 280)}
           if _clean(raw.get("venue_announcement"), 280) else {}),
        "situation": _clean(raw.get("situation"), 900),
        "priorities": [_clean(x, 220) for x in (raw.get("priorities") or [])[:6] if _clean(x, 220)]
        if isinstance(raw.get("priorities"), list) else [],
        "goal_buys": goals,
        "cash_policy": cash,
        "guidance": guidance,
        "pause_domains": pauses,
        "risks": [_clean(x, 200) for x in (raw.get("risks") or [])[:5] if _clean(x, 200)]
        if isinstance(raw.get("risks"), list) else [],
        "next_check_in_ticks": nxt,
        "findings": findings,
        "points_plan": _points_plan(raw.get("points_plan")),
        "expected_next_hour": {k: v for k, v in ((k, _float(v)) for k, v in
                                                 (raw.get("expected_next_hour") or {}).items()
                                                 if k in ("score_delta", "negotiating_delta", "market_delta",
                                                          "deals", "cash_delta"))
                               if v is not None} if isinstance(raw.get("expected_next_hour"), dict) else {},
        "chat_reply": _clean(raw.get("chat_reply"), 1200),
        "chat_summary": _clean(raw.get("chat_summary"), 1500),
        "policies": [{k: _clean(p.get(k), 400) for k in ("id", "text", "status", "reason")}
                     for p in (raw.get("policies") or [])[:6] if isinstance(p, dict)]
        if isinstance(raw.get("policies"), list) else [],
        **({"as_of_tick": _int(raw.get("as_of_tick"), 0, 10**6)} if raw.get("as_of_tick") is not None else {}),
        "cancel_offers": cancels,
        **({"avoid_buy_sets": avoid} if avoid is not None else {}),
        "accept_offers": accepts,
        "post_offers": _post_offers(raw.get("post_offers")),
        "whatsapp_replies": [{"reply_to": _clean(x.get("reply_to"), 60), "text": _clean(x.get("text"), 1500),
                              "why": _clean(x.get("why"), 400), "conclusion": _clean(x.get("conclusion"), 600)}
                             for x in (raw.get("whatsapp_replies") or [])[:6]
                             if isinstance(x, dict) and x.get("reply_to") and (x.get("text") or x.get("conclusion"))]
        if isinstance(raw.get("whatsapp_replies"), list) else [],
        **({"budgets": _budgets(raw.get("budgets"))} if isinstance(raw.get("budgets"), dict) else {}),
        **({"avoid_post_venues": sorted({_clean(v, 12) for v in raw.get("avoid_post_venues") or []
                                         if re.match(r"^v\d{2}$", str(v).strip())})}
           if isinstance(raw.get("avoid_post_venues"), list) else {}),
        "lesson_changes": [{"id": _clean(x.get("id"), 20), "status": x.get("status"), "why": _clean(x.get("why"), 300)}
                           for x in (raw.get("lesson_changes") or [])[:6]
                           if isinstance(x, dict) and x.get("id") and x.get("status") in LESSON_STATUSES]
        if isinstance(raw.get("lesson_changes"), list) else [],
        "code_requests": [{k: _clean(x.get(k), n) for k, n in (("title", 200), ("severity", 10), ("diagnosis", 1500),
                                                              ("proposed_change", 1500), ("impact", 500),
                                                              ("patch_sketch", 2000))}
                          | {"evidence": [_clean(e, 400) for e in (x.get("evidence") or [])[:6]]
                             if isinstance(x.get("evidence"), list) else [_clean(x.get("evidence"), 400)]}
                          for x in (raw.get("code_requests") or [])[:4] if isinstance(x, dict) and x.get("title")]
        if isinstance(raw.get("code_requests"), list) else [],
        "promo_drafts": [{"text": _clean(x.get("text"), 2000), "why": _clean(x.get("why"), 400),
                          "channel": x.get("channel") if x.get("channel") in ("whatsapp", "in_game") else "whatsapp",
                          "to_team": _clean(x.get("to_team"), 12) or None, "to_person": _clean(x.get("to_person"), 80) or None,
                          "audience": x.get("audience") if x.get("audience") in ("team", "person", "group") else None}
                         for x in (raw.get("promo_drafts") or [])[:2] if isinstance(x, dict) and x.get("text")]
        if isinstance(raw.get("promo_drafts"), list) else [],
        "human_tasks": [{"task": _clean(x.get("task"), 400), "why": _clean(x.get("why"), 600)}
                        for x in (raw.get("human_tasks") or [])[:4] if isinstance(x, dict) and x.get("task")]
        if isinstance(raw.get("human_tasks"), list) else [],
        **({"duel_claude_mode": duel_mode} if duel_mode in DUEL_MODES else {}),
        **_broker_policy(raw),
    }


def _broker_policy(raw: dict) -> dict:
    """The broker's Market Test knobs, validated and bounded by bazaar.broker.policy_overlay."""
    if not isinstance(raw.get("broker_policy"), dict):
        return {}
    from bazaar.broker.policy_overlay import validate
    clean, _ = validate(raw["broker_policy"])
    out = {"broker_policy": clean}
    why = _clean(raw.get("broker_policy_why"), 600)
    if why:
        out["broker_policy_why"] = why
    return out


LESSON_STATUSES = ("shadow", "canary", "active", "retired")
LLM_PURPOSES = ("council", "duels", "dealers", "market", "lab", "strategy", "external_intel")
BUDGET_BOUNDS = {"max_spend_per_deal": (10, 120), "max_spend_per_hour": (20, 300)}
LLM_CAP_BOUNDS = (0.5, 40.0)        # USD per purpose per day; the router's per-key 100 $ caps stay on top


def _budgets(raw: dict) -> dict:
    out = {}
    for k, (lo, hi) in BUDGET_BOUNDS.items():
        v = _int(raw.get(k), lo, hi)
        if v is not None:
            out[k] = v
    caps = raw.get("llm_usd_per_day") if isinstance(raw.get("llm_usd_per_day"), dict) else {}
    llm = {}
    for p, v in caps.items():
        f = _float(v)
        if p in LLM_PURPOSES and f is not None:
            llm[p] = max(LLM_CAP_BOUNDS[0], min(LLM_CAP_BOUNDS[1], f))
    if llm:
        out["llm_usd_per_day"] = llm
    return out


def llm_cap(purpose: str, live: Path | None = None) -> float | None:
    """The brain's day cap for one LLM purpose (None = no cap of its own)."""
    caps = ((_plan(live).get("budgets") or {}).get("llm_usd_per_day")) or {}
    v = caps.get(purpose)
    return float(v) if isinstance(v, (int, float)) else None


def _post_offers(raw) -> list[dict]:
    """Targeted offers the brain wants posted: {give: ref, want_card: ref?, want_cash: int?, to: team?, venue, why}."""
    out = []
    for x in (raw or [])[:5] if isinstance(raw, list) else []:
        if not isinstance(x, dict):
            continue
        give = str(x.get("give") or "").upper().strip()
        want_card = str(x.get("want_card") or "").upper().strip() or None
        want_cash = _int(x.get("want_cash"), 1, 500)
        if not REF_RX.match(give) or (want_card and not REF_RX.match(want_card)) or not (want_card or want_cash):
            continue
        to = str(x.get("to") or "").strip() or None
        out.append({"give": give, "want_card": want_card, "want_cash": None if want_card else want_cash,
                    "to": to if to and re.match(r"^t\d{2}$", to) else None,
                    "venue": _clean(x.get("venue"), 12) or "rastro", "why": _clean(x.get("why"), 200)})
    return out


def post_offers(live: Path | None = None) -> list[dict]:
    return list(_plan(live).get("post_offers") or [])


# --------------------------------------------------------------------------- outcomes of the brain's posts
def posts_path(live: Path | None = None) -> Path:
    return Path(live or config.LIVE) / "brain_posts.jsonl"


def post_key(p: dict) -> tuple:
    """What makes two brain posts identical: same card out, same ask (card or cash), same venue, same target."""
    return (str(p.get("give") or ""), str(p.get("want_card") or ""), int(p.get("want_cash") or 0),
            str(p.get("venue") or "rastro"), str(p.get("to") or ""))


def record_post(row: dict, live: Path | None = None) -> None:
    """One line per brain post attempt: {ts, tick, give, want_card, want_cash, venue, to, status, rail, detail,
    offer_id, why}. status: sent | vetoed | refused | error."""
    p = posts_path(live)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), **row}, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def post_history(live: Path | None = None, n: int = 300) -> list[dict]:
    p = posts_path(live)
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def post_outcomes_text(live: Path | None = None, n: int = 10) -> str:
    """The last outcomes of the brain's posts, for its next prompt (so it re-plans what a rail or the server refused)."""
    rows = post_history(live, 200)[-n:]
    lines = []
    for r in rows:
        ask = f"card {r.get('want_card')}" if r.get("want_card") else f"{r.get('want_cash')} P"
        where = f"{r.get('venue') or 'rastro'}" + (f" to {r['to']}" if r.get("to") else "")
        st = r.get("status")
        why = f" by {r.get('rail')}: {r.get('detail')}" if st == "vetoed" else (f": {r.get('detail')}" if r.get("detail") else "")
        lines.append(f"- t{r.get('tick')}: post {r.get('give')} for {ask} on {where} -> {st}{why}"
                     + (f" (offer #{r['offer_id']})" if r.get("offer_id") else ""))
    return "\n".join(lines)


def _float(x) -> float | None:
    try:
        return round(float(x), 2)
    except (TypeError, ValueError):
        return None


def _points_plan(raw) -> dict:
    """{component: {now, target, leader, gap_to_leader, actions: [{action, expected_points}]}}"""
    out = {}
    if not isinstance(raw, dict):
        return out
    for comp, d in list(raw.items())[:6]:
        if not isinstance(d, dict):
            continue
        acts = []
        for a in (d.get("actions") or [])[:5] if isinstance(d.get("actions"), list) else []:
            if isinstance(a, dict) and _clean(a.get("action"), 200):
                acts.append({"action": _clean(a.get("action"), 200), "expected_points": _float(a.get("expected_points"))})
        out[_clean(comp, 30)] = {"now": _float(d.get("now")), "target": _float(d.get("target")),
                                 "leader": _clean(d.get("leader"), 20), "gap_to_leader": _float(d.get("gap_to_leader")),
                                 "actions": acts}
    return out


def big_changes(old: dict | None, new: dict) -> list[str]:
    """Parts of `new` that change money or pause play: they need the council."""
    old = old or {}
    out = []
    og = old.get("goal_buys") or {}
    for ref, p in (new.get("goal_buys") or {}).items():
        before = og.get(ref)
        if p > BIG_GOAL_P and (before is None or p - before > BIG_GOAL_RAISE_P):
            out.append(f"goal {ref} up to {p} P" + (f" (was {before})" if before is not None else ""))
    if (new.get("cash_policy") or {}) != (old.get("cash_policy") or {}) and new.get("cash_policy"):
        out.append(f"cash policy {old.get('cash_policy') or {}} -> {new['cash_policy']}")
    if sorted(new.get("pause_domains") or []) != sorted(old.get("pause_domains") or []) and new.get("pause_domains"):
        out.append(f"pause {new['pause_domains']}")
    if "avoid_buy_sets" in new and sorted(new.get("avoid_buy_sets") or []) != sorted(old.get("avoid_buy_sets") or []):
        out.append(f"avoid buying sets {old.get('avoid_buy_sets') or []} -> {new.get('avoid_buy_sets') or []}")
    if (new.get("budgets") or {}) != (old.get("budgets") or {}) and new.get("budgets"):
        out.append(f"budgets {old.get('budgets') or {}} -> {new['budgets']}")
    if "avoid_post_venues" in new and sorted(new["avoid_post_venues"]) != sorted(old.get("avoid_post_venues") or []):
        out.append(f"stop posting on venues {new['avoid_post_venues']} (was {old.get('avoid_post_venues') or []})")
    fresh = sorted(set(new.get("accept_offers") or []) - set(old.get("accept_offers") or []))
    if fresh:
        out.append(f"accept offers addressed to us {fresh} (may give a last copy)")
    if new.get("duel_claude_mode") and new.get("duel_claude_mode") != old.get("duel_claude_mode"):
        out.append(f"duel mode {old.get('duel_claude_mode')} -> {new['duel_claude_mode']}")
    if "broker_policy" in new and (new.get("broker_policy") or {}) != (old.get("broker_policy") or {}):
        out.append(f"broker policy {old.get('broker_policy') or {}} -> {new.get('broker_policy') or {}}")
    return out


def merge_accepted(old: dict | None, new: dict, council_ok: bool) -> dict:
    """The plan to publish: everything from `new`, but money/pause parts only if the council accepted
    (otherwise the previous ones stay)."""
    if council_ok or not big_changes(old, new):
        return dict(new)
    old = old or {}
    out = dict(new)
    og = old.get("goal_buys") or {}
    goals = {}
    for ref, p in (new.get("goal_buys") or {}).items():
        before = og.get(ref)
        if p > BIG_GOAL_P and (before is None or p - before > BIG_GOAL_RAISE_P):
            if before is not None:
                goals[ref] = before
        else:
            goals[ref] = p
    out["goal_buys"] = goals
    out["cash_policy"] = dict(old.get("cash_policy") or {})
    out["pause_domains"] = list(old.get("pause_domains") or [])
    for k in ("budgets", "avoid_post_venues"):
        if k in old:
            out[k] = old[k]
        else:
            out.pop(k, None)
    if "avoid_buy_sets" in old:
        out["avoid_buy_sets"] = list(old["avoid_buy_sets"])
    else:
        out.pop("avoid_buy_sets", None)
    out["accept_offers"] = [x for x in new.get("accept_offers") or [] if x in set(old.get("accept_offers") or [])]
    if old.get("duel_claude_mode"):
        out["duel_claude_mode"] = old["duel_claude_mode"]
    else:
        out.pop("duel_claude_mode", None)
    if "broker_policy" in old:
        out["broker_policy"] = dict(old["broker_policy"])
        if "broker_policy_why" in old:
            out["broker_policy_why"] = old["broker_policy_why"]
    else:
        out.pop("broker_policy", None)
        out.pop("broker_policy_why", None)
    return out


# --------------------------------------------------------------------------- readers for the bot

def _plan(live: Path | None = None) -> dict:
    cur = current(live)
    return (cur or {}).get("plan") or {}


def venue_announcement(live: Path | None = None) -> str:
    """The brain's text for the next in-game announcement of our venue ("" = the default pitch)."""
    return str(_plan(live).get("venue_announcement") or "")


def goal_buys(live: Path | None = None) -> dict[str, int]:
    return dict(_plan(live).get("goal_buys") or {})


KEEP_ONE_MAX_PAGE_SHARE = 0.5   # an exception to keep-one only for sets we hold at most half of
KEEP_ONE_MIN_GAIN = 5.0         # ...and only for a clear value gain


def accept_offers(live: Path | None = None) -> set[int]:
    """Offers addressed to us that the brain (and the council) decided to accept."""
    return {int(x) for x in _plan(live).get("accept_offers") or [] if isinstance(x, int)}


def keep_one_exception(sit, ref: str, offer_id, live: Path | None = None) -> bool:
    """May we give the last copy of `ref` for this offer? Only for an offer the brain approved, and only
    from a set whose page we hold at most KEEP_ONE_MAX_PAGE_SHARE of (far from the page bonus)."""
    try:
        if int(offer_id) not in accept_offers(live):
            return False
    except (TypeError, ValueError):
        return False
    me = (sit.get("me") if isinstance(sit, dict) else getattr(sit, "me", None)) or {}
    st = str(ref).split("-")[0]
    page = next((p for p in (me.get("album") or {}).get("pages") or [] if p.get("set") == st), None)
    if page and page.get("of"):
        return float(page.get("have") or 0) / float(page["of"]) <= KEEP_ONE_MAX_PAGE_SHARE
    refs = {a.get("ref") for a in me.get("assets") or [] if str(a.get("ref", "")).startswith(st + "-")}
    return len(refs) <= 5


def cancel_offers(live: Path | None = None) -> set[int]:
    """Our own open offers the brain wants cancelled (outliers: far above value/market, or outbid)."""
    return {int(x) for x in _plan(live).get("cancel_offers") or [] if isinstance(x, int)}


def overlay(control: dict, live: Path | None = None) -> dict:
    """The strategy's cash policy and pauses, under what the operator set in control.json."""
    plan = _plan(live)
    if not plan:
        return control
    out = dict(control or {})
    cp = plan.get("cash_policy") or {}
    if "cash_reserve" not in out and cp.get("reserve") is not None:
        out["cash_reserve"] = max(MIN_RESERVE, int(cp["reserve"]))
    if "goal_small_deal_p" not in out and cp.get("max_small_deal") is not None:
        out["goal_small_deal_p"] = int(cp["max_small_deal"])
    if "duel_claude_mode" not in out and plan.get("duel_claude_mode") in DUEL_MODES:
        out["duel_claude_mode"] = plan["duel_claude_mode"]
    for k, v in (plan.get("budgets") or {}).items():
        if k in BUDGET_BOUNDS and k not in out:
            out[k] = v
    if plan.get("min_asks"):                    # per-card minimum asks (a higher floor is always safe)
        out["min_asks"] = {**plan["min_asks"], **(out.get("min_asks") or {})}
    if plan.get("avoid_post_venues"):
        out["avoid_post_venues"] = sorted(set(out.get("avoid_post_venues") or []) | set(plan["avoid_post_venues"]))
    if plan.get("avoid_buy_sets"):                   # union: the operator's list always stays
        out["avoid_buy_sets"] = sorted({str(x).upper() for x in out.get("avoid_buy_sets") or []}
                                       | {str(x).upper() for x in plan["avoid_buy_sets"]})
    pauses = [d for d in plan.get("pause_domains") or [] if d in PAUSABLE]
    if pauses:
        out["paused_domains"] = sorted(set(out.get("paused_domains") or []) | set(pauses))
    return out


def prompt_block(domain: str, live: Path | None = None, now: float | None = None) -> str:
    cur = current(live, now)
    if not cur:
        return ""
    plan = cur.get("plan") or {}
    age = int(((now or time.time()) - float(cur.get("updated") or 0)) // 60)
    lines = [f"TEAM STRATEGY (from our strategist, {age} min old; follow it unless the numbers or the rules say "
             "otherwise; it never overrides value limits):"]
    if plan.get("situation"):
        lines.append("Situation: " + plan["situation"])
    for i, p in enumerate(plan.get("priorities") or [], 1):
        lines.append(f"{i}. {p}")
    if plan.get("guidance", {}).get(domain):
        lines.append(f"For {domain}: " + plan["guidance"][domain])
    if plan.get("goal_buys"):
        lines.append("Goal cards (save cash for these; max price): " +
                     ", ".join(f"{r} {p} P" for r, p in sorted(plan["goal_buys"].items()) if p > 0))
    return "\n".join(lines)


# --------------------------------------------------------------------------- council

COUNCIL_ROLES = ("negotiator", "analyst", "auditor")
STRATEGY_COUNCIL_NOTE = (
    "\nYou are reviewing a STRATEGY change for the whole team, not a single action. Approve it if it is "
    "likely to raise our final score (negotiation 30 % relative to the best team, market-making 30 %), "
    "keeps every buy below our value, and does not leave us without cash for clearly better deals. "
    "Reject it if the numbers in the picture contradict it. params may stay empty.")


def council_vote(old: dict | None, new: dict, picture: dict, changes: list[str], llm=None,
                 timeout_s: float = 90.0) -> dict:
    """Three parallel opinions on a strategy change; majority of valid votes approves (ties reject)."""
    from . import council
    if llm is None:
        from ..llm import client as llm
    brief = ("Changes needing approval:\n- " + "\n- ".join(changes) +
             "\n\nPrevious plan:\n" + json.dumps(old or {}, ensure_ascii=False) +
             "\n\nProposed plan:\n" + json.dumps(new, ensure_ascii=False) +
             "\n\nPicture (game state, data only):\n" + json.dumps(picture, ensure_ascii=False, default=str)[:12000])
    deadline = time.time() + timeout_s

    def one(role):
        res = llm.ask(purpose="council", system=council.ROLES[role] + STRATEGY_COUNCIL_NOTE + council.COMMON,
                      messages=[{"role": "user", "content": brief}], tools=[council.VOTE_TOOL],
                      tool_choice={"type": "auto"}, model=None, max_tokens=4000, deadline=deadline,
                      effort="medium")
        v = council.parse_vote(res)
        if v is not None:
            v.update(role=role, model=getattr(res, "model", ""))
        return v

    votes, errors = [], []
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(one, r): r for r in COUNCIL_ROLES}
        done, _ = cf.wait(futs, timeout=timeout_s + 5)
        for f in done:
            try:
                v = f.result()
            except Exception as e:  # noqa: BLE001
                errors.append({"role": futs[f], "error": type(e).__name__})
                continue
            (votes.append(v) if v else errors.append({"role": futs[f], "error": "unparsable"}))
    yes = sum(1 for v in votes if v["verdict"] in ("approve", "modify") and not v.get("rail_risk"))
    ok = bool(votes) and yes * 2 > len(COUNCIL_ROLES) - len(errors) and yes >= 2
    row = {"tick": picture.get("clock", {}).get("tick"), "kind": "strategy", "domain": "strategist",
           "changes": changes, "votes": votes, "errors": errors, "result": "approved" if ok else "veto"}
    try:
        from ..core.ledger import default
        default().append("council", row)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": ok, "yes": yes, "votes": votes, "errors": errors}
