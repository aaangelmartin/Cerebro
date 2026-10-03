"""Rebuild the game as the brain saw it at a past moment, from the recorder streams and the bot's logs.

World(record_root, live_root).build(ts, out) writes:
  out/latest/       me, my_offers, leaderboard, clock, schedule, levels, catalog, dealers, venues, books/<venue>
  out/feed/<day>.jsonl   the feed up to ts (the strategist's analysis reads it next to latest/)
  out/live/         decisions, outcomes, llm, novelty, council up to ts; status.json; control.json
so a Strategist(live=out/live, record=out/latest, now=lambda: ts) builds the picture of that moment.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

DAY_FILE = "2026-10-03.jsonl"
FULL = ("me", "leaderboard", "clock", "schedule", "levels", "catalog")      # rows carry the whole document
LIVE_LOGS = ("decisions.jsonl", "outcomes.jsonl", "llm.jsonl", "novelty.jsonl", "council.jsonl")


def _rows(path: Path) -> list[dict]:
    out = []
    try:
        with Path(path).open() as f:
            for ln in f:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def _ts(row: dict) -> float:
    return float(row.get("ts") or row.get("seen_at") or 0)


class World:
    def __init__(self, record_root: Path, live_root: Path, day_file: str = DAY_FILE):
        self.record, self.live, self.day_file = Path(record_root), Path(live_root), day_file
        self._cache: dict[str, list[dict]] = {}

    def stream(self, name: str) -> list[dict]:
        if name not in self._cache:
            rows = _rows(self.record / name / self.day_file)
            rows.sort(key=lambda r: (_ts(r), r.get("seq") or 0))
            self._cache[name] = rows
        return self._cache[name]

    def tick_ts(self, tick: int) -> float:
        """Epoch of the first clock row at or after `tick` (+20 s, mid-tick, after the bot acted)."""
        rows = [r for r in self.stream("clock") if (r.get("tick") or 0) >= tick]
        if not rows:
            raise ValueError(f"tick {tick} is not in the recorded clock stream")
        return _ts(rows[0]) + 20.0

    # ------------------------------------------------------------------ documents at ts
    def full_at(self, name: str, ts: float):
        last = None
        for r in self.stream(name):
            if _ts(r) > ts:
                break
            last = r
        if last is None:
            return None
        return last.get("data") if "data" in last else last

    def dealers_at(self, ts: float) -> dict:
        personas: dict[str, dict] = {}
        for r in self.stream("dealers"):
            if _ts(r) > ts:
                break
            d = r.get("data") or {}
            if d.get("personas") is not None:
                for p in d["personas"]:
                    if p.get("id"):
                        personas[p["id"]] = {**personas.get(p["id"], {}), **p}
            elif r.get("kind") == "detail" and r.get("pid"):
                personas[r["pid"]] = {**personas.get(r["pid"], {}), **d}
        return {"personas": list(personas.values())}

    def venues_at(self, ts: float) -> dict:
        last = None
        for r in self.stream("venues"):
            if _ts(r) > ts:
                break
            last = r
        return {"venues": (last or {}).get("venues") or []}

    @staticmethod
    def _apply(book: dict, row: dict) -> None:
        for o in row.get("added") or []:
            if isinstance(o, dict) and o.get("id") is not None:
                book[str(o["id"])] = o
        for oid in row.get("removed") or []:
            book.pop(str(oid.get("id") if isinstance(oid, dict) else oid), None)
        ch = row.get("changed") or []
        items = ch.items() if isinstance(ch, dict) else [(c.get("id"), c) for c in ch if isinstance(c, dict)]
        for oid, c in items:
            if str(oid) in book and isinstance(c, dict):
                book[str(oid)] = {**book[str(oid)], **{k: (v[1] if isinstance(v, list) and len(v) == 2 else v)
                                                        for k, v in c.items() if k != "id"}}

    def my_offers_at(self, ts: float) -> dict:
        book: dict[str, dict] = {}
        for r in self.stream("my_offers"):
            if _ts(r) > ts:
                break
            self._apply(book, r)
        return {"offers": list(book.values())}

    def books_at(self, ts: float) -> dict[str, dict]:
        rows = [(r, "snap") for r in self.stream("book_snapshots")] + [(r, "diff") for r in self.stream("books")]
        rows.sort(key=lambda x: (_ts(x[0]), 0 if x[1] == "snap" else 1, x[0].get("seq") or 0))
        books: dict[str, dict[str, dict]] = {}
        for r, kind in rows:
            if _ts(r) > ts:
                break
            v = r.get("venue")
            if not v:
                continue
            if kind == "snap":
                books[v] = {str(o["id"]): o for o in r.get("offers") or [] if o.get("id") is not None}
            else:
                self._apply(books.setdefault(v, {}), r)
        return {v: {"venue": v, "offers": list(b.values())} for v, b in books.items()}

    # ------------------------------------------------------------------ write
    def build(self, ts: float, out: Path, control: dict | None = None, status_extra: dict | None = None) -> dict:
        out = Path(out)
        latest, live, feed_dir = out / "latest", out / "live", out / "feed"
        for p in (latest / "books", live, feed_dir):
            p.mkdir(parents=True, exist_ok=True)
        cur = self.record / "latest"
        for name in FULL:
            doc = self.full_at(name, ts)
            if doc is None and (cur / f"{name}.json").exists():
                doc = json.loads((cur / f"{name}.json").read_text())
            (latest / f"{name}.json").write_text(json.dumps(doc or {}, ensure_ascii=False))
        (latest / "dealers.json").write_text(json.dumps(self.dealers_at(ts), ensure_ascii=False))
        (latest / "venues.json").write_text(json.dumps(self.venues_at(ts), ensure_ascii=False))
        (latest / "my_offers.json").write_text(json.dumps(self.my_offers_at(ts), ensure_ascii=False))
        for v, b in self.books_at(ts).items():
            (latest / "books" / f"{v}.json").write_text(json.dumps(b, ensure_ascii=False))
        with (feed_dir / self.day_file).open("w") as f:
            for r in self.stream("feed"):
                if _ts(r) <= ts:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        for name in LIVE_LOGS:
            with (live / name).open("w") as f:
                for r in _rows(self.live / name):
                    if _ts(r) <= ts:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
        for name in ("dealer_memory.json",):
            if (self.live / name).exists():
                shutil.copy(self.live / name, live / name)
        clock = json.loads((latest / "clock.json").read_text() or "{}") or {}
        (live / "status.json").write_text(json.dumps({"updated": ts, "tick": clock.get("tick"), "state": "running",
                                                      **(status_extra or {})}))
        (live / "control.json").write_text(json.dumps({"armed": True, "mode": "auto", "caps": {}, "protected": [],
                                                       "paused_domains": [], **(control or {}), "updated": ts}))
        return {"latest": latest, "live": live, "feed": feed_dir, "ts": ts, "tick": clock.get("tick"),
                "built_at": time.time()}
