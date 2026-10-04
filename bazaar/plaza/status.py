"""Is everything on: the clock, the game, the market, the matchmaker, the feed and the caller's agent.

Read from the recorder's `latest/clock.json` (never from the game): `tick`, `tick_seconds`, `next_tick_in`,
`paused`, `doors`, `next_opens`. The page polls this every few seconds and counts down locally in between."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from .feed import venue_fees

STALE_TICKS = 3                 # no recorder file newer than this many tick lengths: the feed is stale
STALE_MIN_S = 45.0              # ... and never less than this: with the doors closed the recorder reads slowly


def _clock(record: Path) -> tuple[dict, float | None]:
    path = Path(record) / "latest" / "clock.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data if isinstance(data, dict) else {}), path.stat().st_mtime
    except (OSError, ValueError):
        return {}, None


def _num(value, default=None):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _iso(value) -> datetime | None:
    try:
        d = datetime.fromisoformat(value)
        return d if d.tzinfo else None
    except (TypeError, ValueError):
        return None


def status(record: Path, venue: str, enabled: bool, mm_paused: bool, team: str | None = None,
           online: bool | None = None, name: str | None = None, now: float | None = None) -> dict:
    """The answer of GET /api/status. `team` and `online` describe the caller, when it is a connected team."""
    now = time.time() if now is None else now
    clock, seen = _clock(record)
    tick_s = _num(clock.get("tick_seconds"), 0) or None
    age = None if seen is None else max(0.0, now - seen)
    doors = str(clock.get("doors") or "").lower()
    game = "closed" if doors == "closed" or not clock else "paused" if clock.get("paused") else "open"
    tick = clock.get("tick") if isinstance(clock.get("tick"), int) and not isinstance(clock.get("tick"), bool) else None
    left = None
    nxt = _num(clock.get("next_tick_in"))
    if game == "open" and tick_s and nxt is not None and age is not None:
        gone = age - nxt
        if gone >= 0:                                          # the recorder's reading is older than a tick
            tick = None if tick is None else tick + 1 + int(gone // tick_s)
            left = tick_s - (gone % tick_s)
        else:
            left = -gone
        left = round(max(0.0, min(left, tick_s)), 1)
    window = max(STALE_TICKS * (tick_s or 15.0), STALE_MIN_S if game != "open" else 0.0)
    feed = "ok" if age is not None and age <= window else "stale"
    market = "off" if not enabled else game
    matchmaker = "paused" if mm_paused else "on" if market == "open" else "waiting"
    opens = _iso(clock.get("next_opens")) if game == "closed" else None
    fee = venue_fees(record).get(venue) or {}
    name = name or os.environ.get("PLAZA_NAME", "v07 Market")
    return {"tick": tick, "tick_seconds": tick_s, "seconds_to_tick": left,
            "time": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"),
            "game": game, "market": market, "matchmaker": matchmaker, "feed": feed,
            "agent": None if team is None else "connected" if online else "offline", "team": team,
            "opens": opens.isoformat() if opens else None,
            "opens_tick": tick + 1 if opens and tick is not None else None,
            "opens_in_s": max(0, int(opens.timestamp() - now)) if opens else None,
            "round": clock.get("round") if isinstance(clock.get("round"), int) else None,
            "round_name": clock.get("round_name") if isinstance(clock.get("round_name"), str) else None,
            "venue": {"id": venue, "name": name, "fee_bps": int(fee.get("bps") or 0),
                      "per_card": int(fee.get("per_card") or 0)},
            "name": name}
