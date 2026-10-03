"""A human's own conversation with a dealer, from the dashboard ("Hablar con un dealer").

GET  /dealer-chat?dealer=banco          the dealers, our open thread with that dealer and what it is worth
POST /dealer-chat/send    {"dealer", "text", "side": "buy|sell", "item", "price"}   opens the thread if needed
POST /dealer-chat/accept  {"thread", "offer", "confirm": true}   without confirm: only the value check
POST /dealer-chat/close   {"thread"}
POST /dealer-chat/release {"thread"}    hand the thread back to the bot

The game routes are the ones the bot uses (core.executor): POST /api/threads, /api/threads/{id}/messages,
/api/threads/{id}/close and /api/offers/{id}/accept. A thread touched here is written to
control.manual_threads; bazaar.dealers.domain leaves those threads alone and opens no other thread with
that dealer. Accept never loses value and never passes the cash reserve or the per-deal cap.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import config
from ..dealers.values import Values, pack_value

DEFAULT_DEALER = "banco"


def gateway():
    from ..gateway import Gateway
    return Gateway(real=config.ALLOW_REAL)


def _control(live: Path) -> dict:
    from ..run import DEFAULT_CONTROL, load_control
    return load_control(live, DEFAULT_CONTROL)


def manual_ids(control: dict) -> set[int]:
    return {int(x) for x in (control or {}).get("manual_threads") or [] if str(x).isdigit()}


def _mark(live: Path, thread: int, on: bool = True) -> list[int]:
    """Add or remove a thread in control.manual_threads (the bot reads control every tick)."""
    live = Path(live)
    from .server import _control_lock
    with _control_lock:
        cur = _control(live)
        ids = manual_ids(cur)
        (ids.add if on else ids.discard)(int(thread))
        cur["manual_threads"] = sorted(ids)
        cur["updated"] = time.time()
        tmp = live / "control.tmp"
        tmp.write_text(json.dumps(cur, indent=1))
        tmp.replace(live / "control.json")
    return sorted(ids)


def _threads(gw) -> list[dict]:
    r = gw.get("/api/me/threads", status="open")
    return [t for t in ((r.get("threads") if isinstance(r, dict) else r) or []) if isinstance(t, dict)]


def _thread_with(gw, dealer: str, threads: list[dict] | None = None) -> dict | None:
    return next((t for t in (_threads(gw) if threads is None else threads) if t.get("kind", "persona") == "persona" and t.get("with") == dealer
                 and t.get("status", "open") == "open"), None)


_CATALOG: dict = {"at": 0.0, "doc": {}}


def _catalog(gw) -> dict:
    if _CATALOG["doc"] and time.time() - _CATALOG["at"] < 300:
        return _CATALOG["doc"]
    try:
        c = gw.get("/api/catalog")
    except Exception:  # noqa: BLE001
        return _CATALOG["doc"]
    if isinstance(c, dict) and c:
        _CATALOG.update(at=time.time(), doc=c)
    return _CATALOG["doc"]


def _side_value(side: dict, gw, me: dict, values: Values, giving: bool) -> tuple[float, bool, list[str]]:
    """(value to us, known, item names) of one side of an offer. `giving`: the side we hand over."""
    side = side or {}
    total, known, names = float(side.get("cash") or 0), True, []
    held = {a.get("id"): a for a in me.get("assets") or []}
    for a in side.get("assets") or []:
        aid = a.get("id") if isinstance(a, dict) else a
        mine = held.get(aid) or (a if isinstance(a, dict) else {})
        names.append(str(mine.get("ref") or f"asset {aid}"))
        v = mine.get("your_value")
        if v is None and mine.get("ref"):
            v = gw.value(str(mine["ref"]))
        if v is None:
            known = False
        total += float(v or 0)
    for ty in side.get("types") or []:
        kind, _, ref = str(ty).partition(":")
        names.append(ref or kind)
        if kind == "card" and giving:              # we choose which copy: the one worth least to us
            mine = sorted(float(a["your_value"]) for a in me.get("assets") or []
                          if a.get("ref") == ref and a.get("your_value") is not None)
            if mine:
                total += mine[0]
            else:
                known = False
        elif kind == "card":
            v = gw.value(ref)
            if v is None:
                known = False
            total += float(v or 0)
        elif kind == "pack" and values.catalog:
            total += pack_value(ref, values)
        else:
            known = False
    return round(total, 2), known, names


def check(offer: dict, gw, me: dict, control: dict) -> dict:
    """What accepting `offer` (made by the dealer) does to us: value in, value out, and why it may not go."""
    values = Values(me, _catalog(gw), {})
    get, known_get, get_names = _side_value(offer.get("give") or {}, gw, me, values, giving=False)
    give, known_give, give_names = _side_value(offer.get("want") or {}, gw, me, values, giving=True)
    pay = int((offer.get("want") or {}).get("cash") or 0)
    cash = int(me.get("cash") or 0)
    reserve = int(control.get("cash_reserve", config.CASH_RESERVE))
    per_deal = int(control.get("max_spend_per_deal", config.MAX_SPEND_PER_DEAL))
    known = known_get and known_give
    gain = round(get - give, 2)
    blocked = None
    if offer.get("status", "open") != "open":
        blocked = f"la oferta ya no está abierta ({offer.get('status')})"
    elif pay > cash - reserve:
        blocked = f"pagar {pay} P deja la caja por debajo de la reserva de {reserve} P (caja {cash} P)"
    elif pay > per_deal:
        blocked = f"pagar {pay} P supera el tope por trato de {per_deal} P"
    elif not known:
        blocked = "no conocemos nuestro valor de alguna carta de la oferta"
    elif gain < 0:
        blocked = f"perdemos valor: recibimos {get} y damos {give}"
    return {"offer": offer.get("id"), "we_get": get_names, "we_give": give_names, "pay": pay,
            "receive_cash": int((offer.get("give") or {}).get("cash") or 0), "value_get": get, "value_give": give,
            "gain": gain, "known": known, "cash": cash, "reserve": reserve, "per_deal": per_deal,
            "final": bool(offer.get("final")), "blocked": blocked}


def _standing(thread: dict, dealer: str) -> dict | None:
    """The dealer's open offer in the thread, if any."""
    for o in thread.get("standing_offers") or []:
        if isinstance(o, dict) and o.get("maker") == dealer and o.get("status", "open") == "open":
            return o
    for m in reversed(thread.get("messages") or []):
        o = m.get("offer") or {}
        if m.get("sender") == dealer and o.get("status") == "open":
            return o
    return None


def state(live: Path, dealer: str = DEFAULT_DEALER, gw=None) -> dict:
    gw = gw or gateway()
    control = _control(live)
    me = gw.get("/api/me") or {}
    personas = [p for p in ((gw.get("/api/dealers") or {}).get("personas") or []) if isinstance(p, dict)]
    unlocked = set(me.get("unlocked") or [])
    dealers = [{"id": p.get("id"), "name": p.get("name"), "level": p.get("level"), "status": p.get("status"),
                "unlocked": p.get("id") in unlocked or bool(p.get("open_to_all")), "menu": p.get("menu") or {}}
               for p in personas if p.get("kind", "dealer") == "dealer" or p.get("menu")]
    threads = _threads(gw)
    thread = _thread_with(gw, dealer, threads)
    open_ids = {int(t.get("id") or 0) for t in threads}
    for gone in manual_ids(control) - open_ids:        # a finished thread needs no guard any more
        control["manual_threads"] = _mark(live, gone, on=False)
    out = {"dealer": dealer, "dealers": dealers, "cash": int(me.get("cash") or 0), "team": me.get("id"),
           "manual_threads": sorted(manual_ids(control)), "thread": None, "standing": None, "check": None,
           "cards": sorted({a["ref"]: {"id": a.get("id"), "ref": a["ref"], "rarity": a.get("rarity"),
                                       "value": a.get("your_value")}
                            for a in me.get("assets") or [] if a.get("ref")}.values(), key=lambda c: c["ref"])}
    if thread:
        out["thread"] = {"id": thread.get("id"), "topic": thread.get("topic"), "created_tick": thread.get("created_tick"),
                         "manual": int(thread.get("id") or 0) in manual_ids(control),
                         "messages": [{"id": m.get("id"), "tick": m.get("tick"), "sender": m.get("sender"),
                                       "text": m.get("text"), "offer": m.get("offer")}
                                      for m in thread.get("messages") or []]}
        standing = _standing(thread, dealer)
        if standing:
            out["standing"] = standing
            out["check"] = check(standing, gw, me, control)
    return out


def _topic(side: str, item: str, me: dict) -> dict:
    item = str(item or "").strip()
    if side not in ("buy", "sell") or not item:
        raise ValueError("para abrir el hilo elige comprar o vender y la carta o el sobre")
    if side == "buy":
        return {"buy": {"pack": item}} if item.lower().startswith("sobre") else {"buy": {"card": item.upper()}}
    mine = sorted((a for a in me.get("assets") or [] if str(a.get("ref")) == item.upper()),
                  key=lambda a: float(a.get("your_value") or 0))
    if not mine:
        raise ValueError(f"no tenemos {item.upper()}")
    return {"sell": {"assets": [mine[0]["id"]]}}      # the copy worth least to us


def send(live: Path, body: dict, gw=None) -> dict:
    gw = gw or gateway()
    dealer = str(body.get("dealer") or DEFAULT_DEALER)
    text = str(body.get("text") or "").strip()[:1000]
    price = body.get("price")
    if price in ("", None):
        price = None
    elif isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
        raise ValueError("el precio debe ser un número mayor que 0")
    thread = _thread_with(gw, dealer)
    opened = False
    if thread is None:
        me = gw.get("/api/me") or {}
        made = gw.post("/api/threads", {"with": dealer, "topic": _topic(str(body.get("side") or ""), body.get("item"), me)}) or {}
        thread = made.get("thread") if isinstance(made.get("thread"), dict) else made
        if not thread.get("id"):
            thread = _thread_with(gw, dealer) or {}
        if not thread.get("id"):
            raise ValueError("el juego no devolvió el hilo abierto")
        opened = True
    tid = int(thread["id"])
    _mark(live, tid)                                   # before the message: the bot must not answer in between
    sent = None
    if text or price is not None:
        msg = {"text": text or f"{int(price)} P."}
        if price is not None:
            msg["price"] = int(price)
        sent = gw.post(f"/api/threads/{tid}/messages", msg)
    return {"thread": tid, "opened": opened, "sent": sent}


def accept(live: Path, body: dict, gw=None) -> dict:
    gw = gw or gateway()
    dealer = str(body.get("dealer") or DEFAULT_DEALER)
    thread = _thread_with(gw, dealer)
    standing = _standing(thread, dealer) if thread else None
    if not standing or (body.get("offer") is not None and int(body["offer"]) != int(standing.get("id") or 0)):
        raise ValueError("esa oferta ya no es la oferta abierta del dealer: recarga el hilo")
    me = gw.get("/api/me") or {}
    chk = check(standing, gw, me, _control(live))
    if chk["blocked"]:
        return {"accepted": False, "check": chk}
    if body.get("confirm") is not True:
        return {"accepted": False, "needs_confirm": True, "check": chk}
    _mark(live, int(thread["id"]))
    payload = {}
    wanted = [str(t)[5:] for t in (standing.get("want") or {}).get("types") or [] if str(t).startswith("card:")]
    if wanted:                                          # the offer asks for a card type: hand over our cheapest copy
        ids = []
        for ref in wanted:
            mine = sorted((a for a in me.get("assets") or [] if a.get("ref") == ref and a.get("id") not in ids),
                          key=lambda a: float(a.get("your_value") or 0))
            if mine:
                ids.append(mine[0]["id"])
        payload = {"assets": ids}
    return {"accepted": True, "check": chk, "result": gw.post(f"/api/offers/{int(standing['id'])}/accept", payload)}


def close(live: Path, body: dict, gw=None) -> dict:
    gw = gw or gateway()
    tid = int(body.get("thread") or 0)
    if not tid:
        raise ValueError("falta el hilo")
    res = gw.post(f"/api/threads/{tid}/close", {})
    return {"closed": tid, "result": res, "manual_threads": _mark(live, tid, on=False)}


def release(live: Path, body: dict) -> dict:
    tid = int(body.get("thread") or 0)
    if not tid:
        raise ValueError("falta el hilo")
    return {"released": tid, "manual_threads": _mark(live, tid, on=False)}
