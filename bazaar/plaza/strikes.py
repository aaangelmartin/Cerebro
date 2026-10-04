"""Warnings and the ban for teams that take a deal we matched to another venue.

A deal counts for this market only when it settles on our venue. The rule, as every team reads it before it
connects:

    A trade this market proposed to your team, for which YOUR team then posted the offer on another venue and
    closed it there, is a strike. The first strike is a warning. At the limit (2) the team loses access to the
    market for good; only the host can lift it.

What is NOT a strike: an offer posted elsewhere and moved to our venue before it closed; a trade we never
proposed; an offer that was already open before we proposed the trade; the team that only accepted (it gets a
notice); a team whose agent was not connected and proved when it happened; a closing whose maker the game's feed
does not show (the host is told, nobody is struck).

Kept on disk (safe.save: atomic, with a .bak) and idempotent: one closing counts once, whatever the restarts."""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from . import safe
from .store import PlazaError, TEAM_RX

LIMIT = 2
MAX_LIMIT = 9
KEEP_SEEN = 4000
KEEP_LOG = 200
ALLOWED_WHEN_BANNED = ("/plaza/api/status", "/plaza/api/me")       # GET only: the ban explains itself there
RULE = ("Deals matched here close on {venue}. One more deal closed elsewhere and your team loses access to "
        "{name} for good.")
BANNED = ("Your team no longer has access to {name}: {n} trades this market matched for you were closed on "
          "another venue. Ask Team {host} in person.")


def action_id(key: str) -> str:
    """The id of the queue action that tells the agent about a strike (same shape as every queue action)."""
    return "a-" + hashlib.sha1(("strike|" + key).encode()).hexdigest()[:12]


class Strikes:
    def __init__(self, path: Path | str, venue: str = "v07", name: str = "v07 Market", host: str = "t10",
                 clock=time.time):
        self.path, self.venue, self.name, self.host, self.clock = Path(path), venue, name, host, clock
        self.lock = threading.RLock()
        data = safe.load(self.path)
        self.on: bool = data.get("on") is not False
        limit = data.get("limit")
        self.limit: int = limit if isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= MAX_LIMIT else LIMIT
        self.accepter: bool = bool(data.get("accepter"))       # does the team that only accepted get a strike too
        self.teams: dict[str, dict] = {k: v for k, v in (data.get("teams") or {}).items()
                                       if isinstance(v, dict) and TEAM_RX.fullmatch(k)} \
            if isinstance(data.get("teams"), dict) else {}
        self.seen: list[str] = [k for k in data.get("seen") or [] if isinstance(k, str)]
        self.log: list[dict] = [e for e in data.get("log") or [] if isinstance(e, dict)]

    def _save(self) -> None:
        safe.save(self.path, {"on": self.on, "limit": self.limit, "accepter": self.accepter, "teams": self.teams,
                              "seen": self.seen[-KEEP_SEEN:], "log": self.log[-KEEP_LOG:]})

    def _team(self, team: str) -> dict:
        t = self.teams.setdefault(team, {})
        t.setdefault("strikes", [])
        t.setdefault("banned", None)
        return t

    @staticmethod
    def _active(t: dict) -> list[dict]:
        return [s for s in t.get("strikes") or [] if not s.get("forgiven")]

    # ---- the rule
    def record(self, key: str, *, match: str, ref: str, venue: str, tick: int | None, parties: list[str],
               maker: str | None, verified, saw, settlement=None, offer=None, predates: bool = False) -> list[dict]:
        """One closing of a matched trade on another venue. `key` names it for good (a second call does nothing).
        `maker` is the team that posted the offer there (None when the feed does not say); `verified` and `saw`
        are the teams proved in the game and the teams whose agent knew of the proposal. Returns what happened:
        {"team", "kind": warning | banned | notice | unknown | skipped, ...}."""
        out: list[dict] = []
        with self.lock:
            if key in self.seen:
                return out
            self.seen.append(key)
            del self.seen[:-KEEP_SEEN]
            base = {"key": key, "match": match, "card": ref, "venue": venue, "tick": tick, "settlement": settlement,
                    "offer": offer, "ts": self.clock(), "seller": parties[0] if parties else None,
                    "buyer": parties[1] if len(parties) > 1 else None}
            if not self.on:
                self._note({**base, "kind": "skipped", "why": "the rule is switched off", "teams": parties})
                self._save()
                return out
            if maker is None or maker not in parties:
                e = {**base, "kind": "unknown", "teams": parties,
                     "why": "the game's feed does not say which team posted the offer: nobody is struck"}
                self._note(e)
                self._save()
                return [e]
            struck = [maker] + ([t for t in parties if t != maker] if self.accepter else [])
            told: list[str] = []
            for team in parties:
                other = next((t for t in parties if t != team), None)
                why = None
                if team == self.host:
                    why = "the host is never struck"
                elif team not in verified:
                    why = "the team was not connected and proved"
                elif team not in saw:
                    why = "its agent had not seen the proposal"
                elif predates and team == maker:
                    why = "the offer was open before the trade was proposed"
                if why:
                    self._note({**base, "kind": "skipped", "team": team, "why": why})
                    continue
                if team not in struck:                         # it only accepted: told, not struck
                    told.append(team)
                    continue
                t = self._team(team)
                strike = {**base, "id": action_id(key + "|" + team), "with": other,
                          "role": "posted" if team == maker else "accepted", "acked": False, "forgiven": False}
                t["strikes"].append(strike)
                n = len(self._active(t))
                kind = "warning"
                if n >= self.limit and not t.get("banned"):
                    t["banned"] = {"by": "rule", "tick": tick, "ts": self.clock(), "strikes": n,
                                   "reason": f"{n} matched trades closed on another venue"}
                    kind = "banned"
                e = {**strike, "kind": kind, "team": team, "strikes": n, "limit": self.limit}
                self._note(e)
                out.append(e)
            for team in told if out else []:                   # a notice only when somebody was in fact struck
                e = {**base, "kind": "notice", "team": team, "with": next((t for t in parties if t != team), None)}
                self._note(e)
                out.append(e)
            self._save()
        return out

    def _note(self, e: dict) -> None:
        self.log.append({k: v for k, v in e.items() if k not in ("acked", "forgiven")})
        del self.log[:-KEEP_LOG]

    # ---- reads
    def banned(self, team: str | None) -> bool:
        """Is the team out? A ban by the rule holds while the rule is on; one by hand always holds."""
        with self.lock:
            b = (self.teams.get(team or "") or {}).get("banned")
            return bool(b) and (self.on or b.get("by") == "host")

    def banned_teams(self) -> frozenset:
        with self.lock:
            return frozenset(t for t in self.teams if self.banned(t))

    def standing(self, team: str) -> dict:
        """What a team is told about itself: {strikes, limit, banned, last, message}. Nothing of another team
        but the id of the one it traded with."""
        with self.lock:
            t = self.teams.get(team) or {}
            active = self._active(t)
            banned = self.banned(team)
            last = active[-1] if active else None
            n = len(active)
            if banned:
                message = (t.get("banned") or {}).get("by") == "host" and \
                    f"Your team no longer has access to {self.name}. Ask Team {int(self.host[1:])} in person." or \
                    BANNED.format(name=self.name, n=n, host=int(self.host[1:]))
            elif n and self.on:
                left = max(1, self.limit - n)
                message = (f"Warning {n} of {self.limit}: a trade matched here ({last['card']} with {last['with']}) "
                           f"was closed on {last['venue']}, not on {self.venue}. "
                           + (RULE.format(venue=self.venue, name=self.name) if left == 1 else
                              f"Deals matched here close on {self.venue}. {left} more and your team loses access "
                              f"to {self.name} for good."))
            else:
                message = None
            shown = active if self.on or banned else []
            evidence = [{k: s.get(k) for k in ("match", "card", "venue", "tick", "with", "seller", "buyer")}
                        for s in shown]
            return {"strikes": len(shown), "limit": self.limit, "banned": banned,
                    "last": evidence[-1] if evidence else None, "evidence": evidence,
                    "acked": all(s.get("acked") for s in active), "message": message, "rule": self.on,
                    "reason": (t.get("banned") or {}).get("reason") if banned else None}

    def actions(self, team: str) -> list[dict]:
        """Queue actions: one `warning` per strike the agent has not acknowledged. Its request only reads the
        team's own standing, so an agent that runs every action as it comes does no harm: read, then ack."""
        with self.lock:
            if not self.on:
                return []
            t = self.teams.get(team) or {}
            active = self._active(t)
            out = []
            for i, s in enumerate(active, 1):
                if s.get("acked"):
                    continue
                out.append({"id": s["id"], "type": "warning", "match": s["match"],
                            "why": f"warning {i} of {self.limit}: {s['card']} with {s['with']} was closed on "
                                   f"{s['venue']}, not on {self.venue}. Trades this market matches close on "
                                   f"{self.venue} (0 fee). At {self.limit} your team loses access for good. "
                                   "Read your standing and acknowledge this.",
                            "request": {"target": "plaza", "method": "GET", "auth": "X-Plaza-Token",
                                        "path": "/plaza/api/me", "body": None}, "strikes": i, "limit": self.limit, "card": s["card"],
                            "venue": s["venue"], "tick": s["tick"]})
            return out

    def ack(self, team: str, aid) -> bool:
        """The agent read the warning. True when `aid` was one of the team's strikes."""
        with self.lock:
            for s in (self.teams.get(team) or {}).get("strikes") or []:
                if s.get("id") == aid:
                    if not s.get("acked"):
                        s["acked"] = True
                        self._save()
                    return True
        return False

    # ---- ours
    def view(self) -> dict:
        """Everything, for our panel: every strike with its evidence, the bans, and what was not counted."""
        with self.lock:
            teams = []
            for team in sorted(self.teams):
                t = self.teams[team]
                if not t.get("strikes") and not t.get("banned"):
                    continue
                teams.append({"team": team, "strikes": len(self._active(t)), "limit": self.limit,
                              "banned": self.banned(team), "ban": t.get("banned"),
                              "evidence": [dict(s) for s in t.get("strikes") or []]})
            return {"on": self.on, "limit": self.limit, "accepter": self.accepter, "teams": teams,
                    "warned": sum(1 for t in teams if t["strikes"] and not t["banned"]),
                    "banned": sum(1 for t in teams if t["banned"]),
                    "log": list(self.log[-60:][::-1])}

    def summary(self, team: str) -> dict:
        """One team's line for our Teams table."""
        with self.lock:
            t = self.teams.get(team) or {}
            return {"strikes": len(self._active(t)), "limit": self.limit, "banned": self.banned(team)}

    def _known(self, team) -> str:
        if not isinstance(team, str) or not TEAM_RX.fullmatch(team) or team == self.host:
            raise PlazaError(400, "bad_request", "name a team, such as t04")
        return team

    def forgive(self, team, strike_id=None) -> dict:
        """Takes one strike back (the newest, or the one named). A ban by the rule that no longer has its
        strikes is lifted with it."""
        team = self._known(team)
        with self.lock:
            t = self._team(team)
            active = self._active(t)
            if strike_id is not None:
                active = [s for s in active if s.get("id") == strike_id]
            if not active:
                raise PlazaError(404, "not_found", "this team has no such strike")
            active[-1].update(forgiven=True, forgiven_ts=self.clock())
            b = t.get("banned")
            if b and b.get("by") == "rule" and len(self._active(t)) < self.limit:
                t["banned"] = None
            self._note({"kind": "forgiven", "team": team, "strike": active[-1]["id"], "ts": self.clock()})
            self._save()
            return self.summary(team)

    def unban(self, team) -> dict:
        """Lets the team back in, one strike short of the limit: the next closing elsewhere bans it again."""
        team = self._known(team)
        with self.lock:
            t = self._team(team)
            if not t.get("banned"):
                raise PlazaError(409, "conflict", "this team is not banned")
            t["banned"] = None
            for s in self._active(t)[max(0, self.limit - 1):]:
                s.update(forgiven=True, forgiven_ts=self.clock())
            self._note({"kind": "unbanned", "team": team, "ts": self.clock()})
            self._save()
            return self.summary(team)

    def ban(self, team, reason=None, tick=None) -> dict:
        team = self._known(team)
        if reason is not None and not isinstance(reason, str):
            raise PlazaError(400, "bad_request", "reason is a short text")
        with self.lock:
            t = self._team(team)
            t["banned"] = {"by": "host", "tick": tick, "ts": self.clock(), "strikes": len(self._active(t)),
                           "reason": " ".join((reason or "by the host").split())[:200]}
            self._note({"kind": "banned", "team": team, "by": "host", "ts": self.clock(),
                        "why": t["banned"]["reason"]})
            self._save()
            return self.summary(team)

    def configure(self, on=None, limit=None, accepter=None) -> dict:
        if on is not None and not isinstance(on, bool):
            raise PlazaError(400, "bad_request", "on is true or false")
        if accepter is not None and not isinstance(accepter, bool):
            raise PlazaError(400, "bad_request", "accepter is true or false")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT):
            raise PlazaError(400, "bad_request", f"limit is a whole number from 1 to {MAX_LIMIT}")
        if on is None and limit is None and accepter is None:
            raise PlazaError(400, "bad_request", "send on, limit or accepter")
        with self.lock:
            if on is not None:
                self.on = on
            if limit is not None:
                self.limit = limit
            if accepter is not None:
                self.accepter = accepter
            self._save()
            return {"on": self.on, "limit": self.limit, "accepter": self.accepter}
