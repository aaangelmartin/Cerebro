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

from . import admin_api, connect as connect_mod, deals as deals_mod, deals_api, matcher, private, public, routes, team_api
from .agentq import AgentQ
from .agentsdoc import agents_md
from .connect import COOKIE, Connect
from .deals import Deals
from .feed import Feed, fee as venue_fee, venue_fees
from .floor import KINDS, Floor
from .store import REF_RX, TEAM_RX, PlazaError, Store

PORT = int(os.environ.get("PLAZA_PORT", "8793"))
NAME = os.environ.get("PLAZA_NAME", "v07 Market")               # the product's visible name: a setting, not a constant
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
# Everything else the page loads: one flat level of folders, lower-case names, three kinds of file.
TYPES = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8",
         "json": "application/json; charset=utf-8"}
STATIC_RX = re.compile(r"/plaza/static/((?:(?:screens|i18n|fixtures|fixtures/admin)/)?[a-z0-9_]{1,40}\.(js|css|json))")
ADMIN_STATIC_RX = re.compile(r"/plaza/admin/static/screens/([a-z0-9_]{1,40}\.(js|css))")     # web/admin/<name>
ADMIN_PAGE = re.compile(r"/plaza/admin/(?:overview|performance|matchmaker|trades|teams|activity|suggestions|venue|docs)")
EXTENSIONS = (team_api, deals_api)         # each fork's routes: get(h, path, q, snap), write(h, method, path, body)
TEAM_PATH = re.compile(r"/plaza/api/team/(t\d{2})")
CARD_PATH = re.compile(r"/plaza/api/card/([A-Z]{3}-\d{2})")
ART_PATH = re.compile(r"/plaza/art/([A-Z]{3}-\d{2})\.svg")
MATCH_PATH = re.compile(r"/plaza/api/match/(m-[0-9a-f]{10})")
ME_CARD_PATH = re.compile(r"/plaza/api/me/card/([A-Z]{3}-\d{2})")
ME_TRADE_PATH = re.compile(r"/plaza/api/me/trade/(m-[0-9a-f]{10})")
MATCH_MSG_PATH = re.compile(r"/plaza/api/match/(m-[0-9a-f]{10})/message")
PAGE_PATH = re.compile(r"/plaza/(?:team/t\d{2}|card/[A-Z]{3}-\d{2}|match/m-[0-9a-f]{10}|floor|market|wall|agents"
                       r"|connect|me|how|home|activity|offers|offers/m-[0-9a-f]{10}|cards|settings|suggest|docs|_kit)")                                                              # deep links
TOKEN_HEADER = "X-Plaza-Token"             # an agent's token from the connection flow (the PIN is the manual way)
LOCAL_BASE = "http://127.0.0.1:8787/plaza"
VERIFY_EVERY_S = 3.0
HOURS_KEPT = 72
PROPOSED_ON_FLOOR = 8                      # a rebuild that proposes more than this does not flood the floor
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

    def __init__(self, live: Path, record: Path, report_fn=None, host: str = HOST, private_dir: Path | None = None):
        self.live, self.record, self.host = Path(live), Path(record), host
        self.store = Store(self.live / "plaza.json", host=host)
        self.feed = Feed(self.live, self.record, VENUE)
        self.floor = Floor(self.live / "plaza_floor.jsonl")
        self.report_fn = report_fn
        self.lock = threading.Lock()
        self.feed_lock = threading.Lock()
        self.snap: dict = {"built": 0.0, "sheets": {}, "matches": [], "cat": {}, "stats": {}, "tick": None,
                           "offers": [], "fees": {}, "art": set(), "hidden": (set(), set()), "candidates": 0}
        self.metrics: dict[str, dict] = {}
        self.started = time.time()
        self.streams: dict[str, int] = {}
        self.token = ""
        self.connect = Connect(self.live / "plaza_connect.json", host=host)
        self.deals = Deals(self.live / "plaza_matches.json", VENUE)
        self.vault = private.Vault(private_dir or self.live.parent / "plaza_private")
        self.queue = AgentQ(self.live / "plaza_agentq.json")
        self.hourly: dict[str, dict] = self._load_hours()
        self.verified_at = 0.0
        self.art: tuple[float, dict] = (0.0, {})
        for ext in (team_api, deals_api, admin_api):          # a fork hangs its own stores on the board here:
            if hasattr(ext, "attach"):                        # board.team_activity, board.suggest, board.perf
                ext.attach(self)

    # ---- hourly counters for our panel
    def _load_hours(self) -> dict:
        try:
            data = json.loads((self.live / "plaza_hourly.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def hour(self, name: str, n: int = 1) -> None:
        key = time.strftime("%Y-%m-%dT%H")
        with self.lock:
            h = self.hourly.setdefault(key, {})
            h[name] = h.get(name, 0) + n
            if len(self.hourly) > HOURS_KEPT:
                for k in sorted(self.hourly)[:-HOURS_KEPT]:
                    self.hourly.pop(k, None)

    def save_hours(self) -> None:
        with self.lock:
            body = json.dumps(self.hourly)
        try:
            tmp = self.live / "plaza_hourly.tmp"
            tmp.write_text(body, encoding="utf-8")
            os.replace(tmp, self.live / "plaza_hourly.json")
        except OSError:
            pass

    def card_art(self) -> dict:
        """ref -> the SVG the dashboard already draws for that card."""
        path = WEB.parent.parent / "dashboard" / "cards.json"
        try:
            mtime = path.stat().st_mtime
            if mtime != self.art[0]:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.art = (mtime, {k: v for k, v in data.items() if isinstance(v, str) and v.startswith("<svg")})
        except (OSError, ValueError):
            pass
        return self.art[1]

    def start_feed(self) -> None:
        """Reads what the game already said and seeds the floor with the recent part."""
        self.feed.refresh()
        self.floor.load(list(self.feed.items)[-300:])

    def tick_feed(self) -> int:
        with self.feed_lock:
            new = self.feed.refresh()
            self.floor.add_game(new)
        if new:
            self.stale()
        return len(new)

    def count(self, route: str, status: int) -> None:
        with self.lock:
            m = self.metrics.setdefault(route, {"requests": 0, "errors": 0})
            m["requests"] += 1
            if status >= 400:
                m["errors"] += 1
        self.hour("requests")
        if status >= 400:
            self.hour("errors")

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
        sessions = self.connect.pending_codes()
        self.verified_at = time.time()
        if not codes and not sessions:
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
                    if not isinstance(m.get("text"), str):
                        continue
                    if sender in codes:
                        self.store.verify(sender, m["text"])
                    if sender in sessions and self.connect.prove(sender, m["text"]):
                        self.store.mark_verified(sender)
                        self.hour("verified")
                        self.stale()

    def verify_soon(self) -> None:
        """The Ready button is waiting: look at the recorded threads now, a few seconds apart at most."""
        if time.time() - self.verified_at > VERIFY_EVERY_S:
            try:
                self._verify()
            except Exception:  # noqa: BLE001
                pass

    def rebuild(self) -> dict:
        report = self._report()
        cat = public.catalog(self.record)
        try:
            self._verify()
        except Exception:  # noqa: BLE001 - verification never takes the board down
            pass
        declared = self.store.declared()
        for team, c in self.connect.overview().items():        # a connected agent counts as a claimed sheet
            d = declared.setdefault(team, {"declared": None, "claimed": False, "verified": False, "seen": None})
            d["claimed"] = d["claimed"] or c["agent"]
        sheets = public.merge(public.public_sheets(report, cat, self.host), declared)
        with self.feed_lock:
            self.floor.add_game(self.feed.refresh())
        fees = venue_fees(self.record)
        tick = self.feed.tick or report.get("tick")
        admin = self.store.admin()
        if hasattr(deals_api, "candidates") and hasattr(deals_api, "sync"):     # the deals fork's own rules
            cands = deals_api.candidates(self, sheets, cat)
            events = deals_api.sync(self, cands, tick, admin)
        else:
            cands = matcher.find(sheets, cat, self.host, VENUE, gate=self.vault.gate)
            events = self.deals.sync(cands, tick, self.feed.venue_log, paused=admin["mm_paused"],
                                     excluded_matches=frozenset(admin["excluded_matches"]))
        proposed = [e for e in events if e.get("state") == "proposed"]
        for e in events:
            self.hour("match_" + str(e.get("state") or e.get("kind") or "event"))
        self.floor.add_game([e for e in events if e.get("state") != "proposed"]
                            + (proposed if len(proposed) <= PROPOSED_ON_FLOOR else []))
        hidden = set(admin["hidden_msgs"]), set(admin["blocked"])
        snap = {"built": time.time(), "tick": tick, "cat": cat, "sheets": sheets, "candidates": len(cands),
                "art": set(self.card_art()), "hidden": hidden,
                "matches": [self.match_view(r, hidden) for r in self.deals.live()], "stats": self._stats(),
                "offers": self.feed.open_offers(fees), "fees": fees}
        with self.lock:
            self.snap = snap
        self.save_hours()
        return snap

    def stale(self) -> None:
        with self.lock:
            self.snap = {**self.snap, "built": 0.0}

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
                "color": c.get("color"), "art": f"/plaza/art/{ref}.svg" if ref in snap.get("art", ()) else None}

    # ---- matches and their threads
    def match_view(self, r: dict, hidden: tuple[set, set], full: bool = False) -> dict:
        """A match as everyone reads it: its state, the terms on the table and the request that closes it."""
        out = {k: v for k, v in r.items() if k not in ("messages", "history", "basis")}   # how the price was
        out["venue"] = VENUE                                                               # reached stays with us
        if r["kind"] == "sale":
            out["recipe"] = matcher.recipe(r["seller"], r["buyer"], r["ref"], r["price"], VENUE)
            out["rastro_fee"] = matcher.rastro_fee(r["price"])
        elif r["kind"] == "swap":
            out["recipe"] = matcher.swap_recipe(r["seller"], r["buyer"], r["ref"], r["ref_back"], VENUE)
        else:
            out["recipe"] = {"note": f"three card-for-card offers on {VENUE}, each addressed to the next team; "
                                     "no cash, no fee"}
        msgs = [m for m in r.get("messages") or []
                if f"{r['id']}:{m['n']}" not in hidden[0] and m["team"] not in hidden[1]]
        out["messages"], out["last_message"] = len(msgs), (msgs[-1] if msgs else None)
        out["teams"] = deals_mod.parties(r)
        if full:
            out["thread"], out["history"] = msgs, r.get("history") or []
        return out

    def trade_view(self, m: dict, snap: dict) -> dict:
        """The same match, drawn: the cards each side puts on the table."""
        card = lambda ref: self.card(ref, snap)   # noqa: E731
        if m["kind"] == "sale":
            sides = [{"team": m["seller"], "gives": [card(m["ref"])], "receives_cash": m["price"]},
                     {"team": m["buyer"], "gives": [], "pays": m["price"]}]
        elif m["kind"] == "swap":
            sides = [{"team": m["seller"], "gives": [card(m["ref"])]}, {"team": m["buyer"], "gives": [card(m["ref_back"])]}]
        else:
            sides = [{"team": leg["from"], "to": leg["to"], "gives": [card(leg["ref"])]} for leg in m.get("legs") or []]
        return {**m, "sides": sides, "name": self.card(m["ref"], snap)["name"]}

    def trades_for(self, team: str, snap: dict) -> list[dict]:
        return [self.trade_view(m, snap) for m in matcher.for_team(snap["matches"], team)]

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
        wanted = dress(looking)
        return {"team": team, "name": s["name"], "host": bool(s.get("host")), "pages": s.get("pages"),
                "album": s.get("album"), "claimed": s["claimed"], "verified": s["verified"],
                "declared_at": s.get("declared_at"), "wants": dress(s["wants"]), "spares": dress(s["spares"]),
                "for_sale": dress(s["for_sale"]), "available": dress(list(available.values())),
                "wanted": wanted, "looking_for": wanted,
                "agent_online": self.connect.online(team),
                "trades": self.trades_for(team, snap),
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
                **({"trades": self.trades_for(q["team"], snap)} if q.get("team") else {}),
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
        conn = self.connect.overview()
        for team, s in snap["sheets"].items():
            if s.get("host"):
                continue
            d = declared.get(team) or {}
            c = conn.get(team) or {}
            teams.append({"team": team, "claimed": bool(d.get("claimed")), "verified": bool(d.get("verified")),
                          "connected": bool(c.get("connected")), "agent": bool(c.get("agent")),
                          "online": bool(c.get("online")), "agent_last_seen": c.get("agent_last_seen"),
                          "pending_sessions": c.get("pending", 0),
                          "limits_set": bool(self.vault.flags(team)),
                          "last_sync": (d.get("declared") or {}).get("updated"),
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
                "teams": teams, "active_teams": sum(1 for t in teams if t["claimed"] or t["agent"]),
                "verified_teams": sum(1 for t in teams if t["verified"]),
                "connected_teams": sum(1 for t in teams if t["connected"]),
                "online_teams": sum(1 for t in teams if t["online"]),
                "match_funnel": self.deals.funnel(), "hourly": self.hours(),
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

    def agent_next(self, team: str, snap: dict) -> dict:
        """The team's agent asks what to do next."""
        mine = matcher.for_team(snap["matches"], team)
        declared = ((self.store.declared().get(team) or {}).get("declared") or {}).get("updated")
        return self.queue.build(team, mine, lambda ref, role, price: self.vault.within(team, ref, role, price),
                                declared, snap["tick"])

    def hours(self, last: int = 24) -> list[dict]:
        with self.lock:
            return [{"hour": k, **self.hourly[k]} for k in sorted(self.hourly)[-last:]]

    def matchmaker(self, snap: dict) -> dict:
        admin = self.store.admin()
        q = self.deals.queue()
        for row in q["queue"]:                                 # yes or no, never the limits themselves
            row["overlap"] = None if row["kind"] != "sale" else \
                self.vault.gate(row["seller"], row["buyer"], row["ref"], row["price"] or 0)[1]
        return {**q, "paused": admin["mm_paused"],
                "excluded_matches": admin["excluded_matches"], "candidates": snap.get("candidates", 0),
                "rules": {"proposal_ticks": deals_mod.PROPOSAL_TICKS, "offer_ticks": deals_mod.OFFER_TICKS,
                          "pass_ticks": deals_mod.PASS_TICKS, "stall_ticks": deals_mod.STALL_TICKS}}

    def force(self, body: dict, snap: dict) -> dict:
        """We propose a sale by hand; it still never involves us and never goes under the floor."""
        seller, buyer, ref = body.get("seller"), body.get("buyer"), body.get("ref")
        for t in (seller, buyer):
            if not isinstance(t, str) or t not in snap["sheets"] or t == self.host:
                raise PlazaError(400, "bad_request", "seller and buyer are two other teams")
        if seller == buyer or not isinstance(ref, str) or ref not in snap["cat"]:
            raise PlazaError(400, "bad_request", "name two different teams and a card of the catalog")
        card = snap["cat"][ref]
        price = body.get("price", card.get("book") or matcher.BOOK.get(card.get("rarity") or "", 0))
        if isinstance(price, bool) or not isinstance(price, (int, float)) \
                or price < matcher.FLOOR.get(card.get("rarity") or "", 1) or price > 2000:
            raise PlazaError(400, "below_floor", "the price is a number at or above the floor of the rarity")
        price = int(round(price))
        m = {"kind": "sale", "seller": seller, "buyer": buyer, "ref": ref, "name": card.get("name"),
             "rarity": card.get("rarity"), "price": price, "basis": "forced", "saves": matcher.rastro_fee(price),
             "last_of_page": False, "priority": 0, "confidence": "forced", "score": 99.0,
             "why": "proposed by the venue"}
        m["id"] = matcher.match_id(m)
        return self.deals.force(m)

    def activity(self, q: dict) -> dict:
        admin = self.store.admin()
        out = self.floor.poll(int(q.get("since") or 0), team=q.get("team"), ref=q.get("ref"), kind=q.get("kind"),
                              limit=300, hidden=set(admin["hidden"]), blocked=set(admin["blocked"]), everything=True)
        if q.get("team"):
            out["sheet"] = self.store.raw(q["team"])
            out["limits_set"] = sorted(self.vault.flags(q["team"]))       # which cards, never how much
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


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "plaza"
    sys_version = ""
    board: Board = None        # type: ignore[assignment]
    budget: Budget = None      # type: ignore[assignment]
    route = "other"
    extra: tuple = ()

    def log_message(self, fmt, *args):   # quiet
        pass

    # ---- plumbing
    def _client(self) -> str:
        local = self.client_address[0] in ("127.0.0.1", "::1")
        cf = self.headers.get("CF-Connecting-IP")       # a tunnel straight to this process: Cloudflare sets it
        if cf and local and re.fullmatch(r"[0-9a-fA-F:.]{3,45}", cf):
            return cf
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
        for k, v in self.extra:
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
        if self.headers.get("CF-Connecting-IP") or self.headers.get("CF-Ray"):
            return False                                # never through the public hostname: the dashboard only
        return bool(self.board.token) and hmac.compare_digest(given, self.board.token)

    def _actor(self, team: str | None = None) -> tuple[str, bool, bool]:
        """Who writes: (team, verified, by token). An agent token from the connection flow, or the team PIN."""
        token = self.headers.get(TOKEN_HEADER)
        if token:
            who, verified = self.board.connect.auth(token)
            if team is not None and team != who:
                raise PlazaError(403, "wrong_team", "this token writes for another team")
            return who, verified, True
        rec = self.board.store.check(team, self.headers.get("X-Plaza-Pin") or "")
        return team, bool(rec.get("verified")), False

    def _session(self, q: dict) -> str | None:
        """The browser's connection session: the query parameter, else the cookie."""
        if q.get("session"):
            return q["session"]
        m = re.search(rf"(?:^|;\s*){COOKIE}=([A-Za-z0-9_-]{{20,64}})(?:;|$)", self.headers.get("Cookie") or "")
        return m.group(1) if m else None

    def me_team(self, q: dict | None = None) -> str:
        """The team that asks about itself: its agent's token, else its connected browser session."""
        if self.headers.get(TOKEN_HEADER):
            return self.board.connect.auth(self.headers.get(TOKEN_HEADER))[0]
        if q is None:
            q = self._filters({k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()})
        st = self._status(q)
        if not st["verified"]:
            raise PlazaError(403, "not_connected", "finish connecting first: " + ", ".join(st["missing"]))
        return st["team"]

    def _status(self, q: dict) -> dict:
        board = self.board
        board.verify_soon()

        def listed(team: str) -> bool:
            d = (board.store.declared().get(team) or {}).get("declared") or {}
            return any(d.get(k) for k in ("wants", "spares", "for_sale"))
        return board.connect.status(self._session(q), listed)

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
                        ("kind", "|".join(KINDS) + r"|offer|deal|pack|craft|announce|agent|game|match|counter|pass|plaza")):
            if q.get(key) is not None:
                if not re.fullmatch(rx, q[key]):
                    raise PlazaError(400, "bad_request", f"bad {key}")
                out[key] = q[key]
        if q.get("session") is not None:
            if not connect_mod.TOKEN_RX.fullmatch(q["session"]):
                raise PlazaError(400, "bad_request", "bad session")
            out["session"] = q["session"]
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
        if path in ("/", "/plaza", "/plaza/") or PAGE_PATH.fullmatch(path):
            if path in ("/", "/plaza"):                   # on its own hostname the root is the landing page
                self.send_response(302 if path == "/" else 301)
                self.send_header("Location", "/plaza/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self._file("index.html", "text/html; charset=utf-8")
        if path in STATIC:
            return self._file(*STATIC[path])
        m = STATIC_RX.fullmatch(path)
        if m:
            return self._file(m.group(1), TYPES[m.group(2)])
        if path == "/plaza/cards.json":                 # the official card art the dashboard already ships
            try:
                body = (WEB.parent.parent / "dashboard" / "cards.json").read_bytes()
            except OSError:
                body = b"{}"
            return self._send(200, body, "application/json; charset=utf-8", cache="public, max-age=3600")
        if path == "/plaza/i18n.json":                  # every page text in English and Spanish, as data
            return self._file("i18n.json", "application/json; charset=utf-8", cache="public, max-age=300")
        if path in ("/plaza/agents.md", "/plaza/AGENTS.md", "/AGENTS.md"):
            try:
                md = agents_md(base=public_url(self.board.live))
            except TypeError:
                md = agents_md()
            return self._send(200, md.encode(), "text/markdown; charset=utf-8", cors=True)
        m = ART_PATH.fullmatch(path)
        if m:                                           # the card as the dashboard draws it
            svg = self.board.card_art().get(m.group(1))
            if not svg:
                return self._error(404, "not_found", "no art for this card")
            if "xmlns=" not in svg[:200]:
                svg = svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
            return self._send(200, svg.encode(), "image/svg+xml; charset=utf-8", cache="public, max-age=3600", cors=True)
        if not path.startswith("/plaza/api/"):
            return self._error(404, "not_found", "no such page")
        self.route = path[len("/plaza/api/"):].split("/")[0]
        if path == "/plaza/api/health":
            return self._json(200, {"ok": True, "enabled": self.board.enabled(), "name": NAME, "api": 1}, cors=True)
        if path == "/plaza/api/openapi.json":
            return self._json(200, routes.openapi(NAME), cors=True)
        if not self.board.enabled():
            return self._error(503, "closed", "the plaza is closed for now")
        snap = self.board.get()
        try:
            q = self._filters({k: v[-1] for k, v in parse_qs(u.query).items()})
        except PlazaError as e:
            return self._error(e.status, e.code, e.message)
        if q.get("team") and q["team"] not in snap["sheets"]:
            return self._error(400, "bad_request", "no such team")
        if self.headers.get(TOKEN_HEADER):               # an agent that reads with its token shows as online
            try:
                self.board.connect.auth(self.headers.get(TOKEN_HEADER))
            except PlazaError:
                pass
        try:
            if path == "/plaza/api/connect/status":
                return self._json(200, self._status(q))
            for ext in EXTENSIONS:                       # each fork's own routes; True once it has answered
                if ext.get(self, path, q, snap):
                    return
            if path == "/plaza/api/me":                  # the team's own view: its browser session or its agent
                team = self.me_team(q)
                st = self._status(q) if not self.headers.get(TOKEN_HEADER) else {"team": team, "verified": True}
                return self._json(200, {"team": team, "read_only": True, "status": st, "tick": snap["tick"],
                                        "limits": self.board.vault.get(team),      # its own, to itself only
                                        "agent": self.board.queue.settings(team),
                                        "venue": VENUE, "home": {**self.board.team_view(team, snap),
                                                                 "matches": self.board.matches_view(snap, team)["matches"]}})
            if path in ("/plaza/api/agent/next", "/plaza/api/agent/cards"):
                team, _ = self.board.connect.auth(self.headers.get(TOKEN_HEADER))
                if path.endswith("/cards"):
                    return self._json(200, {"team": team, "limits": self.board.vault.get(team),
                                            "private": "only your team sees your limits",
                                            **{k: v for k, v in self.board.team_view(team, snap).items()
                                               if k in ("available", "wanted")}})
                return self._json(200, self.board.agent_next(team, snap))
            m = MATCH_PATH.fullmatch(path)
            if m:
                rec = self.board.deals.get(m.group(1))
                view = self.board.match_view(rec, snap.get("hidden", (set(), set())), full=True)
                return self._json(200, {**self.board.trade_view(view, snap), "tick": snap["tick"], "venue": VENUE},
                                  cors=True)
        except PlazaError as e:
            return self._error(e.status, e.code, e.message)
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
        blocked, gone = set(admin["blocked"]), set(admin["hidden_msgs"])
        out = self.board.floor.poll(q.get("since", 0), team=q.get("team"), ref=q.get("ref"), kind=q.get("kind"),
                                    limit=q.get("limit", 100), hidden=set(admin["hidden"]), blocked=blocked)
        out["items"] = [i for i in out["items"] if not (i.get("src") == "plaza" and i.get("msg") is not None and (
            i.get("team") in blocked or f"{i.get('match')}:{i['msg']}" in gone))]
        return out

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
        if path in ("/plaza/admin", "/plaza/admin/") or ADMIN_PAGE.fullmatch(path):
            return self._file("admin.html", "text/html; charset=utf-8")
        if path in ADMIN_STATIC:
            return self._file(*ADMIN_STATIC[path])
        m = ADMIN_STATIC_RX.fullmatch(path)
        if m:
            return self._file("admin/" + m.group(1), TYPES[m.group(2)])
        snap = self.board.get()
        try:
            f = self._filters(q)
        except PlazaError as e:
            return self._error(e.status, e.code, e.message)
        if path == "/plaza/admin/api/overview":
            return self._json(200, self.board.overview(snap))
        if path == "/plaza/admin/api/activity":
            return self._json(200, self.board.activity(f))
        if path == "/plaza/admin/api/matchmaker":
            return self._json(200, self.board.matchmaker(snap))
        try:
            if admin_api.get(self, path, f, snap):
                return
        except PlazaError as e:
            return self._error(e.status, e.code, e.message)
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
                done = admin_api.action(self, str(action), body)
                if done is not None:
                    return self._json(200, {"ok": True, **done})
                if action == "refresh":
                    self.board.tick_feed()
                    self.board.rebuild()
                    return self._json(200, {"ok": True, "admin": self.board.store.admin()})
                if action == "force":
                    rec = self.board.force(body, self.board.get())
                    self.board.rebuild()
                    return self._json(200, {"ok": True, "match": rec["id"]})
                if action == "expire":
                    rec = self.board.deals.expire(body.get("match"))
                    self.board.rebuild()
                    return self._json(200, {"ok": True, "match": rec["id"], "state": rec["state"]})
                out = self.board.store.admin_do(str(action), body.get("team"), body.get("message"), body.get("match"))
                if action in ("pause", "resume", "exclude", "include", "hide", "unhide", "block", "unblock"):
                    self.board.rebuild()
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
            if self.command == "POST" and path in ("/plaza/api/connect/start", "/plaza/api/connect/agent"):
                self.route = "connect"
                if not isinstance(body, dict):
                    raise PlazaError(400, "bad_request", "send a JSON object")
                team = body.get("team")
                if not isinstance(team, str) or team not in public.TEAMS:
                    raise PlazaError(400, "bad_request", "team ids look like t04")
                if path.endswith("/start"):
                    out = self.board.connect.start(team, self._client())
                    base = public_url(self.board.live) or LOCAL_BASE
                    lang = body.get("lang") if body.get("lang") in ("en", "es") else "en"
                    try:
                        out["prompt"] = connect_mod.prompt(team, out["connect_code"], base, VENUE, NAME, lang=lang)
                    except TypeError:                         # the prompt in one language only
                        out["prompt"] = connect_mod.prompt(team, out["connect_code"], base, VENUE, NAME)
                    out["agents_md"], out["status"] = base + "/AGENTS.md", "/plaza/api/connect/status"
                    secure = "; Secure" if "https" in (self.headers.get("X-Plaza-Proto"),
                                                       self.headers.get("X-Forwarded-Proto")) else ""
                    self.extra = (("Set-Cookie", f"{COOKIE}={out['session']}; Path=/plaza; Max-Age="
                                                 f"{out['session_expires_in']}; HttpOnly; SameSite=Lax{secure}"),)
                    self.board.hour("connect_start")
                    return self._json(200, out)
                known = bool((self.board.store.declared().get(team) or {}).get("verified"))
                out = self.board.connect.agent(team, body.get("code"), self._client(), known)
                out["next"] = (f"prove it is you: open a thread with {HOST} in the game and send the code as the "
                               f"message text; then PUT /plaza/api/team/{team} with header {TOKEN_HEADER}")
                self.board.hour("connect_agent")
                self.board.stale()
                return self._json(200, out)
            if self.command == "POST" and path == "/plaza/api/agent/ack":
                self.route = "agent_ack"
                team, _ = self.board.connect.auth(self.headers.get(TOKEN_HEADER))
                if not isinstance(body, dict):
                    raise PlazaError(400, "bad_request", "send a JSON object")
                self.board.hour("agent_acks")
                return self._json(200, self.board.queue.ack(team, body.get("id"), body.get("status"), body.get("note")))
            for ext in EXTENSIONS:
                if ext.write(self, self.command, path, body):
                    return
            if self.command == "POST" and path.startswith("/plaza/api/me/"):
                return self._me_write(path, body)
            m = MATCH_MSG_PATH.fullmatch(path)
            if self.command == "POST" and m:
                self.route = "match_post"
                rec = self.board.deals.get(m.group(1))
                given = body.pop("team", None) if isinstance(body, dict) else None
                team, verified, _ = self._actor(given)
                if team in self.board.store.admin()["blocked"]:
                    raise PlazaError(403, "blocked", "this team cannot post for now")
                rec, item, moved = self.board.deals.message(rec["id"], team, verified, body)
                self.board.floor.add_game([item] + moved)
                self.board.store.touch(team)
                self.board.hour("match_messages")
                self.board.stale()
                snap = self.board.get()
                return self._json(200, {"posted": item["msg"], "match": self.board.trade_view(
                    self.board.match_view(rec, snap.get("hidden", (set(), set())), full=True), snap)})
            if self.command == "POST" and path == "/plaza/api/floor":
                self.route = "floor_post"
                if not isinstance(body, dict):
                    raise PlazaError(400, "bad_request", "send a JSON object")
                team, verified, _ = self._actor(body.pop("team", None))
                if team in self.board.store.admin()["blocked"]:
                    raise PlazaError(403, "blocked", "this team cannot post on the floor for now")
                item = self.board.floor.post(team, verified, body)
                self.board.store.touch(team)
                self.board.hour("floor_posts")
                return self._json(200, {"posted": item})
            m = TEAM_PATH.fullmatch(path)
            if self.command == "PUT" and m:
                self.route = "declare"
                team, _, by_token = self._actor(m.group(1))
                body, limits = private.split(body)             # private limits never reach the public sheet
                declared = self.board.store.declare(team, None if by_token else self.headers.get("X-Plaza-Pin") or "",
                                                    body)
                for ref, fields in limits.items():
                    self.board.vault.put(team, ref, fields)
                self.board.hour("declares")
                self.board.stale()                                           # show it on the next read
                return self._json(200, {"team": team, "declared": declared, "limits_saved": len(limits),
                                        "private": "only your team sees your limits"})
            return self._error(404, "not_found", "no such endpoint")
        except PlazaError as e:
            return self._error(e.status, e.code, e.message)

    def _me_write(self, path: str, body):
        """The connected human: private limits for a card, a trade's mode, an order for its agent. Never the game."""
        self.route = "me_write"
        team = self.me_team()
        if not isinstance(body, dict):
            raise PlazaError(400, "bad_request", "send a JSON object")
        m = ME_CARD_PATH.fullmatch(path)
        if m:
            if m.group(1) not in self.board.get()["cat"]:
                raise PlazaError(404, "not_found", "no such card")
            if set(body) - set(private.FIELDS):
                raise PlazaError(400, "bad_request", "send any of min, max, value")
            self.board.vault.put(team, m.group(1), private.limits(body, private.FIELDS))
            self.board.stale()
            return self._json(200, {"team": team, "ref": m.group(1), "limits": self.board.vault.get(team).get(m.group(1), {}),
                                    "private": "only your team sees your limits"})
        m = ME_TRADE_PATH.fullmatch(path)
        if m:
            rec = self.board.deals.get(m.group(1))
            if team not in deals_mod.parties(rec):
                raise PlazaError(403, "not_a_party", "this is not your trade")
            if set(body) - {"mode", "order", "price"} or not (body.get("mode") or body.get("order")):
                raise PlazaError(400, "bad_request", "send mode (auto, ask_me) or order (accept, counter, pass)")
            if body.get("mode") is not None:
                self.board.queue.set_mode(team, body["mode"], rec["id"])
            if body.get("order") is not None:
                if rec["state"] not in deals_mod.LIVE_STATES:
                    raise PlazaError(409, "closed", f"this match is {rec['state']}")
                if body["order"] == "counter" and rec["kind"] == "sale" and isinstance(body.get("price"), (int, float)) \
                        and not isinstance(body.get("price"), bool) \
                        and body["price"] < matcher.FLOOR.get(rec.get("rarity") or "", 1):
                    raise PlazaError(400, "below_floor", "under the floor of this rarity on this venue")
                self.board.queue.order(team, rec["id"], body["order"], body.get("price"))
                self.board.hour("human_orders")
            return self._json(200, {"team": team, "match": rec["id"], "agent": self.board.queue.settings(team)})
        if path == "/plaza/api/me/settings":
            if set(body) - {"default_mode"}:
                raise PlazaError(400, "bad_request", "send default_mode (auto, ask_me)")
            self.board.queue.set_mode(team, body.get("default_mode"))
            return self._json(200, {"team": team, "agent": self.board.queue.settings(team)})
        raise PlazaError(404, "not_found", "no such endpoint")

    do_POST = _write
    do_PUT = _write

    def do_OPTIONS(self):                               # no cross-site writes: no preflight is ever granted
        self.route = "other"
        self._error(405, "not_allowed", "cross-site writes are not allowed")

    do_DELETE = do_PATCH = do_TRACE = do_CONNECT = do_PROPFIND = do_OPTIONS

    def send_error(self, code, message=None, explain=None):
        """The standard library's own refusals (an unknown method, a broken request line): ours, as JSON, 4xx."""
        self.route = "other"
        try:
            self._error(405 if code == 501 else code if 400 <= code < 500 else 400, "bad_request", "this request is not understood")
        except OSError:
            pass


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
    """Where other teams reach the plaza: PLAZA_PUBLIC_URL, else control.plaza_url, else the tunnel's address."""
    fixed = (os.environ.get("PLAZA_PUBLIC_URL") or "").strip().rstrip("/")
    if re.fullmatch(r"https?://[A-Za-z0-9.:-]{3,120}(?:/plaza)?", fixed):
        return fixed if fixed.endswith("/plaza") else fixed + "/plaza"
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
    waiting = False
    while True:
        try:
            srv = make_server(board)
            break
        except OSError as e:                             # another copy already serves the port: stand by for it
            if e.errno not in (48, 98):
                raise
            if not waiting:
                print(f"plaza: port {PORT} is taken; standing by", flush=True)
            waiting = True
            time.sleep(30.0)
    board.token = admin_token(config.LIVE)                # only once we own the port
    threading.Thread(target=run_ticker, args=(board, threading.Event()), daemon=True).start()
    print(f"plaza -> http://127.0.0.1:{PORT}/plaza/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
