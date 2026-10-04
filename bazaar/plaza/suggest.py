"""The suggestion box: a team tells the host what the market lacks, and reads the host's answer.

A team reads only its own suggestions; our panel reads them all and answers (`Suggest.set`, an admin action)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .store import TEAM_RX, PlazaError, read_json, write_atomic

TOPICS = ("feature", "bug", "price", "other")
STATES = ("open", "planned", "done", "dismissed")
TEXT_MAX = 600
PER_MINUTE = 6
SAME_WITHIN_S = 60.0
KEEP = 2000


class Suggest:
    def __init__(self, path: Path | str, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.lock = threading.Lock()
        data = read_json(self.path)
        self.rows: list[dict] = [r for r in data.get("rows") or [] if isinstance(r, dict) and r.get("id")]
        self.rows = [r for r in self.rows if isinstance(r["id"], str) and isinstance(r.get("team"), str)
                     and isinstance(r.get("text"), str) and isinstance(r.get("ts"), (int, float))]
        n = data.get("n")
        self.n = max([n if isinstance(n, int) and not isinstance(n, bool) else 0]
                     + [int(r["id"][2:]) for r in self.rows if r["id"][2:].isdigit()])

    def _save(self) -> None:
        write_atomic(self.path, json.dumps({"n": self.n, "rows": self.rows}, ensure_ascii=False).encode("utf-8"))

    def add(self, team: str, text, topic=None, tick: int | None = None) -> dict:
        if not isinstance(team, str) or not TEAM_RX.fullmatch(team):
            raise PlazaError(400, "bad_request", "team ids look like t04")
        if not isinstance(text, str) or not text.strip():
            raise PlazaError(400, "bad_request", "text is what you suggest, in a few words")
        if topic is None:
            topic = "other"
        if topic not in TOPICS:
            raise PlazaError(400, "bad_request", "topic is feature, bug, price or other")
        text = " ".join(text.split())[:TEXT_MAX]
        now = self.clock()
        with self.lock:
            mine = [r for r in self.rows if r["team"] == team]
            for r in reversed(mine):                           # the same words again: the same suggestion
                if now - r["ts"] < SAME_WITHIN_S and r["text"] == text:
                    return {"id": r["id"], "status": r["status"]}
            if len([r for r in mine if now - r["ts"] < 60.0]) >= PER_MINUTE:
                raise PlazaError(429, "slow_down", "too many suggestions; try again in a minute")
            self.n += 1
            row = {"id": f"s-{self.n:04d}", "team": team, "topic": topic, "text": text, "status": "open",
                   "reply": None, "tick": tick if isinstance(tick, int) and not isinstance(tick, bool) else None,
                   "ts": now}
            self.rows = (self.rows + [row])[-KEEP:]
            self._save()
            return {"id": row["id"], "status": "open"}

    def mine(self, team: str) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.rows if r["team"] == team]

    def all(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.rows]

    def set(self, sid, status=None, reply=None) -> dict:
        """Ours: move a suggestion and answer it."""
        if status is not None and status not in STATES:
            raise PlazaError(400, "bad_request", "status is open, planned, done or dismissed")
        if reply is not None and not isinstance(reply, str):
            raise PlazaError(400, "bad_request", "reply is a short text")
        with self.lock:
            row = next((r for r in self.rows if r["id"] == sid), None)
            if row is None:
                raise PlazaError(404, "not_found", "no such suggestion")
            if status is not None:
                row["status"] = status
            if reply is not None:
                row["reply"] = " ".join(reply.split())[:TEXT_MAX] or None
            self._save()
            return dict(row)


def of(board) -> Suggest:
    """The market's one suggestion box: `board.suggest` (the panel's `suggestion` action calls its `set`)."""
    box = getattr(board, "suggest", None)
    if box is None:
        with _MAKE:
            box = getattr(board, "suggest", None)
            if box is None:
                box = Suggest(Path(board.live) / "plaza_suggestions.json")
                board.suggest = box
    return box


_MAKE = threading.Lock()
