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
from pathlib import Path

from .store import PlazaError

FIELDS = ("min", "max", "value")
MAX = 2000


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
    def __init__(self, folder: Path | str):
        self.folder = Path(folder)
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
        try:
            data = json.loads(unseal(self.key, self.file.read_bytes()).decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        tmp = self.folder / "limits.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(seal(self.key, json.dumps(self.data).encode("utf-8")))
        os.replace(tmp, self.file)

    # ---- the team itself
    def get(self, team: str) -> dict[str, dict]:
        """Only ever returned to that team."""
        with self.lock:
            return {ref: dict(v) for ref, v in (self.data.get(team) or {}).items()}

    def put(self, team: str, ref: str, fields: dict) -> None:
        """Sets the fields given; a field sent as None is forgotten."""
        with self.lock:
            cur = dict((self.data.get(team) or {}).get(ref) or {})
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
