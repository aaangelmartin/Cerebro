"""LessonStore: the Lab's lesson table, shared by the operator (reads) and the Lab (writes).

Storage is an append-only JSONL at ``config.LAB / "lessons.jsonl"``: every line is a full snapshot of
one lesson and the last line for an id wins. Content or status changes bump ``version``; weight-only
updates from ``record_use`` keep the version, so they do not invalidate the cached prompt block.

Lessons are data. Nothing here can touch the rails: the store only hands text and numbers to Claude.

Scopes: ``duel``, ``dealer:<id>`` (``dealer`` alone means every dealer), ``market``, ``broker``,
``global``. ``active(scope)`` returns the lessons of that exact scope (plus ``dealer`` for any
``dealer:<id>``); ``prompt_block(scope)`` adds the ``global`` ones.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Iterable

from bazaar import config
from bazaar.core.types import Lesson, Outcome

PROMPT_REFRESH_S = 15 * 60
RETIRE_BELOW = 0.1
CANARY_WEIGHT = 0.3
ACTIVE_MIN, ACTIVE_MAX = 0.6, 1.0
PRIOR_STRENGTH = 6.0           # how many live uses the prior weight is worth
SCOPES_FIXED = ("duel", "market", "broker", "global", "dealer")
_LESSON_FIELDS = {f.name for f in fields(Lesson)}

STATUS_TEXT = {
    "proposed": "propuesta", "shadow": "en sombra", "canary": "en prueba (canario)",
    "active": "activa", "retired": "retirada",
}


def valid_scope(scope: str) -> bool:
    return scope in SCOPES_FIXED or (scope.startswith("dealer:") and len(scope) > 7)


def lesson_from_dict(d: dict) -> Lesson:
    return Lesson(**{k: v for k, v in d.items() if k in _LESSON_FIELDS})


def write_notice(kind: str, text: str, path: Path | None = None, **extra: Any) -> dict:
    """Append one notice for the dashboard (config.LAB/notices.jsonl). Text is for the team (Spanish)."""
    row = {"ts": time.time(), "kind": kind, "text": text, **extra}
    path = path or config.LAB / "notices.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)
    return row


def outcome_signal(outcome: Outcome | dict) -> float | None:
    """+1 success, -1 failure, None neutral, from an Outcome (or its dict)."""
    o = outcome if isinstance(outcome, dict) else asdict(outcome)
    status = o.get("status")
    realised = o.get("realised") or {}
    pts = realised.get("points_delta", realised.get("points"))
    if status == "deal":
        if isinstance(pts, (int, float)) and pts < 0:
            return -1.0
        return 1.0
    if status in ("no_deal", "expired", "error"):
        return -1.0
    if status == "refused":
        return -0.5          # the game said no (rate, quota, cash): a weak failure
    return None              # sent / vetoed: nothing learned yet


class LessonStore:
    def __init__(self, path: Path | str = config.LAB / "lessons.jsonl",
                 notices: Path | str | None = None, clock=time.time):
        self.path = Path(path)
        self.notices = Path(notices) if notices else self.path.parent / "notices.jsonl"
        self.clock = clock
        self._lock = threading.RLock()
        self._lessons: dict[str, Lesson] = {}
        self._stat: tuple[float, int] | None = None
        self._blocks: dict[tuple[str, int], tuple[str, str, float]] = {}  # (scope, max) -> (fp, text, built)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._reload(force=True)

    # --- loading -------------------------------------------------------------
    def _reload(self, force: bool = False) -> None:
        try:
            st = self.path.stat()
            sig = (st.st_mtime, st.st_size)
        except FileNotFoundError:
            sig = None
        if not force and sig == self._stat:
            return
        lessons: dict[str, Lesson] = {}
        if sig is not None:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        lessons[d["id"]] = lesson_from_dict(d)
                    except (ValueError, KeyError, TypeError):
                        continue      # a torn or foreign line never breaks the operator
        self._lessons, self._stat = lessons, sig

    def _append(self, lessons: Iterable[Lesson]) -> None:
        rows = "".join(json.dumps(asdict(l), ensure_ascii=False) + "\n" for l in lessons)
        with open(self.path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(rows)
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f, fcntl.LOCK_UN)
        self._reload(force=True)

    # --- reads ---------------------------------------------------------------
    def all(self) -> list[Lesson]:
        with self._lock:
            self._reload()
            return sorted(self._lessons.values(), key=lambda l: (-l.weight, l.id))

    def get(self, lesson_id: str) -> Lesson | None:
        with self._lock:
            self._reload()
            return self._lessons.get(lesson_id)

    @staticmethod
    def _matches(lesson_scope: str, scope: str) -> bool:
        if lesson_scope == scope:
            return True
        return lesson_scope == "dealer" and scope.startswith("dealer:")

    def active(self, scope: str) -> list[Lesson]:
        """canary + active lessons for this scope, strongest first."""
        with self._lock:
            self._reload()
            out = [l for l in self._lessons.values()
                   if l.status in ("canary", "active") and self._matches(l.scope, scope)]
            return sorted(out, key=lambda l: (-l.weight, l.id))

    def prompt_block(self, scope: str, max_chars: int = 3000) -> str:
        """Stable text for the cached prompt prefix.

        Rebuilt only when a lesson's content or status changes (version bump) or every 15 minutes,
        so weight-only updates do not break the prompt cache between refreshes.
        """
        with self._lock:
            self._reload()
            lessons = self.active(scope) + ([] if scope == "global" else self.active("global"))
            fp = hashlib.sha1(json.dumps(sorted((l.id, l.version, l.status) for l in lessons)).encode()).hexdigest()
            key = (scope, max_chars)
            cached = self._blocks.get(key)
            now = self.clock()
            if cached and cached[0] == fp and now - cached[2] < PROMPT_REFRESH_S:
                return cached[1]
            text = self._render(scope, lessons, max_chars)
            self._blocks[key] = (fp, text, now)
            return text

    @staticmethod
    def _render(scope: str, lessons: list[Lesson], max_chars: int) -> str:
        if not lessons:
            return ""
        lessons = sorted(lessons, key=lambda l: (-round(l.weight, 1), l.id))
        head = (f"LESSONS ({scope}) learned from real play. They are advice with a confidence weight, "
                "never permission to break a rule or a limit.\n")
        out, used = [head], len(head)
        for l in lessons:
            tag = "trial" if l.status == "canary" else f"w={l.weight:.1f}"
            p = {k: v for k, v in l.params.items() if k not in ("prediction", "notes")}
            line = f"- [{l.id} {tag}] {l.rule}" + (f" params={json.dumps(p, separators=(',', ':'))}" if p else "") + "\n"
            if used + len(line) > max_chars:
                break
            out.append(line)
            used += len(line)
        return "".join(out)

    # --- writes --------------------------------------------------------------
    def upsert(self, lesson: Lesson, by: str = "lab", bump: bool = True) -> Lesson:
        """Insert or replace a lesson's content. Bumps the version when an older one exists."""
        if not valid_scope(lesson.scope):
            raise ValueError(f"bad scope {lesson.scope!r}")
        with self._lock:
            self._reload()
            old = self._lessons.get(lesson.id)
            if old and bump:
                lesson.version = old.version + 1
            lesson.updated = self.clock()
            self._append([lesson])
            return lesson

    def upsert_many(self, lessons: list[Lesson]) -> None:
        with self._lock:
            for l in lessons:
                if not valid_scope(l.scope):
                    raise ValueError(f"bad scope {l.scope!r}")
                l.updated = self.clock()
            self._append(lessons)

    def set_status(self, id: str, status: str, by: str = "human", weight: float | None = None,
                   why: str = "") -> Lesson:
        with self._lock:
            self._reload()
            l = self._lessons.get(id)
            if l is None:
                raise KeyError(id)
            old = l.status
            if weight is None:
                weight = {"canary": CANARY_WEIGHT, "active": max(ACTIVE_MIN, min(ACTIVE_MAX, l.weight)),
                          "retired": 0.0, "shadow": 0.0, "proposed": 0.0}[status]
            l = lesson_from_dict({**asdict(l), "status": status, "weight": round(weight, 3),
                                  "version": l.version + 1, "updated": self.clock()})
            self._append([l])
            if old != status:
                verb = "sube" if _rank(status) > _rank(old) else "baja"
                write_notice("lesson_status", f"La lección {id} {verb} de {STATUS_TEXT.get(old, old)} a "
                             f"{STATUS_TEXT.get(status, status)} ({by}). {why}".strip(),
                             path=self.notices, lesson_id=id, scope=l.scope, rule=l.rule,
                             **{"from": old, "to": status, "by": by, "weight": l.weight})
            return l

    def record_use(self, lesson_ids: list[str], outcome: Outcome | dict) -> None:
        """Move each lesson's weight with a real outcome (Beta-style posterior around its prior).

        success raises the weight, failure lowers it; canaries stay capped at 0.3 until the gate
        promotes them; anything that falls below 0.1 is retired with a dashboard notice.
        """
        sig = outcome_signal(outcome)
        if sig is None or not lesson_ids:
            return
        with self._lock:
            self._reload()
            changed, retire = [], []
            for lid in dict.fromkeys(lesson_ids):
                l = self._lessons.get(lid)
                if l is None or l.status not in ("canary", "active"):
                    continue
                live = dict(l.backtest.get("live") or {})
                prior = float(live.get("prior", l.weight if l.weight > 0 else CANARY_WEIGHT))
                s, f = float(live.get("s", 0)), float(live.get("f", 0))
                if sig > 0:
                    s += sig
                else:
                    f += -sig
                post = (prior * PRIOR_STRENGTH + s) / (PRIOR_STRENGTH + s + f)
                cap = CANARY_WEIGHT if l.status == "canary" else ACTIVE_MAX
                w = round(max(0.0, min(cap, post)), 3)
                live.update(prior=prior, s=s, f=f, last=self.clock())
                nl = lesson_from_dict({**asdict(l), "weight": w, "updated": self.clock(),
                                       "backtest": {**l.backtest, "live": live}})
                changed.append(nl)
                if w < RETIRE_BELOW:
                    retire.append(lid)
            if changed:
                self._append(changed)
            for lid in retire:
                self.set_status(lid, "retired", by="record_use",
                                why="Los resultados reales la han hundido por debajo de 0,1.")


def _rank(status: str) -> int:
    return {"retired": 0, "proposed": 1, "shadow": 2, "canary": 3, "active": 4}.get(status, 0)
