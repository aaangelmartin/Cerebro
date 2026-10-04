"""The deals routes (CONTRACT.md 1.3) and the two hooks the board calls on every rebuild.

    candidates(board, sheets, cat)      what the matcher may propose now (the value gate, the price rule)
    sync(board, cands, tick, admin)     the matches brought up to date with the game's feed

    GET  /plaza/api/me/trades           a team's matches: what it gives, what it receives, what comes next
    POST /plaza/api/me/trade/ID         {mode} | {order, price} | {offer_id}
    POST /plaza/api/match/ID/message    counter, accept or pass on the thread
    GET  /plaza/api/market              every card: holders, seekers, best ask and bid, last price
    GET  /plaza/api/card/REF            one card, with its last deals between teams and its possible matches
    GET  /plaza/api/stats               what the venue has closed

Nothing here calls the game: the feed is the recorder's file. Nothing here returns a private limit."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from . import deals as deals_mod, matcher
from .perf import Perf
from .quotes import Quoter
from .store import MAX_PRICE, REF_RX, PlazaError

VENUE = matcher.VENUE
TOKEN_HEADER = "X-Plaza-Token"
ME_TRADE = re.compile(r"/plaza/api/me/trade/(m-[0-9a-f]{10})")
MATCH_MSG = re.compile(r"/plaza/api/match/(m-[0-9a-f]{10})/message")
CARD = re.compile(r"/plaza/api/card/([A-Z]{3}-\d{2})")
THREAD_SHOWN = 30
TRADE_KEYS = {"mode", "order", "price", "offer_id"}
STATE_WORDS = {"offer_on_v07": "the offer is on v07", "accepted": "accepted; it settles on the next tick",
               "settled": "settled on v07", "settled_elsewhere": "closed on another venue: it did not count here",
               "passed": "passed", "expired": "expired", "proposed": "proposed"}


def attach(board) -> None:
    board.quoter = Quoter(board.vault)
    board.perf = Perf(board.live, board.record, VENUE, board.host)


def _quoter(board) -> Quoter:
    if getattr(board, "quoter", None) is None:
        attach(board)
    return board.quoter


def _perf(board) -> Perf:
    if getattr(board, "perf", None) is None:
        attach(board)
    return board.perf


def _paused(board) -> frozenset:
    try:
        return frozenset(board.store.paused_teams())
    except Exception:  # noqa: BLE001 - a store without settings pauses nobody
        return frozenset()


def note(board, team: str, kind: str, text: str, by: str = "market", **extra) -> None:
    """One line on the team's own activity record. Never raises; never carries a limit."""
    log = getattr(board, "team_activity", None)
    if log is None:
        return
    try:
        log.add(team, kind, text, by=by, **extra)
    except Exception:  # noqa: BLE001
        pass


# ---- the hooks of Board.rebuild
def candidates(board, sheets: dict, cat: dict) -> list[dict]:
    q = _quoter(board).at(board.feed.tick)
    return matcher.find(sheets, cat, board.host, VENUE, quote=q.quote, refprice=board.feed.team_prices(),
                        traded=board.feed.traded_pairs(), paused=_paused(board))


def sync(board, cands: list[dict], tick, admin: dict) -> list[dict]:
    events = board.deals.sync(cands, tick, board.feed.venue_log, paused=admin["mm_paused"],
                              excluded_matches=frozenset(admin["excluded_matches"]), paused_teams=_paused(board))
    for e in events:
        if e.get("kind") != "match":
            continue
        words = STATE_WORDS.get(e["state"], e["state"])
        kind = "settle" if e["state"] in ("settled", "settled_elsewhere") else \
            "offer" if e["state"] == "offer_on_v07" else "match"
        for team, other in ((e["team"], e["to"]), (e["to"], e["team"])):
            if team:
                note(board, team, kind, f"{e['ref']} with {other}: {words}", match=e["match"], ref=e["ref"],
                     tick=e.get("tick"))
    notes, board.deals.notes = board.deals.notes, []
    for n in notes:
        if n["kind"] == "wrong_venue":
            note(board, n["team"], "offer", f"your offer {n['offer']} for {n['ref']} is on {n['venue']}: this match "
                 f"closes on {VENUE} only (0 fee). Cancel it and post it on {VENUE}.", match=n["match"], ref=n["ref"],
                 tick=n.get("tick"))
    return events


# ---- views
def _team_or_none(h, q: dict) -> str | None:
    """The connected team that asks, when there is one. A bad credential is not an error on a public read."""
    if not (h.headers.get(TOKEN_HEADER) or h._session(q)):
        return None
    try:
        return h.me_team(q)
    except PlazaError:
        return None


def _owned(board, team: str, snap: dict) -> set[str]:
    sheet = (snap.get("sheets") or {}).get(team) or {}
    out = {e["ref"] for e in list(sheet.get("spares") or []) + list(sheet.get("for_sale") or [])}
    try:
        from . import team_api
        out |= set(team_api.owned(board, team, sheet) or [])
    except Exception:  # noqa: BLE001 - the team API may not know the full list
        pass
    return out


def _you(board, team: str | None, ref: str, snap: dict, owned: set[str] | None = None) -> dict | None:
    if not team:
        return None
    sheet = (snap.get("sheets") or {}).get(team) or {}
    owned = _owned(board, team, snap) if owned is None else owned
    as_ = "for_sale" if any(e["ref"] == ref for e in sheet.get("for_sale") or []) else \
        "duplicate" if any(e["ref"] == ref for e in sheet.get("spares") or []) else None
    return {"owned": ref in owned, "want": any(e["ref"] == ref for e in sheet.get("wants") or []), "as": as_}


def trade_for(board, rec: dict, team: str, snap: dict, queue: dict) -> dict:
    """One match as one of its teams sees it."""
    view = board.trade_view(board.match_view(rec, snap.get("hidden", (set(), set())), full=True), snap)
    thread = view.pop("thread", [])
    view.pop("history", None)
    card = lambda ref: board.card(ref, snap)   # noqa: E731
    gives, receives, cash = [], [], 0
    if rec["kind"] == "triangle":
        role = "party"
        for leg in rec.get("legs") or []:
            if leg["from"] == team:
                gives.append(card(leg["ref"]))
            if leg["to"] == team:
                receives.append(card(leg["ref"]))
    else:
        role = "seller" if team == rec["seller"] else "buyer"
        mine, theirs = (rec["ref"], rec.get("ref_back")) if role == "seller" else (rec.get("ref_back"), rec["ref"])
        gives = [card(mine)] if mine else []
        receives = [card(theirs)] if theirs else []
        if rec["kind"] == "sale":
            cash = int(rec.get("price") or 0) * (1 if role == "seller" else -1)
    settings = board.queue.settings(team)
    nxt = None
    if rec["state"] in deals_mod.LIVE_STATES:
        act = next((a for a in queue.get("actions") or [] if a.get("match") == rec["id"]), None)
        if act:
            nxt = {"id": act["id"], "type": act["type"], "why": act["why"], "target": (act.get("request") or {}).get("target")}
        else:
            wait = next((w for w in queue.get("waiting") or [] if w.get("match") == rec["id"]), None)
            nxt = {"waiting": wait["why"] if wait else "nothing to do now"}
    return {**view, "your_role": role, "gives": gives, "receives": receives, "cash": cash,
            "mode": settings["modes"].get(rec["id"], settings["default_mode"]),
            "order": settings["orders"].get(rec["id"]), "thread": thread[-THREAD_SHOWN:], "next": nxt}


def trades_view(board, team: str, snap: dict) -> dict:
    queue = board.agent_next(team, snap)
    rows = [trade_for(board, r, team, snap, queue) for r in board.deals.for_team(team)]
    return {"team": team, "tick": snap.get("tick"), "trades": rows, "counts": board.deals.counts(team)}


def market_view(board, snap: dict, q: dict, team: str | None) -> dict:
    holders: dict[str, int] = {}
    seekers: dict[str, int] = {}
    asks: dict[str, int] = {}
    bids: dict[str, int] = {}

    def best(book: dict, ref: str, price, low: bool) -> None:
        if isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0:
            cur = book.get(ref)
            book[ref] = int(price) if cur is None else (min(cur, int(price)) if low else max(cur, int(price)))

    for t, s in snap["sheets"].items():
        if s.get("host"):
            continue
        for e in list(s.get("spares") or []) + list(s.get("for_sale") or []):
            holders[e["ref"]] = holders.get(e["ref"], 0) + 1
            best(asks, e["ref"], e.get("price"), True)
        for e in s.get("wants") or []:
            seekers[e["ref"]] = seekers.get(e["ref"], 0) + 1
            best(bids, e["ref"], e.get("bid"), False)
    for o in snap.get("offers") or []:
        if o["side"] == "ask":
            best(asks, o["ref"], o.get("price"), True)
        elif o["side"] == "bid":
            best(bids, o["ref"], o.get("price"), False)
    last: dict[str, dict] = {}
    for s in board.feed.sales:
        if s.get("price"):
            last[s["ref"]] = s
    live: dict[str, int] = {}
    for m in snap.get("matches") or []:
        for ref in {m["ref"], m.get("ref_back"), *[leg.get("ref") for leg in m.get("legs") or []]} - {None}:
            live[ref] = live.get(ref, 0) + 1
    owned = _owned(board, team, snap) if team else set()
    sheet = (snap["sheets"].get(team) or {}) if team else {}
    wants = {e["ref"] for e in sheet.get("wants") or []}
    spare = {e["ref"] for e in list(sheet.get("spares") or []) + list(sheet.get("for_sale") or [])}
    sets: dict[str, dict] = {}
    cards = []
    for ref in sorted(snap["cat"]):
        c = snap["cat"][ref]
        sets.setdefault(c.get("set") or ref[:3], {"id": c.get("set") or ref[:3], "name": c.get("set_name"),
                                                 "color": c.get("color")})
        if (q.get("set") and (c.get("set") or ref[:3]) != q["set"]) or (q.get("rarity") and c.get("rarity") != q["rarity"]):
            continue
        row = {**board.card(ref, snap), "holders": holders.get(ref, 0), "seekers": seekers.get(ref, 0),
               "best_ask": asks.get(ref), "best_bid": bids.get(ref),
               "last_price": (last.get(ref) or {}).get("price"), "last_tick": (last.get(ref) or {}).get("tick"),
               "matches": live.get(ref, 0)}
        if team:
            row["you"] = "want" if ref in wants else "spare" if ref in spare else "owned" if ref in owned else None
        cards.append(row)
    return {"tick": snap.get("tick"), "venue": VENUE, "sets": list(sets.values()), "cards": cards, "total": len(cards)}


def card_view(board, ref: str, snap: dict, team: str | None) -> dict:
    out = board.card_view(ref, snap, team)
    deals = []
    for s in board.feed.sales:                                 # sales between two teams only: the public record
        if s["ref"] == ref and not s.get("dealer") and s.get("price") and \
                all(str(s.get(k) or "").startswith("t") for k in ("from", "to")):
            deals.append({"tick": s.get("tick"), "price": s["price"], "venue": s.get("venue"),
                          "seller": s.get("from"), "buyer": s.get("to")})
    possible = []
    for m in out.get("matches") or []:
        possible.append({"kind": m["kind"], "seller": m["seller"], "buyer": m["buyer"], "price": m.get("price"),
                         "state": m["state"], "id": m["id"],
                         **({"finishes_page": bool(m["last_of_page"])} if "last_of_page" in m else {})})
    for m in snap.get("matches") or []:                         # what waits behind a live match: who, never a price
        for a in m.get("alternatives") or []:
            if a.get("ref") == ref:
                possible.append({"kind": a["kind"], "seller": a["seller"], "buyer": a["buyer"],
                                 "price": a.get("price") if team in (a["seller"], a["buyer"]) else None,
                                 "state": "waiting", "id": a["id"]})
    out["deals"] = deals[-12:][::-1]
    out["reference_price"] = board.feed.team_prices().get(ref)      # None: no trade between teams yet
    out["possible_matches"] = possible[:20]
    you = _you(board, team, ref, snap)
    if you is not None:
        out["you"] = you
    return out


# ---- routes
def get(h, path: str, q: dict, snap: dict) -> bool:
    board = h.board
    if path == "/plaza/api/me/trades":
        h._json(200, trades_view(board, h.me_team(q), snap))
        return True
    if path == "/plaza/api/stats":
        from . import server
        h._json(200, _perf(board).stats(board, snap, server.NAME), cors=True)
        return True
    if path == "/plaza/api/market":
        team = _team_or_none(h, q)
        h._json(200, market_view(board, snap, q, team), cors=team is None)
        return True
    m = CARD.fullmatch(path)
    if m:
        if m.group(1) not in snap["cat"]:
            raise PlazaError(404, "not_found", "no such card")
        team = _team_or_none(h, q)
        h._json(200, card_view(board, m.group(1), snap, team), cors=team is None)
        return True
    return False


def _whole(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value) or not 0 < value <= MAX_PRICE:
        raise PlazaError(400, "bad_request", f"{name} is a whole number between 1 and {MAX_PRICE}")
    return int(value)


def _trade(h, mid: str, body) -> None:
    board = h.board
    h.route = "me_write"
    team = h.me_team()
    if not isinstance(body, dict):
        raise PlazaError(400, "bad_request", "send a JSON object")
    unknown = set(body) - TRADE_KEYS
    if unknown or not any(body.get(k) is not None for k in ("mode", "order", "offer_id")):
        raise PlazaError(400, "bad_request", "send mode (auto, ask_me), order (accept, counter, pass) with price, "
                         "or offer_id")
    rec = board.deals.get(mid)
    if team not in deals_mod.parties(rec):
        raise PlazaError(403, "not_a_party", "this is not your trade")
    by = "agent" if h.headers.get(TOKEN_HEADER) else "human"
    extra: dict = {}
    if body.get("order") is not None or body.get("price") is not None:        # validate before changing anything
        if body.get("order") not in ("accept", "counter", "pass"):
            raise PlazaError(400, "bad_request", "order is accept, counter or pass")
        if body["order"] == "counter":
            price = _whole(body.get("price"), "price")
            if rec["kind"] == "sale" and price < matcher.FLOOR.get(rec.get("rarity") or "", 1):
                raise PlazaError(400, "below_floor", "under the floor of this rarity on this venue")
        elif body.get("price") is not None:
            raise PlazaError(400, "bad_request", "only a counter carries a price")
        if rec["state"] not in deals_mod.LIVE_STATES:
            raise PlazaError(409, "closed", f"this match is {rec['state']}")
    if body.get("mode") is not None:
        board.queue.set_mode(team, body["mode"], rec["id"])
        note(board, team, "settings", f"{rec['ref']}: mode {body['mode']}", by=by, match=rec["id"], ref=rec["ref"])
    if body.get("order") is not None:
        board.queue.order(team, rec["id"], body["order"], body.get("price"))
        board.hour("human_orders")
        note(board, team, "order", f"{rec['ref']}: {body['order']}"
             + (f" at {int(body['price'])} P" if body["order"] == "counter" else ""), by=by, match=rec["id"],
             ref=rec["ref"])
    if body.get("offer_id") is not None:
        oid = body["offer_id"]
        with board.feed_lock:
            board.floor.add_game(board.feed.refresh())             # the newest the recorder has
            seen = board.feed.offer(oid)
        rec, events, confirmed = board.deals.report_offer(rec["id"], team, oid, seen)
        board.floor.add_game(events)
        board.hour("offers_reported")
        extra["offer"] = {"id": oid, "confirmed": confirmed, "venue": VENUE,
                          "note": "seen on v07 in the game's feed" if confirmed else
                                  "noted; it counts once the game's feed shows it on v07"}
        note(board, team, "offer", f"{rec['ref']}: offer {oid} " + ("is on v07" if confirmed else "reported"), by=by,
             match=rec["id"], ref=rec["ref"])
    board.stale()
    h._json(200, {"team": team, "match": rec["id"], "state": rec["state"], "agent": board.queue.settings(team), **extra})


def _message(h, mid: str, body) -> None:
    board = h.board
    h.route = "match_post"
    rec = board.deals.get(mid)
    if not isinstance(body, dict):
        raise PlazaError(400, "bad_request", "send a JSON object")
    body = dict(body)
    team, verified, _ = h._actor(body.pop("team", None))
    if team in board.store.admin()["blocked"]:
        raise PlazaError(403, "blocked", "this team cannot post for now")
    again = board.deals.repeated(rec["id"], team, body)
    if again is not None:                                          # said already: the match as it is
        snap = board.get()
        h._json(200, {"posted": None, "repeated": True, "match": board.trade_view(
            board.match_view(again, snap.get("hidden", (set(), set())), full=True), snap)})
        return
    rec, item, moved = board.deals.message(rec["id"], team, verified, body)
    board.floor.add_game([item] + moved)
    board.store.touch(team)
    board.hour("match_messages")
    words = item.get("kind") or "note"
    note(board, team, "message", f"{rec['ref']}: {words}" + (f" at {item['price']} P" if item.get("price") else ""),
         by="agent", match=rec["id"], ref=rec["ref"], tick=item.get("tick"))
    board.stale()
    snap = board.get()
    h._json(200, {"posted": item["msg"], "match": board.trade_view(
        board.match_view(rec, snap.get("hidden", (set(), set())), full=True), snap)})


def write(h, method: str, path: str, body) -> bool:
    if method != "POST":
        return False
    m = ME_TRADE.fullmatch(path)
    if m:
        _trade(h, m.group(1), body)
        return True
    m = MATCH_MSG.fullmatch(path)
    if m:
        _message(h, m.group(1), body)
        return True
    return False


def query(h) -> dict:
    """The raw query of the request, for the few parameters the shared filter does not know."""
    return {k: v[-1] for k, v in parse_qs(urlparse(h.path).query).items()}


__all__ = ["attach", "candidates", "sync", "get", "write", "note", "trades_view", "market_view", "card_view",
           "REF_RX"]
