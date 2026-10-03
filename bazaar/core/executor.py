"""Executor: turns an Action into one API call. Never raises; every result is an Outcome in the ledger.

Accepts re-read the offer (or duel) first and go through rails.verify_fresh. Only the armed rail is
re-checked here; the full rails.check runs before (run.py), since that needs the whole Situation.
"""
from __future__ import annotations

import json
import time

from .. import config
from ..gateway import GameError
from . import rails
from .types import Action, Outcome

BROKER_FILE = config.LIVE / "broker.json"
SERVER_CODES = {"network", "timeout", "upstream", "server_error", "bad_json"}


def _tick(sit, ctx) -> int:
    for o in (ctx, sit):
        t = rails._get(o, "tick")
        if t is not None:
            return int(t)
    return -1


def broker_key() -> str | None:
    try:
        d = json.loads(BROKER_FILE.read_text())
    except (OSError, ValueError):
        return None
    return d.get("broker_key") or d.get("key") or d.get("X-Broker-Key")


def _offers_in(resp: dict) -> list[dict]:
    if isinstance(resp.get("offers"), list):
        return resp["offers"]
    if isinstance(resp.get("items"), list):
        return resp["items"]
    out = list(resp.get("standing_offers") or [])
    out += [m["offer"] for m in resp.get("messages") or [] if isinstance(m, dict) and m.get("offer")]
    for th in resp.get("threads") or []:
        out += _offers_in(th)
    return out


def fetch_offer(gw, action: Action) -> dict | None:
    """Fresh copy of the offer an accept targets: its thread, its venue, then /api/me/offers."""
    p = action.params or {}
    exp = p.get("expect") or {}
    oid = str(p.get("offer"))
    sources = []
    if p.get("thread") or exp.get("thread"):
        sources.append(f"/api/threads/{p.get('thread') or exp.get('thread')}")
    if p.get("venue") or exp.get("venue"):
        sources.append(f"/api/venues/{p.get('venue') or exp.get('venue')}/offers")
    sources.append("/api/me/offers")
    for path in sources:
        try:
            found = [o for o in _offers_in(gw.get(path)) if str(o.get("id")) == oid]
        except GameError:
            continue
        if found:
            return found[-1]
    return None


def fetch_duel(gw, did) -> dict | None:
    resp = gw.get("/api/duels")
    for d in resp.get("duels") or resp.get("items") or []:
        if str(d.get("duel", d.get("id"))) == str(did):
            return d
    return None


def _call(action: Action, gw):
    """(method, path, body, broker_key) for an action."""
    p = action.params or {}
    k = action.kind
    if k == "open_thread":
        body = {"with": p["with"]}
        for f in ("topic", "venue"):
            if p.get(f) is not None:
                body[f] = p[f]
        return "post", "/api/threads", body, None
    if k == "thread_message":
        body = {"text": p.get("text", "")}
        for f in ("price", "offer", "topic"):
            if p.get(f) is not None:
                body[f] = p[f]
        return "post", f"/api/threads/{p['thread']}/messages", body, None
    if k == "close_thread":
        return "post", f"/api/threads/{p['thread']}/close", {}, None
    if k == "accept_offer":
        # When the offer asks for a card type, `assets` names which of our copies we hand over.
        return "post", f"/api/offers/{p['offer']}/accept", ({"assets": list(p["assets"])} if p.get("assets") else {}), None
    if k == "post_offer":
        body = {"venue": p.get("venue", "rastro"), "give": p["give"], "want": p["want"]}
        for f in ("to", "expires_in_ticks"):
            if p.get(f) is not None:
                body[f] = p[f]
        return "post", "/api/offers", body, None
    if k == "cancel_offer":
        return "delete", f"/api/offers/{p['offer']}", None, None
    if k == "duel_message":
        body = {"text": p.get("text", "")}
        for f in ("price", "days"):
            if p.get(f) is not None:
                body[f] = p[f]
        return "post", f"/api/duels/{p['duel']}/messages", body, None
    if k == "duel_accept":
        return "post", f"/api/duels/{p['duel']}/accept", {}, None
    if k == "venue_open":
        body = {"name": p["name"], "fee_bps": int(p.get("fee_bps", 0)), "fee_per_card": int(p.get("fee_per_card", 0)),
                "rules": {"mechanism": p.get("mechanism", "board"), **(p.get("rules") or {})},
                "description": p.get("description", "")}
        return "post", "/api/venues", body, None
    if k == "venue_patch":
        body = {f: p[f] for f in ("fee_bps", "fee_per_card", "description", "rules") if p.get(f) is not None}
        return "patch", f"/api/venues/{p['venue']}", body, None
    if k == "open_pack":
        return "post", f"/api/packs/{int(p['asset'])}/open", {}, None
    if k == "broker_match":
        return "post", "/api/broker/matches", {"sell": p["sell"], "buy": p["buy"], "price": p["price"]}, "broker"
    if k == "broker_announce":
        return "post", "/api/broker/announce", {"text": p.get("text", "")}, "broker"
    raise ValueError(f"unknown action kind {k!r}")


def _realised(action: Action) -> dict:
    """What a successful send commits us to (read by ledger.spend_last_hour / deals_with)."""
    if action.kind != "accept_offer":
        return {}
    exp = (action.params or {}).get("expect") or {}
    give, want = exp.get("give") or {}, exp.get("want") or {}
    return {"cash_out": int(want.get("cash") or 0), "cash_in": int(give.get("cash") or 0),
            "counterparty": exp.get("maker")}


def execute(action: Action, gw, sit=None, ctx=None) -> Outcome:
    tick = _tick(sit, ctx)
    t0 = time.time()
    out = _execute(action, gw, sit, ctx, tick)
    out.response.setdefault("latency_s", round(time.time() - t0, 3))
    if action.kind != "noop":
        lg = rails._get(ctx, "ledger")
        if lg is None:
            from . import ledger as _ledger
            lg = _ledger.default()
        try:
            lg.outcome(out, action)
        except Exception:   # noqa: BLE001 - the ledger must not turn a sent action into an error
            pass
    return out


def _execute(action: Action, gw, sit, ctx, tick: int) -> Outcome:
    if action.kind == "noop":
        return Outcome(action.id, tick, "sent", {"noop": True})
    v = rails.rail_armed(action, sit, ctx)
    if not v.ok:
        return Outcome(action.id, tick, "vetoed", {"rail": v.rail, "detail": v.detail})
    try:
        if action.kind in ("accept_offer", "duel_accept"):
            fresh = fetch_offer(gw, action) if action.kind == "accept_offer" else fetch_duel(gw, action.params.get("duel"))
            v = rails.verify_fresh(action, fresh)
            if not v.ok:
                return Outcome(action.id, tick, "vetoed", {"rail": v.rail, "detail": v.detail})
        method, path, body, bk = _call(action, gw)
        if bk == "broker":
            bk = (action.params or {}).get("broker_key") or broker_key()
            if not bk:
                return Outcome(action.id, tick, "error", {"error": "no_broker_key", "message": str(BROKER_FILE)})
        if method == "delete":
            resp = gw.delete(path)
        elif method == "patch":
            resp = gw.patch(path, body)
        else:
            resp = gw.post(path, body, broker_key=bk) if bk else gw.post(path, body)
        if action.kind == "venue_open" and isinstance(resp, dict):
            # The response carries the broker key: store it (0600) and never let it reach the ledger.
            from bazaar.broker import venue as _venue
            _venue.save_from_response(resp)
            resp = _venue.redact(resp)
        return Outcome(action.id, tick, "sent", resp if isinstance(resp, dict) else {"items": resp}, _realised(action))
    except GameError as e:
        status = "error" if (e.code in SERVER_CODES or e.status >= 500) else "refused"
        return Outcome(action.id, tick, status, {"error": e.code, "message": e.message[:300], "http": e.status,
                                                 **({"next_tick_in": e.next_tick_in} if e.next_tick_in else {})})
    except (KeyError, ValueError, TypeError) as e:
        return Outcome(action.id, tick, "error", {"error": "bad_action", "message": f"{type(e).__name__}: {e}"})
    except Exception as e:  # noqa: BLE001 - never raise into the tick loop
        return Outcome(action.id, tick, "error", {"error": "internal", "message": f"{type(e).__name__}: {e}"[:300]})
