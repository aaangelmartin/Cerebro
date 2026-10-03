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
    return {
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
        "cancel_offers": cancels,
        **({"avoid_buy_sets": avoid} if avoid is not None else {}),
        "accept_offers": accepts,
        **({"duel_claude_mode": duel_mode} if duel_mode in DUEL_MODES else {}),
    }


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
    fresh = sorted(set(new.get("accept_offers") or []) - set(old.get("accept_offers") or []))
    if fresh:
        out.append(f"accept offers addressed to us {fresh} (may give a last copy)")
    if new.get("duel_claude_mode") and new.get("duel_claude_mode") != old.get("duel_claude_mode"):
        out.append(f"duel mode {old.get('duel_claude_mode')} -> {new['duel_claude_mode']}")
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
    if "avoid_buy_sets" in old:
        out["avoid_buy_sets"] = list(old["avoid_buy_sets"])
    else:
        out.pop("avoid_buy_sets", None)
    out["accept_offers"] = [x for x in new.get("accept_offers") or [] if x in set(old.get("accept_offers") or [])]
    if old.get("duel_claude_mode"):
        out["duel_claude_mode"] = old["duel_claude_mode"]
    else:
        out.pop("duel_claude_mode", None)
    return out


# --------------------------------------------------------------------------- readers for the bot

def _plan(live: Path | None = None) -> dict:
    cur = current(live)
    return (cur or {}).get("plan") or {}


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
                      tool_choice={"type": "auto"}, model=None, max_tokens=700, deadline=deadline)
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
