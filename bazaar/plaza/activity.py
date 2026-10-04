"""What each team's agent did on the market, for its own Home screen: one line per event, newest last.

    Activity.add(team, kind, text, by="agent", **extra)     # extra: match, ref, tick
    Activity.since(team, seq, limit)                        # GET /api/me/activity?since=

A team reads only its own lines. A line never carries a private limit, a list of held cards, or a price that is
not already public on a match: callers pass plain words. The file is one JSON line per event; a line cut short by
a crash is skipped on load, and the file is rewritten whole (see store.write_atomic) when it grows."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from .store import TEAM_RX, write_atomic

KINDS = ("connect", "sync", "limits", "queue", "ack", "message", "match", "offer", "settle", "order", "settings",
         "suggestion")
BY = ("agent", "human", "market")
EXTRA = {"match": r"m-[0-9a-f]{10}", "ref": r"[A-Z]{3}-\d{2}"}
TEXT_MAX = 200
KEEP, TRIM_AT = 4000, 6000                 # lines in the file
SAME_WITHIN_S = 30.0                       # the same line twice in a row is one line


class Activity:
    def __init__(self, path: Path | str, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.lock = threading.Lock()
        self.rows: list[dict] = []
        self.seq = 0
        self.last: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue                                       # a line cut short: skip it, keep the rest
            if isinstance(row, dict) and isinstance(row.get("seq"), int) and isinstance(row.get("team"), str):
                self.rows.append(row)
                self.seq = max(self.seq, row["seq"])
                self.last[row["team"]] = row
        self.rows = self.rows[-KEEP:]

    def add(self, team: str, kind: str, text: str, by: str = "agent", **extra) -> dict | None:
        """Appends one line. Returns it, or None when it only repeats the team's last line. Never raises."""
        if not isinstance(team, str) or not TEAM_RX.fullmatch(team) or kind not in KINDS or not isinstance(text, str):
            return None
        row = {"team": team, "ts": self.clock(), "kind": kind, "by": by if by in BY else "agent",
               "text": " ".join(text.split())[:TEXT_MAX]}
        tick = extra.get("tick")
        row["tick"] = tick if isinstance(tick, int) and not isinstance(tick, bool) else None
        for key, rx in EXTRA.items():
            if isinstance(extra.get(key), str) and re.fullmatch(rx, extra[key]):
                row[key] = extra[key]
        with self.lock:
            prev = self.last.get(team)
            if prev and all(prev.get(k) == row.get(k) for k in ("kind", "by", "text", "match", "ref")) \
                    and row["ts"] - prev["ts"] < SAME_WITHIN_S:
                return None
            self.seq += 1
            row = {"seq": self.seq, **row}
            self.rows.append(row)
            self.last[team] = row
            try:
                if len(self.rows) > TRIM_AT:
                    self.rows = self.rows[-KEEP:]
                    write_atomic(self.path, "".join(json.dumps(r, ensure_ascii=False) + "\n"
                                                    for r in self.rows).encode("utf-8"))
                else:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
            except OSError:
                pass                                           # the line stays in memory
            return {k: v for k, v in row.items() if k != "team"}

    def since(self, team: str, seq: int = 0, limit: int = 100) -> dict:
        """The team's lines after `seq`, oldest first; the last `limit` of them."""
        limit = max(1, min(int(limit or 100), 200))
        with self.lock:
            mine = [{k: v for k, v in r.items() if k != "team"} for r in self.rows
                    if r["team"] == team and r["seq"] > seq]
            last = self.last.get(team)
        return {"team": team, "seq": last["seq"] if last else 0, "items": mine[-limit:]}

    def seq_of(self, team: str) -> int:
        with self.lock:
            last = self.last.get(team)
            return last["seq"] if last else 0


def of(board) -> Activity:
    """The market's one activity log: `board.team_activity` (B2 calls `board.team_activity.add(...)` for matches)."""
    log = getattr(board, "team_activity", None)
    if log is None:
        with _MAKE:
            log = getattr(board, "team_activity", None)
            if log is None:
                log = Activity(Path(board.live) / "plaza_activity.jsonl")
                board.team_activity = log
    return log


_MAKE = threading.Lock()
