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
import re
import secrets
import threading
import time
from pathlib import Path

from .store import TEAM_RX, PlazaError, read_json, write_atomic

HOST = "t10"
CODE_TTL_S = 15 * 60.0
SESSION_TTL_S = 12 * 3600.0
ONLINE_S = 90.0
WINDOW_S = 15 * 60.0
# Every team at the venue sits behind one public address, so an address is a whole room. Nothing here is counted
# per team: nobody's own connection is spent by what somebody else asks in its name. A right code always passes.
STARTS_PER_CLIENT = 300                             # per WINDOW_S, per address, over every team
TRIES_PER_CLIENT = 400                              # wrong codes per WINDOW_S, per address: only wrong ones wait
MAX_SESSIONS, SESSIONS_PER_TEAM = 8000, 400         # unanswered ones; more than one address can start in a window
MAX_HITS = 5000
SAVE_SEEN_EVERY_S = 10.0
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"       # no 0/O, 1/I
PROVE_FIRST = ("prove it is your team first: with your own game key, open a thread with t10 in the game and send "
               "your connection code as the text; this token reads and writes once the market has seen it "
               "(a few seconds), so try again shortly")
CODE_RX = re.compile(r"PLAZA-[2-9A-HJ-NP-Z]{6}")
TOKEN_RX = re.compile(r"[A-Za-z0-9_-]{20,64}")
COOKIE = "plaza_session"


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_code() -> str:
    return "PLAZA-" + "".join(secrets.choice(ALPHABET) for _ in range(6))


def prompt(team: str, code: str, base: str, venue: str = "v07", name: str = "Plaza", lang: str = "en") -> str:
    """What the human pastes to its agent, in English or Spanish. `base` is the public address ending in /plaza."""
    n = int(team[1:])
    body = f'{{"team": "{team}", "code": "{code}"}}'
    if lang == "es":
        return (
            f"Eres el agente del Team {n} en The Bazaar. {name} es el mercado de Team 10 en el venue "
            f"{venue} (comisión 0; Team 10 nunca es parte). Base de todas las rutas: {base}\n"
            f"Lee primero {base}/AGENTS.md. Después, con el código {code} (un uso, 15 min):\n"
            f"1. POST /api/connect/agent {body}; envía el agent_token como cabecera X-Plaza-Token "
            "siempre.\n"
            f"2. En el juego, abre un hilo con t10 en el venue {venue} y envía {code} como texto, con TU PROPIA clave del juego. Nunca "
            "envíes esa clave aquí ni a nadie.\n"
            f"3. Repite GET /api/agent/next hasta verified: true (antes, 403 prove_first). Luego PUT "
            f"/api/team/{team} con wants, spares, for_sale.\n"
            "4. En cada tick: GET /api/agent/next, ejecuta cada petición en orden, POST /api/agent/ack. Cierra todo "
            f"en el venue {venue}. Hazlo todo tú."
        )
    return (
        f"You are Team {n}'s trading agent in The Bazaar. {name} is Team 10's market on venue {venue} (0 fee; Team "
        f"10 is never a party). Base URL of every path below: {base}\n"
        f"Read {base}/AGENTS.md first. Then, with code {code} (one use, 15 min):\n"
        f"1. POST /api/connect/agent {body}; send the agent_token you get as header X-Plaza-Token on every request.\n"
        f"2. In the game, open a thread with t10 on venue {venue} and send {code} as the text, using YOUR OWN game key. Never send "
        "that key here or to anyone.\n"
        f"3. Poll GET /api/agent/next until verified: true (403 prove_first before). Then PUT "
        f"/api/team/{team} with wants, spares, for_sale.\n"
        "4. Every tick: GET /api/agent/next, run each request in order, POST /api/agent/ack. Close every deal on "
        f"venue {venue}. Do it all yourself."
    )


class Connect:
    def __init__(self, path: Path | str, host: str = HOST, clock=time.time):
        self.path, self.host, self.clock = Path(path), host, clock
        self.lock = threading.RLock()
        self.hits: dict[tuple, list[float]] = {}
        self.changed: set[str] = set()      # teams whose agent was just replaced by another: the board wipes them
        self.data = self._load()
        self.saved_seen = 0.0
        self.on_event = None                # (team, kind, text): set by the team API to feed the activity log
        self.unsaid: list[tuple] = []

    # ---- file
    def _load(self) -> dict:
        data = read_json(self.path)
        for key in ("sessions", "agents"):
            if not isinstance(data.get(key), dict):
                data[key] = {}
        return data

    def _save(self) -> None:
        write_atomic(self.path, json.dumps(self.data).encode("utf-8"), 0o600)

    def _say(self, team: str, kind: str, text: str) -> None:
        """Tells whoever listens (the team's activity log) what happened; never lets it break a connection."""
        if self.on_event is None:
            self.unsaid = (self.unsaid + [(team, kind, text)])[-200:]      # kept until somebody listens
            return
        try:
            self.on_event(team, kind, text)
        except Exception:  # noqa: BLE001
            pass

    def listen(self, fn) -> None:
        """Sets the listener and tells it what happened before it came."""
        with self.lock:
            self.on_event, late, self.unsaid = fn, self.unsaid, []
        for team, kind, text in late:
            self._say(team, kind, text)

    # ---- limits
    def _take(self, key: tuple, limit: int) -> bool:
        now = self.clock()
        if len(self.hits) > MAX_HITS:                          # forget the spent windows, then the oldest ones;
            live = {k: v for k, v in self.hits.items() if v and now - v[-1] < WINDOW_S}      # never everybody's
            if len(live) > MAX_HITS:
                live = dict(sorted(live.items(), key=lambda kv: kv[1][-1])[len(live) - MAX_HITS // 2:])
            self.hits = live
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
        for sid in [k for k, v in s.items() if v.get("expires", 0) < now
                    or (not v.get("agent_called") and not v.get("verified") and v.get("code_expires", 0) < now)]:
            s.pop(sid, None)                                   # a code nobody redeemed in time opens nothing
        if len(s) > MAX_SESSIONS:                              # sessions nobody's agent answered go first
            spare = sorted((k for k in s if not s[k].get("verified") and not s[k].get("agent_called")),
                           key=lambda k: s[k].get("created", 0))
            for sid in spare[:len(s) - MAX_SESSIONS]:
                s.pop(sid, None)

    # ---- the flow
    def start(self, team, client: str, tick: int | None = None) -> dict:
        """A session and its code. `tick` is the game's tick now: only a game message from then on proves it."""
        team = self._team(team)
        with self.lock:
            if not self._take(("start", "c", client), STARTS_PER_CLIENT):
                raise PlazaError(429, "slow_down", "too many connection attempts; wait a few minutes")
            self._prune()
            now = self.clock()
            s = self.data["sessions"]
            mine = sorted((k for k, v in s.items() if v["team"] == team and not v.get("verified")
                           and not v.get("agent_called")),     # a session whose agent answered is never pushed out
                          key=lambda k: s[k].get("created", 0))
            for sid in mine[:max(0, len(mine) - SESSIONS_PER_TEAM + 1)]:
                s.pop(sid, None)
            session, code = secrets.token_urlsafe(24), new_code()
            s[_h(session)] = {"team": team, "code": code, "created": now, "code_expires": now + CODE_TTL_S,
                              "tick": tick if isinstance(tick, int) and not isinstance(tick, bool) else None,
                              "expires": now + SESSION_TTL_S, "agent_called": None, "token": None,
                              "verified": False, "connected": False}
            self._save()
            return {"team": team, "connect_code": code, "session": session, "code_expires_in": int(CODE_TTL_S),
                    "session_expires_in": int(SESSION_TTL_S)}

    def agent(self, team, code, client: str, team_verified: bool, current: str | None = None) -> dict:
        """The agent's half: the code for a token. `team_verified` says the team already proved itself before.
        The code is looked at first: a right one always passes, whatever others got wrong from the same address."""
        team = self._team(team)
        with self.lock:
            now = self.clock()
            code = code.strip().upper() if isinstance(code, str) else ""
            rec = None
            if CODE_RX.fullmatch(code):
                for v in self.data["sessions"].values():
                    if v["team"] == team and secrets.compare_digest(v["code"], code):
                        rec = v
                        break
            if rec is None or rec.get("agent_called") or rec["code_expires"] < now or rec["expires"] < now:
                if not self._take(("try", "c", client), TRIES_PER_CLIENT):
                    raise PlazaError(429, "locked", "too many wrong codes; wait a few minutes")
                why = "this code was already used" if rec and rec.get("agent_called") else \
                    "this code expired; ask for a new one" if rec else "wrong code for this team"
                raise PlazaError(403, "bad_code", why)
            token = secrets.token_urlsafe(24)
            rec["agent_called"], rec["token"] = now, _h(token)
            active = not team_verified or rec.get("verified")
            if active:                                         # an unverified team: the newest agent is the agent
                self._activate(team, rec)
            self._save()
            self._say(team, "connect", "connected with its code" if active else
                      "connected; it writes once the new code is proved in the game")
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

    def pending_since(self) -> float:
        """When the oldest session still waiting for its proof was started (now, when there is none)."""
        now = self.clock()
        with self.lock:
            return min([v.get("created", now) for v in self.data["sessions"].values()
                        if not v.get("verified") and v.get("expires", 0) >= now] or [now])

    def prove(self, team: str, text: str, tick: int | None = None) -> bool:
        """A message this team sent us in the game carries one of its codes: that session is verified, its agent
        becomes the team's agent and everything else of the team is dropped. `tick` is the message's game tick: a
        message older than the session proves nothing.

        The newest proof wins, always: the game is where a team is itself, so a team that lost its agent to
        somebody else (or to a code it was talked into sending) takes it back by proving a fresh code. Nothing is
        held for later: a session is proved now or it stays what it was."""
        if not isinstance(text, str) or not isinstance(team, str):
            return False
        upper = text.upper()
        with self.lock:
            now = self.clock()
            s = self.data["sessions"]
            hit = next((k for k, v in s.items() if v["team"] == team and not v.get("verified")
                        and v.get("expires", 0) >= now and v["code"] in upper
                        and not (isinstance(tick, int) and isinstance(v.get("tick"), int) and tick < v["tick"])), None)
            if hit is None:
                return False
            before = self.data["agents"].get(team) or {}
            replaced = bool(before.get("verified"))
            if before and before.get("token") != s[hit].get("token"):
                self.changed.add(team)                         # another agent comes in: nothing of the last one stays
            s[hit]["verified"], s[hit]["verified_at"] = True, now
            if s[hit].get("token"):
                self._activate(team, s[hit])
            else:                                              # whoever held the team before the proof is out; the
                self.data["agents"].pop(team, None)            # proved session's agent takes over when it calls
            for k in [k for k, v in s.items() if v["team"] == team and k != hit]:
                s.pop(k, None)                                 # older sessions too: one proof, one way in
            self._save()
            self._say(team, "connect", "proved a new code in the game: the agent connected before is out"
                      if replaced else "proved its code in the game")
            return True

    def reset(self, team: str) -> dict:
        """Ours: forgets the team's agent and every session of it, so that it connects again from nothing."""
        team = self._team(team)
        with self.lock:
            gone = [k for k, v in self.data["sessions"].items() if v["team"] == team]
            for k in gone:
                self.data["sessions"].pop(k, None)
            had = self.data["agents"].pop(team, None) is not None
            self._save()
        self._say(team, "connect", "the host reset this team's connection: connect again")
        return {"team": team, "agent": had, "sessions": len(gone)}

    def auth(self, token) -> tuple[str, bool]:
        """(team, verified) for an agent token; raises 401 otherwise. Counts as the agent's heartbeat."""
        if not isinstance(token, str) or not TOKEN_RX.fullmatch(token):
            raise PlazaError(401, "bad_token", "send your agent token in X-Plaza-Token")
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
                    if v.get("verified") or v.get("expires", 0) < now:
                        break                                  # replaced by a newer agent of the same team
                    raise PlazaError(403, "prove_first", PROVE_FIRST)
        raise PlazaError(401, "bad_token", "unknown agent token; connect again")

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

    def agent_status(self, team: str, listed: bool) -> dict:
        """The same steps, asked by the team's agent with its token (it has no browser session)."""
        with self.lock:
            now = self.clock()
            a = self.data["agents"].get(team) or {}
            online = bool(a.get("last_seen") and now - a["last_seen"] < ONLINE_S)
            steps = {"agent_called": bool(a), "verified": bool(a.get("verified")), "cards_listed": bool(listed),
                     "agent_online": online}
            return {"team": team, **steps, "missing": [k for k, ok in steps.items() if not ok],
                    "connected": all(steps.values()), "agent_last_seen": a.get("last_seen"), "code_expires_in": 0,
                    "session_expires_in": 0}

    def team_of(self, session=None, token=None) -> str | None:
        """The team behind a credential that PROVED itself (a verified agent token, a verified browser session),
        else None. Anybody can start a session or redeem a code in a team's name: until the proof it is nobody."""
        if token:
            try:
                team, verified = self.auth(token)
            except PlazaError:
                return None
            return team if verified else None
        rec = self.session(session)
        return rec["team"] if rec and rec.get("verified") else None

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
