"""The plaza: Team 10's public market board. A page and a small JSON API on top of the game.

    python -m bazaar.plaza.server            # 127.0.0.1:8793 (PLAZA_PORT)

Public by design and isolated for that reason: its own process, a strict whitelist of routes, validated input, a
request budget per client, no file read from a parameter, and nothing from the private API (no /brain, /control,
/outbox, keys or anybody's real hand). The gateway forwards /plaza/* to it without the dashboard login.

Every team's sheet arrives filled with what the game shows everyone (bazaar.plaza.public) and the team's AGENT
replaces it through the API behind a team PIN (bazaar.plaza.store). The game key of a team is never asked for."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import matcher, public
from .store import TEAM_RX, PlazaError, Store

PORT = int(os.environ.get("PLAZA_PORT", "8793"))
WEB = Path(__file__).parent / "web"
HOST = public.HOST
VENUE = matcher.VENUE
REFRESH_S = 15.0
MAX_BODY = 16 * 1024
READS_PER_MIN, WRITES_PER_MIN = 240, 30
STATIC = {"/plaza/static/plaza.css": ("plaza.css", "text/css; charset=utf-8"),
          "/plaza/static/plaza.js": ("plaza.js", "text/javascript; charset=utf-8")}
TEAM_PATH = re.compile(r"/plaza/api/team/(t\d{2})")
SECURITY = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' "
                               "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
}


class Budget:
    """Requests per minute per client; a sliding window in memory."""

    def __init__(self, clock=time.monotonic):
        self.clock, self.hits, self.lock = clock, {}, threading.Lock()

    def take(self, client: str, kind: str) -> bool:
        limit = WRITES_PER_MIN if kind == "write" else READS_PER_MIN
        now = self.clock()
        with self.lock:
            if len(self.hits) > 5000:                         # never grow without bound
                self.hits.clear()
            q = [t for t in self.hits.get((client, kind), []) if now - t < 60.0]
            if len(q) >= limit:
                self.hits[(client, kind)] = q
                return False
            q.append(now)
            self.hits[(client, kind)] = q
            return True


class Board:
    """The data behind the page: sheets, matches and venue stats, rebuilt from files every few seconds."""

    def __init__(self, live: Path, record: Path, report_fn=None, host: str = HOST):
        self.live, self.record, self.host = Path(live), Path(record), host
        self.store = Store(self.live / "plaza.json", host=host)
        self.report_fn = report_fn
        self.lock = threading.Lock()
        self.snap: dict = {"built": 0.0, "sheets": {}, "matches": [], "cat": {}, "stats": {}, "tick": None}

    def enabled(self) -> bool:
        try:
            ctl = json.loads((self.live / "control.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ctl = {}
        return str(ctl.get("plaza", "on")).lower() not in ("off", "false", "0")

    def _report(self) -> dict:
        if self.report_fn is not None:
            return self.report_fn() or {}
        from ..intel.needs import needs_report
        return needs_report(self.record, self.live)

    def _stats(self) -> dict:
        """Deals closed on our venue and what their takers saved against El Rastro, from the public feed."""
        deals, volume, saved, last = 0, 0, 0, None
        try:
            with (self.live / "events.jsonl").open(encoding="utf-8") as f:
                for line in f:
                    if '"settlement"' not in line or f'"{VENUE}"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    p = e.get("payload") or {}
                    if e.get("type") != "settlement" or p.get("venue") != VENUE:
                        continue
                    price = p.get("price") or 0
                    deals, volume, last = deals + 1, volume + price, e.get("tick")
                    saved += matcher.rastro_fee(price)
        except OSError:
            pass
        return {"venue": VENUE, "deals": deals, "volume": volume, "saved_fees": saved, "last_deal_tick": last}

    def _verify(self) -> None:
        """A team proves a claim by sending us, in the game, a thread message with its code."""
        codes = self.store.pending_codes()
        if not codes:
            return
        folder = self.record / "threads"
        try:
            files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:60]
        except OSError:
            return
        for path in files:
            try:
                rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
            except (OSError, ValueError):
                continue
            for th in rows[-1:]:
                if not isinstance(th, dict) or th.get("kind") == "persona":
                    continue
                for m in th.get("messages") or []:
                    sender = m.get("sender")
                    if sender in codes and isinstance(m.get("text"), str):
                        self.store.verify(sender, m["text"])

    def rebuild(self) -> dict:
        report = self._report()
        cat = public.catalog(self.record)
        try:
            self._verify()
        except Exception:  # noqa: BLE001 - verification never takes the board down
            pass
        sheets = public.merge(public.public_sheets(report, cat, self.host), self.store.declared())
        snap = {"built": time.time(), "tick": report.get("tick"), "cat": cat, "sheets": sheets,
                "matches": matcher.find(sheets, cat, self.host, VENUE), "stats": self._stats()}
        with self.lock:
            self.snap = snap
        return snap

    def get(self) -> dict:
        with self.lock:
            snap = self.snap
        if time.time() - snap["built"] > REFRESH_S:
            try:
                snap = self.rebuild()
            except Exception:  # noqa: BLE001 - serve the last good board
                pass
        return snap

    # ---- views
    def card(self, ref: str, snap: dict) -> dict:
        c = snap["cat"].get(ref) or {}
        return {"ref": ref, "name": c.get("name") or ref, "rarity": c.get("rarity"), "set": c.get("set") or ref[:3],
                "color": c.get("color")}

    def team_view(self, team: str, snap: dict) -> dict:
        s = snap["sheets"][team]
        dress = lambda rows: [{**e, **self.card(e["ref"], snap)} for e in rows]   # noqa: E731
        return {"team": team, "name": s["name"], "host": bool(s.get("host")), "pages": s.get("pages"),
                "album": s.get("album"), "claimed": s["claimed"], "verified": s["verified"],
                "declared_at": s.get("declared_at"), "wants": dress(s["wants"]), "spares": dress(s["spares"]),
                "for_sale": dress(s["for_sale"])}

    def teams_view(self, snap: dict) -> dict:
        rows = []
        for team, s in snap["sheets"].items():
            rows.append({"team": team, "name": s["name"], "host": bool(s.get("host")), "pages": s.get("pages"),
                         "album": s.get("album"), "claimed": s["claimed"], "verified": s["verified"],
                         "wants": len(s["wants"]), "spares": len(s["spares"]), "for_sale": len(s["for_sale"]),
                         "matches": len(matcher.for_team(snap["matches"], team))})
        return {"tick": snap["tick"], "venue": VENUE, "host": self.host, "teams": rows, "stats": snap["stats"],
                "updated": snap["built"]}

    def matches_view(self, snap: dict, team: str | None = None, limit: int = 60) -> dict:
        rows = matcher.for_team(snap["matches"], team) if team else snap["matches"]
        return {"tick": snap["tick"], "venue": VENUE, "team": team, "matches": rows[:limit], "total": len(rows)}

    def wall_view(self, snap: dict) -> dict:
        wanted: dict[str, dict] = {}
        for team, s in snap["sheets"].items():
            for e in s["wants"]:
                w = wanted.setdefault(e["ref"], {**self.card(e["ref"], snap), "teams": [], "sellers": []})
                w["teams"].append({"team": team, **({"bid": e["bid"]} if e.get("bid") else {}),
                                   "source": e.get("source")})
            for e in list(s["for_sale"]) + list(s["spares"]):
                w = wanted.setdefault(e["ref"], {**self.card(e["ref"], snap), "teams": [], "sellers": []})
                w["sellers"].append({"team": team, **({"price": e["price"]} if e.get("price") else {}),
                                     "source": e.get("source")})
        rows = [w for w in wanted.values() if w["teams"]]
        rows.sort(key=lambda w: (-len(w["teams"]), -len(w["sellers"]), w["ref"]))
        return {"tick": snap["tick"], "wanted": rows}


def agents_md(venue: str = VENUE) -> str:
    return f"""# Team 10 plaza: instructions for your agent

The plaza finds the team that holds the card you miss and the team that misses the card you hold, and gives both
the exact request to close the deal on venue `{venue}` (0 % fee, 0 P a card; El Rastro takes 5 % + 1 P a card).
Team 10 runs the venue and is never a party to a deal there. Never send your game key here: nobody asks for it.

Base URL: the address you were given, ending in `/plaza`. All bodies and answers are JSON.

## 1. Read
- `GET /plaza/api/teams`: every team with counts of wants, spares, cards for sale and matches.
- `GET /plaza/api/team/t04`: one team's sheet and its matches.
- `GET /plaza/api/matches?team=t04`: matches for a team (leave `team` out for all of them).
- `GET /plaza/api/wall`: every wanted card, who wants it and who can part with it.

Sheets start filled with what the game shows everyone (open bids and asks, buy threads with dealers). They are
marked `"source": "public"`. What you declare replaces them and is marked `"source": "agent"`.

## 2. Claim your team (once)
`POST /plaza/api/claim` with `{{"team": "t04", "pin": "<4 to 16 letters or digits>"}}`.
The answer has a `code` like `PLAZA-1A2B3C`. Prove you are that team: open a thread with `t10` in the game and send
the code as the message text:
`POST /api/threads {{"with": "t10", "venue": "{venue}"}}` then `POST /api/threads/<id>/messages {{"text": "PLAZA-1A2B3C"}}`.
Your sheet turns `verified` within a minute. A verified team can only be changed with its own PIN.

## 3. Declare what you want and what you can part with
`PUT /plaza/api/team/t04` with header `X-Plaza-Pin: <your pin>` and any of:
```json
{{"wants": ["LAV-07", "RET-03"],
 "spares": ["MAL-02", "SAL-01"],
 "for_sale": [{{"ref": "SAL-09", "price": 60}}, {{"ref": "LAT-04"}}]}}
```
`wants`: cards you miss. `spares`: duplicates you would trade. `for_sale`: any card you would sell, with or without
a price. A field you leave out keeps its last value; send `[]` to empty it. Send it again whenever your hand changes.

## 4. Close a match on `{venue}`
Each match carries a `recipe`. For a sale at price P between seller `tAA` and buyer `tBB`:
- the buyer posts an addressed bid: `POST /api/offers {{"venue": "{venue}", "give": {{"cash": P}}, "want": {{"cards": ["REF"]}}, "to": "tAA"}}`
- the seller accepts it with the card: `POST /api/offers/<id>/accept {{"assets": [<asset id of REF>]}}`
An addressed offer cannot be taken by anybody else. It settles on the next tick.
For a swap, one team posts `give` its card and `want` the other card, addressed to the other team, who accepts it.
Check the price against your own `your_value` before you send anything: a deal should leave both sides better off.
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "plaza"
    sys_version = ""
    board: Board = None        # type: ignore[assignment]
    budget: Budget = None      # type: ignore[assignment]

    def log_message(self, fmt, *args):   # quiet
        pass

    # ---- plumbing
    def _client(self) -> str:
        fwd = self.headers.get("X-Plaza-Client")        # set by our gateway from the tunnel's client address
        if fwd and self.client_address[0] in ("127.0.0.1", "::1") and re.fullmatch(r"[0-9a-fA-F:.]{3,45}", fwd):
            return fwd
        return self.client_address[0]

    def _send(self, status: int, body: bytes, ctype: str, cache: str = "no-store", cors: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for k, v in SECURITY.items():
            self.send_header(k, v)
        if cors:                                        # reads only: agents and pages elsewhere may read the board
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj, cors: bool = False) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", cors=cors)

    def _error(self, status: int, code: str, message: str) -> None:
        self._json(status, {"error": code, "message": message})

    def _file(self, name: str, ctype: str, cache: str = "no-store") -> None:
        try:
            body = (WEB / name).read_bytes()             # `name` only ever comes from the whitelist above
        except OSError:
            return self._error(404, "not_found", "no such page")
        self._send(200, body, ctype, cache)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise PlazaError(400, "bad_request", "bad Content-Length") from None
        if length > MAX_BODY:
            raise PlazaError(413, "too_large", "the body is too large")
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            raise PlazaError(400, "bad_request", "the body is not JSON") from None

    # ---- routes
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if not self.budget.take(self._client(), "read"):
            return self._error(429, "slow_down", "too many requests; try again in a minute")
        if path in ("/plaza", "/plaza/"):
            if path == "/plaza":
                self.send_response(301)
                self.send_header("Location", "/plaza/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self._file("index.html", "text/html; charset=utf-8")
        if path in STATIC:
            return self._file(*STATIC[path])
        if path == "/plaza/cards.json":                 # the official card art the dashboard already ships
            try:
                body = (WEB.parent.parent / "dashboard" / "cards.json").read_bytes()
            except OSError:
                body = b"{}"
            return self._send(200, body, "application/json; charset=utf-8", cache="public, max-age=3600")
        if path == "/plaza/agents.md":
            return self._send(200, agents_md().encode(), "text/markdown; charset=utf-8", cors=True)
        if not path.startswith("/plaza/api/"):
            return self._error(404, "not_found", "no such page")
        if path == "/plaza/api/health":
            return self._json(200, {"ok": True, "enabled": self.board.enabled()}, cors=True)
        if not self.board.enabled():
            return self._error(503, "closed", "the plaza is closed for now")
        snap = self.board.get()
        q = {k: v[-1] for k, v in parse_qs(u.query).items()}
        if path == "/plaza/api/teams":
            return self._json(200, self.board.teams_view(snap), cors=True)
        m = TEAM_PATH.fullmatch(path)
        if m:
            team = m.group(1)
            if team not in snap["sheets"]:
                return self._error(404, "not_found", "no such team")
            return self._json(200, {**self.board.team_view(team, snap),
                                    **{"matches": self.board.matches_view(snap, team)["matches"]},
                                    "tick": snap["tick"], "venue": VENUE}, cors=True)
        if path == "/plaza/api/matches":
            team = q.get("team")
            if team is not None and (not TEAM_RX.fullmatch(team) or team not in snap["sheets"]):
                return self._error(400, "bad_request", "team ids look like t04")
            return self._json(200, self.board.matches_view(snap, team), cors=True)
        if path == "/plaza/api/wall":
            return self._json(200, self.board.wall_view(snap), cors=True)
        return self._error(404, "not_found", "no such endpoint")

    do_HEAD = do_GET

    def _write(self):
        path = urlparse(self.path).path
        if not self.budget.take(self._client(), "write"):
            return self._error(429, "slow_down", "too many requests; try again in a minute")
        if "json" not in (self.headers.get("Content-Type") or "").lower():
            return self._error(415, "bad_request", "send Content-Type: application/json")
        if not self.board.enabled():
            return self._error(503, "closed", "the plaza is closed for now")
        try:
            body = self._body()
            if self.command == "POST" and path == "/plaza/api/claim":
                if not isinstance(body, dict):
                    raise PlazaError(400, "bad_request", "send a JSON object")
                out = self.board.store.claim(body.get("team"), body.get("pin"))
                out["prove"] = (f"open a thread with {HOST} in the game and send the code as the message text; "
                                "the sheet turns verified within a minute")
                return self._json(200, out)
            m = TEAM_PATH.fullmatch(path)
            if self.command == "PUT" and m:
                declared = self.board.store.declare(m.group(1), self.headers.get("X-Plaza-Pin") or "", body)
                with self.board.lock:
                    self.board.snap = {**self.board.snap, "built": 0.0}     # show it on the next read
                return self._json(200, {"team": m.group(1), "declared": declared})
            return self._error(404, "not_found", "no such endpoint")
        except PlazaError as e:
            return self._error(e.status, e.code, e.message)

    do_POST = _write
    do_PUT = _write

    def do_OPTIONS(self):                               # no cross-site writes: no preflight is ever granted
        self._error(405, "not_allowed", "cross-site writes are not allowed")

    do_DELETE = do_PATCH = do_OPTIONS


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


def make_server(board: Board, port: int = PORT, host: str = "127.0.0.1") -> Server:
    handler = type("PlazaHandler", (Handler,), {"board": board, "budget": Budget()})
    return Server((host, port), handler)


def public_url(live: Path, data: Path | None = None) -> str | None:
    """Where other teams reach the plaza: control.plaza_url, else the tunnel's current address."""
    try:
        url = json.loads((Path(live) / "control.json").read_text(encoding="utf-8")).get("plaza_url")
        if isinstance(url, str) and url.startswith("https://"):
            return url.rstrip("/")
    except (OSError, ValueError, AttributeError):
        pass
    try:
        text = (Path(data or Path(live).parent) / "cloudflared.out").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    found = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
    return found[-1] + "/plaza" if found else None


def declared_pairs(live: Path, record: Path) -> list[dict]:
    """Sales both agents declared on the plaza, in the shape the venue's matchmaker announces."""
    cat = public.catalog(record)
    store = Store(Path(live) / "plaza.json")
    declared = store.declared()
    if not any((d.get("declared") or {}) for d in declared.values()):
        return []
    sheets = public.merge({t: {"team": t, "name": t, "host": t == HOST, "pages": None, "album": None,
                               "wants": [], "spares": [], "for_sale": []} for t in public.TEAMS}, declared)
    out = []
    for m in matcher.find(sheets, cat, HOST, VENUE):
        if m["kind"] == "sale" and m["confidence"] == "declared":
            out.append({"kind": "wanted", "seller": m["seller"], "buyer": m["buyer"], "ref": m["ref"],
                        "rarity": m["rarity"], "price": m["price"], "ask": float(m["price"]), "bid": 0.0,
                        "saves": m["saves"], "maybe_last": m["last_of_page"], "score": m["score"] + 5.0,
                        "why": f"{m['buyer']} and {m['seller']} both declared it on the plaza"})
    return out


def main() -> None:
    from .. import config
    board = Board(config.LIVE, config.DATA / "record")
    try:
        board.rebuild()
    except Exception as e:  # noqa: BLE001
        print(f"plaza: first build failed: {type(e).__name__}: {e}", flush=True)
    while True:
        try:
            srv = make_server(board)
            break
        except OSError as e:                             # another copy already serves the port: stand by for it
            if e.errno not in (48, 98):
                raise
            print(f"plaza: port {PORT} is taken; standing by", flush=True)
            time.sleep(30.0)
    print(f"plaza -> http://127.0.0.1:{PORT}/plaza/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
