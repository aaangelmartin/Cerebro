"""A team's private limits: the least it sells a card for, the most it pays, what the card is worth to it.

Private means private: only the team itself reads them (its browser session or its agent token). The matcher asks
this module one blind question (do the two limits overlap, and where is the middle?) and never sees a number of
either side on its own. Nobody else does: not another team, not our own panel (it only learns "limits set: yes or
no"), not our bot, brain or broker.

They live in their own folder (0700), outside data/live, in one file encrypted with a key that sits next to it
(0600): a dump, a log or a careless `cat` of the data folder shows nothing. The cipher is the standard library's
HMAC-SHA256 used as a stream (counter mode) with an authentication tag; the same user on this machine could still
read key and file, which is why nothing outside bazaar/plaza may import this module (a test checks it)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

from .store import PlazaError, write_atomic

FIELDS = ("min", "max", "value")
MAX = 2000
HAVE, HAVE_BY_HAND, CHANGED = "#have", "#have_by_hand", "#changed"   # not team ids: a team's limits sit under its id
COOL_TICKS, COOL_S = 20, 300.0                     # a card's min or max moves once in this long


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def seal(key: bytes, plain: bytes) -> bytes:
    enc, mac = hmac.new(key, b"enc", hashlib.sha256).digest(), hmac.new(key, b"mac", hashlib.sha256).digest()
    nonce = secrets.token_bytes(16)
    body = bytes(a ^ b for a, b in zip(plain, _stream(enc, nonce, len(plain))))
    return nonce + body + hmac.new(mac, nonce + body, hashlib.sha256).digest()


def unseal(key: bytes, blob: bytes) -> bytes:
    enc, mac = hmac.new(key, b"enc", hashlib.sha256).digest(), hmac.new(key, b"mac", hashlib.sha256).digest()
    nonce, body, tag = blob[:16], blob[16:-32], blob[-32:]
    if len(blob) < 48 or not hmac.compare_digest(tag, hmac.new(mac, nonce + body, hashlib.sha256).digest()):
        raise ValueError("the private file does not match its key")
    return bytes(a ^ b for a, b in zip(body, _stream(enc, nonce, len(body))))


def _limit(value, name: str):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= MAX:
        raise PlazaError(400, "bad_request", f"{name} is a number between 1 and {MAX}, or null to forget it")
    return int(round(value))


def limits(entry: dict, allowed: tuple) -> dict:
    """The private fields of one entry, validated. Only the names in `allowed` may appear."""
    out = {}
    for k in FIELDS:
        if k in entry:
            if k not in allowed:
                raise PlazaError(400, "bad_request", f"{k} does not apply here")
            out[k] = _limit(entry[k], k)
    return out


def split(body) -> tuple[dict, dict[str, dict]]:
    """Takes the private limits out of a sheet an agent sends: (the public sheet, ref -> limits).

    wants: "LAV-07" or {"ref", "max", "value"}; spares and for_sale: {"ref", "min", "value", ...}."""
    if not isinstance(body, dict):
        return body, {}
    out, priv = dict(body), {}
    for field, allowed in (("wants", ("max", "value")), ("spares", ("min", "value")), ("for_sale", ("min", "value"))):
        rows = body.get(field)
        if not isinstance(rows, list):
            continue
        clean = []
        for e in rows:
            if isinstance(e, dict) and isinstance(e.get("ref"), str):
                got = limits(e, allowed)
                if got:
                    priv.setdefault(e["ref"], {}).update(got)
                e = {k: v for k, v in e.items() if k not in FIELDS}
                if field != "for_sale":
                    if set(e) - {"ref"}:
                        raise PlazaError(400, "bad_request", f"{field} entries are a ref, or a ref with private limits")
                    e = e["ref"]
            clean.append(e)
        out[field] = clean
    return out, priv


class Vault:
    def __init__(self, folder: Path | str, clock=time.time):
        self.folder, self.clock = Path(folder), clock
        self.lock = threading.Lock()
        self.folder.mkdir(parents=True, exist_ok=True)
        os.chmod(self.folder, 0o700)
        self.file = self.folder / "limits.bin"
        self.key = self._key()
        self.data: dict[str, dict[str, dict]] = self._load()

    def _key(self) -> bytes:
        path = self.folder / "key"
        try:
            key = path.read_bytes()
            if len(key) == 32:
                return key
        except OSError:
            pass
        key = secrets.token_bytes(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        return key

    def _load(self) -> dict:
        for path in (self.file, self.file.with_name(self.file.name + ".bak")):     # the copy, when the file is broken
            try:
                data = json.loads(unseal(self.key, path.read_bytes()).decode("utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                return data
        return {}

    def _save(self) -> None:
        write_atomic(self.file, seal(self.key, json.dumps(self.data).encode("utf-8")), 0o600)

    # ---- the cards a team holds: as private as its limits, so they live here and not under data/live
    def have(self, team: str) -> list[str] | None:
        """Only ever returned to that team. None: the team never said what it holds."""
        with self.lock:
            rows = (self.data.get(HAVE) or {}).get(team)
            return list(rows) if isinstance(rows, list) else None

    def set_have(self, team: str, refs: list[str] | None) -> None:
        with self.lock:
            book = self.data.setdefault(HAVE, {})
            if refs is None:
                book.pop(team, None)
            else:
                book[team] = list(refs)
            self._save()

    def have_overrides(self, team: str) -> dict[str, str]:
        """ref -> "add" or "remove": what the human corrected by hand."""
        with self.lock:
            return dict((self.data.get(HAVE_BY_HAND) or {}).get(team) or {})

    def override_have(self, team: str, ref: str, op: str | None) -> None:
        """`op` None releases the card back to the agent."""
        with self.lock:
            mine = self.data.setdefault(HAVE_BY_HAND, {}).setdefault(team, {})
            if op is None:
                mine.pop(ref, None)
            else:
                mine[ref] = op
            self._save()

    # ---- the team itself
    def get(self, team: str) -> dict[str, dict]:
        """Only ever returned to that team."""
        with self.lock:
            return {ref: dict(v) for ref, v in (self.data.get(team) or {}).items()}

    def cooling(self, team: str, ref: str, fields: dict, tick: int | None) -> bool:
        """Would this change a `min` or a `max` that was already changed less than COOL_TICKS ago?

        Setting a limit for the first time is free and so is sending the same number again. Moving it is not:
        a team that moves its limit every tick and watches which matches appear reads the other side's."""
        with self.lock:
            cur = (self.data.get(team) or {}).get(ref) or {}
            moved = any(k in fields and k in cur and fields[k] != cur[k] for k in ("min", "max"))
            last = ((self.data.get(CHANGED) or {}).get(team) or {}).get(ref)
        if not moved or not last:
            return False
        if isinstance(tick, int) and isinstance(last.get("tick"), int):
            return 0 <= tick - last["tick"] < COOL_TICKS
        return 0 <= self.clock() - last.get("ts", 0) < COOL_S

    def put(self, team: str, ref: str, fields: dict, tick: int | None = None) -> None:
        """Sets the fields given; a field sent as None is forgotten. A limit moved again too soon is a 429."""
        if self.cooling(team, ref, fields, tick):
            raise PlazaError(429, "slow_down", f"a card's limit changes once every {COOL_TICKS} ticks")
        with self.lock:
            cur = dict((self.data.get(team) or {}).get(ref) or {})
            if any(k in fields and k in cur and fields[k] != cur[k] for k in ("min", "max")):
                self.data.setdefault(CHANGED, {}).setdefault(team, {})[ref] = {
                    "ts": self.clock(), **({"tick": tick} if isinstance(tick, int) and not isinstance(tick, bool) else {})}
            for k in FIELDS:
                if k in fields:
                    if fields[k] is None:
                        cur.pop(k, None)
                    else:
                        cur[k] = int(fields[k])
            cards = self.data.setdefault(team, {})
            if cur:
                cards[ref] = cur
            else:
                cards.pop(ref, None)
            self._save()

    def drop(self, team: str, ref: str, fields: tuple = FIELDS) -> None:
        self.put(team, ref, {k: None for k in fields})

    # ---- everybody else: yes or no, never a number
    def flags(self, team: str) -> dict[str, bool]:
        with self.lock:
            return {ref: True for ref, v in (self.data.get(team) or {}).items() if v}

    def gate(self, seller: str, buyer: str, ref: str, price: int, floor: int = 1) -> tuple[int | None, bool | None]:
        """The blind question. (price to propose or None, overlap yes / no / no limits set).

        Both limits set: propose only when they overlap, at the middle of the overlap. One limit set: the public
        suggestion passes or does not, unchanged, so the limit itself never shows."""
        with self.lock:
            lo = ((self.data.get(seller) or {}).get(ref) or {}).get("min")
            hi = ((self.data.get(buyer) or {}).get(ref) or {}).get("max")
        if lo is None and hi is None:
            return price, None
        if lo is not None and hi is not None:
            if hi < lo or hi < floor:
                return None, False
            return max(floor, int(round((lo + hi) / 2))), True
        if lo is not None:
            return (price, True) if price >= lo else (None, False)
        return (price, True) if price <= hi else (None, False)

    def within(self, team: str, ref: str, role: str, price: int) -> bool:
        """For the team's own agent queue: is this price inside its own limit?"""
        with self.lock:
            v = (self.data.get(team) or {}).get(ref) or {}
        if role == "seller":
            return v.get("min") is None or price >= v["min"]
        return v.get("max") is None or price <= v["max"]
