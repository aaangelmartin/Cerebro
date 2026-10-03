"""What each team's agent declares on the plaza: wants, spares and cards for sale, behind a team PIN.

One JSON file under the live dir. A team is claimed with a PIN (stored salted and hashed, never in the clear); the
claim returns a short code the team proves in the game (a thread with us whose text carries the code), which marks
the sheet verified. An unverified claim can be replaced by a new claim; a verified one only by its own PIN. The game
key of a team is never asked for and never accepted here."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

REF_RX = re.compile(r"^[A-Z]{3}-\d{2}$")
TEAM_RX = re.compile(r"^t\d{2}$")
PIN_RX = re.compile(r"^[A-Za-z0-9]{4,16}$")
MAX_REFS = 60                      # per list: an album has 60-odd cards
MAX_PRICE = 2000
PIN_TRIES = 5                      # wrong PINs before a team's sheet locks for LOCK_S
LOCK_S = 60.0
HOST = "t10"


class PlazaError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 50_000).hex()


def clean_refs(value, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_REFS:
        raise PlazaError(400, "bad_request", f"{field} must be a list of at most {MAX_REFS} card refs")
    out: list[str] = []
    for r in value:
        if not isinstance(r, str) or not REF_RX.fullmatch(r):
            raise PlazaError(400, "bad_request", f"{field}: card refs look like LAV-03")
        if r not in out:
            out.append(r)
    return out


def clean_sale(value) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_REFS:
        raise PlazaError(400, "bad_request", f"for_sale must be a list of at most {MAX_REFS} entries")
    out, seen = [], set()
    for e in value:
        if isinstance(e, str):
            e = {"ref": e}
        if not isinstance(e, dict) or not isinstance(e.get("ref"), str) or not REF_RX.fullmatch(e["ref"]):
            raise PlazaError(400, "bad_request", 'for_sale entries look like {"ref": "LAV-03", "price": 12}')
        price = e.get("price")
        if price is not None and (isinstance(price, bool) or not isinstance(price, (int, float))
                                  or not 0 < price <= MAX_PRICE):
            raise PlazaError(400, "bad_request", f"price must be a number between 1 and {MAX_PRICE}")
        if e["ref"] in seen:
            continue
        seen.add(e["ref"])
        out.append({"ref": e["ref"], **({"price": int(round(price))} if price is not None else {})})
    return out


class Store:
    def __init__(self, path: Path | str, host: str = HOST, clock=time.time):
        self.path, self.host, self.clock = Path(path), host, clock
        self.lock = threading.Lock()
        self.fails: dict[str, list[float]] = {}

    # ---- file
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    # ---- identity
    def _team(self, team: str) -> str:
        if not isinstance(team, str) or not TEAM_RX.fullmatch(team):
            raise PlazaError(400, "bad_request", "team ids look like t04")
        if team == self.host:
            raise PlazaError(403, "host", "the host team runs this market and has no trading sheet")
        return team

    def _locked(self, team: str) -> bool:
        now = self.clock()
        recent = [t for t in self.fails.get(team, []) if now - t < LOCK_S]
        self.fails[team] = recent
        return len(recent) >= PIN_TRIES

    def _pin_ok(self, rec: dict, pin: str) -> bool:
        return bool(rec.get("pin")) and isinstance(pin, str) and hmac.compare_digest(
            _hash(pin, rec["salt"]), rec["pin"])

    def claim(self, team: str, pin: str) -> dict:
        """Sets the team's PIN. Returns the code to prove in the game. A verified sheet needs its own PIN."""
        team = self._team(team)
        if not isinstance(pin, str) or not PIN_RX.fullmatch(pin):
            raise PlazaError(400, "bad_request", "pin: 4 to 16 letters or digits")
        with self.lock:
            if self._locked(team):
                raise PlazaError(429, "locked", "too many wrong PINs for this team; wait a minute")
            data = self._load()
            rec = (data.get("teams") or {}).get(team) or {}
            if rec.get("verified") and not self._pin_ok(rec, pin):
                self.fails.setdefault(team, []).append(self.clock())
                raise PlazaError(403, "claimed", "this team is verified; use its PIN")
            if not self._pin_ok(rec, pin):                     # a new or replaced (unverified) claim
                salt = secrets.token_hex(8)
                rec = {"salt": salt, "pin": _hash(pin, salt), "verified": False,
                       "code": "PLAZA-" + secrets.token_hex(3).upper(), "claimed": self.clock()}
            data.setdefault("teams", {})[team] = rec
            self._save(data)
            return {"team": team, "verified": bool(rec.get("verified")), "code": rec.get("code")}

    def check(self, team: str, pin: str) -> dict:
        team = self._team(team)
        with self.lock:
            if self._locked(team):
                raise PlazaError(429, "locked", "too many wrong PINs for this team; wait a minute")
            rec = (self._load().get("teams") or {}).get(team) or {}
            if not rec.get("pin"):
                raise PlazaError(403, "unclaimed", "claim this team first: POST /plaza/api/claim")
            if not self._pin_ok(rec, pin or ""):
                self.fails.setdefault(team, []).append(self.clock())
                raise PlazaError(403, "bad_pin", "wrong PIN")
            return rec

    def declare(self, team: str, pin: str | None, body: dict) -> dict:
        """Replaces the fields the agent sends (wants, spares, for_sale); fields left out stay as they were."""
        if not isinstance(body, dict):
            raise PlazaError(400, "bad_request", "send a JSON object")
        unknown = set(body) - {"wants", "spares", "for_sale"}
        if unknown:
            raise PlazaError(400, "bad_request", f"unknown fields: {', '.join(sorted(unknown))[:80]}")
        new = {}
        if "wants" in body:
            new["wants"] = clean_refs(body["wants"], "wants")
        if "spares" in body:
            new["spares"] = clean_refs(body["spares"], "spares")
        if "for_sale" in body:
            new["for_sale"] = clean_sale(body["for_sale"])
        if pin is not None:                                    # None: the caller already checked an agent token
            self.check(team, pin)
        else:
            self._team(team)
        with self.lock:
            data = self._load()
            rec = data.setdefault("teams", {}).setdefault(team, {})
            rec["declared"] = {**(rec.get("declared") or {}), **new, "updated": self.clock()}
            rec["seen"] = self.clock()
            self._save(data)
            return dict(rec["declared"])

    def verify(self, team: str, text: str) -> bool:
        """Marks the team verified when `text` (a message the team sent us in the game) carries its code."""
        if not isinstance(team, str) or not TEAM_RX.fullmatch(team) or not isinstance(text, str):
            return False
        with self.lock:
            data = self._load()
            rec = (data.get("teams") or {}).get(team)
            if not rec or rec.get("verified") or not rec.get("code") or rec["code"] not in text.upper():
                return False
            rec["verified"] = True
            self._save(data)
            return True

    def mark_verified(self, team: str) -> None:
        """The team proved a connection code in the game."""
        with self.lock:
            data = self._load()
            rec = data.setdefault("teams", {}).setdefault(self._team(team), {})
            if not rec.get("verified"):
                rec["verified"] = True
                self._save(data)

    def touch(self, team: str) -> None:
        """The team's agent did something with its PIN: remember when."""
        with self.lock:
            data = self._load()
            rec = (data.get("teams") or {}).get(team)
            if rec:
                rec["seen"] = self.clock()
                self._save(data)

    # ---- moderation (ours, behind the dashboard login)
    def admin(self) -> dict:
        a = self._load().get("admin") or {}
        return {"hidden": [i for i in a.get("hidden") or [] if isinstance(i, int)],
                "blocked": [t for t in a.get("blocked") or [] if isinstance(t, str)],
                "hidden_msgs": [m for m in a.get("hidden_msgs") or [] if isinstance(m, str)],
                "enabled": a.get("enabled", True) is not False,
                "mm_paused": bool(a.get("mm_paused")),
                "excluded_matches": [m for m in a.get("excluded_matches") or [] if isinstance(m, str)]}

    def admin_do(self, action: str, team: str | None = None, message: int | None = None,
                 match: str | None = None) -> dict:
        if action in ("exclude", "include"):
            return self._exclude(action, team, match)
        if action in ("hide", "unhide") and match is not None:      # one line of a match thread
            if not (isinstance(match, str) and re.fullmatch(r"m-[0-9a-f]{10}", match)) \
                    or isinstance(message, bool) or not isinstance(message, int):
                raise PlazaError(400, "bad_request", "name the match and the number of its message")
            with self.lock:
                data = self._load()
                a = data.setdefault("admin", {})
                rows = [x for x in a.get("hidden_msgs") or [] if x != f"{match}:{message}"]
                a["hidden_msgs"] = (rows + [f"{match}:{message}"] if action == "hide" else rows)[-2000:]
                self._save(data)
            return self.admin()
        if action in ("pause", "resume"):
            with self.lock:
                data = self._load()
                data.setdefault("admin", {})["mm_paused"] = action == "pause"
                self._save(data)
            return self.admin()
        if action in ("block", "unblock") and not (isinstance(team, str) and TEAM_RX.fullmatch(team)):
            raise PlazaError(400, "bad_request", "team ids look like t04")
        if action in ("hide", "unhide") and (isinstance(message, bool) or not isinstance(message, int)):
            raise PlazaError(400, "bad_request", "message is the id of an agent message")
        with self.lock:
            data = self._load()
            a = data.setdefault("admin", {})
            hidden, blocked = list(a.get("hidden") or []), list(a.get("blocked") or [])
            if action == "hide" and message not in hidden:
                hidden.append(message)
            elif action == "unhide":
                hidden = [i for i in hidden if i != message]
            elif action == "block" and team not in blocked:
                blocked.append(team)
            elif action == "unblock":
                blocked = [t for t in blocked if t != team]
            elif action in ("on", "off"):
                a["enabled"] = action == "on"
            elif action not in ("hide", "block"):
                raise PlazaError(400, "bad_request", "action: hide, unhide, block, unblock, on, off, refresh, pause, resume, exclude, include, "
                                                    "force, expire")
            a["hidden"], a["blocked"] = hidden[-2000:], blocked
            self._save(data)
        return self.admin()

    def _exclude(self, action: str, team, match) -> dict:
        """Keeps one match out of the matchmaker. Never a team: nobody is left out of the matching."""
        if team is not None:
            raise PlazaError(400, "bad_request", "no team is excluded from the matching; name a match")
        if not (isinstance(match, str) and re.fullmatch(r"m-[0-9a-f]{10}", match)):
            raise PlazaError(400, "bad_request", "match ids look like m-0123456789")
        key, value = "excluded_matches", match
        with self.lock:
            data = self._load()
            a = data.setdefault("admin", {})
            rows = [x for x in a.get(key) or [] if x != value]
            a[key] = (rows + [value] if action == "exclude" else rows)[-200:]
            self._save(data)
        return self.admin()

    def raw(self, team: str) -> dict:
        """A team's record for our own panel: everything but the PIN hash and its salt."""
        rec = (self._load().get("teams") or {}).get(team) or {}
        return {k: v for k, v in rec.items() if k not in ("pin", "salt")}

    # ---- reads (never the PIN, the salt or the code)
    def declared(self) -> dict[str, dict]:
        out = {}
        for team, rec in (self._load().get("teams") or {}).items():
            out[team] = {"declared": rec.get("declared"), "claimed": bool(rec.get("pin")),
                         "verified": bool(rec.get("verified")), "seen": rec.get("seen")}
        return out

    def pending_codes(self) -> dict[str, str]:
        return {t: r["code"] for t, r in (self._load().get("teams") or {}).items()
                if r.get("code") and not r.get("verified")}
