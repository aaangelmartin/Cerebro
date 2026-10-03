"""Perception: one Situation per tick from as few gateway reads as possible.

Every tick (6 reads): /api/clock, /api/me, /api/me/threads?status=open (messages and standing
offers included), /api/me/offers, /api/duels, /api/feed?limit=500.
Only for threads that left the open list since the previous tick: /api/threads/{id} (to learn how
they ended). Every SLOW_EVERY ticks, on the first tick, or when the feed says something changed:
/api/dealers, /api/levels, /api/schedule, /api/venues, /api/leaderboard, /api/venues/rastro/offers.

Side effects, all under config.LIVE:
  events.jsonl       every new public event, de-duplicated by id, with the wall time we saw it
  leaderboard.jsonl  one snapshot each time the public leaderboard refreshes
  novelty.jsonl      every change the novelty detector found
  known.json         what the detector already knows (limits, schedule, levels, dealers, types...)
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .. import config

SLOW_EVERY = 10                     # ticks between slow reads
FEED_LIMIT = 500
# Feed events that make the slow reads worth refreshing right away.
REFRESH_TYPES = ("level.", "persona.", "venue.", "clock.", "announcement", "day.", "dealer.", "schedule.")


@dataclass
class Situation:
    tick: int = 0
    t_hours: float = 0.0
    day: str = ""
    tick_seconds: float = 30.0
    doors: str = "open"
    paused: bool = False
    deadline: float = 0.0                 # epoch by which we must have decided (55 % of the tick)
    limits: dict = field(default_factory=dict)
    me: dict = field(default_factory=dict)
    threads: list = field(default_factory=list)
    my_offers: list = field(default_factory=list)
    duels: list = field(default_factory=list)
    dealers: list = field(default_factory=list)
    levels: list = field(default_factory=list)
    schedule: dict = field(default_factory=dict)
    venues: list = field(default_factory=list)
    rastro_book: list = field(default_factory=list)
    feed_new: list = field(default_factory=list)
    leaderboard: dict = field(default_factory=dict)
    novelty: list = field(default_factory=list)
    values: dict = field(default_factory=dict)  # ref -> our value of one more copy (filled by ctx.value)
    # --- extras (not in the contract's list, safe to ignore) ---
    clock: dict = field(default_factory=dict)
    closed_threads: list = field(default_factory=list)   # threads that left the open list this tick
    tick_start: float = 0.0
    perceived_at: float = 0.0
    slow_tick: int = -1                   # tick of the last slow read
    last_event_id: int = 0
    requests: int = 0
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def cash(self) -> int:
        return int(self.me.get("cash") or 0)

    @property
    def score(self) -> float:
        s = self.me.get("score")
        if isinstance(s, dict):
            s = s.get("score")
        try:
            return float(s or 0.0)
        except (TypeError, ValueError):
            return 0.0


# --------------------------------------------------------------------------- helpers

_LEDGERS: dict = {}


def _append(path: Path, rows: list[dict]) -> None:
    """Append through core.ledger (adds `ts` and keeps per-file ids) when it is importable."""
    if not rows:
        return
    try:
        from .ledger import Ledger
    except ImportError:
        Ledger = None
    if Ledger is not None:
        led = _LEDGERS.get(path.parent)
        if led is None:
            led = _LEDGERS[path.parent] = Ledger(path.parent)
        for r in rows:
            led.append(path.stem, r)
        return
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps({"ts": round(time.time(), 3), **r}, ensure_ascii=False, default=str) + "\n")


def _sig(obj: Any) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def load_known(live: Path) -> dict:
    try:
        return json.loads((live / "known.json").read_text())
    except (OSError, ValueError):
        return {}


def save_known(live: Path, known: dict) -> None:
    tmp = live / "known.tmp"
    tmp.write_text(json.dumps(known, ensure_ascii=False, default=str))
    tmp.replace(live / "known.json")


def _seed_event_types() -> list[str]:
    """Event types seen on Friday, so the detector only flags types that are really new."""
    path = config.FRIDAY / "bot" / "history" / "events.jsonl"
    types: set[str] = set()
    try:
        with path.open() as f:
            for line in f:
                try:
                    types.add(json.loads(line).get("type", ""))
                except ValueError:
                    continue
    except OSError:
        pass
    types.discard("")
    return sorted(types)


class _Reader:
    """Counts reads and turns failures into sit.errors instead of exceptions."""

    def __init__(self, gw):
        self.gw, self.n, self.errors = gw, 0, []

    def get(self, path: str, default=None, **params):
        self.n += 1
        try:
            return self.gw.get(path, **params)
        except Exception as e:  # noqa: BLE001 - one failed read must not lose the tick
            self.errors.append({"path": path, "error": getattr(e, "code", type(e).__name__),
                                "message": str(e)[:200]})
            return default


# --------------------------------------------------------------------------- novelty

def detect_novelty(known: dict, sit: Situation, slow_fresh: bool, live: Path) -> list[dict]:
    """Compare what we see with known.json, update `known` in place and return the changes."""
    out: list[dict] = []

    def note(kind: str, detail: Any, **extra):
        out.append({"kind": kind, "tick": sit.tick, "at": time.time(), "detail": detail, **extra})

    # Limits (every tick: they come with the clock).
    if sit.limits:
        old = known.get("limits")
        if old is not None and old != sit.limits:
            changed = {k: [old.get(k), v] for k, v in sit.limits.items() if old.get(k) != v}
            changed.update({k: [v, None] for k, v in old.items() if k not in sit.limits})
            note("limits", changed)
        known["limits"] = sit.limits
    if sit.tick_seconds:
        old = known.get("tick_seconds")
        if old is not None and old != sit.tick_seconds:
            note("tick_seconds", [old, sit.tick_seconds])
        known["tick_seconds"] = sit.tick_seconds

    if slow_fresh:
        # Schedule: new upcoming items (keyed by when + what).
        items = {f"{u.get('at_hours')}|{u.get('action')}|{_sig(u.get('params'))}": u
                 for u in (sit.schedule or {}).get("upcoming", [])}
        if items:
            old = known.get("schedule")
            if old is not None:
                for k, u in items.items():
                    if k not in old:
                        note("schedule", {"at_hours": u.get("at_hours"), "action": u.get("action"),
                                          "note": u.get("note"), "params": u.get("params")})
            known["schedule"] = sorted(set(items) | set(known.get("schedule") or []))[-200:]
        # Levels: new ones and state changes.
        if sit.levels:
            old = known.get("levels")
            now_levels = {str(lv.get("id")): lv.get("state") for lv in sit.levels}
            if old is not None:
                for lid, st in now_levels.items():
                    if old.get(lid) != st:
                        lv = next(x for x in sit.levels if str(x.get("id")) == lid)
                        note("level", {"id": lid, "from": old.get(lid), "to": st, "name": lv.get("name"),
                                       "how": lv.get("how"), "teaser": lv.get("teaser")})
            known["levels"] = {**(old or {}), **now_levels}
        # Dealers: new ones, status changes, menu changes.
        if sit.dealers:
            old = known.get("dealers")
            now_d = {str(d.get("id")): {"status": d.get("status"), "menu": _sig(d.get("menu")),
                                        "unlock": _sig(d.get("unlock"))} for d in sit.dealers}
            if old is not None:
                for did, v in now_d.items():
                    o = old.get(did)
                    if o is None:
                        note("dealer", {"id": did, "new": True, "status": v["status"]})
                    else:
                        if o.get("status") != v["status"]:
                            note("dealer", {"id": did, "from": o.get("status"), "to": v["status"]})
                        if o.get("menu") != v["menu"]:
                            d = next(x for x in sit.dealers if str(x.get("id")) == did)
                            note("dealer_menu", {"id": did, "menu": d.get("menu")})
                        if o.get("unlock") != v["unlock"]:
                            note("dealer_unlock", {"id": did})
            known["dealers"] = {**(old or {}), **now_d}

    # New event types in the feed.
    if "event_types" not in known:
        known["event_types"] = _seed_event_types()
        seed = True
    else:
        seed = False
    types = set(known["event_types"])
    for e in sit.feed_new:
        t = e.get("type")
        if t and t not in types:
            types.add(t)
            if not seed or known.get("_seeded_feed"):
                note("event_type", {"type": t, "example": {k: e.get(k) for k in ("id", "tick", "actor", "payload")}})
    known["event_types"] = sorted(types)
    known["_seeded_feed"] = True

    # New error codes in the ledger (outcomes.jsonl / decisions.jsonl), read incrementally.
    codes = set(known.get("error_codes") or [])
    first = "error_codes" not in known
    offsets = known.setdefault("ledger_offsets", {})
    for name in ("outcomes.jsonl", "decisions.jsonl"):
        p = live / name
        try:
            size = p.stat().st_size
        except OSError:
            continue
        off = int(offsets.get(name, 0))
        if off > size:
            off = 0
        with p.open("rb") as f:
            f.seek(off)
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1
        offsets[name] = off + end
        for line in chunk[:end].splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            for code in _error_codes(row):
                if code not in codes:
                    codes.add(code)
                    if not first:
                        note("error_code", {"code": code, "file": name})
    known["error_codes"] = sorted(codes)
    return out


def _error_codes(row: Any, depth: int = 0) -> list[str]:
    """Pull game error codes ({"error": "<code>"}) out of a ledger row."""
    if depth > 4 or not isinstance(row, dict):
        return []
    found = []
    for k, v in row.items():
        if k in ("error", "error_code") and isinstance(v, str) and v and len(v) < 60 and " " not in v:
            found.append(v)
        elif isinstance(v, dict):
            found.extend(_error_codes(v, depth + 1))
    return found


# --------------------------------------------------------------------------- perceive

def _num(v: Any) -> float | None:
    """A finite float, or None for missing/non-numeric/NaN values (bools are not numbers here)."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _team_rows(teams) -> list[dict]:
    """Leaderboard teams as a list of dicts (the API sends a list; tolerate a {team: row} map too)."""
    if isinstance(teams, dict):
        return [{"team": k, **(v or {})} for k, v in teams.items()]
    return [t for t in (teams or []) if isinstance(t, dict)]


def perceive(gw, prev: Situation | None, *, live: Path | None = None, slow_every: int = SLOW_EVERY,
             now: float | None = None, clock: dict | None = None) -> Situation:
    """Read the game once and return the Situation for this tick (see module docstring)."""
    live = Path(live or config.LIVE)
    live.mkdir(parents=True, exist_ok=True)
    r = _Reader(gw)
    t0 = time.time() if now is None else now

    if clock is None:                         # run.py may pass the clock it just polled
        clock = gw.get("/api/clock")          # without the clock there is no tick: let it raise
        r.n += 1
    tick = int(clock.get("tick") or 0)
    tick_seconds = _num(clock.get("tick_seconds"))
    if tick_seconds is None or tick_seconds <= 0:
        tick_seconds = 30.0
    paused = bool(clock.get("paused"))
    doors = str(clock.get("doors") or "open")
    nti = _num(clock.get("next_tick_in"))
    # A missing, non-numeric, <= 0 or > tick_seconds countdown says nothing about where in the tick we are:
    # assume the tick starts now rather than producing a deadline that has already passed.
    if paused or doors != "open" or nti is None or nti <= 0 or nti > tick_seconds:
        tick_start = t0
    else:
        tick_start = t0 - (tick_seconds - nti)
    if prev is not None and prev.tick == tick and prev.tick_start:
        tick_start = prev.tick_start           # same tick seen twice: keep the first estimate
    deadline = tick_start + config.DECISION_DEADLINE * tick_seconds

    sit = Situation(tick=tick, t_hours=float(clock.get("t_hours") or 0.0), day=str(clock.get("today") or ""),
                    tick_seconds=tick_seconds, doors=doors, paused=paused, deadline=deadline,
                    limits=dict(clock.get("limits") or {}), clock=clock, tick_start=tick_start)

    me = r.get("/api/me")
    sit.me = me if isinstance(me, dict) else (prev.me if prev else {})

    th = r.get("/api/me/threads", None, status="open")
    sit.threads = list(th.get("threads", [])) if isinstance(th, dict) else (prev.threads if prev else [])
    if prev is not None and isinstance(th, dict):
        open_ids = {t.get("id") for t in sit.threads}
        for old in prev.threads:
            if old.get("id") not in open_ids:
                detail = r.get(f"/api/threads/{old.get('id')}")
                if isinstance(detail, dict):
                    sit.closed_threads.append(detail.get("thread", detail))

    offers = r.get("/api/me/offers")
    sit.my_offers = list(offers.get("offers", [])) if isinstance(offers, dict) else (prev.my_offers if prev else [])

    duels = r.get("/api/duels")
    if isinstance(duels, dict):
        sit.duels = [d for d in duels.get("duels", []) if d.get("status", "live") == "live"]
    elif prev:
        sit.duels = prev.duels

    known = load_known(live)
    last_id = int(prev.last_event_id if prev else known.get("last_event_id", 0) or 0)
    feed = r.get("/api/feed", None, limit=FEED_LIMIT)
    events = list(feed.get("events", [])) if isinstance(feed, dict) else []
    fresh = sorted((e for e in events if int(e.get("id") or 0) > last_id), key=lambda e: e["id"])
    gap = None
    if fresh and last_id:
        oldest = min(int(e.get("id") or 0) for e in events)
        if oldest > last_id + 1:
            gap = {"after": last_id, "before": oldest}
    sit.feed_new = fresh
    sit.last_event_id = fresh[-1]["id"] if fresh else last_id
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    _append(live / "events.jsonl", [{**e, "seen_at": stamp} for e in fresh])

    # Slow reads.
    refresh = any(str(e.get("type", "")).startswith(REFRESH_TYPES) for e in fresh)
    slow = prev is None or refresh or prev.slow_tick < 0 or tick - prev.slow_tick >= slow_every \
        or tick < prev.slow_tick
    if slow:
        d = r.get("/api/dealers")
        sit.dealers = list((d or {}).get("personas", (d or {}).get("dealers", []))) if isinstance(d, dict) else []
        lv = r.get("/api/levels")
        sit.levels = list(lv.get("levels", [])) if isinstance(lv, dict) else []
        sc = r.get("/api/schedule")
        sit.schedule = sc if isinstance(sc, dict) else {}
        v = r.get("/api/venues")
        sit.venues = list(v.get("venues", [])) if isinstance(v, dict) else []
        lb = r.get("/api/leaderboard")
        sit.leaderboard = lb if isinstance(lb, dict) else {}
        rb = r.get("/api/venues/rastro/offers")
        sit.rastro_book = list(rb.get("offers", [])) if isinstance(rb, dict) else []
        sit.slow_tick = tick
        # Keep what we had for any slow read that failed.
        if prev is not None:
            for name in ("dealers", "levels", "schedule", "venues", "leaderboard", "rastro_book"):
                if not getattr(sit, name):
                    setattr(sit, name, getattr(prev, name))
    elif prev is not None:
        for name in ("dealers", "levels", "schedule", "venues", "leaderboard", "rastro_book"):
            setattr(sit, name, getattr(prev, name))
        sit.slow_tick = prev.slow_tick

    # Leaderboard snapshot whenever the public board refreshed.
    lb = sit.leaderboard
    if slow and lb.get("teams"):
        lb_key = f"{lb.get('round')}|{lb.get('tick')}"
        if known.get("last_lb") != lb_key:
            _append(live / "leaderboard.jsonl", [{
                "tick": lb.get("tick"), "seen_tick": tick, "at": stamp, "t_hours": sit.t_hours,
                "round": lb.get("round"), "rounds": lb.get("rounds"),
                "teams": {t.get("team"): {k: t.get(k) for k in
                                          ("score", "negotiating", "market", "level", "album_filled",
                                           "pages_complete", "deals", "rank", "venue", "luck")}
                          for t in _team_rows(lb.get("teams"))}}])
            known["last_lb"] = lb_key

    novelty = detect_novelty(known, sit, slow, live)
    if gap:
        novelty.append({"kind": "feed_gap", "tick": tick, "at": time.time(), "detail": gap})
        known.setdefault("gaps", []).append({**gap, "tick": tick})
        known["gaps"] = known["gaps"][-50:]
    sit.novelty = novelty
    _append(live / "novelty.jsonl", novelty)
    known["last_event_id"] = sit.last_event_id
    known["last_tick"] = tick
    save_known(live, known)

    sit.errors = r.errors
    sit.requests = r.n
    sit.perceived_at = time.time()
    return sit
