"""A fake game for the market's end-to-end tests.

The market never calls the game: it reads the recorder's files. So the fake game is a writer of those files in a
temporary folder (`live/events.jsonl`, `record/latest/{catalog,clock,venues,me}.json`, `record/latest/books/`,
`record/threads/`) plus the few game requests an agent sends with its own key: post an offer, accept one, cancel
one, write in a thread. Ticks move only when a test says so. Nothing here knows an address of the real game."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

HOST = "t10"
VENUE = "v07"
SETS = (("LAV", "Lavapiés", "#E4572E"), ("MAL", "Malasaña", "#E83F8C"), ("LAT", "La Latina", "#F2A541"),
        ("SAL", "Salamanca", "#2EC4B6"), ("RET", "El Retiro", "#7B8CDE"))
BOOK = {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}
PLACEHOLDER = re.compile(r"<your asset id of ([A-Z]{3}-\d{2})>")


def rarity_of(n: int) -> str:
    return "common" if n <= 5 else "uncommon" if n <= 8 else "rare" if n <= 10 else "epic" if n == 11 else "legendary"


def catalog() -> dict:
    sets = []
    for sid, name, color in SETS:
        cards = [{"id": f"{sid}-{n:02d}", "name": f"{name} {n}", "rarity": rarity_of(n), "page": n <= 10}
                 for n in range(1, 13)]
        sets.append({"id": sid, "name": name, "color": color, "released": True, "cards": cards})
    return {"sets": sets, "rarities": {k: {"book": v} for k, v in BOOK.items()}}


class GameError(Exception):
    """What the fake game answers to a request it refuses."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class FakeGame:
    def __init__(self, root: Path | str, teams: list[str] | None = None, tick: int = 1500, tick_seconds: float = 15.0):
        self.root = Path(root)
        self.live, self.record = self.root / "live", self.root / "record"
        for d in (self.live, self.record / "latest" / "books", self.record / "threads"):
            d.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.teams = teams or [f"t{i:02d}" for i in range(1, 19)]
        self.tick, self.tick_seconds = tick, tick_seconds
        self.doors, self.paused = "open", False
        self.ids = {"offer": 30000, "asset": 5000, "event": 0, "thread": 9000}
        self.assets: dict[int, dict] = {}                  # id -> {team, ref}
        self.cash = {t: 500 for t in self.teams}
        self.offers: dict[int, dict] = {}
        self.threads: dict[tuple, int] = {}
        self.venue_stats = {"trades": 0, "volume": 0, "traders": set(), "pairs": set()}
        self.score = {"team": HOST, "score": 37.58, "negotiating": 25.08, "market": 12.5, "mm_points": 7.6}
        self.requests: list[tuple] = []                    # every game request an agent sent, for assertions
        (self.record / "latest" / "catalog.json").write_text(json.dumps(catalog()), encoding="utf-8")
        (self.live / "events.jsonl").touch()
        (self.live / "control.json").write_text(json.dumps({"plaza": "on"}), encoding="utf-8")
        self.write_state()

    # ---- the recorder's files
    def _write(self, path: Path, obj) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(obj), encoding="utf-8")
        os.replace(tmp, path)

    def write_state(self) -> None:
        with self.lock:
            latest = self.record / "latest"
            self._write(latest / "clock.json", {
                "tick": self.tick, "tick_seconds": self.tick_seconds, "paused": self.paused,
                "next_tick_in": 9.0, "round": 3, "round_name": "Sunday", "doors": self.doors, "today": "sun",
                "today_name": "Sunday", "next_opens": "2026-10-04T09:00:00+02:00", "next_name": "Sunday"})
            v = self.venue_stats
            self._write(latest / "venues.json", {"venues": [
                {"venue": "rastro", "name": "El Rastro", "owner": None, "status": "open", "fee_bps": 500,
                 "fee_per_card": 1, "house": True},
                {"venue": VENUE, "name": "v07 Market", "owner": HOST, "owner_name": "Team 10", "status": "open",
                 "fee_bps": 0, "fee_per_card": 0, "rules": {"mechanism": "board"}, "trades": v["trades"],
                 "volume": v["volume"], "traders": len(v["traders"]), "pairs": len(v["pairs"]),
                 "description": "Zero fees.", "opened_tick": 179},
                {"venue": "v16", "name": "Mercado Dieciséis", "owner": "t16", "status": "open", "fee_bps": 100,
                 "fee_per_card": 0, "trades": 3, "volume": 400, "traders": 4, "pairs": 3}]})
            self._write(latest / "me.json", {"id": HOST, "name": "Team 10", "tick": self.tick,
                                             "tick_seconds": self.tick_seconds, "score": self.score,
                                             "venue": {"venue": VENUE}})
            for venue in ("rastro", VENUE, "v16"):
                rows = [o for o in self.offers.values() if o["venue"] == venue and o["status"] == "open" and not o["to"]]
                self._write(latest / "books" / f"{venue}.json", {"venue": venue, "tick": self.tick, "offers": rows})

    def touch(self) -> None:
        """The recorder is alive: its files are fresh."""
        self.write_state()

    def stale(self, seconds: float = 600.0) -> None:
        """The recorder stopped: every file looks old."""
        old = time.time() - seconds
        for path in list((self.record / "latest").rglob("*.json")) + [self.live / "events.jsonl"]:
            os.utime(path, (old, old))

    def emit(self, kind: str, payload: dict, actor: str | None = None) -> dict:
        with self.lock:
            self.ids["event"] += 1
            e = {"id": self.ids["event"], "ts": time.time(), "tick": self.tick, "type": kind, "actor": actor,
                 "payload": payload}
            with (self.live / "events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(e) + "\n")
            return e

    def report(self) -> dict:
        """What `bazaar.intel.needs` would deduce: here, nothing but names (agents declare everything)."""
        return {"tick": self.tick, "rivals": {t: {"name": f"Team {int(t[1:])}"} for t in self.teams}}

    # ---- the clock and the doors
    def advance(self, ticks: int = 1) -> int:
        with self.lock:
            if self.paused or self.doors != "open":
                self.write_state()
                return self.tick
            self.tick += ticks
            for o in self.offers.values():
                if o["status"] == "open" and o["expires_tick"] < self.tick:
                    o["status"] = "expired"
            self.write_state()
            return self.tick

    def set_doors(self, doors: str) -> None:
        self.doors = doors
        self.write_state()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.write_state()

    # ---- hands
    def give(self, team: str, *refs: str) -> list[int]:
        out = []
        with self.lock:
            for ref in refs:
                self.ids["asset"] += 1
                self.assets[self.ids["asset"]] = {"team": team, "ref": ref}
                out.append(self.ids["asset"])
        return out

    def hand(self, team: str) -> list[str]:
        return sorted(a["ref"] for a in self.assets.values() if a["team"] == team)

    def asset_of(self, team: str, ref: str) -> int | None:
        return next((i for i, a in self.assets.items() if a["team"] == team and a["ref"] == ref), None)

    # ---- what an agent sends with its own key
    def request(self, team: str, method: str, path: str, body: dict | None = None) -> dict:
        """One game request by `team`. Placeholders `<your asset id of REF>` are the agent's job, not the game's."""
        body = body or {}
        self.requests.append((team, method, path, json.loads(json.dumps(body))))
        if PLACEHOLDER.search(json.dumps(body)) or "<" in path:
            raise GameError(400, "a placeholder was sent to the game")
        if self.paused or self.doors != "open":
            raise GameError(409, "the market is closed")
        if method == "POST" and path == "/api/offers":
            return self.post_offer(team, body)
        m = re.fullmatch(r"/api/offers/(\d+)/accept", path)
        if method == "POST" and m:
            return self.accept(team, int(m.group(1)), body)
        m = re.fullmatch(r"/api/offers/(\d+)", path)
        if method == "DELETE" and m:
            return self.cancel(team, int(m.group(1)))
        if method == "POST" and path == "/api/threads":
            return self.thread(team, body.get("to") or body.get("with"), body.get("text") or body.get("message") or "")
        raise GameError(404, "no such game route")

    def _cards(self, side: dict) -> list[str]:
        out = []
        for c in list(side.get("cards") or []) + list(side.get("types") or []):
            out.append(c.split(":", 1)[1] if isinstance(c, str) and c.startswith("card:") else c)
        return out

    def post_offer(self, team: str, body: dict) -> dict:
        give, want = dict(body.get("give") or {}), dict(body.get("want") or {})
        venue, to = body.get("venue") or "rastro", body.get("to")
        with self.lock:
            for aid in give.get("assets") or []:
                if (self.assets.get(aid) or {}).get("team") != team:
                    raise GameError(400, "you do not hold that asset")
            if int(give.get("cash") or 0) > self.cash[team]:
                raise GameError(400, "not enough cash")
            if to is not None and to not in self.teams:
                raise GameError(400, "unknown team")
            self.ids["offer"] += 1
            give_view = {**give, "assets": [{"id": a, "ref": self.assets[a]["ref"]} for a in give.get("assets") or []]}
            offer = {"id": self.ids["offer"], "maker": team, "to": to, "venue": venue, "give": give_view,
                     "want": want, "created_tick": self.tick, "expires_tick": self.tick + 40, "status": "open"}
            self.offers[offer["id"]] = offer
            self.emit("offer.listed", {"offer": {k: v for k, v in offer.items() if k != "status"}}, team)
            self.write_state()
            return {"id": offer["id"], "status": "open"}

    def cancel(self, team: str, oid: int) -> dict:
        with self.lock:
            o = self.offers.get(oid)
            if not o or o["maker"] != team or o["status"] != "open":
                raise GameError(404, "no such open offer of yours")
            o["status"] = "cancelled"
            self.emit("offer.cancelled", {"offer": oid, "venue": o["venue"]}, team)
            self.write_state()
            return {"id": oid, "status": "cancelled"}

    def accept(self, team: str, oid: int, body: dict | None = None) -> dict:
        body = body or {}
        with self.lock:
            o = self.offers.get(oid)
            if not o or o["status"] != "open":
                raise GameError(409, "the offer is not open")
            if o["maker"] == team or (o["to"] and o["to"] != team):
                raise GameError(403, "the offer is not for you")
            maker, cash_m, cash_t = o["maker"], int(o["give"].get("cash") or 0), int(o["want"].get("cash") or 0)
            items = []
            for a in o["give"].get("assets") or []:
                if self.assets[a["id"]]["team"] != maker:
                    raise GameError(409, "the maker no longer holds the card")
                items.append((a["id"], maker, team))
            wanted = self._cards(o["want"])
            given = list(body.get("assets") or [])
            for ref in wanted:
                aid = next((i for i in given if (self.assets.get(i) or {}) == {"team": team, "ref": ref}), None)
                if aid is None:
                    raise GameError(400, f"send your asset id of {ref}")
                given.remove(aid)
                items.append((aid, team, maker))
            if self.cash[maker] < cash_m or self.cash[team] < cash_t:
                raise GameError(409, "not enough cash")
            self.cash[maker] += cash_t - cash_m
            self.cash[team] += cash_m - cash_t
            for aid, _, to in items:
                self.assets[aid]["team"] = to
            o["status"] = "settled"
            price = cash_m or cash_t
            if o["venue"] == VENUE:
                v = self.venue_stats
                v["trades"] += 1
                v["volume"] += price
                v["traders"].update((maker, team))
                v["pairs"].add(tuple(sorted((maker, team))))
                self.score["mm_points"] = round(self.score["mm_points"] + 0.4, 2)
            self.emit("settlement", {"venue": o["venue"], "price": price, "parties": [maker, team], "offer": oid,
                                     "items": [{"ref": self.assets[a]["ref"], "frm": f, "to": t} for a, f, t in items]})
            self.write_state()
            return {"id": oid, "status": "settled"}

    def thread(self, team: str, other: str | None, text: str) -> dict:
        """A message of `team` in its thread with `other`, as the recorder keeps it: one JSON line per snapshot."""
        if other not in self.teams and other != HOST:
            raise GameError(400, "unknown team")
        with self.lock:
            key = tuple(sorted((team, other)))
            if key not in self.threads:
                self.ids["thread"] += 1
                self.threads[key] = self.ids["thread"]
            tid = self.threads[key]
            path = self.record / "threads" / f"{tid}.json"
            try:
                last = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
            except (OSError, ValueError, IndexError):
                last = {"id": tid, "kind": "team", "team": other, "with": team, "status": "open",
                        "created_tick": self.tick, "messages": []}
            last["messages"].append({"id": len(last["messages"]) + 1, "tick": self.tick, "sender": team, "text": text})
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(last) + "\n")
            return {"thread": tid}
