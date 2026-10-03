"""The brain's budget: day caps, one intensity knob (0-100) and the governor that moves it.

- Caps come from control.json (`brain_day_cap`, `day_cap`), clamped by hard maxima in code.
- `brain_intensity` (0-100) maps monotonically to how often the brain plans, which events wake it at once,
  how much of the picture it reads, how many re-asks it may spend and whether minor changes go to the council.
- A cost model measured from llm.jsonl turns a level into dollars per hour, so a slider can show its price.
- In `auto` mode a governor picks the level every few ticks from the budget left for the hours left and from
  what is happening in the game; every change is logged with its reason (brain_budget.jsonl).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from bazaar import config

BRAIN_CAP_DEFAULT = float(config.ENV.get("BAZAAR_STRATEGY_DAY_CAP_USD", "60"))
BRAIN_CAP_MAX = 100.0
BRAIN_CAP_MIN = 5.0
DEFAULT_LEVEL = 50
MODES = ("auto", "manual")
ALWAYS_KINDS = ("chat", "external", "official", "bargain")      # a plan at once at every level
MID_KINDS = ("dealer", "level", "set", "schedule", "novelty", "review")
HIGH_KINDS = ("score", "us", "offer", "venue")
DEFAULT_PLAN_USD = 0.38          # used until llm.jsonl has enough plans to measure
DEFAULT_COUNCIL_USD = 0.09
RESERVE_DUELS_USD = 15.0         # a duel session still to come (66 duels with Opus)
RESERVE_BENCH_USD = 0.5          # per Market Test still to come (the brain plans around each)
COUNCIL_USD_H = 2.0              # what the trading council costs per hour of play
OTHER_USD_H = 1.5                # dealers + market + lab per hour of play
TOTAL_DEFAULT = float(config.ENV.get("BAZAAR_BUDGET_TOTAL_USD", "220"))   # Saturday + Sunday, all keys
TOTAL_MIN, TOTAL_MAX = 50.0, 300.0                                        # three keys x 100 $ is the hard ceiling
FAST_TICK_WEIGHT = 1.5           # an hour of 15 s ticks costs about this many hours of 30 s ticks
TOMORROW = {"sat": "sun"}        # the event ends on Sunday
BRAIN_SHARE_MAX = 0.5            # the brain may take at most this share of what is left for a day
PURPOSE_SLACK = 1.5              # the brain's own per-purpose caps may reach this multiple of the split
LOG = "brain_budget.jsonl"
UNKNOWN_CLOSE_H = 6.0

# anchors (level, interval in ticks): linear in between; 0 -> every 20 ticks, 50 -> 8, 100 -> 3
_INTERVAL = ((0, 20), (50, 8), (100, 3))


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _lerp(points, level: float) -> float:
    level = _clamp(float(level), points[0][0], points[-1][0])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if level <= x1:
            return y0 + (y1 - y0) * (level - x0) / (x1 - x0)
    return points[-1][1]


def control(live: Path | None = None) -> dict:
    try:
        return json.loads((Path(live or config.LIVE) / "control.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def brain_day_cap(ctl: dict | None = None, live: Path | None = None) -> float:
    """control.json "brain_day_cap" if the team set one; else today's share of the event budget (written by the
    governor to brain_budget.json); else the default. Always inside the hard limits."""
    ctl = control(live) if ctl is None else ctl
    try:
        if ctl.get("caps_day") not in (None, config.madrid_day()):
            raise ValueError("the team's cap was set for another day")
        v = float(ctl.get("brain_day_cap"))
    except (TypeError, ValueError):
        st = read_state(live)
        try:
            v = float(st.get("brain_cap_today")) if st.get("day") == config.madrid_day() else BRAIN_CAP_DEFAULT
        except (TypeError, ValueError):
            v = BRAIN_CAP_DEFAULT
    return _clamp(v, BRAIN_CAP_MIN, BRAIN_CAP_MAX)


def budget_total(ctl: dict | None = None, live: Path | None = None) -> float:
    ctl = control(live) if ctl is None else ctl
    try:
        v = float(ctl.get("budget_total_usd"))
    except (TypeError, ValueError):
        v = TOTAL_DEFAULT
    return _clamp(v, TOTAL_MIN, TOTAL_MAX)


def _day_hours(d: dict) -> tuple[float, float]:
    """(hours, tick seconds) of a calendar day from the clock's `days` list."""
    from datetime import datetime
    try:
        h = (datetime.fromisoformat(d["closes"]).timestamp() - datetime.fromisoformat(d["opens"]).timestamp()) / 3600.0
        return max(0.0, h), float(d.get("tick_seconds") or 30.0)
    except (KeyError, TypeError, ValueError):
        return 0.0, 30.0


def event_plan(*, clock: dict, upcoming: list[dict] | None, days_spent: dict | None, total: float,
               now: float | None = None) -> dict:
    """Split what is left of the event budget between today and tomorrow, and today's part between purposes.

    `days_spent`: the router's {"sat": {"usd", "by_purpose"}, "sun": {...}}. Hours are weighted by tick rate
    (15 s ticks decide twice as often) and every duel session / Market Test still to come keeps a reserve on
    its own day. Nothing is hard-coded per day: Sunday simply gets whatever Saturday leaves."""
    now = now or time.time()
    days_spent = days_spent or {}
    today = clock.get("today") or config.madrid_day()
    spent_by_day = {d: float((v or {}).get("usd") or 0.0) for d, v in days_spent.items() if d in ("sat", "sun")}
    spent_total = round(sum(spent_by_day.values()), 4)
    spent_today = spent_by_day.get(today, 0.0)
    by_purpose = (days_spent.get(today) or {}).get("by_purpose") or {}
    remaining = max(0.0, total - spent_total)
    h_today = hours_left(clock, now) if clock.get("doors") in (None, "open") else 0.0
    tick_today = float(clock.get("tick_seconds") or 30.0)
    w_today = h_today * (FAST_TICK_WEIGHT if tick_today <= 20 else 1.0)
    h_tom = w_tom = 0.0
    tom = TOMORROW.get(today)
    for d in clock.get("days") or []:
        if tom and d.get("day") == tom:
            h_tom, tick_tom = _day_hours(d)
            w_tom = h_tom * (FAST_TICK_WEIGHT if tick_tom <= 20 else 1.0)
    t = clock.get("t_hours")
    ups = [u for u in upcoming or [] if isinstance(u.get("at_hours"), (int, float))
           and (not isinstance(t, (int, float)) or u["at_hours"] >= t)]
    close_at = min([u["at_hours"] for u in ups if u.get("action") == "day_closes"] or [float("inf")])
    n = {"duels_today": 0, "bench_today": 0, "duels_tomorrow": 0, "bench_tomorrow": 0}
    for u in ups:
        if u.get("action") not in ("duels", "bench"):
            continue
        when = "today" if u["at_hours"] <= close_at else "tomorrow"
        if when == "tomorrow" and not tom:
            continue
        n[f"{u['action']}_{when}"] += 1
    res_today = RESERVE_DUELS_USD * n["duels_today"] + RESERVE_BENCH_USD * n["bench_today"]
    res_tom = RESERVE_DUELS_USD * n["duels_tomorrow"] + RESERVE_BENCH_USD * n["bench_tomorrow"]
    scale = min(1.0, remaining / (res_today + res_tom)) if res_today + res_tom > 0 else 1.0
    res_today, res_tom = res_today * scale, res_tom * scale
    flex = max(0.0, remaining - res_today - res_tom)
    w = w_today + w_tom
    left_today = res_today + (flex * w_today / w if w > 0 else (flex if not tom else 0.0))
    left_today = min(left_today, remaining, max(0.0, config.DAY_CAP_MAX_USD - spent_today))
    running = COUNCIL_USD_H * h_today + OTHER_USD_H * h_today          # council + dealers + market + lab
    duels_today = RESERVE_DUELS_USD * n["duels_today"] * scale
    brain_left = _clamp(left_today - duels_today - running, 0.0, BRAIN_SHARE_MAX * left_today)
    spent_brain = float(by_purpose.get("strategy") or 0.0)
    third = OTHER_USD_H * h_today / 3.0
    caps = {"strategy": spent_brain + brain_left,
            "duels": float(by_purpose.get("duels") or 0.0) + duels_today,
            "council": float(by_purpose.get("council") or 0.0) + COUNCIL_USD_H * h_today,
            "dealers": float(by_purpose.get("dealers") or 0.0) + third,
            "market": float(by_purpose.get("market") or 0.0) + third,
            "lab": float(by_purpose.get("lab") or 0.0) + third}
    return {"day": today, "budget_total": round(total, 2), "spent_total": round(spent_total, 2),
            "remaining_total": round(remaining, 2), "spent_today": round(spent_today, 2),
            "plan_today": round(spent_today + left_today, 2), "left_today": round(left_today, 2),
            "plan_tomorrow": round(max(0.0, remaining - left_today), 2),
            "hours_today": round(h_today, 2), "hours_tomorrow": round(h_tom, 2),
            "sessions": n, "reserves": {"today": round(res_today, 2), "tomorrow": round(res_tom, 2)},
            "brain_cap_today": round(_clamp(spent_brain + brain_left, 0.0, BRAIN_CAP_MAX), 2),
            "brain_left_today": round(brain_left, 2),
            "usd_per_hour_target": round(brain_left / h_today, 2) if h_today > 0 else 0.0,
            "day_usd_per_hour": round(left_today / h_today, 2) if h_today > 0 else 0.0,
            "purpose_caps": {k: round(v, 2) for k, v in caps.items()}}


def purpose_cap(purpose: str, live: Path | None = None) -> float | None:
    """The most the brain's own per-purpose cap may be today (the split, with slack). None = no plan yet."""
    st = read_state(live)
    if st.get("day") != config.madrid_day():
        return None
    v = ((st.get("plan") or {}).get("purpose_caps") or {}).get(purpose)
    try:
        spent = float((((st.get("plan") or {}).get("spent_by_purpose")) or {}).get(purpose) or 0.0)
        return round(spent + (float(v) - spent) * PURPOSE_SLACK, 2)
    except (TypeError, ValueError):
        return None


def mode(ctl: dict | None = None, live: Path | None = None) -> str:
    ctl = control(live) if ctl is None else ctl
    m = ctl.get("brain_intensity_mode")
    return m if m in MODES else "auto"


def manual_level(ctl: dict | None = None, live: Path | None = None) -> int:
    ctl = control(live) if ctl is None else ctl
    try:
        return int(_clamp(round(float(ctl.get("brain_intensity"))), 0, 100))
    except (TypeError, ValueError):
        return DEFAULT_LEVEL


def settings(level: float) -> dict:
    """What a level means. Every field moves one way only as the level rises."""
    level = int(_clamp(round(float(level)), 0, 100))
    kinds = list(ALWAYS_KINDS)
    if level >= 35:
        kinds += MID_KINDS
    if level >= 70:
        kinds += HIGH_KINDS
    return {"level": level,
            "interval_ticks": int(round(_lerp(_INTERVAL, level))),
            "wake_kinds": kinds,                       # event kinds that trigger a plan at once
            "wake_on_score_drop": level >= 50,
            "min_gap_s": int(round(_lerp(((0, 300), (50, 200), (100, 150)), level))),
            "picture_chars": int(round(_lerp(((0, 14000), (50, 26000), (100, 40000)), level))),
            "max_reasks": 0 if level < 25 else 1,
            "council_minor": level >= 40}              # money, pauses and budgets always go to the council


# ----------------------------------------------------------------------------- cost model
def _rows(path: Path, since: float) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
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


def measured(live: Path | None = None, now: float | None = None, window_s: float = 6 * 3600) -> dict:
    """Average dollars per plan and per council vote on a brain proposal, from llm.jsonl."""
    now = now or time.time()
    rows = _rows(Path(live or config.LIVE) / "llm.jsonl", now - window_s)
    plans = [float(r["cost_usd"]) for r in rows if r.get("purpose") == "strategy" and r.get("cost_usd")]
    council = [float(r["cost_usd"]) for r in rows if r.get("purpose") == "council" and r.get("cost_usd")]
    return {"plan_usd": round(sum(plans) / len(plans), 4) if len(plans) >= 3 else DEFAULT_PLAN_USD,
            "plans_measured": len(plans),
            "council_usd": round(sum(council) / len(council), 4) if len(council) >= 3 else DEFAULT_COUNCIL_USD,
            "council_measured": len(council)}


def estimate_usd_per_hour(level: float, tick_seconds: float = 30.0, m: dict | None = None) -> float:
    """Dollars per hour of play at this level: scheduled plans + event-driven ones + re-asks + council votes."""
    m = m or {"plan_usd": DEFAULT_PLAN_USD, "council_usd": DEFAULT_COUNCIL_USD}
    s = settings(level)
    ticks_h = 3600.0 / max(1.0, float(tick_seconds or 30.0))
    scheduled = ticks_h / s["interval_ticks"]
    events = _lerp(((0, 1.0), (35, 2.0), (70, 5.0), (100, 9.0)), s["level"])       # immediate plans per hour
    plans = min(scheduled + events, 3600.0 / s["min_gap_s"])
    size = s["picture_chars"] / 26000.0                                            # input grows with the picture
    per_plan = float(m["plan_usd"]) * (0.45 + 0.55 * size) * (1.0 + 0.15 * s["max_reasks"])
    votes = plans * (0.35 if s["council_minor"] else 0.15) * 3
    return round(plans * per_plan + votes * float(m["council_usd"]), 2)


def table(tick_seconds: float = 30.0, m: dict | None = None, step: int = 10) -> list[dict]:
    return [{"level": lv, "interval_ticks": settings(lv)["interval_ticks"],
             "usd_per_hour": estimate_usd_per_hour(lv, tick_seconds, m)} for lv in range(0, 101, step)]


def level_for_budget(usd_per_hour: float, tick_seconds: float = 30.0, m: dict | None = None) -> int:
    """The highest level whose estimated cost fits this many dollars per hour (0 if none fits)."""
    best = 0
    for lv in range(0, 101, 5):
        if estimate_usd_per_hour(lv, tick_seconds, m) <= usd_per_hour:
            best = lv
    return best


# ----------------------------------------------------------------------------- governor
def hours_left(clock: dict, now: float | None = None) -> float:
    """Real hours until today's close (0 when the doors are closed)."""
    now = now or time.time()
    if clock.get("doors") not in (None, "open"):
        return 0.0
    closes = clock.get("closes")
    try:
        from datetime import datetime
        end = datetime.fromisoformat(str(closes)).timestamp()
        return max(0.0, (end - now) / 3600.0)
    except (TypeError, ValueError):
        return UNKNOWN_CLOSE_H                     # doors open but no closing time published: assume a normal day


def govern(*, clock: dict, spent: float, cap: float, upcoming: list[dict] | None = None,
           signals: dict | None = None, tick_seconds: float = 30.0, m: dict | None = None,
           now: float | None = None) -> tuple[int, str]:
    """(level, reason) for auto mode. `signals`: {bargain, chat, behind_pace, rank_drop, duels_live, bench_live,
    unchanged, no_feasible_action}; `upcoming`: schedule rows {at_hours, action}."""
    sig = signals or {}
    if clock.get("paused"):
        return 0, "game paused"
    hl = hours_left(clock, now)
    if hl <= 0:
        return 0, "doors closed"
    left = max(0.0, cap - spent)                          # `cap` is already net of the duel/bench reserves
    t = clock.get("t_hours")
    soon = []
    for u in upcoming or []:
        at, act = u.get("at_hours"), u.get("action")
        if not isinstance(at, (int, float)) or not isinstance(t, (int, float)) or at < t:
            continue
        if at - t <= 0.25 and act in ("bench", "duels", "persona_opens", "persona_patch", "round"):
            soon.append(act)
    pace = left / max(hl, 0.25)                           # dollars per hour we can afford to the close
    base = level_for_budget(pace, tick_seconds, m)
    level, why = base, [f"{left:.1f} $ left for {hl:.1f} h -> {pace:.2f} $/h"]
    boost = 0
    if sig.get("bargain"):
        boost = max(boost, 30); why.append("bargain open")
    if sig.get("duels_live") or sig.get("bench_live"):
        boost = max(boost, 20); why.append("session live")
    if soon:
        boost = max(boost, 15); why.append(f"{soon[0]} within 15 min")
    if sig.get("chat"):
        boost = max(boost, 15); why.append("team message")
    if sig.get("rank_drop") or sig.get("behind_pace"):
        boost = max(boost, 10); why.append("behind the pace")
    cut = 0
    if sig.get("unchanged"):
        cut = max(cut, 20); why.append("nothing changed since the last plan")
    if sig.get("no_feasible_action"):
        cut = max(cut, 20); why.append("no feasible action")
    level = level + boost - cut
    ceiling = level_for_budget(pace * 2.0, tick_seconds, m)      # a boost may spend at most twice the pace
    if boost:
        level = min(level, max(base, ceiling))
    if left <= 0:
        return 0, "brain budget spent"
    return int(_clamp(level, 5, 100)), "; ".join(why)


def log_change(live: Path | None, level: int, reason: str, mode_: str, now: float | None = None) -> None:
    p = Path(live or config.LIVE) / LOG
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": now or time.time(), "level": level, "mode": mode_, "reason": reason},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def state_path(live: Path | None = None) -> Path:
    return Path(live or config.LIVE) / "brain_budget.json"


def read_state(live: Path | None = None) -> dict:
    try:
        return json.loads(state_path(live).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def write_state(live: Path | None, doc: dict) -> None:
    p = state_path(live)
    try:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, default=str))
        tmp.replace(p)
    except OSError:
        pass


def report(live: Path | None = None, clock: dict | None = None, spend: dict | None = None,
           now: float | None = None) -> dict:
    """What GET /brain/budget returns."""
    live = Path(live or config.LIVE)
    now = now or time.time()
    ctl = control(live)
    st = read_state(live)
    clock = clock or {}
    tick_s = float(clock.get("tick_seconds") or 30.0)
    m = measured(live, now)
    md = mode(ctl)
    level = int(st.get("level", manual_level(ctl))) if md == "auto" else manual_level(ctl)
    spend = spend or {}
    spent = float((spend.get("by_purpose") or {}).get("strategy") or st.get("spent_today") or 0.0)
    cap = brain_day_cap(ctl, live)
    plan = st.get("plan") or {}
    hl = hours_left(clock, now)
    per_h = estimate_usd_per_hour(level, tick_s, m)
    day_spent = float(spend.get("usd") or 0.0)
    by_key = spend.get("by_key") or {}
    return {"mode": md, "level": level, "reason": st.get("reason"), "changed": st.get("changed"),
            "settings": settings(level), "usd_per_hour_now": per_h, "table": table(tick_s, m),
            "measured": m, "spent_today": round(spent, 2), "cap_today": cap,
            "cap_limits": {"brain_max": BRAIN_CAP_MAX, "day_max": config.DAY_CAP_MAX_USD},
            "day_total_spent": round(day_spent, 2), "day_cap": config.day_cap_usd(),
            "hours_left": round(hl, 2), "projected_spend_by_close": round(min(cap, spent + per_h * hl), 2),
            "keys_headroom": {k: round(max(0.0, config.KEY_CAP_USD - float(v.get("usd_total") or 0.0)), 2)
                              for k, v in by_key.items() if not v.get("dead")},
            "keys_spent": {k: round(float(v.get("usd_total") or 0.0), 2) for k, v in by_key.items()},
            "keys_dead": {k: v.get("dead") for k, v in by_key.items() if v.get("dead")},
            "budget_total": plan.get("budget_total", budget_total(ctl)), "spent_total": plan.get("spent_total"),
            "remaining_total": plan.get("remaining_total"), "plan_today": plan.get("plan_today"),
            "plan_tomorrow": plan.get("plan_tomorrow"), "usd_per_hour_target": plan.get("usd_per_hour_target"),
            "plan": plan, "caps_set_by_team": {k: ctl.get(k) for k in ("brain_day_cap", "day_cap") if k in ctl},
            "history": _rows(live / LOG, now - 3 * 3600)[-30:]}


def validate_control(body: dict) -> dict:
    """The budget fields of POST /control, validated. Raises ValueError."""
    out: dict[str, Any] = {}
    for k in ("brain_day_cap", "day_cap"):          # null = back to the automatic split of the event budget
        if k in body and body[k] is None:
            out[k] = None
    body = {k: v for k, v in body.items() if not (k in ("brain_day_cap", "day_cap") and v is None)}
    if "brain_intensity" in body:
        v = body["brain_intensity"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100:
            raise ValueError("brain_intensity must be a number from 0 to 100")
        out["brain_intensity"] = int(round(v))
    if "brain_intensity_mode" in body:
        if body["brain_intensity_mode"] not in MODES:
            raise ValueError(f"brain_intensity_mode must be one of {list(MODES)}")
        out["brain_intensity_mode"] = body["brain_intensity_mode"]
    if "brain_day_cap" in body:
        v = body["brain_day_cap"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not BRAIN_CAP_MIN <= v <= BRAIN_CAP_MAX:
            raise ValueError(f"brain_day_cap must be {BRAIN_CAP_MIN:.0f}-{BRAIN_CAP_MAX:.0f} $")
        out["brain_day_cap"] = float(v)
    if "budget_total_usd" in body:
        v = body["budget_total_usd"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not TOTAL_MIN <= v <= TOTAL_MAX:
            raise ValueError(f"budget_total_usd must be {TOTAL_MIN:.0f}-{TOTAL_MAX:.0f} $")
        out["budget_total_usd"] = float(v)
    if "brain_day_cap" in body or "day_cap" in body:
        out["caps_day"] = config.madrid_day()        # a cap set by hand holds for that day only
    if "day_cap" in body:
        v = body["day_cap"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not config.DAY_CAP_MIN_USD <= v <= config.DAY_CAP_MAX_USD:
            raise ValueError(f"day_cap must be {config.DAY_CAP_MIN_USD:.0f}-{config.DAY_CAP_MAX_USD:.0f} $")
        out["day_cap"] = float(v)
    return out
