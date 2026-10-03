"""Anthropic key router: which key and which model each call uses, and what it all costs.

- Picks the live key with the most budget left (KEY_CAP_USD each, whole weekend).
- 401/403/credit errors kill a key; 429/529/timeouts put it on cooldown.
- Spend per key and per Madrid day (fri/sat/sun) lives in data/live/llm_spend.json (atomic writes).
- At DEGRADE_AT of DAY_CAP_USD, model=None and explicit Opus step one rung down DEGRADE_LADDER.
"""
from __future__ import annotations

import fcntl
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import config

log = logging.getLogger("bazaar.llm")
MADRID = ZoneInfo("Europe/Madrid")
CACHE_READ_X, CACHE_WRITE_X = 0.1, 1.25


class LLMUnavailable(Exception):
    """No key, budget spent or every key failing."""


class LLMTimeout(Exception):
    pass


def madrid_day(now: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now, MADRID).strftime("%a").lower()[:3]


def cost_usd(model: str, usage: dict) -> float:
    pin, pout = config.PRICES.get(model) or config.PRICES.get(_family(model)) or (4.0, 20.0)
    u = {k: (usage.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                          "cache_creation_input_tokens")}
    return (u["input_tokens"] * pin + u["output_tokens"] * pout + u["cache_read_input_tokens"] * pin * CACHE_READ_X
            + u["cache_creation_input_tokens"] * pin * CACHE_WRITE_X) / 1e6


def _family(model: str) -> str:
    for m in config.DEGRADE_LADDER:
        if model.startswith(m.rsplit("-", 1)[0]):
            return m
    return model


class KeyRouter:
    def __init__(self, keys: list[tuple[str, str]] | None = None, path: Path | str | None = None,
                 key_cap: float | None = None, day_cap: float | None = None, clock=time.time):
        self.keys = list(config.anthropic_keys() if keys is None else keys)
        self.path = Path(path or config.LIVE / "llm_spend.json")
        self.key_cap = config.KEY_CAP_USD if key_cap is None else key_cap
        self.day_cap = config.DAY_CAP_USD if day_cap is None else day_cap
        self.clock = clock
        self.lock = threading.RLock()
        self.dead: dict[str, str] = {}          # label -> why
        self.cool: dict[str, float] = {}        # label -> epoch when usable again
        self.state = {"keys": {}, "days": {}}
        self._reload()

    def _reload(self):
        try:
            loaded = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if isinstance(loaded, dict):
            self.state = {"keys": loaded.get("keys") or {}, "days": loaded.get("days") or {}}

    # --- keys ---------------------------------------------------------------------
    def key_spent(self, label: str) -> float:
        return float(self.state["keys"].get(label, 0.0))

    def available(self) -> list[str]:
        now = self.clock()
        with self.lock:
            return [lb for lb, _ in self.keys if lb not in self.dead and self.cool.get(lb, 0) <= now
                    and self.key_spent(lb) < self.key_cap]

    def pick(self, exclude: set[str] = frozenset()) -> tuple[str, str] | None:
        """(label, key) with most budget left, or None if none is usable right now."""
        with self.lock:
            ok = [lb for lb in self.available() if lb not in exclude] or self.available()
            if not ok:
                return None
            lb = max(ok, key=lambda x: self.key_cap - self.key_spent(x))
            return lb, dict(self.keys)[lb]

    def next_ready(self) -> float | None:
        """Epoch when a cooling key comes back (None if every key is dead or capped)."""
        with self.lock:
            waits = [self.cool.get(lb, 0) for lb, _ in self.keys
                     if lb not in self.dead and self.key_spent(lb) < self.key_cap]
            return min(waits) if waits else None

    def mark_dead(self, label: str, why: str):
        with self.lock:
            self.dead[label] = why
        log.warning("llm key %s dead: %s", label, why)

    def cooldown(self, label: str, seconds: float):
        with self.lock:
            self.cool[label] = max(self.cool.get(label, 0), self.clock() + seconds)

    # --- budget and models -----------------------------------------------------------
    def day(self) -> str:
        return madrid_day(self.clock())

    def day_spent(self, day: str | None = None) -> float:
        return float(self.state["days"].get(day or self.day(), {}).get("usd", 0.0))

    def degraded(self) -> bool:
        return self.day_spent() >= config.DEGRADE_AT * self.day_cap

    def resolve(self, model: str | None) -> str:
        """The model this call will really use; raises LLMUnavailable when the day cap is spent."""
        if self.day_spent() >= self.day_cap:
            raise LLMUnavailable(f"day cap {self.day_cap}$ spent")
        ladder = config.DEGRADE_LADDER
        if model is None:
            return ladder[1] if self.degraded() else ladder[0]
        if self.degraded() and model == ladder[0]:
            log.warning("llm degraded: %s -> %s (day spend %.2f$)", model, ladder[1], self.day_spent())
            return ladder[1]
        return model

    def model_now(self) -> str:
        try:
            return self.resolve(None)
        except LLMUnavailable:
            return "none"

    def record(self, label: str, model: str, usage: dict, purpose: str = "") -> float:
        cost = cost_usd(model, usage)
        with self.lock, _FileLock(self.path.with_suffix(".lock")):
            self._reload()                       # another process (broker) may have written since
            k = self.state["keys"]
            k[label] = round(k.get(label, 0.0) + cost, 6)
            d = self.state["days"].setdefault(self.day(), {"usd": 0.0, "by_key": {}, "by_purpose": {}, "by_model": {},
                                                           "calls": 0})
            d["usd"] = round(d["usd"] + cost, 6)
            d["calls"] = d.get("calls", 0) + 1
            for field, name in (("by_key", label), ("by_purpose", purpose or "?"), ("by_model", model)):
                bucket = d.setdefault(field, {})
                bucket[name] = round(bucket.get(name, 0.0) + cost, 6)
            self._save()
        return cost

    def summary(self) -> dict:
        with self.lock:
            day = self.day()
            d = self.state["days"].get(day, {})
            now = self.clock()
            by_key = {lb: {"usd_total": round(self.key_spent(lb), 4), "usd_today": round(d.get("by_key", {}).get(lb, 0), 4),
                           "cap": self.key_cap, "dead": self.dead.get(lb),
                           "cooldown_s": round(max(0.0, self.cool.get(lb, 0) - now), 1)} for lb, _ in self.keys}
            return {"day": day, "usd": round(d.get("usd", 0.0), 4), "cap": self.day_cap,
                    "degrade_at": round(config.DEGRADE_AT * self.day_cap, 2), "by_key": by_key,
                    "by_purpose": d.get("by_purpose", {}), "by_model": d.get("by_model", {}),
                    "calls": d.get("calls", 0), "model_now": self.model_now()}

    def _save(self):
        tmp = self.path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(self.state, indent=1))
        tmp.replace(self.path)


class _FileLock:
    """Advisory lock so several processes can add to the same spend file."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.f = open(self.path, "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()
