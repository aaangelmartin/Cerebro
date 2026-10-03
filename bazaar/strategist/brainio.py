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

import re

import json
import threading
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
CHAT_DUP_WINDOW_S = 15.0
_CHAT_LOCK = threading.Lock()


def chat_post(live: Path, text: str, by: str = "", role: str = "user", refs: dict | None = None,
              now: float | None = None) -> dict:
    text = str(text or "").strip()[:2000]
    if not text:
        raise ValueError("text is empty")
    row = {"ts": now or time.time(), "role": role if role in ("user", "brain") else "user",
           "by": str(by or ("cerebro" if role == "brain" else "equipo"))[:40], "text": text}
    if refs:
        row["refs"] = refs
    with _CHAT_LOCK:
        if row["role"] == "user":           # the dashboard sometimes submits twice: same by + text within 15 s
            for r in reversed(read_rows(Path(live) / "brain_chat.jsonl", row["ts"] - CHAT_DUP_WINDOW_S, 50)):
                if r.get("role") == "user" and r.get("by") == row["by"] and r.get("text") == text:
                    return {**r, "duplicate": True}
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


# --------------------------------------------------------------------------- WhatsApp reply_to
def _hhmm(ts) -> str:
    try:
        from zoneinfo import ZoneInfo
        import datetime as _dt
        return _dt.datetime.fromtimestamp(float(ts), ZoneInfo("Europe/Madrid")).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return ""


def resolve_reply_to(raw, records: list[dict]) -> str | None:
    """Map the brain's reply_to to an intake record id. Accepts the id itself; a time label ("11:06", Madrid
    time of the message) or an author/team name only when exactly one record matches. None when ambiguous."""
    raw = str(raw or "").strip()
    if not raw:
        return None
    ids = {str(r.get("id")): r for r in records if r.get("id") is not None}
    if raw in ids:
        return raw
    if raw.strip("[]") in ids:
        return raw.strip("[]")
    import re as _re
    m = _re.search(r"\b(\d{1,2}):(\d{2})\b", raw)
    if m:
        label = f"{int(m.group(1)):02d}:{m.group(2)}"
        hits = [r for r in records if _hhmm(r.get("ts") or r.get("received_at")) == label]
        if len(hits) == 1:
            return str(hits[0].get("id"))
        if len(hits) > 1:
            return None
    low = raw.lower()
    hits = [r for r in records if low and any(low in str(r.get(k) or "").lower() or str(r.get(k) or "").lower() in low
                                              for k in ("author", "by", "team") if r.get(k))]
    return str(hits[0].get("id")) if len(hits) == 1 else None


# --------------------------------------------------------------------------- sanity check
def _num_in(text: str) -> bool:
    return any(ch.isdigit() for ch in str(text or ""))


_ES_WORDS = {"el", "los", "las", "que", "para", "con", "una", "por", "nuestro", "nuestra", "vendemos", "compramos",
             "hola", "gracias", "tienda", "cartas", "precio", "también", "pero", "muy", "está", "están", "hay"}


def looks_non_english(text: str) -> bool:
    """WhatsApp/announcement drafts go to an English-speaking group: flag Spanish-looking text."""
    t = str(text or "").lower()
    if not t.strip():
        return False
    if any(ch in t for ch in "¿¡ñ"):
        return True
    words = [w.strip(".,;:!?()\"'") for w in t.split()]
    hits = sum(1 for w in words if w in _ES_WORDS)
    return hits >= 2 and hits / max(1, len(words)) > 0.06


# --------------------------------------------------------------------------- messages: the game first
# Other teams are run by agents that read /api/me/offers every tick: an addressed offer IS the message.
# WhatsApp stays for alliances and for people who asked us something.
_REF = re.compile(r"\b[A-Z]{3}-\d{2}\b")
_PRICE = re.compile(r"\b(\d{1,3})\s*P\b")
_OWN_VENUE = re.compile(r"\bv0?7\b", re.I)
_WE_SELL = re.compile(r"\b(we have|we hold|our spare|we can sell|we sell|we are selling|we offer|for you at)\b", re.I)
_FILLER = re.compile(r"^\W*(thanks|thank you|noted|got it|ok(ay)?|great|perfect|pleasure|cheers|done|all good)\b", re.I)
MAX_WHATSAPP_DRAFTS = 1


def is_pitch(text: str) -> bool:
    """A sell/buy pitch or a nudge to trade on our venue: things an in-game offer or announcement says better."""
    t = str(text or "")
    return bool(_REF.search(t)) or bool(_OWN_VENUE.search(t))


def reply_is_filler(text: str, record: dict | None = None) -> bool:
    """A WhatsApp reply nobody needs: the sender asked nothing and the text is a courtesy."""
    t = str(text or "").strip()
    if not t:
        return False
    if record is not None:
        asked = ("?" in str(record.get("text") or "") or bool(record.get("actionable"))
                 or bool(_REF.search(str(record.get("text") or "")))      # a proposal about a card
                 or bool(
            {"request", "question", "complaint", "offer_ref"} & set(record.get("types") or [])))
        if not asked:
            return True                                   # they asked nothing: no reply needed
        return bool(_FILLER.match(t)) and "?" not in t and len(t) < 120 and not _num_in(t)
    return bool(_FILLER.match(t)) and "?" not in t and len(t) < 200 and not _num_in(t)


def pitch_to_offer(draft: dict, held: set[str]) -> dict | None:
    """'Team 9: we have MAL-02 for you at 6 P' -> an offer addressed to t09 (the rails still price-check it)."""
    text = str(draft.get("text") or "")
    refs = set(_REF.findall(text))
    prices = _PRICE.findall(text)
    to = draft.get("to_team")
    if not to:
        try:
            from bazaar.outbox.store import recipient
            to = recipient(text).get("to_team")
        except Exception:  # noqa: BLE001
            to = None
    if (not to or not re.match(r"^t\d{2}$", str(to)) or len(refs) != 1 or len(prices) != 1
            or not _WE_SELL.search(text) or _OWN_VENUE.search(text)):
        return None
    ref = next(iter(refs))
    if ref not in held:
        return None
    return {"give": ref, "want_card": None, "want_cash": int(prices[0]), "to": to, "venue": "rastro",
            "why": "addressed offer instead of a WhatsApp pitch"}


def message_policy(plan: dict, held: set[str] | None = None, allies: set[str] | None = None) -> dict:
    """Talk to the other teams' agents in the game, not on WhatsApp. Sell pitches become addressed offers,
    venue nudges belong in the in-game announcement, and at most one proactive WhatsApp draft survives (allies
    or something an offer cannot say). Courtesy replies lose their text. What was dropped is in `messages_dropped`."""
    if allies is None:
        try:
            from bazaar.market.protocol import ALLIED_VENUES
            allies = set(ALLIED_VENUES.values())
        except Exception:  # noqa: BLE001
            allies = set()
    held = set(held or [])
    out = dict(plan)
    dropped, keep = [], []
    posts = list(plan.get("post_offers") or [])
    for d in plan.get("promo_drafts") or []:
        text = str(d.get("text") or "")
        to = d.get("to_team")
        if not to:
            try:
                from bazaar.outbox.store import recipient
                to = recipient(text).get("to_team")
            except Exception:  # noqa: BLE001
                to = None
        if d.get("channel") == "in_game":
            if not out.get("venue_announcement") and len(text) <= 280 and _OWN_VENUE.search(text):
                out["venue_announcement"] = text
            dropped.append({"text": text[:120], "why": "in-game text goes in venue_announcement"})
            continue
        if to in allies:
            keep.append(d)
            continue
        if is_pitch(text):
            offer = pitch_to_offer({**d, "to_team": to}, held)
            same = offer and any(p.get("give") == offer["give"] and p.get("to") == offer["to"] for p in posts)
            if offer and not same and len(posts) < 5:
                posts.append(offer)
            dropped.append({"text": text[:120], "why": "addressed offer posted instead" if offer else
                            "pitch or venue nudge: use post_offers / venue_announcement"})
            continue
        keep.append(d)
    keep.sort(key=lambda d: 0 if (d.get("to_team") in allies) else 1)
    for d in keep[MAX_WHATSAPP_DRAFTS:]:
        dropped.append({"text": str(d.get("text") or "")[:120], "why": "more than one WhatsApp draft in a plan"})
    out["promo_drafts"] = keep[:MAX_WHATSAPP_DRAFTS]
    out["post_offers"] = posts
    reps = []
    for r in plan.get("whatsapp_replies") or []:
        if reply_is_filler(r.get("text")):
            dropped.append({"text": str(r.get("text") or "")[:120], "why": "courtesy reply nobody asked for"})
            r = {**r, "text": ""}
        reps.append(r)
    out["whatsapp_replies"] = reps
    if dropped:
        out["messages_dropped"] = dropped
    return out


# --------------------------------------------------------------------------- aiming to win
WIN_TOL = 0.05


def win_text(win: dict | None) -> str:
    """The win math as a short prompt block (the full numbers are in the picture under win_math)."""
    if not isinstance(win, dict) or not win.get("components"):
        return ""
    lines = [f"\n\nWIN MATH (computed by code; mission: {win.get('mission')}; hours left today "
             f"{win.get('hours_left_today')}, tomorrow {win.get('hours_tomorrow')}):"]
    for comp in ("score", "negotiating", "market"):
        c = (win.get("components") or {}).get(comp) or {}
        if not c:
            continue
        lines.append(f"- {comp}: we {c.get('now')}, leader {c.get('leader')} {c.get('leader_score')}, gap {c.get('gap')}, "
                     f"required +{c.get('required_per_hour')}/h (we made {c.get('our_gain_last_hour')} last hour), "
                     f"min target next hour {c.get('min_target_next_hour')}")
    for comp in ("negotiating", "market"):
        for a in (win.get("action_menu") or {}).get(comp) or []:
            cash = f", needs {a.get('cash')} P" if a.get("cash") else ""
            short = f" (short by {a.get('cash_short')} P)" if not a.get("feasible") else ""
            short += "" if a.get("next_hour", True) else " (later today, not this hour)"
            lines.append(f"- [{a.get('id')}] {a.get('action')} -> +{a.get('expected_points')} points{cash}{short}; "
                         f"plan field: {a.get('how')}")
    lines.append("Set each points_plan target at or above its min target, cite the menu ids you use, and put each "
                 "used action in its plan field so the bot executes it.")
    return "\n".join(lines)


def _menu_unused(plan_comp: dict, menu: list[dict]) -> list[dict]:
    text = " ".join(str(a.get("action") or "") for a in plan_comp.get("actions") or [])
    return [m for m in menu if m.get("feasible") and m.get("next_hour", True) and (m.get("expected_points") or 0) > 0
            and f"[{m.get('id')}]" not in text and f"{m.get('id')} " not in text and f"{m.get('id')}:" not in text]


def win_errors(plan: dict, win: dict | None) -> list[str]:
    """A plan may not under-aim: per component the target reaches the required pace, or it names the binding
    constraint with numbers and still uses every feasible menu action."""
    if not isinstance(win, dict) or not win.get("components"):
        return []
    errors = []
    pp = plan.get("points_plan") or {}
    for comp in ("negotiating", "market"):
        c = (win.get("components") or {}).get(comp) or {}
        menu = (win.get("action_menu") or {}).get(comp) or []
        need_target = c.get("min_target_next_hour")
        d = pp.get(comp)
        if not isinstance(d, dict):
            if need_target is not None and ((c.get("gap") or 0) > 0 or _menu_unused({}, menu)):
                errors.append(f"points_plan.{comp} is missing (min target next hour {need_target})")
            continue
        target, now = d.get("target"), c.get("now")
        acts = d.get("actions") or []
        total = sum(float(a.get("expected_points") or 0) for a in acts)
        unused = _menu_unused(d, menu)
        ids = ", ".join(f"[{m['id']}] +{m['expected_points']}" for m in unused)
        constrained = bool(d.get("constraint")) and _num_in(d.get("constraint"))
        low = need_target is not None and (target is None or target + WIN_TOL < need_target)
        if low and not constrained:
            errors.append(f"points_plan.{comp} target {target} is below the pace to pass the leader (min "
                          f"{need_target}: we {now}, leader {c.get('leader_score')}, required "
                          f"+{c.get('required_per_hour')}/h): raise it, or state `constraint` with numbers")
        if unused and (low or (target is not None and now is not None and total + WIN_TOL < target - now) or not acts):
            errors.append(f"points_plan.{comp} leaves feasible win_math menu actions unused: {ids}. Use them (cite "
                          f"the id in the action and fill the plan field in `how`)")
    return errors


def win_repair(plan: dict, win: dict | None) -> dict:
    """After one re-ask the plan still under-aims: code fills in the unused feasible menu actions and lifts the
    target to what they add up to (capped by the required pace). Menu accepts go into accept_offers."""
    if not isinstance(win, dict) or not win.get("components"):
        return plan
    out = dict(plan)
    pp = {k: dict(v) for k, v in (plan.get("points_plan") or {}).items() if isinstance(v, dict)}
    accepts = list(out.get("accept_offers") or [])
    for comp in ("negotiating", "market"):
        c = (win.get("components") or {}).get(comp) or {}
        menu = (win.get("action_menu") or {}).get(comp) or []
        d = pp.setdefault(comp, {"now": c.get("now"), "target": None, "leader": c.get("leader"),
                                 "gap_to_leader": c.get("gap"), "actions": []})
        acts = list(d.get("actions") or [])
        for m in _menu_unused(d, menu):
            acts.append({"action": f"[{m['id']}] {m['action']}"[:200], "expected_points": m["expected_points"]})
            if m.get("how") == "accept_offers" and m.get("offer") is not None and m["offer"] not in accepts:
                accepts.append(m["offer"])
        d["actions"] = acts[:8]
        total = sum(float(a.get("expected_points") or 0) for a in d["actions"])
        now, need = c.get("now"), c.get("min_target_next_hour")
        if now is not None:
            reach = round(now + total, 2)
            cur = d.get("target")
            if need is not None and (cur is None or cur + WIN_TOL < need):
                d["target"] = round(min(need, max(reach, cur or now)), 2) if reach < need else need
                if reach + WIN_TOL < need and not d.get("constraint"):
                    d["constraint"] = (f"every feasible action this hour adds +{total:.2f}; the pace to pass the "
                                       f"leader needs +{need - now:.2f}")
    out["points_plan"] = pp
    out["accept_offers"] = accepts[:6]
    return out


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
    for i, d in enumerate(plan.get("promo_drafts") or [], 1):
        if looks_non_english(d.get("text")):
            errors.append(f"promo_draft {i} is not in English (the WhatsApp group and in-game chat are in English)")
    for i, r in enumerate(plan.get("whatsapp_replies") or [], 1):
        if looks_non_english(r.get("text")):
            errors.append(f"whatsapp_reply {i} is not in English (the WhatsApp group is in English)")
    if looks_non_english(plan.get("venue_announcement")):
        errors.append("venue_announcement is not in English (the in-game board is in English)")
    pp = plan.get("points_plan") or {}
    if not pp:
        errors.append("points_plan is missing (targets per component, gap to the leader, actions with expected points)")
    errors.extend(win_errors(plan, pic.get("win_math")))
    tick = (pic.get("clock") or {}).get("tick")
    if isinstance(tick, int) and isinstance(plan.get("as_of_tick"), int) and tick - plan["as_of_tick"] > 6:
        errors.append(f"plan says as_of_tick {plan['as_of_tick']} but the game is at {tick}: stale facts")
    return errors


# --------------------------------------------------------------------------- hourly review
def hourly_review(live: Path, scoreboard_now: dict, now: float | None = None, window_s: float = 3600,
                  win: dict | None = None) -> dict | None:
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
    pace = {}
    for comp, c in ((win or {}).get("components") or {}).items():
        need = c.get("required_per_hour")
        got = realised.get(comp)
        if need is not None and got is not None:
            pace[comp] = {"required_per_hour": need, "realised_last_hour": got, "behind": got + 1e-9 < need}
            if got + 1e-9 < need:
                verdict.append(f"{comp}: BEHIND the pace to pass the leader (need +{need:.2f}/h, got {got:+.2f})")
    row = {"ts": now, "tick": (scoreboard_now or {}).get("tick"), "plan_tick": p.get("tick"),
           "plan_ts": p.get("updated"), "expected": exp, "realised": realised, "pace": pace,
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
    if any(e.startswith("promo_draft ") for e in errors):
        out["promo_drafts"] = [d for d in plan.get("promo_drafts") or [] if not looks_non_english(d.get("text"))]
    if any(e.startswith("whatsapp_reply ") for e in errors):
        out["whatsapp_replies"] = [{**r, "text": ""} if looks_non_english(r.get("text")) else r
                                   for r in plan.get("whatsapp_replies") or []]
    if any(e.startswith("venue_announcement ") for e in errors):
        out.pop("venue_announcement", None)
    if any(e.startswith("points_plan.") for e in errors):
        out = win_repair(out, pic.get("win_math"))
    out["validation_errors"] = errors
    return out
