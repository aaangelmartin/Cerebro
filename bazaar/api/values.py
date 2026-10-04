"""Card values to us for the dashboard: GET /values.

Built from the recorder's latest /api/me and catalog plus the exact /api/me/value answers the bot already
fetched (data/live/exact_values.json, written by bazaar.run each tick). Nothing here talks to the game.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from ..dealers.values import Values

CACHE_S = 5.0
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "key": None, "doc": None}


def _read(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    inner = d.get("data")
    return inner if isinstance(inner, dict) and ("assets" in inner or "sets" in inner) else d


def build(record: Path, live: Path, now: float | None = None) -> dict:
    """{"updated", "items": {REF: {value, exact, held, held_value, spare_value, book, rarity, set, page, name}}}.
    value = what ONE MORE copy is worth to us (exact when the game told us for our current copy count,
    else book x affinity x copy marginal). held_value = what our best held copy is worth (from /api/me)."""
    now = now or time.time()
    me = _read(Path(record) / "latest" / "me.json")
    catalog = _read(Path(record) / "latest" / "catalog.json")
    try:
        exact = json.loads((Path(live) / "exact_values.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        exact = {}
    v = Values(me, catalog, exact if isinstance(exact, dict) else {})
    items = {}
    for ref, c in v.cards.items():
        held = v.count(ref)
        ex = v.exact.get(ref)
        is_exact = bool(isinstance(ex, dict) and ex.get("count") == held and ex.get("value") is not None)
        value = float(ex["value"]) if is_exact else v.estimate_next(ref)
        own = sorted((float(a["your_value"]) for a in v.held.get(ref, []) if a.get("your_value") is not None),
                     reverse=True)
        items[ref] = {
            "value": round(value, 2), "exact": is_exact,
            "exact_at": ex.get("at") if is_exact else None,
            "held": held,
            "held_value": round(own[0], 2) if own else None,
            "spare_value": (round(own[-1], 2) if len(own) >= 2 else
                            round(v.book(ref) * v.affinity.get(v.set_of(ref), 1.0) * v.marginal(held - 1), 2)
                            if held >= 2 else None),
            "book": v.book(ref), "rarity": c.get("rarity"), "set": c.get("set"),
            "page": c.get("page") is not False, "name": c.get("name"), "released": bool(c.get("released")),
        }
    return {"updated": now, "affinity": v.affinity, "items": items}


def card_values(record: Path, live: Path) -> dict:
    key = (str(record), str(live))
    with _lock:
        if _cache["doc"] is not None and _cache["key"] == key and time.time() - _cache["at"] < CACHE_S:
            return _cache["doc"]
    doc = build(record, live)
    with _lock:
        _cache.update(at=time.time(), key=key, doc=doc)
    return doc
