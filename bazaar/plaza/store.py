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
PIN_RX = re.compile(r"^[A-Za-z0-9]{8,32}$")       # long enough that guessing it is not a plan
MAX_REFS = 60                      # per list: an album has 60-odd cards
MAX_HAVE = 200                     # every card a team holds
MAX_PRICE = 2000
LISTS = ("wants", "spares", "for_sale")
LANGS = ("en", "es")
PIN_TRIES = 5                      # wrong PINs from one client for one team before that client waits LOCK_S:
LOCK_S = 60.0                      # the guesser waits, never the team (its own client is counted apart)
MAX_FAILS = 5000
CLAIM_TTL_S = 30 * 60.0            # a PIN claim nobody proved in the game stops being looked for
HOST = "t10"


class PlazaError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def write_atomic(path: Path, data: bytes, mode: int | None = None) -> None:
    """Writes a temporary file and renames it over `path`; the copy it replaces stays as `<name>.bak`.

    A process that dies half way leaves the old file whole, and a file that no longer parses is read from the
    copy (`read_json`)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode if mode is not None else 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    try:
        old = path.read_bytes()
    except OSError:
        old = None
    if old:
        bak = path.with_name(path.name + ".bak")
        tmp2 = path.with_name(path.name + ".bak.tmp")
        fd = os.open(tmp2, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode if mode is not None else 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(old)
        os.replace(tmp2, bak)
    os.replace(tmp, path)


def read_json(path: Path, kind: type = dict):
    """The file, else its `.bak` when the file is missing or does not parse, else an empty `kind`."""
    path = Path(path)
    for p in (path, path.with_name(path.name + ".bak")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, kind):
            return data
    return kind()


def whole(value, name: str, top: int = MAX_PRICE) -> int:
    """A whole number from 1 to `top`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (
            float("inf"), float("-inf")) or int(value) != value or not 1 <= value <= top:
        raise PlazaError(400, "bad_request", f"{name} is a whole number from 1 to {top}")
    return int(value)


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 50_000).hex()


def clean_refs(value, field: str, top: int = MAX_REFS) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > top:
        raise PlazaError(400, "bad_request", f"{field} must be a list of at most {top} card refs")
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
        return read_json(self.path)

    def _save(self, data: dict) -> None:
        write_atomic(self.path, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    # ---- identity
    def _team(self, team: str) -> str:
        if not isinstance(team, str) or not TEAM_RX.fullmatch(team):
            raise PlazaError(400, "bad_request", "team ids look like t04")
        if team == self.host:
            raise PlazaError(403, "host", "the host team runs this market and has no trading sheet")
        return team

    def _locked(self, team: str, client: str = "") -> bool:
        now = self.clock()
        if len(self.fails) > MAX_FAILS:
            self.fails = {k: v for k, v in self.fails.items() if v and now - v[-1] < LOCK_S}
        recent = [t for t in self.fails.get((client, team), []) if now - t < LOCK_S]
        if recent:
            self.fails[(client, team)] = recent
        else:
            self.fails.pop((client, team), None)
        return len(recent) >= PIN_TRIES

    def _pin_ok(self, rec: dict, pin: str) -> bool:
        return bool(rec.get("pin")) and isinstance(pin, str) and hmac.compare_digest(
            _hash(pin, rec["salt"]), rec["pin"])

    def claim(self, team: str, pin: str, client: str = "") -> dict:
        """Sets the team's PIN. Returns the code to prove in the game. A verified team's PIN is only the one it
        proved: nobody sets a new one over it here."""
        team = self._team(team)
        if not isinstance(pin, str) or not PIN_RX.fullmatch(pin):
            raise PlazaError(400, "bad_request", "pin: 8 to 32 letters or digits")
        with self.lock:
            if self._locked(team, client):
                raise PlazaError(429, "locked", "too many wrong PINs; wait a minute")
            data = self._load()
            rec = (data.get("teams") or {}).get(team) or {}
            if rec.get("verified") and not self._pin_ok(rec, pin):
                self.fails.setdefault((client, team), []).append(self.clock())
                raise PlazaError(403, "claimed", "this team is verified; use its PIN, or connect its agent")
            if not self._pin_ok(rec, pin):                     # a new or replaced (unverified) claim: only the PIN
                salt = secrets.token_hex(8)                    # and its code change; nothing is published before proof
                rec = {**{k: v for k, v in rec.items() if k in ("settings", "seen")},
                       "salt": salt, "pin": _hash(pin, salt), "verified": False, "pin_proved": False,
                       "code": "PLAZA-" + secrets.token_hex(4).upper(), "claimed": self.clock()}
            data.setdefault("teams", {})[team] = rec
            self._save(data)
            return {"team": team, "verified": bool(rec.get("verified")), "code": rec.get("code")}

    def check(self, team: str, pin: str, client: str = "") -> dict:
        team = self._team(team)
        with self.lock:
            if self._locked(team, client):
                raise PlazaError(429, "locked", "too many wrong PINs; wait a minute")
            rec = (self._load().get("teams") or {}).get(team) or {}
            if not rec.get("pin"):
                raise PlazaError(403, "unclaimed", "claim this team first: POST /plaza/api/claim")
            if not self._pin_ok(rec, pin or ""):
                self.fails.setdefault((client, team), []).append(self.clock())
                raise PlazaError(403, "bad_pin", "wrong PIN")
            return rec

    def declare(self, team: str, pin: str | None, body: dict) -> dict:
        """Replaces the fields the agent sends (wants, spares, for_sale); fields left out stay as they were."""
        if not isinstance(body, dict):
            raise PlazaError(400, "bad_request", "send a JSON object")
        unknown = set(body) - set(LISTS)
        if unknown:
            raise PlazaError(400, "bad_request", f"unknown key {', '.join(sorted(map(str, unknown)))[:60]}; "
                             f"allowed: {', '.join(LISTS)}, have")
        new = {}
        if "wants" in body:
            new["wants"] = clean_refs(body["wants"], "wants")
        if "spares" in body:
            new["spares"] = clean_refs(body["spares"], "spares")
        if "for_sale" in body:
            new["for_sale"] = clean_sale(body["for_sale"])
        if pin is not None:                                    # None: the caller already checked the credential
            self.check(team, pin)
        else:
            self._team(team)
        with self.lock:
            data = self._load()
            rec = data.setdefault("teams", {}).setdefault(team, {})
            dec = {**(rec.get("declared") or {}), **new, "updated": self.clock()}
            if dec.get("bids"):                                # a bid goes with its want
                dec["bids"] = {r: b for r, b in dec["bids"].items() if r in (dec.get("wants") or [])}
            rec["declared"] = dec
            rec["seen"] = self.clock()
            self._save(data)
            return {k: v for k, v in dec.items() if k != "bids"}

    def verify(self, team: str, text: str) -> bool:
        """Marks the team verified when `text` (a message the team sent us in the game) carries its code."""
        if not isinstance(team, str) or not TEAM_RX.fullmatch(team) or not isinstance(text, str):
            return False
        with self.lock:
            data = self._load()
            rec = (data.get("teams") or {}).get(team)
            if not rec or rec.get("pin_proved") or not rec.get("code") or rec["code"] not in text.upper():
                return False
            if not rec.get("verified"):                        # whatever was there before the proof is nobody's
                for key in ("declared", "overrides"):
                    rec.pop(key, None)
            rec["verified"] = rec["pin_proved"] = True
            self._save(data)
            return True

    def mark_verified(self, team: str) -> None:
        """The team proved a connection code in the game."""
        with self.lock:
            data = self._load()
            rec = data.setdefault("teams", {}).setdefault(self._team(team), {})
            if not rec.get("verified"):
                # Anyone could set a PIN or leave a sheet in this team's name before it proved itself: the PIN that
                # was never proved in the game stops working and nothing left behind goes live.
                for key in ("pin", "salt", "code", "claimed", "declared", "overrides"):
                    rec.pop(key, None)
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
                raise PlazaError(400, "bad_request", "action: hide, unhide, block, unblock, on, off, refresh, pause, resume, exclude, include, reset_team, "
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
        """What every team shows: its agent's lists with its human's overrides on top.

        Only for a team that proved itself in the game. Anyone can start a connection in another team's name, so
        a sheet published before the proof is kept (`unproved`) and shown to nobody until the code is seen."""
        out = {}
        for team, rec in (self._load().get("teams") or {}).items():
            eff, ok = effective(rec), bool(rec.get("verified"))
            out[team] = {"declared": eff if ok else None, "unproved": bool(eff) and not ok,
                         "claimed": bool(rec.get("pin")), "verified": ok, "seen": rec.get("seen")}
        return out

    def sheet(self, team: str) -> dict:
        """One team's lists for its own page: the agent's, the overrides and the result."""
        rec = (self._load().get("teams") or {}).get(team) or {}
        return {"declared": dict(rec.get("declared") or {}), "overrides": _overrides(rec),
                "effective": effective(rec) or {}, "bids": dict((rec.get("declared") or {}).get("bids") or {})}

    # ---- one card at a time (POST /api/me/cards)
    def edit(self, team: str, op: str, lst: str, ref: str, human: bool, price: int | None = None,
             bid: int | None = None) -> None:
        """Adds or removes one card of a list, or releases a human override.

        A human's change is an override: it is kept apart, wins over the agent's list and survives the agent's
        next full sheet until it is released. An agent's change edits its own list."""
        team = self._team(team)
        if lst not in LISTS or op not in ("add", "remove", "release") or not REF_RX.fullmatch(ref or ""):
            raise PlazaError(400, "bad_request", "op is add, remove or release; list is wants, spares or for_sale")
        with self.lock:
            data = self._load()
            rec = data.setdefault("teams", {}).setdefault(team, {})
            over = rec.setdefault("overrides", {}).setdefault(lst, {})
            if op == "release":
                over.pop(ref, None)
            elif human:
                if op == "add" and ref not in over and len([1 for o in over.values() if o.get("op") == "add"]) >= MAX_REFS:
                    raise PlazaError(400, "bad_request", f"{lst} holds at most {MAX_REFS} cards")
                over[ref] = {"op": op, "ts": self.clock(), **({"price": price} if price is not None else {}),
                             **({"bid": bid} if bid is not None else {})}
            else:
                dec = rec.setdefault("declared", {})
                rows = list(dec.get(lst) or [])
                key = (lambda e: e["ref"]) if lst == "for_sale" else (lambda e: e)
                rows = [e for e in rows if key(e) != ref]
                if op == "add":
                    if len(rows) >= MAX_REFS:
                        raise PlazaError(400, "bad_request", f"{lst} holds at most {MAX_REFS} cards")
                    rows.append({"ref": ref, **({"price": price} if price is not None else {})}
                                if lst == "for_sale" else ref)
                dec[lst] = rows
                if lst == "wants":
                    bids = dict(dec.get("bids") or {})
                    bids.pop(ref, None)
                    if op == "add" and bid is not None:
                        bids[ref] = bid
                    dec["bids"] = bids
                dec["updated"] = self.clock()
            rec["seen"] = self.clock()
            self._save(data)

    def lock_limits(self, team: str, ref: str, fields) -> None:
        """Remembers which private fields of a card the human set (their names, never their numbers), so the
        agent's next sheet does not write over them. `fields` None releases the card."""
        with self.lock:
            data = self._load()
            rec = data.setdefault("teams", {}).setdefault(self._team(team), {})
            locks = rec.setdefault("overrides", {}).setdefault("limits", {})
            if fields is None:
                locks.pop(ref, None)
            else:
                locks[ref] = sorted(set(locks.get(ref) or []) | {f for f in fields if f in ("min", "max", "value")})
            self._save(data)

    # ---- settings of the team (the language of its page, its pause)
    def settings(self, team: str) -> dict:
        s = ((self._load().get("teams") or {}).get(team) or {}).get("settings") or {}
        return {"lang": s.get("lang") if s.get("lang") in LANGS else "en", "paused": bool(s.get("paused"))}

    def set_settings(self, team: str, lang=None, paused=None) -> dict:
        if lang is not None and lang not in LANGS:
            raise PlazaError(400, "bad_request", "lang is en or es")
        if paused is not None and not isinstance(paused, bool):
            raise PlazaError(400, "bad_request", "paused is true or false")
        with self.lock:
            data = self._load()
            rec = data.setdefault("teams", {}).setdefault(self._team(team), {})
            s = rec.setdefault("settings", {})
            if lang is not None:
                s["lang"] = lang
            if paused is not None:
                s["paused"] = paused
            self._save(data)
        return self.settings(team)

    def paused_teams(self) -> set[str]:
        """Teams that asked for no new matches (their live ones go on). The matcher reads this."""
        return {t for t, r in (self._load().get("teams") or {}).items() if (r.get("settings") or {}).get("paused")}

    def pending_codes(self) -> dict[str, str]:
        now = self.clock()
        return {t: r["code"] for t, r in (self._load().get("teams") or {}).items()
                if r.get("code") and r.get("pin") and not r.get("pin_proved")
                and now - (r.get("claimed") or 0) < CLAIM_TTL_S}

    def wipe(self, team: str) -> None:
        """The team changed hands (another agent proved a new code): its sheet, overrides and PIN go; it stays
        proved. The agent that came in publishes again."""
        with self.lock:
            data = self._load()
            rec = (data.get("teams") or {}).get(self._team(team))
            if rec:
                for key in ("pin", "salt", "code", "claimed", "pin_proved", "declared", "overrides"):
                    rec.pop(key, None)
                self._save(data)

    def reset(self, team: str) -> None:
        """Ours: the team is unproved again, with no PIN, sheet or overrides; its settings stay."""
        with self.lock:
            data = self._load()
            rec = (data.get("teams") or {}).get(self._team(team))
            if rec:
                for key in ("pin", "salt", "code", "claimed", "pin_proved", "verified", "declared", "overrides"):
                    rec.pop(key, None)
                self._save(data)


def _overrides(rec: dict) -> dict:
    o = rec.get("overrides") or {}
    return {**{lst: {r: dict(v) for r, v in (o.get(lst) or {}).items() if isinstance(v, dict)} for lst in LISTS},
            "limits": {r: list(v) for r, v in (o.get("limits") or {}).items() if isinstance(v, list)}}


def effective(rec: dict) -> dict | None:
    """The lists a team shows: its agent's, then every human override (add puts the card in, remove takes it out).
    None when neither the agent nor the human declared anything."""
    dec, over = rec.get("declared"), _overrides(rec)
    if not dec and not any(over[lst] for lst in LISTS):
        return dec
    out = dict(dec or {})
    for lst in LISTS:
        if lst not in out and not over[lst]:
            continue
        rows = list(out.get(lst) or [])
        key = (lambda e: e["ref"]) if lst == "for_sale" else (lambda e: e)
        for ref, o in over[lst].items():
            rows = [e for e in rows if key(e) != ref]
            if o.get("op") == "add":
                rows.append({"ref": ref, **({"price": o["price"]} if o.get("price") else {})}
                            if lst == "for_sale" else ref)
        out[lst] = rows
    out.setdefault("updated", max([o.get("ts") or 0 for lst in LISTS for o in over[lst].values()] or [0]) or None)
    return out
