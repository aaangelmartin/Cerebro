"""A reference agent for v07 Market: connect, publish your cards, run your queue, close on venue v07.

It uses only what AGENTS.md documents (the market's public API) and the game's own API with YOUR team's key.
Copy it, keep the loop, replace `sheet()` and `decide()` with your own judgement.

    export GAME_URL=https://<the game>      GAME_KEY=<your team key>      # the key never leaves this process
    python agent_example.py --plaza https://<host>/plaza --team t16 --code PLAZA-7K2Q9M     # first time
    python agent_example.py --plaza https://<host>/plaza --team t16                         # afterwards
    python agent_example.py --plaza https://<host>/plaza --team t16 --dry-run --once        # look, send nothing

The agent token is kept in `--token-file` (mode 600) or read from PLAZA_TOKEN. Standard library only. The game
key is read from the environment, sent only to GAME_URL as header X-Team-Key, and never printed."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

VENUE = "v07"
HOST_TEAM = "t10"
PLACEHOLDER = re.compile(r"<your asset id of ([A-Z]{3}-\d{2})>")


def http_json(method: str, url: str, body=None, headers: dict | None = None, timeout: float = 15.0):
    """One JSON request. Returns (status, answer); a refusal is an answer too, never an exception."""
    data = None if body is None else json.dumps(body).encode()
    h = {"Accept": "application/json", **({"Content-Type": "application/json"} if data is not None else {}),
         **(headers or {})}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, h, method=method), timeout=timeout) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
        e.close()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return 0, {"error": "network", "message": str(e)[:120]}
    try:
        return status, json.loads(raw or b"{}")
    except ValueError:
        return status, {"error": "not_json", "message": raw[:120].decode(errors="replace")}


class Agent:
    def __init__(self, team: str, plaza: str, token: str | None = None, game: str | None = None,
                 key: str | None = None, dry_run: bool = False, http=http_json, log=print, sleep=time.sleep):
        if not plaza.rstrip("/").endswith("/plaza"):
            raise ValueError("the market address ends in /plaza")
        self.team, self.plaza, self.token = team, plaza.rstrip("/"), token
        self.host = self.plaza[:-len("/plaza")]
        self.game, self._key = (game or "").rstrip("/"), key
        self.dry_run, self.http, self.log, self.sleep = dry_run, http, log, sleep
        self.limits: dict[str, dict] = {}                  # our own private limits, as we last published them

    # ---- the two doors: the market (token) and the game (your own key)
    def market(self, method: str, path: str, body=None):
        """A call to the market. `path` is under the base (`/api/...`) or absolute (`/plaza/api/...`)."""
        url = (self.host if path.startswith("/plaza/") else self.plaza) + path
        return self.http(method, url, body, {"X-Plaza-Token": self.token} if self.token else {})

    def to_game(self, method: str, path: str, body=None):
        if not self.game or not self._key:
            return 0, {"error": "no_game", "message": "set GAME_URL and GAME_KEY"}
        return self.http(method, self.game + path, body, {"X-Team-Key": self._key})

    # ---- once: connect and prove
    def connect(self, code: str) -> str:
        st, out = self.market("POST", "/api/connect/agent", {"team": self.team, "code": code})
        if st != 200:
            raise RuntimeError(f"connect failed: {out.get('error')}: {out.get('message')}")
        self.token = out["agent_token"]
        self.log(f"connected as {self.team} (verified: {out.get('verified')})")
        return self.token

    def prove(self, code: str) -> bool:
        """Sends the code to the host in the game, with our own key: that is the proof of identity."""
        st, th = self.to_game("POST", "/api/threads", {"with": HOST_TEAM, "venue": VENUE})
        if st not in (200, 201) or "id" not in th:
            self.log(f"could not open the thread with {HOST_TEAM}: {th.get('message') or th.get('error')}")
            return False
        st, out = self.to_game("POST", f"/api/threads/{th['id']}/messages", {"text": code})
        self.log("code sent in the game" if st in (200, 201) else f"the game refused the code: {out.get('message')}")
        return st in (200, 201)

    # ---- your cards
    def assets(self) -> list[dict]:
        st, me = self.to_game("GET", "/api/me")
        return [a for a in (me.get("assets") or []) if a.get("kind", "card") == "card"] if st == 200 else []

    def sheet(self) -> dict:
        """Your sheet from your real hand. Replace this with your own judgement.

        have: every card. spares: second copies, never sold under a quarter of what the card is worth to you
        (that is what a second copy is worth). wants: every released card you do not hold, each with a `max` (the
        game's list price of its rarity): without a limit of your own the market never trades for you blind."""
        held: dict[str, list[dict]] = {}
        for a in self.assets():
            held.setdefault(a["ref"], []).append(a)
        spares = []
        for ref, copies in sorted(held.items()):
            if len(copies) > 1:
                worth = copies[0].get("your_value")
                spares.append({"ref": ref, "min": max(1, int(worth / 4) + 1)} if worth else ref)
        st, cat = self.to_game("GET", "/api/catalog")
        book = {k: v.get("book") for k, v in (cat.get("rarities") or {}).items() if isinstance(v, dict)} if st == 200 else {}
        wants = []
        for c in sorted((c for s in (cat.get("sets") or []) if s.get("released", True) for c in s.get("cards") or []
                         if not c.get("hidden") and c["id"] not in held), key=lambda c: c["id"]) if st == 200 else []:
            most = book.get(c.get("rarity"))                # never above the game's list price; put your own value here
            wants.append({"ref": c["id"], "max": int(most)} if most else c["id"])
        return {"wants": wants, "spares": spares, "for_sale": [], "have": sorted(held)}

    def publish(self, sheet: dict | None = None):
        sheet = sheet if sheet is not None else self.sheet()
        self.limits = {e["ref"]: {k: e[k] for k in ("min", "max", "value") if k in e}
                       for part in ("wants", "spares", "for_sale") for e in sheet.get(part) or [] if isinstance(e, dict)}
        if self.dry_run:
            self.log(f"dry run: would publish {json.dumps(sheet)[:300]}")
            return 200, {}
        st, out = self.market("PUT", f"/api/team/{self.team}", sheet)
        self.log(f"published {len(sheet.get('wants') or [])} wants, {len(sheet.get('spares') or [])} spares"
                 if st == 200 else f"publish refused: {out.get('message')}")
        return st, out

    # ---- the loop
    def fill(self, body, mine: dict[str, int]):
        """Replaces "<your asset id of REF>" with the id of our copy of that card."""
        if isinstance(body, dict):
            return {k: self.fill(v, mine) for k, v in body.items()}
        if isinstance(body, list):
            return [self.fill(v, mine) for v in body]
        m = PLACEHOLDER.fullmatch(body) if isinstance(body, str) else None
        if m:
            if m.group(1) not in mine:
                raise LookupError(f"we do not hold {m.group(1)}")
            return mine[m.group(1)]
        return body

    def stand(self, match_id: str) -> tuple[dict, str, int | None, int]:
        """(the match, our role, our own limit for its card or None, the price on the table)."""
        st, m = self.market("GET", f"/api/match/{match_id}")
        if st != 200:
            return {}, "", None, 0
        role = "seller" if m.get("seller") == self.team else "buyer"
        ours = self.limits.get(m.get("ref") or "", {})
        return m, role, ours.get("min") if role == "seller" else ours.get("max"), int(m.get("price") or 0)

    def takes(self, match_id: str) -> tuple[bool, str]:
        """Would WE trade at the price now on the table? Checked against our own limits before anything is sent
        to the game: the queue is advice, the limit is ours. A sale of a card we set no limit for is never done
        blind, whoever suggests the price."""
        m, role, limit, price = self.stand(match_id)
        if not m:
            return False, "could not read the match"
        if m.get("kind") != "sale":
            return True, ""
        if limit is None:
            return False, f"no limit of ours for {m.get('ref')}: not traded blind"
        if (role == "seller" and price < limit) or (role == "buyer" and price > limit):
            return False, f"{price} P is outside our limit for {m.get('ref')}"
        return True, ""

    def decide(self, action: dict):
        """The queue hands us the decision: the other team set the price, it is outside our limit, or we set no
        limit. Inside our limit: accept. Outside: counter at our limit. No limit of ours: nothing (None); set a
        `min` or a `max` for the card and the queue goes on. Yours to improve."""
        m, role, limit, price = self.stand(action["match"])
        if not m or limit is None:
            return None
        if (role == "seller" and price >= limit) or (role == "buyer" and price <= limit):
            return {"action": "accept"}
        return {"action": "counter", "price": limit}

    def run_action(self, a: dict) -> tuple[bool, str]:
        """Runs one action of the queue. Returns (done, note)."""
        r = a["request"]
        if a["type"] == "sync_cards":
            st, out = self.publish()
        elif a["type"] == "decide":
            word = self.decide(a)
            if word is None:
                return False, "no limit of ours for this card: set one, or decide by hand"
            st, out = self.market(r["method"], r["path"], word)
        elif r["target"] == "game":
            if a["type"] in ("post_offer", "accept_offer") and a.get("match"):
                ok, why = self.takes(a["match"])               # the price is checked against OUR limits first
                if not ok:
                    return False, "refused: " + why
            try:
                body = r.get("body") or {}
                if PLACEHOLDER.search(json.dumps(body)):
                    body = self.fill(body, {x["ref"]: x["id"] for x in self.assets()})
            except LookupError as e:
                return False, str(e)
            if body.get("venue", VENUE) != VENUE:
                return False, f"refused: this deal closes on {VENUE}"
            st, out = self.to_game(r["method"], r["path"], body)
            then = a.get("then")
            if 200 <= st < 300 and then and out.get("id") is not None:     # tell the market which offer it is
                self.market(then["method"], then["path"], {"offer_id": out["id"]})
        else:
            st, out = self.market(r["method"], r["path"], r.get("body"))
        ok = 200 <= st < 300
        return ok, "" if ok else f"{st} {out.get('error') or ''} {out.get('message') or ''}".strip()[:200]

    def step(self) -> dict:
        """One turn: read the queue, run each action in order, acknowledge each one."""
        st, q = self.market("GET", "/api/agent/next")
        if st != 200:
            self.log(f"queue not read: {st} {q.get('error')}")
            return {"actions": [], "poll_after_s": 60}
        for a in q.get("actions") or []:
            what = f"{a['type']} {a.get('match') or ''}: {a.get('why')}"
            if self.dry_run:
                self.log(f"dry run: would do {what} -> {a['request']['target']} {a['request']['method']} {a['request']['path']}")
                continue
            ok, note = self.run_action(a)
            self.log(f"{'done' if ok else 'failed'}: {what}" + (f" ({note})" if note else ""))
            self.market("POST", "/api/agent/ack", {"id": a["id"], "status": "done" if ok else "failed",
                                                    **({"note": note} if note else {})})
        for w in q.get("waiting") or []:
            self.log(f"waiting on {w['match']}: {w['why']}")
        return q

    def run(self, once: bool = False) -> None:
        while True:
            q = self.step()
            if once:
                return
            self.sleep(max(3, min(120, q.get("poll_after_s") or 20)))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Reference agent for v07 Market. GAME_URL and GAME_KEY come from the environment.")
    p.add_argument("--plaza", default=os.environ.get("PLAZA_URL"), help="the market's address, ending in /plaza")
    p.add_argument("--team", required=True, help="your team id, such as t16")
    p.add_argument("--code", help="the code from the Connect button (first time only)")
    p.add_argument("--token-file", default=".plaza_token", help="where the agent token is kept (mode 600)")
    p.add_argument("--dry-run", action="store_true", help="read and print; send nothing to the game or the market")
    p.add_argument("--once", action="store_true", help="one turn, then stop")
    a = p.parse_args(argv)
    if not a.plaza:
        p.error("give --plaza or set PLAZA_URL")
    token_file = Path(a.token_file)
    token = os.environ.get("PLAZA_TOKEN") or (token_file.read_text().strip() if token_file.exists() else None)
    agent = Agent(a.team, a.plaza, token, os.environ.get("GAME_URL"), os.environ.get("GAME_KEY"), dry_run=a.dry_run)
    if a.code and a.dry_run:
        p.error("--code connects, which is a write: run it without --dry-run")
    if a.code:
        fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(agent.connect(a.code))
        agent.prove(a.code)
    if not agent.token:
        print("no token: run once with --code <the code from Connect>", file=sys.stderr)
        return 2
    if not a.dry_run:
        agent.publish()
    agent.run(once=a.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
