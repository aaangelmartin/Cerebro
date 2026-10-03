"""Our own `board` venue: open it once (idempotent), keep the broker key safe, announce.

Decision (CONTRACTS.md): open at 09:03 Saturday (game hour 4.05, right after the +150 P grant), fee 0, mechanism
`board` so our broker (bazaar.broker.run) matches the Market Test bench itself. Cost: bond 250 (refundable) + 20 P.

The broker key comes back ONCE in the opening response. It is written to data/live/broker.json (chmod 600) and is
never logged or printed. Whoever executes a `venue_open` Action must call `save_from_response(resp)` on the
response and must not write the raw response anywhere else; `open_venue(gw)` does all of that in one call.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from .. import config
from ..core.types import Action

BROKER_FILE = config.LIVE / "broker.json"
OPEN_AT_HOURS = 4.05
BOND, OPENING_FEE = 250, 20
VENUE_NAME = "Team 10 · fair broker, 0 fee"
VENUE_DESCRIPTION = ("Zero fees. A broker matches every crossing pair card by card at the midpoint, "
                     "any copy included. Built by Team 10 for everyone.")
KEY_FIELDS = ("broker_key", "key", "X-Broker-Key")


# --------------------------------------------------------------------------- key storage

def load() -> dict:
    try:
        d = json.loads(BROKER_FILE.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def load_key() -> str | None:
    """Our venue's broker key: env BAZAAR_BROKER_KEY overrides data/live/broker.json."""
    env = config.ENV.get("BAZAAR_BROKER_KEY")
    if env:
        return env
    d = load()
    for k in KEY_FIELDS:
        if d.get(k):
            return str(d[k])
    return None


def _find_key(resp: Any) -> str | None:
    if isinstance(resp, dict):
        for k in KEY_FIELDS:
            if isinstance(resp.get(k), str) and resp[k]:
                return resp[k]
        for v in resp.values():
            if isinstance(v, dict):
                k = _find_key(v)
                if k:
                    return k
    return None


def _find_venue_id(resp: Any) -> str | None:
    if isinstance(resp, dict):
        v = resp.get("venue")
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            return _find_venue_id(v) or v.get("id")
        if isinstance(resp.get("id"), str) and str(resp["id"]).startswith("v"):
            return resp["id"]
    return None


def redact(resp: Any) -> Any:
    """A copy of a response with every broker key replaced (safe to log)."""
    if isinstance(resp, dict):
        return {k: ("<redacted>" if k in KEY_FIELDS else redact(v)) for k, v in resp.items()}
    if isinstance(resp, list):
        return [redact(v) for v in resp]
    return resp


def save_from_response(resp: dict) -> dict:
    """Store the broker key of a venue-opening response in broker.json (0600). Returns the redacted record."""
    key = _find_key(resp)
    rec = {"venue": _find_venue_id(resp), "opened_at": time.time(), "mechanism": "board"}
    if key:
        rec["broker_key"] = key
    BROKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BROKER_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(rec, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, BROKER_FILE)
    return redact(rec)


# --------------------------------------------------------------------------- opening

def our_venue(me: dict) -> str | None:
    """Our venue id from /api/me (`venue` may be an id, a dict, or under score.venue)."""
    for v in (me.get("venue"), (me.get("score") or {}).get("venue")):
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            vid = v.get("venue") or v.get("id")
            if vid:
                return str(vid)
    return None


def should_open(sit: Any, reserve: int | None = None) -> bool:
    """True when it is time to open: hour >= 4.05, doors open, level >= 2, no venue yet, and cash for bond + fee +
    reserve. `sit` is a core.state.Situation (or anything with t_hours, doors, paused, me)."""
    reserve = config.CASH_RESERVE if reserve is None else reserve
    me = getattr(sit, "me", None) or {}
    if our_venue(me) or (load().get("venue") and load_key()):
        return False
    if (getattr(sit, "t_hours", 0) or 0) < OPEN_AT_HOURS or getattr(sit, "paused", False):
        return False
    if getattr(sit, "doors", "open") not in ("open", None, ""):
        return False
    if (me.get("level") or 0) < 2:
        return False
    return (me.get("cash") or 0) >= BOND + OPENING_FEE + reserve


def open_action(sit: Any = None) -> Action:
    """The Action run.py sends through rails + executor. After it succeeds, call save_from_response(response)."""
    return Action(kind="venue_open", domain="broker", source="code", priority=30.0,
                  params={"name": VENUE_NAME, "fee_bps": 0, "fee_per_card": 0, "mechanism": "board",
                          "description": VENUE_DESCRIPTION},
                  reason="Open our own board venue (fee 0) so our broker plays the Market Test: 30 % of the score.",
                  expected={"cost": BOND + OPENING_FEE, "refundable": BOND})


def open_venue(gw, name: str = VENUE_NAME, description: str = VENUE_DESCRIPTION) -> dict:
    """Open our board venue unless we already have one. Idempotent. Returns a redacted summary:
    {"venue": id, "reused": bool, "has_key": bool}. Raises gateway.GameError on refusal (it costs nothing)."""
    me = gw.get("/api/me")
    vid = our_venue(me)
    if vid:
        stored = load()
        if not load_key() and me.get("broker_key"):
            save_from_response({"venue": vid, "broker_key": me["broker_key"]})
        return {"venue": vid, "reused": True, "has_key": bool(load_key()),
                "stored_venue": stored.get("venue")}
    resp = gw.post("/api/venues", {"name": name, "fee_bps": 0, "fee_per_card": 0,
                                   "rules": {"mechanism": "board"}, "description": description})
    rec = save_from_response(resp)
    if not rec.get("venue"):
        rec["venue"] = our_venue(gw.get("/api/me"))
        if rec["venue"]:
            d = load()
            d["venue"] = rec["venue"]
            save_from_response(d)
    return {"venue": rec.get("venue"), "reused": False, "has_key": bool(load_key())}


def announce(gw, text: str, key: str | None = None) -> dict:
    """Public announcement from our venue (X-Broker-Key)."""
    key = key or load_key()
    if not key:
        raise RuntimeError("no broker key stored")
    return gw.post("/api/broker/announce", {"text": str(text)[:1200]}, broker_key=key)
