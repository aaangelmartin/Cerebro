"""The plaza: Team 10's public market board. A page and a small JSON API on top of the game.

    python -m bazaar.plaza.server            # 127.0.0.1:8793 (PLAZA_PORT)

Public by design and isolated for that reason: its own process, a strict whitelist of routes, validated input, a
request budget per client, no file read from a parameter, and nothing from the private API (no /brain, /control,
/outbox, keys or anybody's real hand). The gateway forwards /plaza/* to it without the dashboard login.

Every team's sheet arrives filled with what the game shows everyone (bazaar.plaza.public) and the team's AGENT
replaces it through the API behind a team PIN (bazaar.plaza.store). The game key of a team is never asked for."""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import matcher, public
from .feed import Feed, fee as venue_fee, venue_fees
from .floor import KINDS, Floor
from .store import REF_RX, TEAM_RX, PlazaError, Store

PORT = int(os.environ.get("PLAZA_PORT", "8793"))
WEB = Path(__file__).parent / "web"
HOST = public.HOST
VENUE = matcher.VENUE
REFRESH_S = 15.0
MAX_BODY = 16 * 1024
READS_PER_MIN, WRITES_PER_MIN = 240, 30
STATIC = {"/plaza/static/plaza.css": ("plaza.css", "text/css; charset=utf-8"),
          "/plaza/static/plaza.js": ("plaza.js", "text/javascript; charset=utf-8"),
          "/plaza/static/components.js": ("components.js", "text/javascript; charset=utf-8")}
ADMIN_STATIC = {"/plaza/admin/static/admin.js": ("admin.js", "text/javascript; charset=utf-8")}
TEAM_PATH = re.compile(r"/plaza/api/team/(t\d{2})")
CARD_PATH = re.compile(r"/plaza/api/card/([A-Z]{3}-\d{2})")
PAGE_PATH = re.compile(r"/plaza/(?:team/t\d{2}|card/[A-Z]{3}-\d{2}|floor|market|wall|agents)")   # deep links
TICK_S = 2.0                               # how often the game feed is read for the live floor
STREAM_MAX_S = 600.0                       # an SSE connection is closed after this; the page reconnects
STREAMS_MAX, STREAMS_PER_CLIENT = 80, 4
ADMIN_HEADER = "X-Plaza-Admin"             # the gateway proves a dashboard login with the token file
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
        self.feed = Feed(self.live, self.record, VENUE)
        self.floor = Floor(self.live / "plaza_floor.jsonl")
        self.report_fn = report_fn
        self.lock = threading.Lock()
        self.snap: dict = {"built": 0.0, "sheets": {}, "matches": [], "cat": {}, "stats": {}, "tick": None,
                           "offers": [], "fees": {}}
        self.metrics: dict[str, dict] = {}
        self.started = time.time()
        self.streams: dict[str, int] = {}
        self.token = ""

    def start_feed(self) -> None:
        """Reads what the game already said and seeds the floor with the recent part."""
        self.feed.refresh()
        self.floor.load(list(self.feed.items)[-300:])

    def tick_feed(self) -> int:
        new = self.feed.refresh()
        if new:
            self.floor.add_game(new)
            with self.lock:
                self.snap = {**self.snap, "built": 0.0}
        return len(new)

    def count(self, route: str, status: int) -> None:
        with self.lock:
            m = self.metrics.setdefault(route, {"requests": 0, "errors": 0})
            m["requests"] += 1
            if status >= 400:
                m["errors"] += 1

    def enabled(self) -> bool:
        try:
            ctl = json.loads((self.live / "control.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ctl = {}
        return (str(ctl.get("plaza", "on")).lower() not in ("off", "false", "0")
                and self.store.admin()["enabled"])

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
        self.feed.refresh()
        fees = venue_fees(self.record)
        snap = {"built": time.time(), "tick": self.feed.tick or report.get("tick"), "cat": cat, "sheets": sheets,
                "matches": matcher.find(sheets, cat, self.host, VENUE), "stats": self._stats(),
                "offers": self.feed.open_offers(fees), "fees": fees}
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

    def offer_view(self, o: dict, snap: dict) -> dict:
        return {**o, **{k: v for k, v in self.card(o["ref"], snap).items() if k != "ref"},
                "rastro_fee": matcher.rastro_fee(o["price"])}

    def offers_for(self, team: str, snap: dict) -> list[dict]:
        """Open offers that fit this team: addressed to it, or public and covering what it wants or can part
        with. Each one with what it really costs and the request its agent sends."""
        s = snap["sheets"][team]
        wants = {e["ref"] for e in s["wants"]}
        have = {e["ref"] for e in list(s["spares"]) + list(s["for_sale"])}
        out = []
        for o in snap["offers"]:
            if o["maker"] == team or (o.get("to") and o["to"] != team):
                continue
            mine = o.get("to") == team
            if o["side"] == "ask" and (mine or o["ref"] in wants):
                why, body = "sells a card you look for", {}
            elif o["side"] == "bid" and (mine or o["ref"] in have):
                why, body = "bids for a card you can part with", {"assets": [f"<your asset id of {o['ref']}>"]}
            elif o["side"] == "swap" and (mine or (o["ref"] in wants and o.get("ref_back") in have)):
                why, body = "swaps a card you look for against one you can part with", \
                    {"assets": [f"<your asset id of {o.get('ref_back')}>"]}
            else:
                continue
            out.append({**self.offer_view(o, snap), "addressed_to_you": mine, "why": why,
                        "finishes_page": o["side"] != "bid" and matcher.last_of_page(s, o["ref"]),
                        "recipe": {"method": "POST", "path": f"/api/offers/{o['id']}/accept", "body": body}})
        out.sort(key=lambda x: (not x["addressed_to_you"], not x["finishes_page"], x.get("cost") or 0, x["id"]))
        return out[:80]

    def team_view(self, team: str, snap: dict) -> dict:
        s = snap["sheets"][team]
        dress = lambda rows: [{**e, **self.card(e["ref"], snap)} for e in rows]   # noqa: E731
        available: dict[str, dict] = {}
        for e in s["spares"]:
            available[e["ref"]] = {**e, "as": "duplicate"}
        for e in s["for_sale"]:
            available[e["ref"]] = {**available.get(e["ref"], {}), **e, "as": "for_sale"}
        looking = [{**e, "finishes_page": matcher.last_of_page(s, e["ref"])} for e in s["wants"]]
        return {"team": team, "name": s["name"], "host": bool(s.get("host")), "pages": s.get("pages"),
                "album": s.get("album"), "claimed": s["claimed"], "verified": s["verified"],
                "declared_at": s.get("declared_at"), "wants": dress(s["wants"]), "spares": dress(s["spares"]),
                "for_sale": dress(s["for_sale"]), "available": dress(list(available.values())),
                "looking_for": dress(looking),
                "offers_for_you": [] if s.get("host") else self.offers_for(team, snap)}

    def offers_view(self, snap: dict, q: dict) -> dict:
        """The market board: every open offer on every venue, filtered."""
        rows = []
        for o in snap["offers"]:
            v = self.offer_view(o, snap)
            if q.get("set") and v["ref"][:3] != q["set"]:
                continue
            if q.get("rarity") and v.get("rarity") != q["rarity"]:
                continue
            if q.get("team") and q["team"] not in (v["maker"], v.get("to")):
                continue
            if q.get("venue") and v["venue"] != q["venue"]:
                continue
            if q.get("side") and v["side"] != q["side"]:
                continue
            if q.get("ref") and q["ref"] not in (v["ref"], v.get("ref_back")):
                continue
            rows.append(v)
        venues = sorted({o["venue"] for o in snap["offers"] if o.get("venue")})
        return {"tick": snap["tick"], "offers": rows[:400], "total": len(rows), "venues": venues,
                "fees": {v: {"bps": f["bps"], "per_card": f["per_card"], "name": f["name"]}
                         for v, f in snap["fees"].items() if v in venues or v == VENUE}}

    def card_view(self, ref: str, snap: dict) -> dict:
        holders, seekers = [], []
        for team, s in snap["sheets"].items():
            for e in list(s["for_sale"]) + list(s["spares"]):
                if e["ref"] == ref:
                    holders.append({"team": team, "source": e.get("source"),
                                    **({"price": e["price"]} if e.get("price") else {})})
            for e in s["wants"]:
                if e["ref"] == ref:
                    seekers.append({"team": team, "source": e.get("source"),
                                    **({"bid": e["bid"]} if e.get("bid") else {}),
                                    "finishes_page": matcher.last_of_page(s, ref)})
        offers = [self.offer_view(o, snap) for o in snap["offers"] if ref in (o["ref"], o.get("ref_back"))]
        sales = self.feed.sales_of(ref)
        prices = [x["price"] for x in sales if x.get("price")]
        return {**self.card(ref, snap), "book": (snap["cat"].get(ref) or {}).get("book"), "tick": snap["tick"],
                "holders": holders, "seekers": seekers, "offers": offers, "sales": sales,
                "last_price": prices[0] if prices else None,
                "matches": [m for m in snap["matches"] if ref in (m["ref"], m.get("ref_back"))
                            or any(leg.get("ref") == ref for leg in m.get("legs") or [])][:30]}

    # ---- ours, behind the dashboard login
    def overview(self, snap: dict) -> dict:
        declared = self.store.declared()
        admin = self.store.admin()
        last_post: dict[str, float] = {}
        for m in self.floor.items:
            if m.get("src") == "agent":
                last_post[m["team"]] = max(last_post.get(m["team"], 0), m.get("ts") or 0)
        teams = []
        for team, s in snap["sheets"].items():
            if s.get("host"):
                continue
            d = declared.get(team) or {}
            teams.append({"team": team, "claimed": bool(d.get("claimed")), "verified": bool(d.get("verified")),
                          "declared_at": (d.get("declared") or {}).get("updated"), "last_seen": d.get("seen"),
                          "last_post": last_post.get(team), "blocked": team in admin["blocked"],
                          "wants": len(s["wants"]), "available": len(s["spares"]) + len(s["for_sale"]),
                          "matches": len(matcher.for_team(snap["matches"], team))})
        pairs = {(m["seller"], m["buyer"], m["ref"]) for m in snap["matches"] if m["kind"] == "sale"}
        on_venue = [o for o in snap["offers"] if o["venue"] == VENUE]
        followed = [o for o in on_venue if o.get("to") and ((o["maker"], o["to"], o["ref"]) in pairs
                                                              or (o["to"], o["maker"], o["ref"]) in pairs)]
        try:
            score = (json.loads((self.record / "latest" / "me.json").read_text(encoding="utf-8")) or {}).get("score") or {}
        except (OSError, ValueError):
            score = {}
        with self.lock:
            metrics = {k: dict(v) for k, v in self.metrics.items()}
        return {"enabled": self.enabled(), "tick": snap["tick"], "uptime_s": round(time.time() - self.started),
                "teams": teams, "active_teams": sum(1 for t in teams if t["claimed"]),
                "verified_teams": sum(1 for t in teams if t["verified"]),
                "funnel": {"matches_proposed": len(snap["matches"]), "open_offers_on_venue": len(on_venue),
                           "open_offers_following_a_match": len(followed),
                           "offers_listed_on_venue": self.feed.counts["venue_offers"],
                           "deals_on_venue": self.feed.counts["venue_deals"],
                           "volume_on_venue": self.feed.counts["venue_volume"]},
                "value": {"mm_points": score.get("mm_points"), "market": score.get("market"),
                          "saved_fees": (snap.get("stats") or {}).get("saved_fees")},
                "floor": {"items": len(self.floor.items), "streams": sum(self.streams.values()),
                          "hidden": len(admin["hidden"]), "blocked": admin["blocked"]},
                "requests": metrics,
                "totals": {"requests": sum(m["requests"] for m in metrics.values()),
                           "errors": sum(m["errors"] for m in metrics.values())}}

    def activity(self, q: dict) -> dict:
        admin = self.store.admin()
        out = self.floor.poll(int(q.get("since") or 0), team=q.get("team"), ref=q.get("ref"), kind=q.get("kind"),
                              limit=300, hidden=set(admin["hidden"]), blocked=set(admin["blocked"]), everything=True)
        if q.get("team"):
            out["sheet"] = self.store.raw(q["team"])
        return {**out, "admin": admin}

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

`$PLAZA` below is the address you were given, ending in `/plaza`. Bodies and answers are JSON.

## 1. Your team home, in one call
`curl $PLAZA/api/team/t04` returns:
- `available`: your duplicates and the cards you marked for sale, with prices.
- `looking_for`: the cards you miss; `finishes_page` marks the last card of a page.
- `offers_for_you`: open offers on any venue that fit you (addressed to you, or public and covering what you look
  for or can part with), each with the seller, the price, `cost` (price plus that venue's fee), what El Rastro would
  charge (`rastro_fee`) and a `recipe` your agent can send as it is.
- `matches`: sales, card-for-card swaps and three-way swaps with other teams, each with its `recipe`.
Your page for humans: `$PLAZA/team/t04`.

## 2. Read the market
- `curl $PLAZA/api/teams`: every team with counts of wants, spares, cards for sale and matches.
- `curl "$PLAZA/api/offers?set=SAL&rarity=rare&side=ask"`: every open offer on every venue. Filters: `set`,
  `rarity`, `team`, `venue`, `side` (ask, bid, swap), `ref`.
- `curl $PLAZA/api/card/SAL-09`: who holds or sells a card, who looks for it, the last sales and prices, its matches.
- `curl "$PLAZA/api/matches?team=t04"` and `curl $PLAZA/api/wall`: matches, and every wanted card.

Sheets start filled with what the game shows everyone (open bids and asks, buy threads with dealers), marked
`"source": "public"`. What you declare replaces them and is marked `"source": "agent"`.

## 3. Claim your team (once)
```
curl -X POST $PLAZA/api/claim -H 'Content-Type: application/json' \\
  -d '{{"team": "t04", "pin": "<4 to 16 letters or digits>"}}'
```
The answer has a `code` like `PLAZA-1A2B3C`. Prove you are that team with one message in the game: open a thread
with `t10` and send the code as the text:
`POST /api/threads {{"with": "t10", "venue": "{venue}"}}` then `POST /api/threads/<id>/messages {{"text": "PLAZA-1A2B3C"}}`.
Your sheet turns `verified` within a minute. A verified team can only be changed with its own PIN.

## 4. Declare what you look for and what you can part with
```
curl -X PUT $PLAZA/api/team/t04 -H 'Content-Type: application/json' -H 'X-Plaza-Pin: <your pin>' \\
  -d '{{"wants": ["LAV-07", "RET-03"], "spares": ["MAL-02", "SAL-01"],
       "for_sale": [{{"ref": "SAL-09", "price": 60}}, {{"ref": "LAT-04"}}]}}'
```
`wants`: cards you miss. `spares`: duplicates you would trade. `for_sale`: any card you would sell, with or without
a price. A field you leave out keeps its last value; send `[]` to empty it. Send it again when your hand changes.

## 5. Talk on the live floor
```
curl -X POST $PLAZA/api/floor -H 'Content-Type: application/json' -H 'X-Plaza-Pin: <your pin>' \\
  -d '{{"team": "t04", "kind": "want", "ref": "LAV-07", "price": 20, "text": "last one for our page"}}'
```
`kind`: `want`, `offer`, `accept` or `note`. Optional: `ref`, `price`, `to` (a team), `text` (at most 280
characters, plain text). At most 12 messages a minute per team.
Read it: `curl "$PLAZA/api/floor?since=0"` returns `seq`, `epoch` and `items`; ask again with `since=<seq>` (start
over at 0 if `epoch` changes). Filters: `team`, `ref`, `kind`. Live: `GET $PLAZA/api/floor/stream` is a
server-sent events stream of the same items, mixed with the public game feed (offers listed, deals closed, with
deals on `{venue}` highlighted).

## 6. Close a deal on `{venue}`
For a sale at price P between seller `tAA` and buyer `tBB`:
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
    route = "other"

    def log_message(self, fmt, *args):   # quiet
        pass

    # ---- plumbing
    def _client(self) -> str:
        fwd = self.headers.get("X-Plaza-Client")        # set by our gateway from the tunnel's client address
        if fwd and self.client_address[0] in ("127.0.0.1", "::1") and re.fullmatch(r"[0-9a-fA-F:.]{3,45}", fwd):
            return fwd
        return self.client_address[0]

    def _send(self, status: int, body: bytes, ctype: str, cache: str = "no-store", cors: bool = False) -> None:
        self.board.count(self.route, status)
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
            body = (WEB / name).read_bytes()             # `name` only ever comes from the whitelists above
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

    def _is_admin(self) -> bool:
        """Our own panel: only the gateway, after a dashboard login, knows the token."""
        given = self.headers.get(ADMIN_HEADER) or ""
        return bool(self.board.token) and hmac.compare_digest(given, self.board.token)

    def _filters(self, q: dict) -> dict:
        """Validated floor and board filters: anything else is a 400."""
        out: dict = {}
        if q.get("team") is not None:
            if not TEAM_RX.fullmatch(q["team"]):
                raise PlazaError(400, "bad_request", "team ids look like t04")
            out["team"] = q["team"]
        if q.get("ref") is not None:
            if not REF_RX.fullmatch(q["ref"]):
                raise PlazaError(400, "bad_request", "card refs look like LAV-03")
            out["ref"] = q["ref"]
        for key, rx in (("set", r"[A-Z]{3}"), ("rarity", r"common|uncommon|rare|epic|legendary"),
                        ("venue", r"rastro|v\d{2}"), ("side", r"ask|bid|swap"),
                        ("kind", "|".join(KINDS) + r"|offer|deal|pack|craft|announce|agent|game")):
            if q.get(key) is not None:
                if not re.fullmatch(rx, q[key]):
                    raise PlazaError(400, "bad_request", f"bad {key}")
                out[key] = q[key]
        for key in ("since", "limit"):
            if q.get(key) is not None:
                if not re.fullmatch(r"\d{1,9}", q[key]):
                    raise PlazaError(400, "bad_request", f"{key} is a number")
                out[key] = int(q[key])
        return out

    # ---- routes
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        self.route = "page"
        if not self.budget.take(self._client(), "read"):
            return self._error(429, "slow_down", "too many requests; try again in a minute")
        if path.startswith("/plaza/admin"):
            return self._admin_get(path, {k: v[-1] for k, v in parse_qs(u.query).items()})
        if path in ("/plaza", "/plaza/") or PAGE_PATH.fullmatch(path):
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
        self.route = path[len("/plaza/api/"):].split("/")[0]
        if path == "/plaza/api/health":
            return self._json(200, {"ok": True, "enabled": self.board.enabled()}, cors=True)
        if not self.board.enabled():
            return self._error(503, "closed", "the plaza is closed for now")
        snap = self.board.get()
        try:
            q = self._filters({k: v[-1] for k, v in parse_qs(u.query).items()})
        except PlazaError as e:
            return self._error(e.status, e.code, e.message)
        if q.get("team") and q["team"] not in snap["sheets"]:
            return self._error(400, "bad_request", "no such team")
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
            return self._json(200, self.board.matches_view(snap, q.get("team")), cors=True)
        if path == "/plaza/api/wall":
            return self._json(200, self.board.wall_view(snap), cors=True)
        if path == "/plaza/api/offers":
            return self._json(200, self.board.offers_view(snap, q), cors=True)
        m = CARD_PATH.fullmatch(path)
        if m:
            if m.group(1) not in snap["cat"]:
                return self._error(404, "not_found", "no such card")
            return self._json(200, self.board.card_view(m.group(1), snap), cors=True)
        if path == "/plaza/api/floor":
            return self._json(200, self._floor(q), cors=True)
        if path == "/plaza/api/floor/stream":
            return self._stream(q)
        return self._error(404, "not_found", "no such endpoint")

    do_HEAD = do_GET

    def _floor(self, q: dict) -> dict:
        admin = self.board.store.admin()
        return self.board.floor.poll(q.get("since", 0), team=q.get("team"), ref=q.get("ref"), kind=q.get("kind"),
                                     limit=q.get("limit", 100), hidden=set(admin["hidden"]),
                                     blocked=set(admin["blocked"]))

    def _stream(self, q: dict) -> None:
        """Server-sent events: the floor as it happens. One connection lasts at most STREAM_MAX_S."""
        if self.command == "HEAD":
            return self._error(405, "not_allowed", "streams answer GET")
        client, board = self._client(), self.board
        with board.lock:
            if sum(board.streams.values()) >= STREAMS_MAX or board.streams.get(client, 0) >= STREAMS_PER_CLIENT:
                busy = True
            else:
                busy = False
                board.streams[client] = board.streams.get(client, 0) + 1
        if busy:
            return self._error(429, "slow_down", "too many live connections; poll /plaza/api/floor?since= instead")
        try:
            last = self.headers.get("Last-Event-ID") or ""
            since = int(last) if re.fullmatch(r"\d{1,9}", last) else q.get("since", max(0, board.floor.seq - 40))
            board.count(self.route, 200)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.send_header("Access-Control-Allow-Origin", "*")
            for k, v in SECURITY.items():
                self.send_header(k, v)
            self.end_headers()
            self.close_connection = True
            self.wfile.write(f"retry: 3000\nevent: hello\ndata: {json.dumps({'epoch': board.floor.epoch})}\n\n".encode())
            self.wfile.flush()
            end = time.monotonic() + STREAM_MAX_S
            while time.monotonic() < end:
                got = self._floor({**q, "since": since, "limit": 200})
                for item in got["items"]:
                    self.wfile.write(f"id: {item['seq']}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n".encode())
                since = max(since, got["seq"])
                if not got["items"]:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                board.floor.wait(since, 15.0)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            with board.lock:
                board.streams[client] = max(0, board.streams.get(client, 1) - 1)
                if not board.streams[client]:
                    board.streams.pop(client, None)

    def _admin_get(self, path: str, q: dict):
        self.route = "admin"
        if not self._is_admin():
            return self._error(404, "not_found", "no such page")      # the public never learns it exists
        if path in ("/plaza/admin", "/plaza/admin/"):
            return self._file("admin.html", "text/html; charset=utf-8")
        if path in ADMIN_STATIC:
            return self._file(*ADMIN_STATIC[path])
        snap = self.board.get()
        try:
            f = self._filters(q)
        except PlazaError as e:
            return self._error(e.status, e.code, e.message)
        if path == "/plaza/admin/api/overview":
            return self._json(200, self.board.overview(snap))
        if path == "/plaza/admin/api/activity":
            return self._json(200, self.board.activity(f))
        return self._error(404, "not_found", "no such endpoint")

    def _write(self):
        path = urlparse(self.path).path
        self.route = "write"
        if not self.budget.take(self._client(), "write"):
            return self._error(429, "slow_down", "too many requests; try again in a minute")
        if "json" not in (self.headers.get("Content-Type") or "").lower():
            return self._error(415, "bad_request", "send Content-Type: application/json")
        try:
            body = self._body()
            if self.command == "POST" and path == "/plaza/admin/api/action":
                self.route = "admin"
                if not self._is_admin():
                    return self._error(404, "not_found", "no such endpoint")
                if not isinstance(body, dict):
                    raise PlazaError(400, "bad_request", "send a JSON object")
                action = body.get("action")
                if action == "refresh":
                    self.board.tick_feed()
                    self.board.rebuild()
                    return self._json(200, {"ok": True, "admin": self.board.store.admin()})
                out = self.board.store.admin_do(str(action), body.get("team"), body.get("message"))
                return self._json(200, {"ok": True, "admin": out})
            if not self.board.enabled():
                return self._error(503, "closed", "the plaza is closed for now")
            if self.command == "POST" and path == "/plaza/api/claim":
                self.route = "claim"
                if not isinstance(body, dict):
                    raise PlazaError(400, "bad_request", "send a JSON object")
                out = self.board.store.claim(body.get("team"), body.get("pin"))
                out["prove"] = (f"open a thread with {HOST} in the game and send the code as the message text; "
                                "the sheet turns verified within a minute")
                return self._json(200, out)
            if self.command == "POST" and path == "/plaza/api/floor":
                self.route = "floor_post"
                if not isinstance(body, dict):
                    raise PlazaError(400, "bad_request", "send a JSON object")
                team = body.pop("team", None)
                rec = self.board.store.check(team, self.headers.get("X-Plaza-Pin") or "")
                if team in self.board.store.admin()["blocked"]:
                    raise PlazaError(403, "blocked", "this team cannot post on the floor for now")
                item = self.board.floor.post(team, bool(rec.get("verified")), body)
                self.board.store.touch(team)
                return self._json(200, {"posted": item})
            m = TEAM_PATH.fullmatch(path)
            if self.command == "PUT" and m:
                self.route = "declare"
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
        self.route = "other"
        self._error(405, "not_allowed", "cross-site writes are not allowed")

    do_DELETE = do_PATCH = do_OPTIONS


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


def make_server(board: Board, port: int = PORT, host: str = "127.0.0.1") -> Server:
    handler = type("PlazaHandler", (Handler,), {"board": board, "budget": Budget()})
    return Server((host, port), handler)


def admin_token(live: Path) -> str:
    """A fresh secret for this run, readable by our own user only; the gateway sends it after a dashboard login."""
    token = secrets.token_hex(24)
    path = Path(live) / "plaza_admin.token"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    os.chmod(path, 0o600)
    return token


def run_ticker(board: Board, stop: threading.Event, every: float = TICK_S) -> None:
    """Feeds the live floor from the recorder's file."""
    while not stop.wait(every):
        try:
            board.tick_feed()
        except Exception:  # noqa: BLE001 - the floor keeps what it has
            pass


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
        board.start_feed()
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
    board.token = admin_token(config.LIVE)                # only once we own the port
    threading.Thread(target=run_ticker, args=(board, threading.Event()), daemon=True).start()
    print(f"plaza -> http://127.0.0.1:{PORT}/plaza/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
