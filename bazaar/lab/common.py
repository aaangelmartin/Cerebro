"""Small helpers shared by the Lab modules: catalog lookups, JSONL io, safe imports of CORE-A pieces."""
from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from bazaar import config

CATALOG_PATH = config.ROOT / "sim" / "data" / "catalog.json"
RARITY_BOOK = {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}
PACK_LIST = {"sobre_barrio": 26, "sobre_plata": 150}
WINDOW_TICKS = 30            # a "time window" for evidence diversity (30 min on Friday's 60 s ticks)
REF_RE = re.compile(r"^[A-Z]{3}-\d{2}$")


@lru_cache(maxsize=1)
def catalog() -> dict:
    try:
        return json.loads(CATALOG_PATH.read_text())
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=1)
def card_index() -> dict[str, dict]:
    out = {}
    for s in catalog().get("sets", []):
        for c in s.get("cards", []):
            out[c["id"]] = {"set": s["id"], "rarity": c["rarity"], "book": c["book"], "name": c.get("name", "")}
    return out


def rarity_of(item: str) -> str:
    """'LAV-09' -> 'rare'; 'sobre_plata' -> 'pack:sobre_plata'; anything else -> 'unknown'."""
    if not item:
        return "unknown"
    item = item.split(":", 1)[1] if item.startswith(("card:", "pack:")) else item
    if item.startswith("sobre_"):
        return f"pack:{item}"
    c = card_index().get(item)
    if c:
        return c["rarity"]
    if REF_RE.match(item):
        return "unknown"
    return item


def book_of(item: str) -> float | None:
    r = rarity_of(item)
    if r.startswith("pack:"):
        return PACK_LIST.get(r[5:])
    c = card_index().get(item)
    return c["book"] if c else RARITY_BOOK.get(r)


def read_jsonl(path: Path, offset: int = 0) -> tuple[list[dict], int]:
    """Rows from byte ``offset`` to the last complete line; returns (rows, new_offset)."""
    rows: list[dict] = []
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
    except FileNotFoundError:
        return rows, offset
    end = data.rfind(b"\n")
    if end < 0:
        return rows, offset
    for line in data[: end + 1].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows, offset + end + 1


def iter_jsonl(path: Path) -> Iterator[dict]:
    rows, _ = read_jsonl(path)
    yield from rows


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
    tmp.replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def window_of(tick: int | None, src: str = "live") -> str:
    return f"{src}:{(tick or 0) // WINDOW_TICKS}"


# --- CORE-A pieces, with safe fallbacks while they are being written ----------------------------
_INVISIBLE = re.compile(r"[\u0000-\u0008\u000b-\u001f\u007f​-‏‪-‮⁠-⁤﻿]")


def wrap(text: str, source: str) -> str:
    """Every foreign text goes through core.untrusted.wrap before a prompt."""
    try:
        from bazaar.core.untrusted import wrap as _wrap
        return _wrap(text, source)
    except ImportError:
        clean = _INVISIBLE.sub("", str(text or ""))[:600].replace("<", "‹").replace(">", "›")
        src = re.sub(r"[^\w:.-]", "", source)[:40]
        return f"<untrusted source='{src}'>{clean}</untrusted>"


def now() -> float:
    return time.time()
