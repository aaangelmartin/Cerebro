"""Hard limits on what the brain and the council may spend, whatever triggers arrive.

The intensity level gives a minimum gap between plans that no game event can shorten: events only mark the
picture "dirty" and are read at the next allowed slot. A team chat message may cut the gap, coalesced (all the
messages waiting are answered in one plan). A true emergency (a big bargain that needs funding, a duel session
starting) may cut it too, once in a while. On top, a rolling 30-minute spend bucket per purpose, derived from
the budget plan, stops the brain and the council's model calls when they run ahead of their hourly target.
Duels and the per-tick dealer/market decisions are never limited here.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from bazaar import config

WINDOW_S = 1800.0                   # the rolling window of the spend buckets
SLACK = 1.25                        # a purpose may run this far above its hourly target inside the window
CHAT_SLACK = 2.0                    # a team chat message may still get a plan up to this multiple
CHAT_COALESCE_S = 120.0             # at most one chat-triggered plan this often
EMERGENCY_GAP_S = 60.0              # a true emergency may plan this soon after the last plan...
EMERGENCY_EVERY_S = 600.0           # ...but only once in this long
EMERGENCY_GAIN_P = 25               # a bargain worth this much that still needs cash
COUNCIL_CACHE_TICKS = 30            # one vote per distinct proposal
SMALL_SPEND_P = 25                  # below intensity 50 only money moves this big go to the model
LOW_LEVEL = 50
MIN_STRATEGY_USD_H = 1.0            # floors so a tiny remainder never freezes the brain or the council entirely
MIN_COUNCIL_USD_H = 0.6
_GAP = ((0, 600), (20, 420), (40, 240), (50, 180), (70, 120), (100, 90))
MATERIAL = ("goal ", "accept_offers", "cancel_offers", "post_offers", "reserve ", "promo_draft", "whatsapp_reply",
            "no priorities", "dealer_orders", "workshop")
MONEY_WORDS = ("goal ", "cash policy", "budgets", "pause ", "accept offers")


def _lerp(points, x: float) -> float:
    x = max(points[0][0], min(points[-1][0], float(x)))
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def min_gap_s(level: float) -> float:
    """Seconds that must pass between two brain plans at this intensity (level 40 -> 240 s)."""
    return round(_lerp(_GAP, level))


# ----------------------------------------------------------------------------- real spend from llm.jsonl
def _tail_rows(path: Path, since: float, max_bytes: int = 1_500_000) -> list[dict]:
    out = []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if float(r.get("ts") or 0) >= since:
                    out.append(r)
    except OSError:
        pass
    return out


def spent_window(live: Path | None = None, purposes: tuple[str, ...] | None = None, window_s: float = WINDOW_S,
                 now: float | None = None, rows: list[dict] | None = None) -> float:
    """Dollars spent in the last `window_s` on these purposes (all purposes when None)."""
    now = now or time.time()
    if rows is None:
        rows = _tail_rows(Path(live or config.LIVE) / "llm.jsonl", now - window_s)
    return round(sum(float(r.get("cost_usd") or 0.0) for r in rows
                     if float(r.get("ts") or 0) >= now - window_s and (purposes is None or r.get("purpose") in purposes)), 4)


def trailing(live: Path | None = None, now: float | None = None, window_s: float = WINDOW_S) -> dict:
    """The real spend rate, dollars per hour, over the last `window_s`: all purposes, the brain, the council."""
    now = now or time.time()
    rows = _tail_rows(Path(live or config.LIVE) / "llm.jsonl", now - window_s)
    k = 3600.0 / window_s
    by: dict[str, float] = {}
    for r in rows:
        if r.get("cost_usd"):
            by[str(r.get("purpose"))] = by.get(str(r.get("purpose")), 0.0) + float(r["cost_usd"])
    return {"window_s": window_s, "all": round(sum(by.values()) * k, 2),
            "brain": round(by.get("strategy", 0.0) * k, 2), "council": round(by.get("council", 0.0) * k, 2),
            "by_purpose": {p: round(v * k, 2) for p, v in sorted(by.items(), key=lambda x: -x[1])}}


def targets(plan: dict | None, hours_left: float, level_usd_h: float | None = None) -> dict:
    """Dollars per hour each limited purpose may spend from now, from the budget plan (budget.event_plan)."""
    plan = plan or {}
    hl = max(float(hours_left or 0.0), 0.25)
    caps = plan.get("purpose_caps") or {}
    spent = plan.get("spent_by_purpose") or {}
    brain_left = plan.get("brain_left_today")
    if brain_left is None and caps.get("strategy") is not None:
        brain_left = float(caps["strategy"]) - float(spent.get("strategy") or 0.0)
    strat = float(brain_left) / hl if brain_left is not None else (level_usd_h or 4.0)
    if level_usd_h:
        strat = min(strat, float(level_usd_h))          # a manual level means its own cost, not the cap's
    council = ((float(caps["council"]) - float(spent.get("council") or 0.0)) / hl) if caps.get("council") is not None else 2.0
    return {"strategy": round(max(MIN_STRATEGY_USD_H, strat), 2), "council": round(max(MIN_COUNCIL_USD_H, council), 2)}


def bucket(purpose: str, target_usd_h: float, live: Path | None = None, now: float | None = None,
           slack: float = SLACK, rows: list[dict] | None = None) -> dict:
    """{ok, spent, allowed}: the rolling-window spend of `purpose` against target x slack."""
    allowed = round(float(target_usd_h) * slack * WINDOW_S / 3600.0, 4)
    spent = spent_window(live, (purpose,), WINDOW_S, now, rows)
    return {"ok": spent < allowed, "spent": spent, "allowed": allowed, "purpose": purpose}


# ----------------------------------------------------------------------------- when may the brain plan
def is_emergency(events: list[dict], session_start: bool = False) -> bool:
    """A bargain worth EMERGENCY_GAIN_P or more that still needs cash, or a duel session starting."""
    if session_start:
        return True
    for e in events or []:
        if e.get("kind") != "bargain":
            continue
        d = e.get("data") or {}
        try:
            if float(d.get("gain") or 0) >= EMERGENCY_GAIN_P and float(d.get("gap") or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def gate(*, now: float, level: float, last_plan_ts: float, has_chat: bool, last_chat_plan_ts: float = 0.0,
         emergency: bool = False, last_emergency_ts: float = 0.0, strategy_bucket: dict | None = None,
         chat_bucket_ok: bool = True) -> dict:
    """May the brain plan now? {ok, why, kind}: kind is "chat", "emergency" or "slot"."""
    since = now - float(last_plan_ts or 0.0)
    gap = min_gap_s(level)
    b = strategy_bucket or {"ok": True}
    if has_chat:
        if now - float(last_chat_plan_ts or 0.0) < CHAT_COALESCE_S or since < 10.0:
            return {"ok": False, "why": "team messages wait to be answered together", "kind": "chat"}
        if not chat_bucket_ok:
            return {"ok": False, "why": "brain spend far above its pace: the team message waits", "kind": "chat"}
        return {"ok": True, "why": "", "kind": "chat"}
    if not b.get("ok", True):
        return {"ok": False, "why": "brain spend above its pace (%.2f of %.2f $ in 30 min): keeping the last plan"
                % (b.get("spent", 0.0), b.get("allowed", 0.0)), "kind": "slot"}
    if emergency and since >= EMERGENCY_GAP_S and now - float(last_emergency_ts or 0.0) >= EMERGENCY_EVERY_S:
        return {"ok": True, "why": "", "kind": "emergency"}
    if since < gap:
        return {"ok": False, "why": "next plan in %d s (intensity %d)" % (gap - since, level), "kind": "slot"}
    return {"ok": True, "why": "", "kind": "slot"}


def material(errors: list[str]) -> bool:
    """Do these sanity-check errors justify a second (paid) answer? Wording-only errors are repaired in code."""
    return any(str(e).startswith(MATERIAL) for e in errors or [])


# ----------------------------------------------------------------------------- the brain's council votes
def money_changes(changes: list[str]) -> list[str]:
    return [c for c in changes or [] if str(c).startswith(MONEY_WORDS)]


def _amounts(text: str) -> list[float]:
    out, cur = [], ""
    for ch in str(text) + " ":
        if ch.isdigit() or (ch == "." and cur):
            cur += ch
        elif cur:
            try:
                out.append(float(cur.rstrip(".")))
            except ValueError:
                pass
            cur = ""
    return out


def votable(changes: list[str], level: float) -> list[str]:
    """The changes that deserve a model vote at this level: below 50, only money moves of SMALL_SPEND_P or more
    (and pauses); from 50, every money move plus the minor ones."""
    if level >= LOW_LEVEL:
        return list(changes or [])
    out = []
    for c in money_changes(changes):
        if str(c).startswith(("pause ", "accept offers")) or any(a >= SMALL_SPEND_P for a in _amounts(c)):
            out.append(c)
    return out


def vote_key(changes: list[str]) -> str:
    return hashlib.sha1(json.dumps(sorted(str(c) for c in changes or []), ensure_ascii=False).encode()).hexdigest()[:16]


class VoteCache:
    """One council vote per distinct proposal: the same set of changes within COUNCIL_CACHE_TICKS reuses it."""

    def __init__(self, ticks: int = COUNCIL_CACHE_TICKS):
        self.ticks, self.rows = ticks, {}

    def get(self, changes: list[str], tick) -> dict | None:
        hit = self.rows.get(vote_key(changes))
        if hit and isinstance(tick, int) and isinstance(hit.get("tick"), int) and 0 <= tick - hit["tick"] <= self.ticks:
            return hit["council"]
        return None

    def put(self, changes: list[str], tick, council: dict) -> None:
        self.rows[vote_key(changes)] = {"tick": tick, "council": council}
        if len(self.rows) > 100:
            self.rows.pop(next(iter(self.rows)))


def offline_vote(changes: list[str], why: str) -> dict:
    """The council's answer with no model call: what the rails guard anyway (goals inside value, accepts) is
    approved, the rest keeps the old values."""
    safe = all(str(c).startswith(("goal ", "accept offers")) for c in changes or [])
    return {"ok": bool(safe), "yes": 0, "votes": [], "errors": [],
            "offline": True, "why": why + (": approved (the rails guard it)" if safe else ": kept the old values")}


# ----------------------------------------------------------------------------- the trading council (the bot)
def _level(live: Path) -> int:
    try:
        ctl = json.loads((live / "control.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ctl = {}
    if ctl.get("brain_intensity_mode") == "manual" and ctl.get("brain_intensity") is not None:
        try:
            return int(ctl["brain_intensity"])
        except (TypeError, ValueError):
            pass
    try:
        return int(json.loads((live / "brain_budget.json").read_text(encoding="utf-8")).get("level", 50))
    except (OSError, ValueError, TypeError):
        return 50


def _budget_state(live: Path) -> dict:
    for name in ("brain_budget.json",):
        try:
            d = json.loads((live / name).read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except (OSError, ValueError):
            continue
    return {}


def action_spend(action: Any) -> float:
    """Cash this action would pay out (0 for sells and swaps)."""
    exp = getattr(action, "expected", None) or {}
    for k in ("spend", "cost", "price"):
        if isinstance(exp.get(k), (int, float)):
            return float(exp[k])
    p = getattr(action, "params", None) or {}
    give = p.get("give") or {}
    if isinstance(give.get("cash"), (int, float)):
        return float(give["cash"])
    if isinstance(p.get("price"), (int, float)) and ((p.get("topic") or {}).get("buy") or exp.get("buying")):
        return float(p["price"])
    return 0.0


def trading_council_gate(action: Any, live: Path | None = None, now: float | None = None,
                         level: int | None = None, council_target: float | None = None,
                         rows: list[dict] | None = None) -> tuple[str, str] | None:
    """Should the trading council skip the model for this action? None = ask the model as usual; otherwise
    ("approve" | "veto", why). The rails have already passed the action when the council sees it."""
    live = Path(live or config.LIVE)
    now = now or time.time()
    lvl = _level(live) if level is None else int(level)
    spend = action_spend(action)
    gain = (getattr(action, "expected", None) or {}).get("value_gain")
    if lvl < LOW_LEVEL and spend < SMALL_SPEND_P and not str(getattr(action, "kind", "")).startswith("duel"):
        return "approve", "small move (%.0f P < %d P) at intensity %d: the rails passed it, no vote" % (spend, SMALL_SPEND_P, lvl)
    if council_target is None:
        st = _budget_state(live)
        plan = st.get("plan") or {}
        council_target = targets(plan, float(plan.get("hours_today") or 6.0))["council"]
    b = bucket("council", council_target, live, now, rows=rows)
    if b["ok"]:
        return None
    if str(getattr(action, "kind", "")).startswith("duel"):
        return "approve", "council budget spent for now: duel move approved (never block a duel)"
    if isinstance(gain, (int, float)) and gain > 0:
        return "approve", "council budget spent for now (%.2f of %.2f $ in 30 min): the rails passed it with gain %.1f" % (
            b["spent"], b["allowed"], gain)
    return "veto", "council budget spent for now (%.2f of %.2f $ in 30 min) and no clear gain: held" % (b["spent"], b["allowed"])
