"""Our panel's routes (CONTRACT.md 1.4), called by server.py only after the admin check.

    GET  /plaza/admin/api/status         our processes and switches
    GET  /plaza/admin/api/performance    what the venue earns us: the game's count against ours (perf.py)
    GET  /plaza/admin/api/trades         every match, by state or team
    GET  /plaza/admin/api/teams          every team: connected, verified, online, limits set
    GET  /plaza/admin/api/suggestions    every suggestion
    GET  /plaza/admin/api/venue          the venue as the game shows it
    POST /plaza/admin/api/action         {"action": "suggestion", "id", "status", "reply"}
                                         {"action": "forgive", "team", "strike"?}   take a strike back
                                         {"action": "unban", "team"} / {"action": "ban", "team", "reason"?}
                                         {"action": "strikes", "on"?, "limit"?, "accepter"?}   the rule itself

Strikes (strikes.py): `teams` carries each team's `standing`, and `teams` and `performance` carry `strikes`, every
strike with its evidence.

The panel never sees a private limit: only "limits set" and "the two limits overlap", yes or no."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import deals as deals_mod, deals_api
from .store import PlazaError, TEAM_RX

STATE_RX = re.compile("|".join(deals_mod.STATES) + "|live|done")
RECORDER_STALE_S = 180.0


def _json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _ago(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


def _game(board, admin: dict) -> dict:
    """game / market / matchmaker, as the status route of the team API says them."""
    try:
        from . import status as status_mod
        st = status_mod.status(board.record, deals_api.VENUE, board.enabled(), admin["mm_paused"])
        return {k: st.get(k) for k in ("game", "market", "matchmaker", "feed", "tick")}
    except Exception:  # noqa: BLE001 - the status module is another fork's: fall back to the recorder's clock
        clock = _json(board.record / "latest" / "clock.json", {}) or {}
        game = "closed" if str(clock.get("doors") or "").lower() == "closed" else \
            "paused" if clock.get("paused") else "open"
        market = "off" if not board.enabled() else game
        return {"game": game, "market": market, "feed": None, "tick": clock.get("tick"),
                "matchmaker": "paused" if admin["mm_paused"] else "on" if market == "open" else "waiting"}


def status_view(board, snap: dict) -> dict:
    from . import server
    admin = board.store.admin()
    now = time.time()
    g = _game(board, admin)
    live = len(snap.get("matches") or [])
    url = server.public_url(board.live)
    rec = _json(board.live / "recorder_status.json", None)
    rec_age = now - float(rec.get("updated") or 0) if isinstance(rec, dict) else None
    venue = (deals_api._perf(board).me().get("venue") or {})
    broker = deals_api._perf(board).broker()
    fee = venue.get("fee_bps")
    procs = [
        {"id": "server", "name": "Server", "state": "on" if board.enabled() else "off",
         "detail": f"up {_ago(now - board.started)}" + ("" if board.enabled() else "; switched off")},
        {"id": "tunnel", "name": "Tunnel", "state": "on" if url else "off",
         "detail": "public address known" if url else "no public address: teams cannot reach the market"},
        {"id": "matchmaker", "name": "Matchmaker", "state": g["matchmaker"],
         "detail": f"{live} live match{'' if live == 1 else 'es'}, {snap.get('candidates', 0)} candidates"},
        {"id": "recorder", "name": "Recorder", "detail": "no status file" if rec_age is None else
         f"feed at tick {rec.get('tick')}, {_ago(rec_age)} ago",
         "state": "off" if rec_age is None else "on" if rec_age < RECORDER_STALE_S else "stale"},
        {"id": "venue", "name": "Venue v07", "state": venue.get("status") or "unknown",
         "detail": "no data from the game" if fee is None else f"{fee / 100:g} % fee, {venue.get('trades', 0)} trades"},
        {"id": "broker", "name": "Broker", "state": broker["state"], "detail": broker["detail"]},
    ]
    return {"tick": snap.get("tick") or g.get("tick"), "processes": procs, "game": g["game"], "market": g["market"],
            "feed": g.get("feed"), "enabled": board.enabled(), "paused": bool(admin["mm_paused"]),
            "public_url": url}


def trades_view(board, snap: dict, state: str | None, team: str | None) -> dict:
    hidden = snap.get("hidden", (set(), set()))
    tick = board.deals.tick
    rows = []
    for r in board.deals.all():
        if team and team not in deals_mod.parties(r):
            continue
        if state == "live" and r["state"] not in deals_mod.LIVE_STATES:
            continue
        if state == "done" and r["state"] not in deals_mod.DONE_STATES:
            continue
        if state not in (None, "live", "done") and r["state"] != state:
            continue
        view = board.trade_view(board.match_view(r, hidden, full=True), snap)
        last = r.get("last_tick") or r["state_tick"]
        view["basis"] = r.get("basis")                         # how the price was reached: a word, never a limit
        view["overlap"] = None if r["kind"] != "sale" else \
            deals_api._quoter(board).overlap(r["seller"], r["buyer"], r["ref"])
        view["stalled"] = r["state"] in deals_mod.LIVE_STATES and tick - last > deals_mod.STALL_TICKS
        view["quiet_ticks"] = tick - last
        rows.append(view)
    rows.sort(key=lambda v: (v["state"] not in deals_mod.LIVE_STATES, -(v.get("state_tick") or 0), v["id"]))
    return {"tick": snap.get("tick"), "trades": rows[:300], "counts": board.deals.counts(team), "total": len(rows),
            "closed": list(board.deals.closed)[-60:][::-1]}


def teams_view(board, snap: dict) -> dict:
    teams = board.overview(snap)["teams"]
    paused = deals_api._paused(board)
    for t in teams:
        t["paused"] = t["team"] in paused
        t.setdefault("standing", board.strikes.summary(t["team"]))
    return {"tick": snap.get("tick"), "teams": teams, "strikes": board.strikes.view(),
            "connected": sum(1 for t in teams if t["connected"]),
            "agents": sum(1 for t in teams if t["agent"]), "verified": sum(1 for t in teams if t["verified"]),
            "online": sum(1 for t in teams if t["online"])}


def _box(board):
    box = getattr(board, "suggest", None)
    if box is not None and hasattr(box, "all"):
        return box
    from . import suggest
    return suggest.of(board)


def suggestions_view(board) -> dict:
    try:
        rows = _box(board).all()
    except Exception:  # noqa: BLE001 - no box yet
        rows = []
    counts = {s: 0 for s in ("open", "planned", "done", "dismissed")}
    for r in rows:
        counts[r.get("status") or "open"] = counts.get(r.get("status") or "open", 0) + 1
    rows.sort(key=lambda r: (r.get("status") != "open", -(r.get("ts") or 0)))
    return {"suggestions": rows, "counts": counts}


def venue_view(board, snap: dict) -> dict:
    from . import server
    perf = deals_api._perf(board)
    venue = perf.me().get("venue") or next((v for v in perf.venues() if v.get("venue") == deals_api.VENUE), {})
    others = [{k: v.get(k) for k in ("venue", "name", "owner", "status", "fee_bps", "fee_per_card", "trades",
                                     "volume", "traders", "pairs")}
              for v in perf.venues() if v.get("venue") != deals_api.VENUE]
    others.sort(key=lambda v: -(v.get("trades") or 0))
    return {"tick": snap.get("tick"), "venue": venue, "public_url": server.public_url(board.live),
            "read_only": "our bot changes the fee and the description with its game key", "others": others,
            "broker": perf.broker(),
            "note": "v07 is a board venue: public offers that cross are paired by our broker; addressed offers "
                    "between two teams settle on their own"}


def get(h, path: str, q: dict, snap: dict) -> bool:
    board = h.board
    if path == "/plaza/admin/api/status":
        h._json(200, status_view(board, snap))
        return True
    if path == "/plaza/admin/api/performance":
        out = deals_api._perf(board).performance(board, snap)
        view = board.strikes.view()
        alerts = [{"kind": "strike", "tick": e.get("tick"),
                   "text": (f"{e['team']} is banned: {e.get('strikes')} matched trades closed elsewhere. Talk to the "
                            "team in person; lift it on Teams if it was a mistake."
                            if e["kind"] == "banned" else
                            f"{e['team']} got warning {e.get('strikes')} of {e.get('limit')}: {e.get('card')} closed "
                            f"on {e.get('venue')}. Talk to the team; forgive it on Teams if it was a mistake."
                            if e["kind"] == "warning" else
                            f"{e.get('card')} between {' and '.join(e.get('teams') or [])} closed on {e.get('venue')} "
                            "and the feed does not say who posted the offer: nobody was struck.")}
                  for e in view["log"] if e.get("kind") in ("warning", "banned", "unknown")][:3]
        h._json(200, {**out, "strikes": view, "alerts": alerts + list(out.get("alerts") or [])})
        return True
    if path == "/plaza/admin/api/trades":
        raw = deals_api.query(h)
        state, team = raw.get("state"), q.get("team") or raw.get("team")
        if state is not None and not STATE_RX.fullmatch(state):
            raise PlazaError(400, "bad_request", "state is one of " + ", ".join(deals_mod.STATES) + ", live, done")
        if team is not None and not TEAM_RX.fullmatch(team):
            raise PlazaError(400, "bad_request", "team ids look like t04")
        h._json(200, trades_view(board, snap, state, team))
        return True
    if path == "/plaza/admin/api/teams":
        h._json(200, teams_view(board, snap))
        return True
    if path == "/plaza/admin/api/suggestions":
        h._json(200, suggestions_view(board))
        return True
    if path == "/plaza/admin/api/venue":
        h._json(200, venue_view(board, snap))
        return True
    return False


def action(h, action: str, body: dict) -> dict | None:
    """One of our panel's actions; None when it is not one of this module's."""
    strikes = h.board.strikes
    if action in ("forgive", "unban", "ban", "strikes"):
        if action == "strikes":
            if set(body) - {"action", "on", "limit", "accepter"}:
                raise PlazaError(400, "bad_request", "send on (true, false), limit (1 to 9) or accepter (true, false)")
            out = {"strikes": strikes.configure(body.get("on"), body.get("limit"), body.get("accepter"))}
        elif action == "forgive":
            if set(body) - {"action", "team", "strike"}:
                raise PlazaError(400, "bad_request", "send team and, to name one, strike")
            out = {"team": body.get("team"), "standing": strikes.forgive(body.get("team"), body.get("strike"))}
        elif action == "unban":
            if set(body) - {"action", "team"}:
                raise PlazaError(400, "bad_request", "send team")
            out = {"team": body.get("team"), "standing": strikes.unban(body.get("team"))}
        else:
            if set(body) - {"action", "team", "reason"}:
                raise PlazaError(400, "bad_request", "send team and, if you like, reason")
            out = {"team": body.get("team"), "standing": strikes.ban(body.get("team"), body.get("reason"),
                                                                    h.board.snap.get("tick"))}
        if body.get("team"):
            deals_api.note(h.board, body["team"], "warning", {"forgive": "the host took one warning back",
                           "unban": "the host let your team back in: one warning stays",
                           "ban": "the host closed the market to your team"}[action], by="market")
        h.board.rebuild()
        return out
    if action != "suggestion":
        return None
    unknown = set(body) - {"action", "id", "status", "reply"}
    if unknown or not isinstance(body.get("id"), str) or (body.get("status") is None and body.get("reply") is None):
        raise PlazaError(400, "bad_request", "send id with status (open, planned, done, dismissed) and/or reply")
    box = _box(h.board)
    row = box.answer(body["id"], body.get("status"), body.get("reply")) if hasattr(box, "answer") \
        else box.set(body["id"], body.get("status"), body.get("reply"))
    deals_api.note(h.board, row.get("team"), "suggestion", f"the host answered your suggestion: {row.get('status')}",
                   by="market")
    return {"suggestion": row}
