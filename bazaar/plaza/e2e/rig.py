"""The market's server on a temporary folder, next to a fake game, and fake agents that use only the public API.

    rig = Rig().start()
    seller = rig.agent("t01", for_sale=[{"ref": "SAL-10", "price": 70, "min": 60}], have=["SAL-10"])
    buyer = rig.agent("t02", wants=[{"ref": "SAL-10", "max": 90}])
    rig.run(8)              # refresh the board, let every agent work its queue, move one tick; eight times
    rig.stop()

Nothing here imports the bot, reads `.env` or knows an address of the real game."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from .. import server as S
from .fakegame import PLACEHOLDER, FakeGame, GameError

ADMIN_TOKEN = "e2e-admin-token"


class Rig:
    def __init__(self, root: Path | str | None = None, port: int = 0):
        self.own_root = root is None
        self.root = Path(root or tempfile.mkdtemp(prefix="plaza-e2e-"))
        self.port = port
        self.game = FakeGame(self.root)
        self.agents: dict[str, SimAgent] = {}
        self.board = self.srv = None
        self.no_have = False
        self.base = ""

    # ---- the server
    def start(self) -> "Rig":
        self.board = S.Board(self.game.live, self.game.record, report_fn=self.game.report,
                             private_dir=self.root / "private")
        self.board.token = ADMIN_TOKEN
        self.board.start_feed()
        self.board.rebuild()
        self.srv = S.make_server(self.board, port=self.port)
        self.port = self.srv.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def halt(self) -> None:
        if self.srv is not None:
            self.srv.shutdown()
            self.srv.server_close()
            self.srv = None

    def stop(self) -> None:
        self.halt()
        if self.own_root:
            shutil.rmtree(self.root, ignore_errors=True)

    def restart(self) -> None:
        """The process dies and comes back on the same files (same port, so agents keep their address)."""
        self.halt()
        self.start()

    def refresh(self) -> dict:
        """What the server's ticker does every few seconds, now."""
        self.board.tick_feed()
        return self.board.rebuild()

    # ---- requests
    def call(self, method: str, path: str, body=None, token: str | None = None, session: str | None = None,
             admin: bool = False, client: str | None = None, raw: bytes | None = None, headers: dict | None = None,
             timeout: float = 10.0):
        """(status, parsed JSON or text, headers). `client` is the address the gateway would forward."""
        h = dict(headers or {})
        data = raw
        if body is not None and raw is None:
            data = json.dumps(body).encode()
        if data is not None and "Content-Type" not in h:
            h["Content-Type"] = "application/json"
        if token:
            h[S.TOKEN_HEADER] = token
        if session:
            h["Cookie"] = f"{S.COOKIE}={session}"
        if admin:
            h[S.ADMIN_HEADER] = ADMIN_TOKEN
        if client:
            h["X-Plaza-Client"] = client
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, _parse(r.read(), r.headers), r.headers
        except urllib.error.HTTPError as e:
            raw_body = e.read()
            e.close()
            return e.code, _parse(raw_body, e.headers), e.headers

    # ---- agents
    def agent(self, team: str, wants=(), spares=(), for_sale=(), have=None, verify: bool = True,
              hand: list[str] | None = None) -> "SimAgent":
        a = SimAgent(self, team)
        a.sheet = {"wants": list(wants), "spares": list(spares), "for_sale": list(for_sale)}
        owned = hand if hand is not None else sorted({*(_ref(x) for x in spares), *(_ref(x) for x in for_sale),
                                                      *(have or [])})
        if have is not None:
            a.sheet["have"] = list(have)
        self.game.give(team, *owned)
        a.connect(verify=verify)
        a.publish()
        self.agents[team] = a
        return a

    def run(self, rounds: int = 6, until=None) -> int:
        """Rounds of: read the feed and rebuild, every agent works its queue, the game moves one tick."""
        for i in range(rounds):
            self.refresh()
            if until is not None and until():
                return i
            for a in list(self.agents.values()):
                if a.alive:
                    a.step()
                    a.resync()
            self.game.advance()
        self.refresh()
        return rounds

    def match_of(self, a: str, b: str, ref: str | None = None) -> dict | None:
        """The newest match between two teams, in any state."""
        rows = [m for m in self.board.deals.all() if {m.get("seller"), m.get("buyer")} == {a, b}
                and (ref is None or ref in (m.get("ref"), m.get("ref_back")))]
        return rows[-1] if rows else None


def _ref(x) -> str:
    return x["ref"] if isinstance(x, dict) else x


def _parse(raw: bytes, headers):
    if "json" in (headers.get("Content-Type") or ""):
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode("utf-8", errors="replace")
    return raw.decode("utf-8", errors="replace")


class SimAgent:
    """A team's agent as AGENTS.md describes it: connect, prove, publish, then work the queue every tick."""

    def __init__(self, rig: Rig, team: str):
        self.rig, self.team = rig, team
        self.client = f"10.9.{int(team[1:])}.1"            # its own address, so its own request budget
        self.session = self.token = self.code = None
        self.sheet: dict = {}
        self.alive = True
        self.log: list[tuple] = []                         # (action type, "done" | "failed", note)

    def api(self, method: str, path: str, body=None, **kw):
        return self.rig.call(method, path, body, token=self.token, client=self.client, **kw)

    def connect(self, verify: bool = True) -> None:
        s, start, _ = self.rig.call("POST", "/plaza/api/connect/start", {"team": self.team}, client=self.client)
        assert s == 200, (s, start)
        self.session, self.code = start["session"], start["connect_code"]
        s, got, _ = self.rig.call("POST", "/plaza/api/connect/agent", {"team": self.team, "code": self.code},
                                  client=self.client)
        assert s == 200, (s, got)
        self.token = got["agent_token"]
        if verify:
            self.prove()

    def prove(self) -> None:
        """The proof of identity: the code, sent to the host in the game with the team's own key."""
        self.rig.game.request(self.team, "POST", "/api/threads", {"to": self.rig.game_host(), "text": self.code})
        self.rig.refresh()

    def publish(self, sheet: dict | None = None):
        if sheet is not None:
            self.sheet = sheet
        out = self.api("PUT", f"/plaza/api/team/{self.team}", self.sheet)
        if out[0] == 400 and "have" in self.sheet and "have" in str(out[1]):
            self.rig.no_have = True                        # the server predates `have` (CONTRACT 1.1): go on without
            out = self.api("PUT", f"/plaza/api/team/{self.team}", {k: v for k, v in self.sheet.items() if k != "have"})
        return out

    def resync(self) -> bool:
        """After a trade the hand changed: drop what was sold and what was found, and publish again."""
        hand = set(self.rig.game.hand(self.team))
        new = {"wants": [x for x in self.sheet.get("wants", []) if _ref(x) not in hand],
               "spares": [x for x in self.sheet.get("spares", []) if _ref(x) in hand],
               "for_sale": [x for x in self.sheet.get("for_sale", []) if _ref(x) in hand]}
        if "have" in self.sheet:
            new["have"] = sorted(hand)
        if new == self.sheet:
            return False
        self.sheet = new
        self.publish()
        return True

    def queue(self) -> dict:
        s, q, _ = self.api("GET", "/plaza/api/agent/next")
        assert s == 200, (s, q)
        return q

    def limit(self, ref: str, role: str):
        rows = self.sheet.get("for_sale", []) if role == "seller" else self.sheet.get("wants", [])
        row = next((x for x in rows if isinstance(x, dict) and x["ref"] == ref), {})
        return row.get("min") if role == "seller" else row.get("max")

    def _fill(self, obj):
        """Replaces `<your asset id of REF>` with the asset id; anything else in angle brackets stays."""
        if isinstance(obj, str):
            m = PLACEHOLDER.fullmatch(obj)
            return self.rig.game.asset_of(self.team, m.group(1)) if m else obj
        if isinstance(obj, list):
            return [self._fill(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self._fill(v) for k, v in obj.items()}
        return obj

    def step(self, only: int | None = None, ack: bool = True) -> list[tuple]:
        """Runs the queue once, in order. `only` stops after that many actions (an agent that dies half way)."""
        done = []
        for i, a in enumerate(self.queue()["actions"]):
            if only is not None and i >= only:
                break
            req, kind = a["request"], a["type"]
            status, note = "done", None
            try:
                if kind == "sync_cards":
                    s, out, _ = self.publish()
                    if s != 200:
                        status, note = "failed", f"{s} {out}"
                elif req["target"] == "game":
                    got = self.rig.game.request(self.team, req["method"], req["path"], self._fill(req.get("body")))
                    then = a.get("then")                           # report the id the game gave, when asked to
                    if then and then.get("target") == "plaza":
                        body = json.loads(json.dumps(then.get("body") or {}).replace(
                            '"<the id the game gave your offer>"', str(got.get("id"))))
                        s, out, _ = self.api(then["method"], then["path"], body)
                        if s >= 400:
                            note = f"then: {s} {out.get('error') if isinstance(out, dict) else out}"
                else:
                    body = req.get("body")
                    if kind == "decide":                           # outside my limits: counter at my own limit
                        m = self.rig.call("GET", f"/plaza/api/match/{a['match']}", client=self.client)[1]
                        role = "seller" if m.get("seller") == self.team else "buyer"
                        mine = self.limit(m["ref"], role)
                        body = {"action": "counter", "price": mine} if mine else {"action": "pass"}
                    s, out, _ = self.api(req["method"], req["path"], body)
                    if s >= 400:
                        status, note = "failed", f"{s} {out.get('error') if isinstance(out, dict) else out}"
            except GameError as e:
                status, note = "failed", f"game {e.status}: {e.message}"
            if ack:
                s, out, _ = self.api("POST", "/plaza/api/agent/ack", {"id": a["id"], "status": status,
                                                                      **({"note": note} if note else {})})
                assert s == 200, (s, out)
            self.log.append((kind, status, note))
            done.append((kind, status, note))
        return done


def _game_host(self) -> str:
    return self.board.host


Rig.game_host = _game_host

SECRET_RX = re.compile(r"Traceback|File \"/|/Users/|\.py\", line")
