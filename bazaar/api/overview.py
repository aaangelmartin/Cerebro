"""One aggregate read for the supervisor dashboard: everything the page shows, in a single GET /overview.

It only reads files under data/live and data/lab (plus a cheap local ping of the gateway); it never talks to
the game. The page polls it every 3 s with ?since=<last decision id> so the activity stream stays incremental.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import config

TEAM = "t10"
VENUE_BOND = 250
DOORS_OPEN_AT = config.ENV.get("BAZAAR_DOORS_OPEN", "09:00")   # wall clock (Madrid) when the doors reopen
GATEWAY_PING_TTL = 10.0
_gateway_cache: dict = {"at": 0.0, "value": None}


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _tail(path: Path, since: int | None = None, limit: int = 200) -> list[dict]:
    from .server import _tail as tail
    return tail(path, since, limit)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _age(ts, now: float):
    ts = _num(ts)
    return round(now - ts, 1) if ts else None


# --------------------------------------------------------------------------- clock
def clock_view(status: dict, tick_latest: dict, known: dict, now: float) -> dict:
    tick_s = _num(status.get("tick_seconds")) or _num(known.get("tick_seconds")) or 60.0
    t = _num(status.get("t_hours"))
    doors = status.get("doors")
    out = {"tick": status.get("tick"), "tick_seconds": tick_s, "t_hours": t, "doors": doors,
           "paused": status.get("paused"), "day": status.get("day"), "next_tick_in": None,
           "closes_at": None, "opens_at": None, "next_event": None}
    start = _num(tick_latest.get("tick_start"))
    if doors == "open" and start and tick_latest.get("tick") == status.get("tick"):
        out["next_tick_in"] = round(max(0.0, start + tick_s - now), 1)
    events = []
    for item in known.get("schedule") or []:
        try:
            at, action, _ = str(item).split("|", 2)
            events.append((float(at), action))
        except ValueError:
            continue
    events.sort()
    if t is not None:
        upcoming = [(at, a) for at, a in events if at > t + 1e-6]
        nxt = next(((at, a) for at, a in upcoming if a not in ("day_opens", "day_closes")), None)
        running = doors == "open" and not status.get("paused")
        if nxt:
            # Game hours run at wall-clock speed only while the doors are open.
            out["next_event"] = {"at_hours": nxt[0], "action": nxt[1],
                                 "at": now + (nxt[0] - t) * 3600 if running else None}
        close = next((at for at, a in upcoming if a == "day_closes"), None)
        if close is not None and running:
            out["closes_at"] = now + (close - t) * 3600
    if doors != "open" or status.get("paused"):
        out["opens_at"] = DOORS_OPEN_AT
    return out


# --------------------------------------------------------------------------- team
def team_view(live: Path, status: dict) -> dict:
    rows = _tail(live / "leaderboard.jsonl", None, 120)
    out = {"score": status.get("score"), "rank": None, "teams": None, "negotiating": None, "market": None,
           "venue": None, "delta_1h": None, "round": None, "tick": None}
    if not rows:
        return out
    last = rows[-1]
    teams = last.get("teams") or {}
    if isinstance(teams, list):
        teams = {t.get("team"): t for t in teams if isinstance(t, dict)}
    me = teams.get(TEAM) or {}
    rounds = [r for r in last.get("rounds") or [] if r.get("status") == "active"]
    out.update(score=me.get("score", out["score"]), rank=me.get("rank"), teams=len(teams),
               negotiating=me.get("negotiating"), market=me.get("market"), venue=me.get("venue"),
               tick=last.get("tick"), round=(rounds[0].get("name") if rounds else None))
    tick = _num(last.get("tick"))
    if tick is not None and _num(me.get("score")) is not None:
        old = [r for r in rows if _num(r.get("tick")) is not None and tick - _num(r["tick"]) >= 60]
        ref = old[-1] if old else rows[0]
        ref_teams = ref.get("teams") or {}
        if isinstance(ref_teams, list):
            ref_teams = {t.get("team"): t for t in ref_teams if isinstance(t, dict)}
        before = _num((ref_teams.get(TEAM) or {}).get("score"))
        if before is not None and ref is not last:
            out["delta_1h"] = round(float(me["score"]) - before, 2)
    return out


# --------------------------------------------------------------------------- activity
def activity(live: Path, since: int | None, limit: int = 60) -> tuple[list[dict], int | None]:
    """Decisions newer than `since`, each joined with its outcome and council verdict."""
    decisions = _tail(live / "decisions.jsonl", since, limit)
    if not decisions:
        return [], since
    ids = {(d.get("action") or {}).get("id") for d in decisions}
    outcomes: dict = {}
    for o in _tail(live / "outcomes.jsonl", None, 600):
        if o.get("action_id") in ids:
            outcomes[o["action_id"]] = o
    council: dict = {}
    for c in _tail(live / "council.jsonl", None, 100):
        if c.get("action_id") in ids:
            council[c["action_id"]] = {k: c.get(k) for k in ("result", "why", "roles")}
    rows = []
    for d in decisions:
        a = d.get("action") or {}
        o = outcomes.get(a.get("id"))
        rows.append({
            "id": d.get("id"), "ts": d.get("ts"), "tick": d.get("tick"), "action_id": a.get("id"),
            "kind": a.get("kind"), "domain": a.get("domain"), "params": a.get("params") or {},
            "reason": a.get("reason") or "", "expected": a.get("expected") or {},
            "source": d.get("source") or a.get("source"), "verdict": d.get("verdict") or {},
            "dry_run": bool(d.get("dry_run")), "latency_s": d.get("latency_s"),
            "outcome": ({"status": o.get("status"), "error": (o.get("response") or {}).get("error"),
                         "message": (o.get("response") or {}).get("message")} if o else None),
            "council": council.get(a.get("id")),
        })
    return rows, decisions[-1].get("id")


# --------------------------------------------------------------------------- duels
def duels_view(live: Path, tick_latest: dict, now: float) -> dict:
    live_duels = []
    tick = tick_latest.get("tick")
    for d in tick_latest.get("duels") or []:
        if not isinstance(d, dict):
            continue
        rival_offer = d.get("rival_offer") or {}
        our_offer = d.get("your_offer") or {}
        limit = _num(d.get("your_limit"))
        rp = _num(rival_offer.get("price")) if isinstance(rival_offer, dict) else None
        margin = None
        if rp is not None and limit is not None:
            margin = round(limit - rp if d.get("role") == "buyer" else rp - limit, 1)
        last_rival = max((_num(m.get("tick")) or -1 for m in d.get("messages") or []
                          if isinstance(m, dict) and str(m.get("from", m.get("sender", ""))) == str(d.get("rival"))),
                         default=None)
        live_duels.append({
            "id": d.get("duel", d.get("id")), "role": d.get("role"), "rival": d.get("rival"), "item": d.get("item"),
            "limit": limit, "rounds": d.get("rounds"), "status": d.get("status"),
            "rival_price": rp, "our_price": _num(our_offer.get("price")) if isinstance(our_offer, dict) else None,
            "margin": margin, "deadline_tick": d.get("deadline_tick"),
            "silent_ticks": (int(tick - last_rival) if tick is not None and last_rival not in (None, -1)
                             else (int(tick - (_num(d.get("started_tick")) or tick)) if tick is not None else None)),
        })
    # Today's tally from the outcomes journal (Madrid day ~ local day of this machine).
    midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    accepted = messages = 0
    for o in _tail(live / "outcomes.jsonl", None, 2000):
        if (_num(o.get("ts")) or 0) < midnight or o.get("domain") != "duels":
            continue
        if o.get("kind") == "duel_accept" and o.get("status") in ("sent", "deal"):
            accepted += 1
        elif o.get("kind") == "duel_message" and o.get("status") in ("sent", "deal"):
            messages += 1
    return {"tick": tick, "live": live_duels, "today": {"accepted": accepted, "messages": messages}}


# --------------------------------------------------------------------------- lab
def lab_view(lab: Path, now: float) -> dict:
    counts = {"active": 0, "canary": 0, "shadow": 0, "proposed": 0, "retired": 0}
    try:
        from ..lab.store import LessonStore
        lessons = [l.__dict__ for l in LessonStore(lab / "lessons.jsonl").all()]
    except Exception:  # noqa: BLE001
        lessons = _tail(lab / "lessons.jsonl", None, 1000)
    for l in lessons:
        s = l.get("status")
        if s in counts:
            counts[s] += 1
    st = _read_json(lab / "lab_status.json", {}) or {}
    notices = _tail(lab / "notices.jsonl", None, 12)
    return {"counts": counts, "notices": notices[::-1], "updated": st.get("updated"), "age_s": _age(st.get("updated"), now),
            "spent_today": st.get("spent_today"), "day_cap": st.get("day_cap"), "errors": (st.get("errors") or [])[-5:]}


# --------------------------------------------------------------------------- processes
def gateway_ping(url: str = config.GATEWAY_URL, now: float | None = None) -> dict:
    """Is the legacy gateway answering? Hits a local route that never reaches the game (401 still means alive)."""
    now = now or time.time()
    if _gateway_cache["value"] is not None and now - _gateway_cache["at"] < GATEWAY_PING_TTL:
        return _gateway_cache["value"]
    t0 = time.time()
    try:
        with urllib.request.urlopen(url + "/gateway/whoami", timeout=1.5) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except (urllib.error.URLError, OSError, ValueError):
        code = None
    value = {"ok": code is not None, "code": code, "latency_ms": round((time.time() - t0) * 1000)}
    _gateway_cache.update(at=now, value=value)
    return value


def processes(live: Path, lab: Path, status: dict, broker: dict, now: float, gateway: dict) -> list[dict]:
    tick_s = _num(status.get("tick_seconds")) or 60.0
    open_ = status.get("doors") == "open" and not status.get("paused")
    lab_st = _read_json(lab / "lab_status.json", {}) or {}
    rec_st = _read_json(live / "recorder_status.json", {}) or {}
    str_st = _read_json(live / "strategist_status.json", {}) or {}
    out = []
    for name, upd, ticks in (("Bot", status.get("updated"), 3), ("Broker", broker.get("updated"), 2),
                             ("Laboratorio", lab_st.get("updated"), None), ("Grabadora", rec_st.get("updated"), 3),
                             ("Cerebro", str_st.get("updated"), 3)):
        age = _age(upd, now)
        limit = max(ticks * tick_s, 0 if open_ else 60.0) if ticks else 600.0
        out.append({"name": name, "age_s": age, "ok": age is not None and age <= limit,
                    "warn": age is not None and limit / 2 < age <= limit})
    lanes = rec_st.get("lanes") or {}
    keyed = lanes.get("keyed") or {}
    out.append({"name": "Pasarela", "age_s": None, "ok": gateway.get("ok"), "warn": False,
                "latency_ms": gateway.get("latency_ms"),
                "recorder_rps": {k: (v or {}).get("rps_60s") for k, v in lanes.items()},
                "keyed_down_since": keyed.get("down_since")})
    return out


def strategy_view(live: Path, now: float) -> dict:
    """The strategist's current plan, compact (full plan and history at GET /strategy)."""
    cur = _read_json(live / "strategy.json", {}) or {}
    st = _read_json(live / "strategist_status.json", {}) or {}
    plan = cur.get("plan") or {}
    return {"age_s": _age(cur.get("updated"), now), "tick": cur.get("tick"), "reason": cur.get("reason"),
            "situation": plan.get("situation"), "priorities": plan.get("priorities") or [],
            "goal_buys": plan.get("goal_buys") or {}, "cash_policy": plan.get("cash_policy") or {},
            "guidance": plan.get("guidance") or {}, "risks": plan.get("risks") or [],
            "council": cur.get("council"), "heartbeat_age_s": _age(st.get("updated"), now),
            "spent_today": st.get("spent_today"), "errors": st.get("errors") or [],
            "findings": plan.get("findings") or [], "events": cur.get("events") or [],
            "duel_claude_mode": plan.get("duel_claude_mode")}


def recorder_view(live: Path, now: float) -> dict:
    """Is everything being recorded? Heartbeat, lane outages, feed gaps (for the sidebar)."""
    st = _read_json(live / "recorder_status.json", {}) or {}
    lanes = st.get("lanes") or {}
    down = [k for k, v in lanes.items() if (v or {}).get("down_since")]
    return {"state": st.get("state"), "age_s": _age(st.get("updated"), now), "feed_gaps": st.get("feed_gaps", 0),
            "last_event_id": st.get("last_event_id"), "down": down,
            "rps": {k: (v or {}).get("rps_60s") for k, v in lanes.items()}}


# --------------------------------------------------------------------------- alerts
def alerts(live: Path, status: dict, broker: dict, lab_v: dict) -> list[dict]:
    out = []
    for e in status.get("last_errors") or []:
        level = "bad" if e.get("where") == "breaker" else "warn"
        out.append({"ts": e.get("at"), "level": level, "kind": "breaker" if level == "bad" else "error",
                    "where": e.get("where"), "text": e.get("error")})
    for e in (status.get("perceive") or {}).get("errors") or []:
        out.append({"ts": status.get("updated"), "level": "warn", "kind": "perceive", "where": "lectura",
                    "text": e if isinstance(e, str) else json.dumps(e, ensure_ascii=False)[:200]})
    for e in (broker.get("errors") or [])[-5:]:
        out.append({"ts": e.get("t"), "level": "warn", "kind": "error", "where": f"broker.{e.get('where')}",
                    "text": e.get("error")})
    for e in lab_v.get("errors") or []:
        out.append({"ts": e.get("ts"), "level": "warn", "kind": "error", "where": "lab", "text": e.get("error")})
    for n in _tail(live / "novelty.jsonl", None, 10):
        out.append({"ts": n.get("at") or n.get("ts"), "level": "warn", "kind": "novelty", "where": n.get("kind"),
                    "text": n.get("detail") if isinstance(n.get("detail"), str)
                    else json.dumps(n.get("detail"), ensure_ascii=False, default=str)[:200], "raw": n})
    out.sort(key=lambda a: _num(a.get("ts")) or 0, reverse=True)
    return out[:12]


# --------------------------------------------------------------------------- all together
def build(live: Path, lab: Path, stop_file: Path, since: int | None = None, now: float | None = None,
          gateway: dict | None = None) -> dict:
    now = now or time.time()
    status = _read_json(live / "status.json", {}) or {}
    tick_latest = _read_json(live / "tick_latest.json", {}) or {}
    known = _read_json(live / "known.json", {}) or {}
    broker = _read_json(live / "broker_status.json", {}) or {}
    try:
        from ..llm import client
        spend = client.spend_today()
    except Exception:  # noqa: BLE001
        spend = status.get("spend") or {}
    rows, last_id = activity(live, since)
    lab_v = lab_view(lab, now)
    gw = gateway if gateway is not None else gateway_ping(now=now)
    threads = {str(t.get("id")): t.get("with") for t in tick_latest.get("threads") or [] if isinstance(t, dict)}
    return {
        "now": now,
        "status": {k: status.get(k) for k in ("state", "mode", "armed", "write", "allow_real", "control", "domains",
                                               "breakers", "cash")} | {
            "age_s": _age(status.get("updated"), now), "stop_file": stop_file.exists(), "present": bool(status)},
        "clock": clock_view(status, tick_latest, known, now),
        "team": team_view(live, status),
        "bond": VENUE_BOND,
        "spend": {k: spend.get(k) for k in ("day", "usd", "cap", "degrade_at", "model_now", "calls", "by_purpose")},
        "broker": {k: broker.get(k) for k in ("updated", "session", "active_runs", "mode", "writes", "rule",
                                              "has_key", "efficiency_estimate", "session_stats", "matches_total",
                                              "last_result", "stall_efficiency")},
        "duels": duels_view(live, tick_latest, now),
        "lab": lab_v,
        "alerts": alerts(live, status, broker, lab_v),
        "processes": processes(live, lab, status, broker, now, gw),
        "recorder": recorder_view(live, now),
        "strategy": strategy_view(live, now),
        "threads": threads,
        "activity": rows,
        "last_id": last_id,
    }
