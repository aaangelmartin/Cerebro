"""JSON files that survive a crash half way through a write.

`save` writes a temporary file, keeps the previous copy as `<name>.bak` and renames; `load` falls back to the
`.bak` when the main file does not parse. Used by the stores of matches and of the agents' queues."""
from __future__ import annotations

import json
import os
from pathlib import Path


def bak(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def load(path: Path | str, default=None):
    """The file's content, else its backup's, else `default`. Only a JSON object counts."""
    path = Path(path)
    for p in (path, bak(path)):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return {} if default is None else default


def save(path: Path | str, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False))
        f.flush()
        os.fsync(f.fileno())
    try:
        if path.exists():
            json.loads(path.read_text(encoding="utf-8"))      # only a copy that parses becomes the backup
            os.replace(path, bak(path))
    except (OSError, ValueError):
        pass
    os.replace(tmp, path)
