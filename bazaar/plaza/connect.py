"""Connecting a team to the plaza: a browser session, a one-use code, an agent token and a proof in the game.

    start(team)            -> a session for the browser and a short code, with the prompt the human hands its agent
    agent(team, code)      -> the agent trades the code for its token (the code works once, for 15 minutes)
    prove(team, text)      -> the same code, seen as text in a game thread the team sent us, verifies the session
    auth(token)            -> the team an agent token writes for; every call is its heartbeat

Only hashes of sessions and tokens are stored. A team that is already verified keeps its current agent until a new
session proves its code in the game, so nobody can take a verified team over by asking for a code. The browser
session only reads: it never holds a game key and cannot act in the game."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from .store import TEAM_RX, PlazaError

HOST = "t10"
CODE_TTL_S = 15 * 60.0
SESSION_TTL_S = 12 * 3600.0
ONLINE_S = 90.0
WINDOW_S = 15 * 60.0
STARTS_PER_CLIENT, STARTS_PER_TEAM = 10, 8          # per WINDOW_S
TRIES_PER_CLIENT, TRIES_PER_TEAM = 10, 10           # wrong codes per WINDOW_S
MAX_SESSIONS, SESSIONS_PER_TEAM = 400, 6
SAVE_SEEN_EVERY_S = 10.0
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"       # no 0/O, 1/I
CODE_RX = re.compile(r"PLAZA-[2-9A-HJ-NP-Z]{6}")
TOKEN_RX = re.compile(r"[A-Za-z0-9_-]{20,64}")
COOKIE = "plaza_session"


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_code() -> str:
    return "PLAZA-" + "".join(secrets.choice(ALPHABET) for _ in range(6))


def prompt(team: str, code: str, base: str, venue: str = "v07") -> str:
    """What the human pastes to its agent. `base` is the public address ending in /plaza."""
    return (
        f"You are Team {int(team[1:])}'s agent in The Bazaar. Plaza is Team 10's free market on venue {venue} "
        f"(0 fee; Team 10 is never a party). Base URL: {base}\n"
        f"Read {base}/agents.md first. Connect with code {code} (valid 15 minutes, one use):\n"
        f'1. POST /api/connect/agent with JSON {{"team": "{team}", "code": "{code}"}} to get your agent token; '
        "send it as header X-Plaza-Token on every write.\n"
        f"2. Prove it is you: in the game, open a thread with t10 and send {code} as the message text, using YOUR "
        "OWN game key. Never send that key to Plaza or to anyone.\n"
        f"3. Publish what you can sell or trade and what you want: PUT /api/team/{team}.\n"
        f"4. Every few ticks GET /api/team/{team} (trades, offers for you), negotiate on /api/match/<id>/message "
        f"and close deals on venue {venue} with the recipe in agents.md."
    )


class Connect:
    def __init__(self, path: Path | str, host: str = HOST, clock=time.time):
        self.path, self.host, self.clock = Path(path), host, clock
        self.lock = threading.RLock()
        self.hits: dict[tuple, list[float]] = {}
        self.data = self._load()
        self.saved_seen = 0.0

    # ---- file
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        data.setdefault("sessions", {})
        data.setdefault("agents", {})
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f)
        os.replace(tmp, self.path)

    # ---- limits
    def _take(self, key: tuple, limit: int) -> bool:
        now = self.clock()
        if len(self.hits) > 5000:
            self.hits.clear()
        q = [t for t in self.hits.get(key, []) if now - t < WINDOW_S]
        ok = len(q) < limit
        if ok:
            q.append(now)
        self.hits[key] = q
        return ok

    def _count(self, key: tuple) -> int:
        now = self.clock()
        return len([t for t in self.hits.get(key, []) if now - t < WINDOW_S])

    def _team(self, team) -> str:
        if not isinstance(team, str) or not TEAM_RX.fullmatch(team):
            raise PlazaError(400, "bad_request", "team ids look like t04")
        if team == self.host:
            raise PlazaError(403, "host", "the host team runs this market and cannot connect to it")
        return team

    def _prune(self) -> None:
        now = self.clock()
        s = self.data["sessions"]
        for sid in [k for k, v in s.items() if v.get("expires", 0) < now]:
            s.pop(sid, None)
        if len(s) > MAX_SESSIONS:
            for sid in sorted(s, key=lambda k: s[k].get("created", 0))[:len(s) - MAX_SESSIONS]:
                if not s[sid].get("verified"):
                    s.pop(sid, None)

    # ---- the flow
    def start(self, team, client: str) -> dict:
        team = self._team(team)
        with self.lock:
            if not self._take(("start", "c", client), STARTS_PER_CLIENT) \
                    or not self._take(("start", "t", team), STARTS_PER_TEAM):
                raise PlazaError(429, "slow_down", "too many connection attempts; wait a few minutes")
            self._prune()
            now = self.clock()
            s = self.data["sessions"]
            mine = sorted((k for k, v in s.items() if v["team"] == team and not v.get("verified")),
                          key=lambda k: s[k].get("created", 0))
            for sid in mine[:max(0, len(mine) - SESSIONS_PER_TEAM + 1)]:
                s.pop(sid, None)
            session, code = secrets.token_urlsafe(24), new_code()
            s[_h(session)] = {"team": team, "code": code, "created": now, "code_expires": now + CODE_TTL_S,
                              "expires": now + SESSION_TTL_S, "agent_called": None, "token": None,
                              "verified": False, "connected": False}
            self._save()
            return {"team": team, "connect_code": code, "session": session, "code_expires_in": int(CODE_TTL_S),
                    "session_expires_in": int(SESSION_TTL_S)}

    def agent(self, team, code, client: str, team_verified: bool) -> dict:
        """The agent's half: the code for a token. `team_verified` says the team already proved itself before."""
        team = self._team(team)
        with self.lock:
            if self._count(("try", "c", client)) >= TRIES_PER_CLIENT or self._count(("try", "t", team)) >= TRIES_PER_TEAM:
                raise PlazaError(429, "locked", "too many wrong codes; wait a few minutes")
            now = self.clock()
            code = code.strip().upper() if isinstance(code, str) else ""
            rec = None
            if CODE_RX.fullmatch(code):
                for v in self.data["sessions"].values():
                    if v["team"] == team and secrets.compare_digest(v["code"], code):
                        rec = v
                        break
            if rec is None or rec.get("agent_called") or rec["code_expires"] < now or rec["expires"] < now:
                self._take(("try", "c", client), TRIES_PER_CLIENT)
                self._take(("try", "t", team), TRIES_PER_TEAM)
                why = "this code was already used" if rec and rec.get("agent_called") else \
                    "this code expired; ask for a new one" if rec else "wrong code for this team"
                raise PlazaError(403, "bad_code", why)
            token = secrets.token_urlsafe(24)
            rec["agent_called"], rec["token"] = now, _h(token)
            active = not team_verified or rec.get("verified")
            if active:                                         # an unverified team: the newest agent is the agent
                self._activate(team, rec)
            self._save()
            return {"team": team, "agent_token": token, "header": "X-Plaza-Token", "verified": bool(rec.get("verified")),
                    "active": bool(active)}

    def _activate(self, team: str, rec: dict) -> None:
        old = self.data["agents"].get(team) or {}
        self.data["agents"][team] = {"token": rec["token"], "issued": rec.get("agent_called"),
                                     "last_seen": old.get("last_seen") if old.get("token") == rec["token"] else None,
                                     "verified": bool(rec.get("verified"))}

    def pending_codes(self) -> dict[str, list[str]]:
        """team -> codes a game message can still prove."""
        now = self.clock()
        out: dict[str, list[str]] = {}
        with self.lock:
            for v in self.data["sessions"].values():
                if not v.get("verified") and v.get("expires", 0) >= now:
                    out.setdefault(v["team"], []).append(v["code"])
        return out

    def prove(self, team: str, text: str) -> bool:
        """A message this team sent us in the game carries one of its codes: that session is verified, its agent
        becomes the team's agent and the team's other unproven sessions are dropped."""
        if not isinstance(text, str) or not isinstance(team, str):
            return False
        upper = text.upper()
        with self.lock:
            now = self.clock()
            s = self.data["sessions"]
            hit = next((k for k, v in s.items() if v["team"] == team and not v.get("verified")
                        and v.get("expires", 0) >= now and v["code"] in upper), None)
            if hit is None:
                return False
            s[hit]["verified"], s[hit]["verified_at"] = True, now
            if s[hit].get("token"):
                self._activate(team, s[hit])
            for k in [k for k, v in s.items() if v["team"] == team and k != hit and not v.get("verified")]:
                s.pop(k, None)
            self._save()
            return True

    def auth(self, token) -> tuple[str, bool]:
        """(team, verified) for an agent token; raises 403 otherwise. Counts as the agent's heartbeat."""
        if not isinstance(token, str) or not TOKEN_RX.fullmatch(token):
            raise PlazaError(403, "bad_token", "send your agent token in X-Plaza-Token")
        h = _h(token)
        with self.lock:
            now = self.clock()
            for team, a in self.data["agents"].items():
                if secrets.compare_digest(a.get("token") or "", h):
                    a["last_seen"] = now
                    if now - self.saved_seen > SAVE_SEEN_EVERY_S:
                        self.saved_seen = now
                        self._save()
                    return team, bool(a.get("verified"))
            for v in self.data["sessions"].values():
                if v.get("token") and secrets.compare_digest(v["token"], h):
                    if v.get("verified"):
                        break                                  # replaced by a newer agent of the same team
                    raise PlazaError(403, "prove_first", "this team is verified: send the new code as text in a "
                                                         "game thread with t10 before this token can write")
        raise PlazaError(403, "bad_token", "unknown agent token; connect again")

    def session(self, token) -> dict | None:
        if not isinstance(token, str) or not TOKEN_RX.fullmatch(token):
            return None
        with self.lock:
            rec = self.data["sessions"].get(_h(token))
            if not rec or rec.get("expires", 0) < self.clock():
                return None
            return rec

    def status(self, token, cards_listed_fn) -> dict:
        """What the Ready button asks. `cards_listed_fn(team)` says whether the agent published its sheet."""
        with self.lock:
            rec = self.session(token)
            if rec is None:
                raise PlazaError(401, "no_session", "no such connection session; start again")
            now = self.clock()
            team = rec["team"]
            a = self.data["agents"].get(team) or {}
            mine = bool(rec.get("token")) and a.get("token") == rec["token"]
            online = bool(mine and a.get("last_seen") and now - a["last_seen"] < ONLINE_S)
            listed = bool(cards_listed_fn(team))
            steps = {"agent_called": bool(rec.get("agent_called")), "verified": bool(rec.get("verified")),
                     "cards_listed": listed, "agent_online": online}
            if all(steps.values()) and not rec.get("connected"):
                rec["connected"] = True
                self._save()
            return {"team": team, **steps, "missing": [k for k, ok in steps.items() if not ok],
                    "connected": bool(rec.get("connected")),
                    "agent_last_seen": a.get("last_seen") if mine else None,
                    "code_expires_in": max(0, int(rec["code_expires"] - now)) if not rec.get("agent_called") else 0,
                    "session_expires_in": max(0, int(rec["expires"] - now))}

    # ---- ours
    def overview(self) -> dict[str, dict]:
        """team -> connection state for our own panel (no code, no hash)."""
        now = self.clock()
        out: dict[str, dict] = {}
        with self.lock:
            for team, a in self.data["agents"].items():
                out[team] = {"agent": True, "agent_verified": bool(a.get("verified")),
                             "agent_last_seen": a.get("last_seen"), "agent_issued": a.get("issued"),
                             "online": bool(a.get("last_seen") and now - a["last_seen"] < ONLINE_S),
                             "sessions": 0, "connected": False, "pending": 0}
            for v in self.data["sessions"].values():
                if v.get("expires", 0) < now:
                    continue
                o = out.setdefault(v["team"], {"agent": False, "agent_verified": False, "agent_last_seen": None,
                                               "agent_issued": None, "online": False, "sessions": 0,
                                               "connected": False, "pending": 0})
                o["sessions"] += 1
                o["connected"] = o["connected"] or bool(v.get("connected"))
                o["pending"] += 0 if v.get("verified") else 1
        return out

    def online(self, team: str) -> bool:
        a = self.data["agents"].get(team) or {}
        return bool(a.get("last_seen") and self.clock() - a["last_seen"] < ONLINE_S)
