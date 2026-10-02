"""Record everything the game shows publicly, so we can analyse it later.

    .venv/bin/python -m bot.recorder          # appends to bot/data/history/

The public feed only keeps its last 500 events (about 15 ticks), and the event stream cannot be
replayed, so anything older is lost for good. This polls it every few seconds, de-duplicates by
event id and appends to disk, plus a leaderboard snapshot and the clock once per tick.

  history/events.jsonl      every public event, in order, each with the wall time we saw it
  history/leaderboard.jsonl one line per tick: every team's score, deals, album, rank, venue
  history/state.json        the last event id and tick recorded (so a restart continues)

Reads go through the team gateway without the team key (public rate budget), so they cost the
bot nothing.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = Path(os.environ.get("BOT_HISTORY_DIR") or ROOT / "data" / "history")
BASE = os.environ.get("BOT_GATEWAY_URL", "http://127.0.0.1:8787").rstrip("/")
TOKEN = ""
POLL = 4.0


def get(path: str):
    req = urllib.request.Request(BASE + path, headers={"X-Team-Key": TOKEN} if TOKEN else {})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def append(name: str, rows: list):
    with (OUT / name).open("a") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def load_state() -> dict:
    try:
        return json.loads((OUT / "state.json").read_text())
    except (OSError, ValueError):
        return {"last_event": 0, "last_tick": -1, "gaps": []}


def save_state(st: dict):
    tmp = OUT / "state.tmp"
    tmp.write_text(json.dumps(st))
    tmp.replace(OUT / "state.json")


def main():
    global TOKEN
    OUT.mkdir(parents=True, exist_ok=True)
    from .core import load_env
    TOKEN = load_env().get("GATEWAY_TOKEN", "")
    st = load_state()
    print(f"recording to {OUT} (from event {st['last_event']}, tick {st['last_tick']})", flush=True)
    while True:
        try:
            events = get("/api/feed?limit=500").get("events", [])
            fresh = sorted((e for e in events if e.get("id", 0) > st["last_event"]), key=lambda e: e["id"])
            if fresh:
                oldest = min(e["id"] for e in events)
                if st["last_event"] and oldest > st["last_event"] + 1:
                    # The feed rolled past events we never saw: record the hole rather than hide it.
                    gap = {"after": st["last_event"], "before": oldest, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
                    st.setdefault("gaps", []).append(gap)
                    print(f"gap: missed events {gap['after'] + 1}..{gap['before'] - 1}", flush=True)
                now = time.strftime("%Y-%m-%d %H:%M:%S")
                append("events.jsonl", [{**e, "seen_at": now} for e in fresh])
                st["last_event"] = fresh[-1]["id"]

            clock = get("/api/clock")
            tick = clock.get("tick")
            if tick is not None and tick != st["last_tick"]:
                lb = get("/api/leaderboard")
                append("leaderboard.jsonl", [{
                    "tick": tick, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "t_hours": clock.get("t_hours"), "round": lb.get("round"), "rounds": lb.get("rounds"),
                    "teams": {t["team"]: {k: t.get(k) for k in
                                          ("score", "negotiating", "market", "level", "album_filled",
                                           "pages_complete", "deals", "rank", "venue", "luck", "rarest", "badges")}
                              for t in lb.get("teams", [])}}])
                st["last_tick"] = tick
            save_state(st)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"retrying after {e.__class__.__name__}: {e}", flush=True)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
