"""A practice market: the real server on a temporary folder, a game that is not the game, three teams.

    python -m bazaar.plaza.sandbox [--port 8893] [--game-port 8894] [--tick 5]

One command starts the market (`http://127.0.0.1:8893/plaza`), a simulated game over HTTP with the real game's
routes (`http://127.0.0.1:8894`) and its own clock, and two counterparties that run `agent_example.py` with
nothing but AGENTS.md's calls. The third team, t01, is left for the agent under test: `POST <game>/sandbox/guest` answers
its Connect prompt (a fresh code each time), the game address and its simulated key, and
`GET <game>/sandbox/status` says how far it got (also written to `<root>/status.json`).

The keys here are made up for this run and open nothing but this simulated game. The real market (:8793), the
gateway, the bot and the real game are never touched."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import agent_example
from .e2e.fakegame import BOOK, HOST, VENUE, GameError, catalog, rarity_of
from .e2e.rig import Rig

GUEST = "t01"
# ref -> copies. The guest holds a duplicate one counterparty misses, and misses a duplicate the other holds.
HANDS = {
    "t01": ["SAL-10", "SAL-10", "RET-03", "LAV-03", "LAV-04", "LAV-05", "LAV-06", "LAV-07"],
    "t02": ["LAT-06", "LAV-01", "LAV-02"],
    "t03": ["LAV-08", "LAV-08", "MAL-02", "RET-07"],
}
SHEETS = {
    "t02": {"wants": [{"ref": "SAL-10", "max": 90}], "spares": [], "for_sale": []},
    "t03": {"wants": ["RET-03"], "spares": [{"ref": "LAV-08", "min": 12}], "for_sale": []},
}


def card(ref: str) -> dict:
    n = int(ref[4:])
    return {"kind": "card", "ref": ref, "set": ref[:3], "rarity": rarity_of(n), "your_value": float(BOOK[rarity_of(n)])}


class Game:
    """The fake game behind HTTP, with the real game's two calls for a thread and a key per team."""

    def __init__(self, rig: Rig, keys: dict[str, str]):
        self.rig, self.game, self.teams = rig, rig.game, {v: k for k, v in keys.items()}
        self.thread_of: dict[int, tuple[str, str]] = {}
        self.url = ""

    def me(self, team: str) -> dict:
        g = self.game
        with g.lock:
            assets = [{"id": i, **card(a["ref"])} for i, a in g.assets.items() if a["team"] == team]
            return {"id": team, "name": f"Team {int(team[1:])}", "cash": g.cash[team], "assets": assets,
                    "tick": g.tick, "tick_seconds": g.tick_seconds}

    def open_thread(self, team: str, body: dict) -> dict:
        other = body.get("with")
        if other not in g_teams(self.game):
            raise GameError(400, "`with` is a team id such as t10")
        if other == HOST and body.get("venue") == VENUE:      # as the real game: nobody deals with a
            raise GameError(409, "self_venue: t10 owns v07; open the thread on El Rastro (venue rastro)")  # venue's owner there
        g = self.game
        with g.lock:
            key = tuple(sorted((team, other)))
            if key not in g.threads:
                g.ids["thread"] += 1
                g.threads[key] = g.ids["thread"]
            tid = g.threads[key]
            self.thread_of[tid] = key
        return {"id": tid, "with": other, "venue": body.get("venue"), "status": "open"}

    def message(self, team: str, tid: int, body: dict) -> dict:
        key = self.thread_of.get(tid)
        if not key or team not in key:
            raise GameError(404, "no such thread of yours")
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise GameError(400, "`text` is the message")
        other = key[0] if key[1] == team else key[1]
        self.game.thread(team, other, text)
        return {"id": tid, "status": "open", "sent": True}

    def guest(self) -> dict:
        """What the agent under test is given: a fresh Connect prompt (the code works once, for 60 minutes), the
        game's address and its simulated key."""
        s, got, _ = self.rig.call("POST", "/plaza/api/connect/start", {"team": GUEST})
        key = next(k for k, t in self.teams.items() if t == GUEST)
        return {"team": GUEST, "prompt": got["prompt"], "code": got["connect_code"], "agents_md": got["agents_md"],
                "game": self.url, "game_key": key, "status": self.url + "/sandbox/status"}

    def handle(self, team: str, method: str, path: str, body: dict, query: dict | None = None) -> dict:
        query = query or {}
        g = self.game
        if method == "GET" and path == "/api/me":
            return self.me(team)
        if method == "GET" and path == "/api/me/value":
            ref = (query.get("card") or [""])[0]
            if not re.fullmatch(r"[A-Z]{3}-\d{2}", ref):
                raise GameError(400, "card is a card id such as LAV-09")
            worth = card(ref)["your_value"]
            return {"card": ref, "value": worth / 4 if ref in g.hand(team) else worth}
        if method == "GET" and path == "/api/catalog":
            return catalog()
        if method == "GET" and path == "/api/clock":
            return {"tick": g.tick, "tick_seconds": g.tick_seconds, "paused": g.paused, "doors": g.doors}
        if method == "GET" and path == "/api/venues":
            return json.loads((g.record / "latest" / "venues.json").read_text(encoding="utf-8"))
        m = re.fullmatch(r"/api/offers/(\d+)", path)
        if method == "GET" and m:
            o = g.offers.get(int(m.group(1)))
            if not o:
                raise GameError(404, "no such offer")
            return o
        if method == "GET" and path == "/api/offers":
            return {"offers": [o for o in g.offers.values() if o["status"] == "open" and team in (o["maker"], o["to"])]}
        if method == "POST" and path == "/api/threads":
            return self.open_thread(team, body)
        m = re.fullmatch(r"/api/threads/(\d+)/messages", path)
        if method == "POST" and m:
            return self.message(team, int(m.group(1)), body)
        return g.request(team, method, path, body)


def g_teams(game) -> list[str]:
    return [*game.teams, HOST]


def game_server(game: Game, port: int) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401 - quiet
            pass

        def _send(self, status: int, obj) -> None:
            raw = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _do(self) -> None:
            path = self.path.split("?", 1)[0]
            if self.command == "GET" and path == "/sandbox/status":
                return self._send(200, status(game.rig))
            if self.command == "POST" and path == "/sandbox/guest":         # a fresh code and prompt for the guest
                return self._send(200, game.guest())
            team = game.teams.get(self.headers.get("X-Team-Key") or "")
            if not team:
                return self._send(401, {"error": "unauthorized", "message": "send your team key as header X-Team-Key"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._send(400, {"error": "bad_request", "message": "send a JSON object"})
            try:
                from urllib.parse import parse_qs
                query = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                self._send(200, game.handle(team, self.command, path, body, query))
            except GameError as e:
                self._send(e.status, {"error": "refused", "message": e.message})
            except Exception:  # noqa: BLE001 - a practice game: never a trace to the caller
                self._send(500, {"error": "server", "message": "the simulated game failed on that request"})

        do_GET = do_POST = do_DELETE = do_PUT = _do

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def status(rig: Rig) -> dict:
    """What an observer needs: per team connected, verified, sheet published; every match with its state."""
    board, teams = rig.board, {}
    for t in HANDS:
        s, view, _ = rig.call("GET", f"/plaza/api/team/{t}")
        view = view if s == 200 and isinstance(view, dict) else {}
        agents = rig.call("GET", "/plaza/admin/api/teams", admin=True)[1]
        row = next((x for x in (agents.get("teams") or []) if x.get("team") == t), {}) if isinstance(agents, dict) else {}
        teams[t] = {"connected": bool(row.get("connected") or row.get("agent")), "verified": bool(row.get("verified")),
                    "online": bool(row.get("online")),
                    "sheet_published": bool(view.get("available") or view.get("wanted")),
                    "available": [c.get("ref") for c in view.get("available") or []],
                    "wanted": [c.get("ref") for c in view.get("wanted") or []],
                    "hand": rig.game.hand(t), "cash": rig.game.cash[t]}
    matches = [{"id": m["id"], "kind": m.get("kind"), "state": m.get("state"), "seller": m.get("seller"),
                "buyer": m.get("buyer"), "ref": m.get("ref"), "price": m.get("price"), "offer": m.get("offer"),
                "settled_venue": m.get("settled_venue")} for m in board.deals.all()]
    mine = [m for m in matches if GUEST in (m["seller"], m["buyer"])]
    return {"tick": rig.game.tick, "guest": GUEST, "teams": teams, "matches": matches,
            "guest_settled_on_v07": [m["id"] for m in mine if m["state"] == "settled"],
            "passed": bool(teams[GUEST]["verified"] and any(m["state"] == "settled" for m in mine))}


class Counterparty(agent_example.Agent):
    """The reference agent with a fixed sheet, kept true to its hand."""

    plan: dict = {}

    def sheet(self) -> dict:
        held = [a["ref"] for a in self.assets()]
        return {"wants": [x for x in self.plan["wants"] if _ref(x) not in held],
                "spares": [x for x in self.plan["spares"] if held.count(_ref(x)) > 1],
                "for_sale": [x for x in self.plan["for_sale"] if _ref(x) in held], "have": sorted(set(held))}


def _ref(x) -> str:
    return x["ref"] if isinstance(x, dict) else x


def start(port: int = 8893, game_port: int = 8894, tick: float = 5.0, log=lambda *_: None) -> dict:
    rig = Rig(port=port).start()
    port = rig.port
    os.environ["PLAZA_PUBLIC_URL"] = f"http://127.0.0.1:{port}/plaza"      # what the prompt and AGENTS.md print
    rig.game.tick_seconds = tick
    keys = {t: f"SIMKEY-{t}-{os.urandom(4).hex()}" for t in HANDS}
    for t, refs in HANDS.items():
        rig.game.give(t, *refs)
    game = Game(rig, keys)
    gsrv = game_server(game, game_port)
    game_port = gsrv.server_address[1]
    game_url, plaza = f"http://127.0.0.1:{game_port}", f"http://127.0.0.1:{port}/plaza"
    game.url = game_url
    stop = threading.Event()

    def clock() -> None:
        while not stop.wait(tick):
            try:
                rig.game.advance()
                rig.refresh()
                (rig.root / "status.json").write_text(json.dumps(status(rig), indent=1), encoding="utf-8")
            except Exception as e:  # noqa: BLE001 - keep the practice market up
                log(f"clock: {type(e).__name__}: {e}")

    threading.Thread(target=clock, daemon=True).start()

    def counterparty(team: str) -> None:
        s, got, _ = rig.call("POST", "/plaza/api/connect/start", {"team": team})
        a = Counterparty(team, plaza, game=game_url, key=keys[team], log=lambda m, t=team: log(f"{t}: {m}"),
                         sleep=lambda s_: stop.wait(min(s_, tick)))
        a.plan = SHEETS[team]
        a.connect(got["connect_code"])
        a.prove(got["connect_code"])
        a.wait_verified(pause=min(1.0, tick))
        while not stop.is_set():
            try:
                a.publish()
                a.step()
            except Exception as e:  # noqa: BLE001
                log(f"{team}: {type(e).__name__}: {e}")
            stop.wait(tick)

    for t in SHEETS:
        threading.Thread(target=counterparty, args=(t,), daemon=True).start()
    return {"rig": rig, "game_server": gsrv, "stop": stop, "plaza": plaza, "game": game_url, "team": GUEST,
            "agents_md": plaza + "/AGENTS.md", "status": game_url + "/sandbox/status",
            "guest": game_url + "/sandbox/guest", "root": str(rig.root), "game_obj": game}


def main() -> None:
    ap = argparse.ArgumentParser(description="A practice v07 Market with a simulated game and two counterparties.")
    ap.add_argument("--port", type=int, default=8893)
    ap.add_argument("--game-port", type=int, default=8894)
    ap.add_argument("--tick", type=float, default=5.0, help="seconds per simulated tick")
    args = ap.parse_args()
    info = start(args.port, args.game_port, args.tick, log=lambda m: print(m, file=sys.stderr, flush=True))
    out = {k: info[k] for k in ("plaza", "agents_md", "game", "team", "status", "guest", "root")}
    print(json.dumps(out), flush=True)
    try:
        while True:
            time.sleep(600)
    except KeyboardInterrupt:
        pass
    finally:
        info["stop"].set()
        info["game_server"].shutdown()
        info["rig"].stop()


if __name__ == "__main__":
    main()
