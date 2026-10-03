"""A thread per match: its state, read from the game, and what the two agents say to each other.

    proposed -> offer_on_v07 -> accepted -> settled          (or passed, expired)

`offer_on_v07` and `settled` come from the public game feed: an offer on our venue addressed between the two teams
for that card, and the settlement between them. The game publishes no event when an offer is accepted, so
`accepted` is the word of the team that receives the offer (action "accept" on the thread); the settlement that
follows confirms it. One match is active per card and team (matcher.assign); the rest wait as alternatives. A
proposal nobody follows expires, and a match a team passed on is not proposed again for a while."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from . import matcher
from .store import MAX_PRICE, REF_RX, PlazaError

LIVE_STATES = ("proposed", "offer_on_v07", "accepted")
DONE_STATES = ("settled", "passed", "expired")
STATES = LIVE_STATES + DONE_STATES
ACTIONS = ("counter", "accept", "pass")
PROPOSAL_TICKS = 120            # a proposal with no message and no offer expires after this
OFFER_TICKS = 90                # an offer seen on the venue and never settled
PASS_TICKS = 240                # a passed match is not proposed again for this long
EXPIRED_TICKS = 120
SETTLED_TICKS = 600
STALL_TICKS = 40                # our panel calls a live match stalled after this long without news
MAX_TEXT = 280
MAX_MESSAGES = 80
MAX_DONE = 400
PER_TEAM_PER_MIN = 12
ID_RX = re.compile(r"m-[0-9a-f]{10}")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
COOL = {"passed": PASS_TICKS, "expired": EXPIRED_TICKS, "settled": SETTLED_TICKS}


def parties(m: dict) -> list[str]:
    return list(m.get("teams") or [m["seller"], m["buyer"]])


def clean_message(body, kind: str, rarity: str | None) -> dict:
    if not isinstance(body, dict):
        raise PlazaError(400, "bad_request", "send a JSON object")
    unknown = set(body) - {"action", "price", "cards", "text"}
    if unknown:
        raise PlazaError(400, "bad_request", f"unknown fields: {', '.join(sorted(unknown))[:80]}")
    out: dict = {}
    action = body.get("action")
    if action is not None:
        if action not in ACTIONS:
            raise PlazaError(400, "bad_request", f"action is one of {', '.join(ACTIONS)}")
        out["action"] = action
    price = body.get("price")
    if price is not None:
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not 0 < price <= MAX_PRICE:
            raise PlazaError(400, "bad_request", f"price must be a number between 1 and {MAX_PRICE}")
        floor = matcher.FLOOR.get(rarity or "", 1)
        if kind == "sale" and price < floor:
            raise PlazaError(400, "below_floor", f"a {rarity} card is not sold under {floor} P on this venue")
        out["price"] = int(round(price))
    cards = body.get("cards")
    if cards is not None:
        if not isinstance(cards, list) or len(cards) > 4 or not all(isinstance(r, str) and REF_RX.fullmatch(r) for r in cards):
            raise PlazaError(400, "bad_request", "cards is a list of at most 4 refs like LAV-03")
        out["cards"] = list(dict.fromkeys(cards))
    text = body.get("text")
    if text is not None:
        if not isinstance(text, str):
            raise PlazaError(400, "bad_request", "text must be a string")
        text = " ".join(_CONTROL.sub("", text).split())
        if len(text) > MAX_TEXT:
            raise PlazaError(400, "bad_request", f"text: at most {MAX_TEXT} characters")
        if text:
            out["text"] = text
    if out.get("action") == "counter" and "price" not in out and "cards" not in out:
        raise PlazaError(400, "bad_request", "a counter names a price or cards")
    if not out.get("action") and "text" not in out:
        raise PlazaError(400, "bad_request", "send an action (counter, accept, pass) or a short text")
    return out


class Deals:
    def __init__(self, path: Path | str, venue: str = matcher.VENUE, clock=time.time):
        self.path, self.venue, self.clock = Path(path), venue, clock
        self.lock = threading.RLock()
        self.rate: dict[str, list[float]] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        self.matches: dict[str, dict] = data.get("matches") or {}
        self.cool: dict[str, int] = data.get("cool") or {}
        self.forced: list[dict] = data.get("forced") or []
        self.log_pos = 0
        self.tick = 0
        self.next_msg = max([m["n"] for r in self.matches.values() for m in r.get("messages") or []], default=0) + 1

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"matches": self.matches, "cool": self.cool, "forced": self.forced},
                                  ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    # ---- state
    def _move(self, rec: dict, state: str, tick: int, events: list, **extra) -> None:
        if rec["state"] == state:
            return
        rec.update(state=state, state_tick=tick, updated=self.clock(), **extra)
        rec.setdefault("history", []).append({"state": state, "tick": tick, "ts": self.clock()})
        if state in COOL:
            self.cool[rec["id"]] = tick + COOL[state]
        events.append({"src": "plaza", "kind": "match", "ts": self.clock(), "tick": tick, "match": rec["id"],
                       "state": state, "team": rec["seller"], "to": rec["buyer"], "ref": rec["ref"],
                       "ref_back": rec.get("ref_back"), "price": rec.get("price"), "match_kind": rec["kind"],
                       "highlight": state in ("settled", "accepted")})

    def _game(self, log: list[dict], events: list) -> None:
        """Applies what the game said on our venue since the last call."""
        if len(log) < self.log_pos:
            self.log_pos = 0
        new, self.log_pos = log[self.log_pos:], len(log)
        if not new:
            return
        live = [r for r in self.matches.values() if r["state"] in LIVE_STATES and r["kind"] != "triangle"]
        for e in new:
            tick = e.get("tick") or 0
            if e["t"] == "listed" and e.get("to"):
                for r in live:
                    if r["state"] == "proposed" and {e["maker"], e["to"]} == {r["seller"], r["buyer"]} \
                            and e["ref"] in (r["ref"], r.get("ref_back")) and tick >= r["proposed_tick"]:
                        self._move(r, "offer_on_v07", tick, events, offer=e["id"], offer_maker=e["maker"],
                                   **({"price": e["price"]} if e.get("price") and r["kind"] == "sale" else {}))
                        break
            elif e["t"] == "cancelled":
                for r in live:
                    if r["state"] == "offer_on_v07" and r.get("offer") == e["id"]:
                        self._move(r, "proposed", tick, events, offer=None, offer_maker=None)
            elif e["t"] == "settled":
                for r in live:
                    if r["state"] in LIVE_STATES and set(e["parties"]) == {r["seller"], r["buyer"]} \
                            and (r["ref"] in e["refs"] or r.get("ref_back") in e["refs"]) and tick >= r["proposed_tick"]:
                        self._move(r, "settled", tick, events,
                                   **({"price": e["price"]} if e.get("price") and r["kind"] == "sale" else {}))
                        break

    def sync(self, cands: list[dict], tick: int | None, log: list[dict], paused: bool = False,
             excluded_matches=frozenset()) -> list[dict]:
        """Brings the threads up to date with the candidates and the game. Returns the floor items for what changed."""
        events: list[dict] = []
        tick = int(tick or 0)
        with self.lock:
            self.tick = tick
            before = json.dumps([(r["id"], r["state"], r.get("price"), r.get("alternatives")) for r in self.matches.values()])
            self._game(log, events)
            for r in self.matches.values():                                    # nobody followed it
                if r["state"] == "proposed" and tick - r["state_tick"] > PROPOSAL_TICKS and not r.get("forced") \
                        and tick - (r.get("last_tick") or r["state_tick"]) > PROPOSAL_TICKS:
                    self._move(r, "expired", tick, events)
                elif r["state"] in ("offer_on_v07", "accepted") and tick - r["state_tick"] > OFFER_TICKS:
                    self._move(r, "expired", tick, events)
            self.cool = {k: v for k, v in self.cool.items() if v > tick}
            fresh = {c["id"]: c for c in cands}
            blocked = lambda m: m["id"] in excluded_matches       # noqa: E731 - a match, never a team
            for mid in [k for k, r in self.matches.items() if r["state"] == "proposed" and not r.get("messages")
                        and not r.get("forced") and (k not in fresh or blocked(r))]:
                self.matches.pop(mid)                                          # the sheets changed: withdrawn
            for mid in [k for k, r in self.matches.items() if r["state"] in DONE_STATES and k not in self.cool]:
                self.matches.pop(mid)                                          # may be proposed again
            live = [r for r in self.matches.values() if r["state"] in LIVE_STATES]
            live.sort(key=lambda r: (-LIVE_STATES.index(r["state"]), not r.get("forced"), not r.get("messages"),
                                     r.get("priority", 4), r["proposed_tick"]))
            order = live + ([] if paused else
                            [c for c in cands if c["id"] not in self.matches and not blocked(c)])
            active = matcher.assign(order, skip=frozenset(self.cool) - {r["id"] for r in live})
            now = self.clock()
            for m in active:
                r = self.matches.get(m["id"])
                if r is None:
                    r = {**{k: v for k, v in m.items() if k != "recipe"}, "state": "proposed", "proposed_tick": tick,
                         "state_tick": tick, "proposed": now, "updated": now, "suggested": m["price"],
                         "messages": [], "agreed": [], "offer": None,
                         "history": [{"state": "proposed", "tick": tick, "ts": now}]}
                    self.matches[m["id"]] = r
                    events.append({"src": "plaza", "kind": "match", "ts": now, "tick": tick, "match": r["id"],
                                   "state": "proposed", "team": r["seller"], "to": r["buyer"], "ref": r["ref"],
                                   "ref_back": r.get("ref_back"), "price": r["price"], "match_kind": r["kind"],
                                   "highlight": False})
                else:
                    c = fresh.get(m["id"])
                    if c:
                        r.update({k: c[k] for k in ("why", "last_of_page", "priority", "confidence", "score") if k in c})
                        if r["state"] == "proposed" and not r.get("price_by") and not r.get("forced"):
                            r.update({k: c[k] for k in ("price", "saves", "basis") if k in c}, suggested=c["price"])
                r["alternatives"] = m["alternatives"]
            keep = {m["id"] for m in active}
            for mid in [k for k, r in self.matches.items() if r["state"] in LIVE_STATES and k not in keep]:
                self.matches.pop(mid)                                          # lost its slot to a match further on
            done = sorted((r for r in self.matches.values() if r["state"] in DONE_STATES), key=lambda r: r["updated"])
            for r in done[:max(0, len(done) - MAX_DONE)]:
                self.matches.pop(r["id"], None)
            if events or before != json.dumps([(r["id"], r["state"], r.get("price"), r.get("alternatives"))
                                               for r in self.matches.values()]):
                self._save()
        return events

    # ---- reads
    def live(self) -> list[dict]:
        with self.lock:
            rows = [r for r in self.matches.values() if r["state"] in LIVE_STATES]
        rows.sort(key=lambda r: (r.get("priority", 4), r.get("confidence") != "declared", -r.get("score", 0),
                                 r["kind"], r["ref"], r["seller"], r["buyer"]))
        return rows

    def all(self) -> list[dict]:
        with self.lock:
            return list(self.matches.values())

    def get(self, mid: str) -> dict:
        with self.lock:
            r = self.matches.get(mid) if isinstance(mid, str) and ID_RX.fullmatch(mid) else None
        if r is None:
            raise PlazaError(404, "not_found", "no such match (it may have expired)")
        return r

    def funnel(self) -> dict:
        out = {s: 0 for s in STATES}
        with self.lock:
            for r in self.matches.values():
                out[r["state"]] = out.get(r["state"], 0) + 1
        return out

    # ---- the agents
    def message(self, mid: str, team: str, verified: bool, body) -> tuple[dict, dict, list[dict]]:
        """One line of negotiation. Returns (the match, the floor item, the state changes it caused)."""
        with self.lock:
            rec = self.get(mid)
            if team not in parties(rec):
                raise PlazaError(403, "not_a_party", "only the teams of this match talk on its thread")
            if rec["state"] not in LIVE_STATES:
                raise PlazaError(409, "closed", f"this match is {rec['state']}")
            msg = clean_message(body, rec["kind"], rec.get("rarity"))
            now = self.clock()
            recent = [t for t in self.rate.get(team, []) if now - t < 60.0]
            if len(recent) >= PER_TEAM_PER_MIN:
                self.rate[team] = recent
                raise PlazaError(429, "slow_down", f"at most {PER_TEAM_PER_MIN} messages a minute per team")
            self.rate[team] = recent + [now]
            action = msg.get("action")
            events: list[dict] = []
            if action == "counter":
                if "price" in msg and rec["kind"] == "sale":
                    rec["price"], rec["price_by"] = msg["price"], team
                    rec["saves"] = matcher.rastro_fee(msg["price"])
                rec["agreed"] = [team]
            elif action == "accept":
                if team not in rec["agreed"]:
                    rec["agreed"] = rec["agreed"] + [team]
                if rec["state"] == "offer_on_v07" and team != rec.get("offer_maker"):
                    self._move(rec, "accepted", self.tick, events)
            elif action == "pass":
                self._move(rec, "passed", self.tick, events, passed_by=team)
            item = {"n": self.next_msg, "team": team, "verified": bool(verified), "ts": now, "tick": self.tick, **msg}
            self.next_msg += 1
            rec["messages"] = (rec.get("messages") or [])[-(MAX_MESSAGES - 1):] + [item]
            rec["updated"], rec["last_tick"] = now, self.tick
            self._save()
            other = next((t for t in parties(rec) if t != team), None)
            floor = {"src": "plaza", "kind": action or "note", "ts": now, "tick": self.tick, "match": rec["id"],
                     "team": team, "to": other, "ref": rec["ref"], "ref_back": rec.get("ref_back"),
                     "verified": bool(verified), "msg": item["n"], "state": rec["state"],
                     **{k: msg[k] for k in ("price", "cards", "text") if k in msg}, "highlight": False}
            return rec, floor, events

    # ---- ours
    def force(self, cand: dict) -> dict:
        """We put a match first in the queue: it takes its slots before anything else and does not expire."""
        with self.lock:
            now = self.clock()
            self.cool.pop(cand["id"], None)
            self.matches[cand["id"]] = {
                **{k: v for k, v in cand.items() if k != "recipe"}, "state": "proposed", "proposed_tick": self.tick,
                "state_tick": self.tick, "proposed": now, "updated": now, "suggested": cand["price"], "messages": [],
                "agreed": [], "offer": None, "forced": True, "alternatives": [],
                "history": [{"state": "proposed", "tick": self.tick, "ts": now}]}
            self._save()
            return self.matches[cand["id"]]

    def expire(self, mid: str) -> dict:
        with self.lock:
            rec = self.get(mid)
            if rec["state"] in LIVE_STATES:
                self._move(rec, "expired", self.tick, [])
                self._save()
            return rec

    def queue(self) -> dict:
        """The matchmaker for our panel: what is proposed and why, and what is stuck."""
        tick = self.tick
        rows = []
        for r in self.live():
            last = r.get("last_tick") or r["state_tick"]
            rows.append({"id": r["id"], "kind": r["kind"], "state": r["state"], "seller": r["seller"],
                         "buyer": r["buyer"], "ref": r["ref"], "ref_back": r.get("ref_back"), "price": r.get("price"),
                         "suggested": r.get("suggested"), "basis": r.get("basis"), "priority": r.get("priority"),
                         "confidence": r.get("confidence"), "score": r.get("score"), "why": r.get("why"),
                         "forced": bool(r.get("forced")), "age_ticks": tick - r["proposed_tick"],
                         "quiet_ticks": tick - last, "messages": len(r.get("messages") or []),
                         "alternatives": len(r.get("alternatives") or []),
                         "stalled": tick - last > STALL_TICKS})
        return {"tick": tick, "queue": rows, "stalled": [r for r in rows if r["stalled"]], "funnel": self.funnel(),
                "cooling": len(self.cool)}
