"""El cerebro's files: chat, memory (policies), events, reviews, and the code-side sanity check of a plan.

Files in data/live (one JSON object per line unless noted):

  brain_chat.jsonl     {"ts": float, "role": "user"|"brain", "by": str, "text": str, "refs": {...}?}
                       users write through POST /brain/chat; the brain answers after its next run
  brain_memory.json    {"updated": float, "chat_summary": str, "policies": [{"id": "P1", "text": str, "from": "chat"|"brain"|"review",
                        "by": str, "since": float, "status": "active"|"retired", "reason": str, "updated": float}]}
                       (a JSON document) durable policies shown in every prompt; the brain re-evaluates them
  brain_events.jsonl   {"ts": float, "tick": int|null, "kind": str, "text": str, "data": {...}}
                       kind: dealer | level | set | schedule | venue | score | us | offer | novelty | chat | review
  strategist_findings.jsonl  {"ts", "tick", "topic", "finding", "evidence"}
  strategist_reviews.jsonl   {"ts", "tick", "plan_tick", "plan_ts", "expected": {...}, "realised": {...}, "verdict": str}
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

MAX_POLICIES = 30


def _append(path: Path, row: dict) -> None:
    with Path(path).open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def read_rows(path: Path, since: float | None = None, limit: int = 200) -> list[dict]:
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines[-5000:]:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if since is not None and float(r.get("ts") or 0) <= since:
            continue
        out.append(r)
    return out[-limit:]


# --------------------------------------------------------------------------- chat
def chat_post(live: Path, text: str, by: str = "", role: str = "user", refs: dict | None = None,
              now: float | None = None) -> dict:
    text = str(text or "").strip()[:2000]
    if not text:
        raise ValueError("text is empty")
    row = {"ts": now or time.time(), "role": role if role in ("user", "brain") else "user",
           "by": str(by or ("cerebro" if role == "brain" else "equipo"))[:40], "text": text}
    if refs:
        row["refs"] = refs
    _append(Path(live) / "brain_chat.jsonl", row)
    return row


def chat_since(live: Path, since: float | None = None, limit: int = 200) -> list[dict]:
    return read_rows(Path(live) / "brain_chat.jsonl", since, limit)


# --------------------------------------------------------------------------- memory
def memory(live: Path) -> dict:
    try:
        d = json.loads((Path(live) / "brain_memory.json").read_text())
        return d if isinstance(d, dict) else {"policies": []}
    except (OSError, ValueError):
        return {"policies": []}


def set_memory(live: Path, key: str, value) -> None:
    mem = memory(live)
    mem[key] = value
    mem["updated"] = time.time()
    path = Path(live) / "brain_memory.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(mem, ensure_ascii=False, indent=1))
    tmp.replace(path)


def apply_policies(live: Path, updates: list[dict], by: str = "brain", now: float | None = None) -> list[dict]:
    """Add or update policies: {id?, text, status, reason, from?}. Returns the changed ones."""
    now = now or time.time()
    mem = memory(live)
    pols = mem.get("policies") or []
    by_id = {p.get("id"): p for p in pols}
    changed = []
    for u in updates or []:
        if not isinstance(u, dict):
            continue
        pid = str(u.get("id") or "").strip()
        text = str(u.get("text") or "").strip()[:400]
        status = u.get("status") if u.get("status") in ("active", "retired") else "active"
        if pid and pid in by_id:
            p = by_id[pid]
            if text:
                p["text"] = text
            p.update(status=status, reason=str(u.get("reason") or p.get("reason") or "")[:300], updated=now)
            changed.append(p)
        elif text:
            nid = f"P{1 + max([int(str(x)[1:]) for x in by_id if str(x)[1:].isdigit()] or [0])}"
            p = {"id": nid, "text": text, "from": u.get("from") or by, "by": u.get("by") or by, "since": now,
                 "status": status, "reason": str(u.get("reason") or "")[:300], "updated": now}
            pols.append(p)
            by_id[nid] = p
            changed.append(p)
    active = [p for p in pols if p.get("status") == "active"]
    retired = [p for p in pols if p.get("status") != "active"]
    mem["policies"] = (active + retired)[:MAX_POLICIES]
    mem["updated"] = now
    path = Path(live) / "brain_memory.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(mem, ensure_ascii=False, indent=1))
    tmp.replace(path)
    return changed


# --------------------------------------------------------------------------- events
def log_event(live: Path, kind: str, text: str, tick=None, data: dict | None = None, now: float | None = None) -> dict:
    row = {"ts": now or time.time(), "tick": tick, "kind": kind, "text": str(text)[:400], "data": data or {}}
    _append(Path(live) / "brain_events.jsonl", row)
    return row


# --------------------------------------------------------------------------- sanity check
def _num_in(text: str) -> bool:
    return any(ch.isdigit() for ch in str(text or ""))


def validate(plan: dict, pic: dict) -> list[str]:
    """Code-side checks of a sanitised plan against the picture. Returns errors (empty = valid)."""
    errors = []
    sets = pic.get("sets") or {}
    missing_value = {m["ref"]: m.get("value_to_us") for s in sets.values() for m in s.get("missing") or []}
    page_refs = set(missing_value)
    avoid = set(plan.get("avoid_buy_sets") or []) | set((pic.get("control") or {}).get("avoid_buy_sets") or [])
    held_refs = set(pic.get("held_refs") or [])
    for ref, p in (plan.get("goal_buys") or {}).items():
        if p <= 0:
            continue
        if ref[:3] in avoid:
            errors.append(f"goal {ref} is in a set we avoid buying ({sorted(avoid)})")
        if ref in held_refs:
            errors.append(f"goal {ref}: we already hold it")
        elif ref not in page_refs:
            errors.append(f"goal {ref} is not a missing page card")
        v = missing_value.get(ref)
        if v is not None and p >= v:
            errors.append(f"goal {ref} at {p} P is not below its value to us ({v})")
    cash = (pic.get("us") or {}).get("cash")
    cp = plan.get("cash_policy") or {}
    if isinstance(cash, (int, float)) and cp.get("reserve") is not None and cp["reserve"] > max(cash, 0) + 40:
        errors.append(f"reserve {cp['reserve']} P is far above our cash {cash} P")
    to_us = {o.get("offer") for o in ((pic.get("research") or {}).get("offers_to_us") or [])}
    to_us |= {o.get("offer") for o in ((pic.get("card_needs") or {}).get("opportunities") or [])
              if o.get("kind") in ("sell_to_bid", "buy_below_value") and o.get("offer") is not None}
    for oid in plan.get("accept_offers") or []:
        if oid not in to_us:
            errors.append(f"accept_offers {oid} is not an open offer addressed to us or listed in card_needs")
    for p in plan.get("post_offers") or []:
        if p.get("give") not in held_refs:
            errors.append(f"post_offers gives {p.get('give')}, which we do not hold")
        if p.get("want_card") and p["want_card"][:3] in avoid:
            errors.append(f"post_offers wants {p['want_card']}, a set we avoid")
    ours = set(pic.get("our_open_offer_ids") or [])
    for oid in plan.get("cancel_offers") or []:
        if ours and oid not in ours:
            errors.append(f"cancel_offers {oid} is not one of our open offers")
    for i, pr in enumerate(plan.get("priorities") or [], 1):
        if not _num_in(pr):
            errors.append(f"priority {i} cites no number (values, prices or scores): '{pr[:80]}'")
    for k, g in (plan.get("guidance") or {}).items():
        for ref in avoid:
            if f"buy {ref}" in g or f"Buy {ref}" in g:
                errors.append(f"guidance.{k} tells to buy {ref}, a set we avoid")
    pp = plan.get("points_plan") or {}
    if not pp:
        errors.append("points_plan is missing (targets per component, gap to the leader, actions with expected points)")
    tick = (pic.get("clock") or {}).get("tick")
    if isinstance(tick, int) and isinstance(plan.get("as_of_tick"), int) and tick - plan["as_of_tick"] > 6:
        errors.append(f"plan says as_of_tick {plan['as_of_tick']} but the game is at {tick}: stale facts")
    return errors


# --------------------------------------------------------------------------- hourly review
def hourly_review(live: Path, scoreboard_now: dict, now: float | None = None, window_s: float = 3600) -> dict | None:
    """Compare the plan published about an hour ago (its expected_next_hour) with what happened since."""
    now = now or time.time()
    plans = read_rows(Path(live) / "strategy.jsonl", None, 400)
    old = [p for p in plans if now - float(p.get("updated") or p.get("ts") or 0) >= window_s * 0.9]
    if not old:
        return None
    p = old[-1]
    exp = ((p.get("plan") or {}).get("expected_next_hour")) or {}
    base = p.get("score_at_plan") or {}
    us_now = (scoreboard_now or {}).get("us_now") or {}
    realised = {k: round(float(us_now.get(k) or 0) - float(base.get(k) or 0), 2)
                for k in ("score", "negotiating", "market") if base.get(k) is not None}
    verdict = []
    for k, v in realised.items():
        e = exp.get(f"{k}_delta")
        if isinstance(e, (int, float)):
            verdict.append(f"{k}: expected {e:+.2f}, got {v:+.2f}")
    row = {"ts": now, "tick": (scoreboard_now or {}).get("tick"), "plan_tick": p.get("tick"),
           "plan_ts": p.get("updated"), "expected": exp, "realised": realised,
           "verdict": "; ".join(verdict) or "no expectation to compare"}
    _append(Path(live) / "strategist_reviews.jsonl", row)
    return row


def repair(plan: dict, pic: dict, errors: list[str]) -> dict:
    """Drop the parts of a plan that still fail the sanity check (after one re-ask), keep the rest."""
    out = dict(plan)
    bad_goals = {e.split()[1] for e in errors if e.startswith("goal ")}
    out["goal_buys"] = {r: p for r, p in (plan.get("goal_buys") or {}).items() if r not in bad_goals}
    bad_acc = {e.split()[1] for e in errors if e.startswith("accept_offers ")}
    out["accept_offers"] = [x for x in plan.get("accept_offers") or [] if str(x) not in bad_acc]
    bad_can = {e.split()[1] for e in errors if e.startswith("cancel_offers ")}
    out["cancel_offers"] = [x for x in plan.get("cancel_offers") or [] if str(x) not in bad_can]
    if any(e.startswith("reserve ") for e in errors):
        out["cash_policy"] = {k: v for k, v in (plan.get("cash_policy") or {}).items() if k != "reserve"}
    out["validation_errors"] = errors
    return out
