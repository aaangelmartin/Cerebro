"""Append-only JSONL journals in data/live/ that the Lab and the dashboard read.

Files: decisions, outcomes, llm, events, leaderboard, council (`<name>.jsonl`). Every record gets a
per-file increasing `id` and a `ts` (epoch seconds), so readers can poll with `since_id`.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .. import config

NAMES = ("decisions", "outcomes", "llm", "events", "leaderboard", "council")
SPEND_STATUSES = {"sent", "deal"}
_CHUNK = 64 * 1024


def _jsonable(x):
    return asdict(x) if is_dataclass(x) else x


class Ledger:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root or config.LIVE)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._next: dict[str, int] = {}

    def path(self, name: str) -> Path:
        return self.root / f"{name}.jsonl"

    # --- writing ------------------------------------------------------------------
    def append(self, name: str, rec: dict) -> dict:
        rec = dict(_jsonable(rec))
        with self._lock:
            if name not in self._next:
                last = self._last_line(name)
                self._next[name] = int(last.get("id", 0)) + 1 if last else 1
            rec = {"id": self._next[name], "ts": round(rec.pop("ts", None) or time.time(), 3), **rec}
            line = json.dumps(rec, ensure_ascii=False, default=str) + "\n"
            with self.path(name).open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
            self._next[name] += 1
        return rec

    def decision(self, action, verdict, source: str = "", latency_s: float | None = None, tick: int | None = None,
                 **extra) -> dict:
        return self.append("decisions", {"tick": tick, "action": _jsonable(action), "verdict": _jsonable(verdict),
                                         "source": source or getattr(action, "source", ""),
                                         "latency_s": latency_s, **extra})

    def outcome(self, outcome, action=None, **extra) -> dict:
        rec = dict(_jsonable(outcome))
        if action is not None:
            rec.update(kind=action.kind, domain=action.domain, lesson_ids=list(action.lesson_ids))
        return self.append("outcomes", {**rec, **extra})

    # --- reading ------------------------------------------------------------------
    def tail(self, name: str, since_id: int | None = None, limit: int = 200) -> list[dict]:
        """Records with id > since_id (oldest first), at most the last `limit`."""
        out: list[dict] = []
        for rec in self._backwards(name):
            if since_id is not None and int(rec.get("id", 0)) <= since_id:
                break
            out.append(rec)
            if len(out) >= limit:
                break
        out.reverse()
        return out

    def since_time(self, name: str, t0: float) -> list[dict]:
        out = []
        for rec in self._backwards(name):
            if float(rec.get("ts", 0)) < t0:
                break
            out.append(rec)
        out.reverse()
        return out

    def spend_last_hour(self, now: float | None = None) -> float:
        """Primas that left our cash in the last hour (outcomes with realised.cash_out, once per action)."""
        return sum(r.get("cash_out", 0) or 0 for r in self._spend_records(3600, now).values())

    def deals_with(self, team: str, hours: float = 1.0, now: float | None = None) -> int:
        return sum(1 for r in self._spend_records(hours * 3600, now, deals=True).values()
                   if r.get("counterparty") == team)

    def _spend_records(self, window: float, now: float | None, deals: bool = False) -> dict:
        now = time.time() if now is None else now
        best: dict[str, dict] = {}
        for rec in self.since_time("outcomes", now - window):
            if rec.get("status") not in SPEND_STATUSES:
                continue
            real = rec.get("realised") or {}
            if deals and not real.get("counterparty"):
                continue
            if not deals and not real.get("cash_out"):
                continue
            key = rec.get("action_id") or f"#{rec.get('id')}"
            if key not in best or (real.get("cash_out") or 0) > (best[key].get("cash_out") or 0):
                best[key] = real
        return best

    def _last_line(self, name: str) -> dict | None:
        return next(iter(self._backwards(name)), None)

    def _backwards(self, name: str):
        """Yield parsed records from the end of the file, skipping broken lines."""
        p = self.path(name)
        try:
            f = p.open("rb")
        except FileNotFoundError:
            return
        with f:
            f.seek(0, os.SEEK_END)
            pos, rest = f.tell(), b""
            while pos > 0:
                step = min(_CHUNK, pos)
                pos -= step
                f.seek(pos)
                buf = f.read(step) + rest
                lines = buf.split(b"\n")
                rest = lines.pop(0)              # maybe partial: keep for the next chunk
                for raw in reversed(lines):
                    rec = _parse(raw)
                    if rec is not None:
                        yield rec
            rec = _parse(rest)
            if rec is not None:
                yield rec


def _parse(raw: bytes):
    raw = raw.strip()
    if not raw:
        return None
    try:
        rec = json.loads(raw)
    except ValueError:
        return None
    return rec if isinstance(rec, dict) else None


_default: Ledger | None = None
_default_lock = threading.Lock()


def default() -> Ledger:
    """The process-wide ledger on config.LIVE."""
    global _default
    with _default_lock:
        if _default is None:
            _default = Ledger()
        return _default
