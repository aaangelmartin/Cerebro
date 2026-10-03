"""The live floor: what agents say on the plaza, mixed with the public game feed, in one ordered stream.

Agent messages are structured (kind, card, price, to, short text), stored as lines in a bounded file, and never
carry HTML: the page escapes every string. Each stream item gets a sequence number; a reader asks for what came
after the last one it saw, or waits for the next."""
from __future__ import annotations

import collections
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from .store import MAX_PRICE, REF_RX, TEAM_RX, PlazaError

KINDS = ("want", "offer", "accept", "note")
MAX_TEXT = 280
KEEP = 900                                  # items in memory
KEEP_FILE = 1500                            # agent messages on disk before the file is trimmed to half
PER_TEAM_PER_MIN = 12
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_message(body) -> dict:
    if not isinstance(body, dict):
        raise PlazaError(400, "bad_request", "send a JSON object")
    unknown = set(body) - {"kind", "ref", "price", "to", "text"}
    if unknown:
        raise PlazaError(400, "bad_request", f"unknown fields: {', '.join(sorted(unknown))[:80]}")
    kind = body.get("kind")
    if kind not in KINDS:
        raise PlazaError(400, "bad_request", f"kind must be one of {', '.join(KINDS)}")
    out: dict = {"kind": kind}
    ref = body.get("ref")
    if ref is not None:
        if not isinstance(ref, str) or not REF_RX.fullmatch(ref):
            raise PlazaError(400, "bad_request", "ref looks like LAV-03")
        out["ref"] = ref
    elif kind in ("want", "offer"):
        raise PlazaError(400, "bad_request", f"a {kind} message names a card in ref")
    price = body.get("price")
    if price is not None:
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not 0 < price <= MAX_PRICE:
            raise PlazaError(400, "bad_request", f"price must be a number between 1 and {MAX_PRICE}")
        out["price"] = int(round(price))
    to = body.get("to")
    if to is not None:
        if not isinstance(to, str) or not TEAM_RX.fullmatch(to):
            raise PlazaError(400, "bad_request", "to is a team id like t04")
        out["to"] = to
    text = body.get("text")
    if text is not None:
        if not isinstance(text, str):
            raise PlazaError(400, "bad_request", "text must be a string")
        text = " ".join(_CONTROL.sub("", text).split())
        if len(text) > MAX_TEXT:
            raise PlazaError(400, "bad_request", f"text: at most {MAX_TEXT} characters")
        if text:
            out["text"] = text
    if "ref" not in out and "text" not in out:
        raise PlazaError(400, "bad_request", "say something: a card in ref or a short text")
    return out


class Floor:
    def __init__(self, path: Path | str, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.items: collections.deque = collections.deque(maxlen=KEEP)
        self.seq = 0
        self.epoch = secrets.token_hex(4)                      # changes on restart: readers start over
        self.cond = threading.Condition()
        self.rate: dict[str, list[float]] = {}
        self.next_id = 1
        self.lines = 0

    def load(self, game_items: list[dict]) -> None:
        """At start: the stored agent messages and the recent game items, in time order."""
        agent = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if isinstance(m, dict) and isinstance(m.get("id"), int):
                    agent.append(m)
        except OSError:
            pass
        self.lines = len(agent)
        self.next_id = max([m["id"] for m in agent], default=0) + 1
        merged = sorted(agent[-300:] + list(game_items), key=lambda m: (m.get("ts") or 0))
        with self.cond:
            for m in merged:
                self._push(m)

    def _push(self, item: dict) -> dict:
        self.seq += 1
        item = {**item, "seq": self.seq}
        self.items.append(item)
        return item

    def add_game(self, items: list[dict]) -> None:
        if not items:
            return
        with self.cond:
            for m in items:
                self._push(m)
            self.cond.notify_all()

    def post(self, team: str, verified: bool, body) -> dict:
        msg = clean_message(body)
        if msg.get("to") == team:
            raise PlazaError(400, "bad_request", "to is another team")
        now = self.clock()
        with self.cond:
            recent = [t for t in self.rate.get(team, []) if now - t < 60.0]
            if len(recent) >= PER_TEAM_PER_MIN:
                self.rate[team] = recent
                raise PlazaError(429, "slow_down", f"at most {PER_TEAM_PER_MIN} messages a minute per team")
            self.rate[team] = recent + [now]
            item = {"src": "agent", "id": self.next_id, "ts": now, "team": team, "verified": bool(verified), **msg}
            self.next_id += 1
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                self.lines += 1
                if self.lines > KEEP_FILE:
                    self._trim()
            except OSError:
                pass
            out = self._push(item)
            self.cond.notify_all()
            return out

    def _trim(self) -> None:
        rows = self.path.read_text(encoding="utf-8").splitlines()[-KEEP_FILE // 2:]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("\n".join(rows) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        self.lines = len(rows)

    @staticmethod
    def _shown(m: dict, hidden: set, blocked: set) -> bool:
        if m.get("src") != "agent":
            return True
        return m.get("id") not in hidden and m.get("team") not in blocked

    def poll(self, since: int = 0, team: str | None = None, ref: str | None = None, kind: str | None = None,
             limit: int = 100, hidden: set | None = None, blocked: set | None = None,
             everything: bool = False) -> dict:
        hidden, blocked = hidden or set(), blocked or set()
        with self.cond:
            rows = [m for m in self.items if m["seq"] > since]
            seq = self.seq
        out = []
        for m in rows:
            if not everything and not self._shown(m, hidden, blocked):
                continue
            if team and team not in (m.get("team"), m.get("to")):
                continue
            if ref and ref not in ([m.get("ref"), m.get("ref_back")] + list(m.get("refs") or [])):
                continue
            if kind and kind != m.get("kind") and kind != m.get("src"):
                continue
            if everything and m.get("src") == "agent":
                m = {**m, "hidden": m.get("id") in hidden, "blocked": m.get("team") in blocked}
            out.append(m)
        return {"epoch": self.epoch, "seq": seq, "items": out[-max(1, min(limit, 300)):]}

    def wait(self, since: int, timeout: float) -> bool:
        with self.cond:
            if self.seq > since:
                return True
            return self.cond.wait(timeout)
