"""Feedback plumbing for the trading domains (duels, dealers, market): the lesson loop's two ends.

1. ``cited(ctx, ids)``: the lesson ids Claude says it relied on, kept only if they are real canary/active
   lessons; the domains copy them onto ``Action.lesson_ids``.
2. ``close(ledger, ...)``: when a negotiation ends (duel closed, dealer thread closed with or without a
   deal, our market offer filled or expired) the domain appends ONE outcome to the ledger with status
   ``deal`` | ``no_deal``, what was realised, the originating action ids and the lesson ids.

The Lab process ingests those closings and calls ``LessonStore.record_use``; the trading loop never
touches lesson weights. Everything here swallows its errors: feedback must never break a tick.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from bazaar.core.types import Outcome

log = logging.getLogger("bazaar.lab.feedback")

LESSON_IDS_SCHEMA = {"type": "array", "items": {"type": "string"},
                     "description": "Ids of the LESSONS you relied on for this decision (e.g. L01); [] if none."}
CITE_TEXT = "Cite the lesson ids you relied on in lesson_ids ([] if none); never invent ids."


def cited(ctx: Any, ids: Any) -> list[str]:
    store = getattr(ctx, "lessons", None) if ctx is not None else None
    if store is None or not hasattr(store, "known_ids") or not ids:
        return []
    try:
        return list(store.known_ids(list(ids) if isinstance(ids, (list, tuple)) else []))
    except Exception:  # noqa: BLE001
        return []


def close(ledger: Any, *, domain: str, key: str, status: str, tick: Any = 0,
          action_ids: Iterable[str] = (), lesson_ids: Iterable[str] = (), realised: dict | None = None,
          response: dict | None = None) -> dict | None:
    """Append one closing outcome; returns the ledger record (None without a ledger or on error)."""
    if ledger is None or not hasattr(ledger, "outcome"):
        return None
    status = status if status in ("deal", "no_deal") else "no_deal"
    try:
        tick = int(tick or 0)
    except (TypeError, ValueError):
        tick = 0
    out = Outcome(action_id=f"close:{key}", tick=tick, status=status, response=dict(response or {}),
                  realised={k: v for k, v in (realised or {}).items() if v is not None})
    try:
        return ledger.outcome(out, None, closing=key, domain=domain, kind="close",
                              action_ids=list(dict.fromkeys(str(a) for a in action_ids if a)),
                              lesson_ids=list(dict.fromkeys(str(x) for x in lesson_ids if x)))
    except Exception as e:  # noqa: BLE001
        log.warning("closing %s not logged: %s", key, e)
        return None


def track(book: dict, key: str, action_id: str, lesson_ids: Iterable[str], keep: int = 40) -> None:
    """Remember which actions (and lessons) belong to one negotiation, in a small JSON-able dict."""
    rec = book.setdefault(str(key), {"actions": [], "lessons": []})
    if action_id and action_id not in rec["actions"]:
        rec["actions"] = (rec["actions"] + [action_id])[-keep:]
    for x in lesson_ids or []:
        if x not in rec["lessons"]:
            rec["lessons"].append(x)
