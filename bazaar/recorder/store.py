"""On-disk layout of the recorder (see README.md): daily-rotated append-only JSONL streams, JSON documents
rewritten atomically, the recorder's own resume state, and a small index for readers.

    <root>/<stream>/<YYYY-MM-DD>.jsonl   one record per line: {"seq", "ts", ...}; seq grows per stream forever
    <root>/latest/<name>.json            last value of something (me, leaderboard, a venue's book...)
    <root>/duels/<id>.json, threads/<id>.json   accumulated transcripts
    <root>/state.json                    resume state (offsets, hashes); only the recorder reads it
    <root>/index.json                    streams, files, counts, last seq/tick: what readers start from
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

_TAIL_CHUNK = 64 * 1024


def sig(obj: Any) -> str:
    """Stable short hash of any JSON-able value."""
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:16]


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":"))


def write_json(path: Path, obj: Any) -> None:
    """Atomic replace: readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str))
    tmp.replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def last_record(path: Path) -> dict | None:
    """Last parseable JSON line of a file (skips a torn last line after a crash)."""
    try:
        f = path.open("rb")
    except OSError:
        return None
    with f:
        f.seek(0, os.SEEK_END)
        pos, rest = f.tell(), b""
        while pos > 0:
            step = min(_TAIL_CHUNK, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + rest
            lines = buf.split(b"\n")
            rest = lines.pop(0)
            for raw in reversed(lines):
                rec = _parse(raw)
                if rec is not None:
                    return rec
        return _parse(rest)


def _parse(raw: bytes) -> dict | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        rec = json.loads(raw)
    except ValueError:
        return None
    return rec if isinstance(rec, dict) else None


def iter_records(path: Path):
    """Every parseable record of one stream file, oldest first."""
    try:
        with path.open("rb") as f:
            for raw in f:
                rec = _parse(raw)
                if rec is not None:
                    yield rec
    except OSError:
        return


class Store:
    def __init__(self, root: Path | str, day_fn=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.day_fn = day_fn or (lambda: time.strftime("%Y-%m-%d"))
        self._seq: dict[str, int] = {}
        self._count: dict[str, int] = {}          # records written by this process, per stream
        self._last: dict[str, dict] = {}          # stream -> {"seq", "ts", "tick"} of the last record

    # --- streams ------------------------------------------------------------------------------------------
    def stream_dir(self, stream: str) -> Path:
        return self.root / stream

    def files(self, stream: str) -> list[Path]:
        d = self.stream_dir(stream)
        return sorted(d.glob("*.jsonl")) if d.is_dir() else []

    def last(self, stream: str) -> dict | None:
        """Last record of a stream across its files (newest file first)."""
        for p in reversed(self.files(stream)):
            rec = last_record(p)
            if rec is not None:
                return rec
        return None

    def _next_seq(self, stream: str) -> int:
        if stream not in self._seq:
            last = self.last(stream)
            self._seq[stream] = int(last.get("seq", 0)) if last else 0
        self._seq[stream] += 1
        return self._seq[stream]

    def append(self, stream: str, rec: dict, ts: float | None = None) -> dict:
        row = {"seq": self._next_seq(stream), "ts": round(ts if ts is not None else time.time(), 3), **rec}
        d = self.stream_dir(stream)
        d.mkdir(parents=True, exist_ok=True)
        with (d / f"{self.day_fn()}.jsonl").open("a", encoding="utf-8") as f:
            f.write(dump(row) + "\n")
        self._count[stream] = self._count.get(stream, 0) + 1
        self._last[stream] = {"seq": row["seq"], "ts": row["ts"], "tick": row.get("tick")}
        return row

    # --- documents ----------------------------------------------------------------------------------------
    def put(self, rel: str, obj: Any) -> None:
        write_json(self.root / rel, obj)

    def get(self, rel: str, default: Any = None) -> Any:
        return read_json(self.root / rel, default)

    # --- index --------------------------------------------------------------------------------------------
    def write_index(self, extra: dict | None = None) -> dict:
        streams = {}
        for d in sorted(p for p in self.root.iterdir() if p.is_dir()):
            fs = sorted(d.glob("*.jsonl"))
            if not fs:
                continue
            last = self._last.get(d.name) or {k: v for k, v in (last_record(fs[-1]) or {}).items()
                                              if k in ("seq", "ts", "tick")}
            streams[d.name] = {"files": [f.name for f in fs], "bytes": sum(f.stat().st_size for f in fs),
                               "last_seq": last.get("seq"), "last_ts": last.get("ts"), "last_tick": last.get("tick"),
                               "written_this_run": self._count.get(d.name, 0)}
        docs = sorted(str(p.relative_to(self.root)) for p in (self.root / "latest").glob("**/*.json")) \
            if (self.root / "latest").is_dir() else []
        idx = {"updated": round(time.time(), 3), "root": str(self.root), "streams": streams, "latest": docs,
               "duels": len(list((self.root / "duels").glob("*.json"))) if (self.root / "duels").is_dir() else 0,
               "threads": len(list((self.root / "threads").glob("*.json"))) if (self.root / "threads").is_dir() else 0,
               **(extra or {})}
        write_json(self.root / "index.json", idx)
        return idx
