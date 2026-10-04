"""The work queue of a team's agent: the next concrete requests it sends, in order, with its own game key.

    next(team)  -> actions: sync your cards, post this addressed offer on the venue, accept offer N, counter at X
    ack(id)     -> done or failed

The plaza never acts in the game: it tells the agent what to send. Each trade runs in mode `auto` (the agent goes
ahead only at a price the market suggested or the team itself named, and only when the team set a limit that the
price respects; a price the other side chose, or a card with no limit, is handed to the agent as `decide`) or `ask_me` (it waits for the human, who orders Accept,
Counter at a price or Pass from the page; the order becomes an action here). An action carries only its own team's
data: the other side's limits are never in it."""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from . import safe
from .store import MAX_PRICE, PlazaError

NO_SHEET = ("YOU ARE NOT DONE: publish your sheet NOW with PUT /plaza/api/team/<your team> (your duplicates in spares, "
            "the cards you miss in wants, every card you hold in have, with your own min and max); without it you get "
            "no deals. Then keep polling GET /plaza/api/agent/next for ever")
MODES = ("auto", "ask_me")
ORDERS = ("accept", "counter", "pass")
SYNC_EVERY_S = 600.0
RETRY_S = 60.0
MAX_TRIES = 3
KEEP_ACKS = 300
POLL_S = 20


def _id(*parts) -> str:
    return "a-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


class AgentQ:
    def __init__(self, path: Path | str, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.lock = threading.RLock()
        data = safe.load(self.path)
        self.data: dict[str, dict] = {k: v for k, v in data.items() if isinstance(v, dict)}

    def _save(self) -> None:
        safe.save(self.path, self.data)

    def _team(self, team: str) -> dict:
        t = self.data.setdefault(team, {})
        t.setdefault("default", "auto")
        t.setdefault("modes", {})
        t.setdefault("orders", {})
        t.setdefault("acks", {})
        return t

    # ---- the human, from the page
    def settings(self, team: str) -> dict:
        with self.lock:
            t = self._team(team)
            return {"default_mode": t["default"], "modes": dict(t["modes"]), "orders": dict(t["orders"])}

    def set_mode(self, team: str, mode, match: str | None = None) -> None:
        if mode not in MODES:
            raise PlazaError(400, "bad_request", "mode is auto or ask_me")
        with self.lock:
            t = self._team(team)
            if match is None:
                t["default"] = mode
            else:
                t["modes"][match] = mode
            self._save()

    def order(self, team: str, match: str, action, price=None) -> dict:
        if action not in ORDERS:
            raise PlazaError(400, "bad_request", "order is accept, counter or pass")
        o = {"action": action, "ts": self.clock()}
        if action == "counter":
            if isinstance(price, bool) or not isinstance(price, (int, float)) or not 0 < price <= MAX_PRICE:
                raise PlazaError(400, "bad_request", f"a counter needs a price between 1 and {MAX_PRICE}")
            o["price"] = int(round(price))
        with self.lock:
            self._team(team)["orders"][match] = o
            self._save()
        return o

    # ---- the agent
    def ack(self, team: str, action_id, status, note=None) -> dict:
        if not isinstance(action_id, str) or not action_id.startswith("a-") or len(action_id) != 14:
            raise PlazaError(400, "bad_request", "id is the id of an action from /plaza/api/agent/next")
        if status not in ("done", "failed"):
            raise PlazaError(400, "bad_request", "status is done or failed")
        if note is not None and not isinstance(note, str):
            raise PlazaError(400, "bad_request", "note is a short text")
        with self.lock:
            t = self._team(team)
            a = t["acks"].get(action_id) or {"tries": 0}
            if a.get("status") == "done":                       # acknowledged already: the same answer again
                return {"id": action_id, **a}
            a = {"status": status, "ts": self.clock(), "tries": a["tries"] + 1,
                 **({"note": " ".join(note.split())[:200]} if note else {})}
            t["acks"][action_id] = a
            if len(t["acks"]) > KEEP_ACKS:
                for k in sorted(t["acks"], key=lambda k: t["acks"][k]["ts"])[:len(t["acks"]) - KEEP_ACKS]:
                    t["acks"].pop(k, None)
            for mid, o in list(t["orders"].items()):            # an order is spent once its action is done
                if o.get("id") == action_id and status == "done":
                    t["orders"].pop(mid, None)
            self._save()
            return {"id": action_id, **a}

    def build(self, team: str, matches: list[dict], within, declared_at: float | None, tick: int | None,
              tick_s: float | None = None) -> dict:
        """The ordered actions for `team`. `matches` are its live matches, unmasked, each with its recipe;
        `within(ref, role, price)` answers from the team's OWN limits."""
        now = self.clock()
        actions, waiting, failed = [], [], []
        with self.lock:
            t = self._team(team)
            live = {m["id"] for m in matches}
            for mid in [k for k in t["orders"] if k not in live]:
                t["orders"].pop(mid, None)

            def add(kind: str, match: dict | None, why: str, request: dict, *key, **extra) -> None:
                aid = _id(team, kind, match["id"] if match else "", *key)
                ack = t["acks"].get(aid)
                if ack and ack["status"] == "done":
                    return
                if ack and ack["tries"] >= MAX_TRIES:
                    failed.append({"id": aid, "type": kind, "match": match["id"] if match else None,
                                   "note": ack.get("note")})
                    return
                if ack and now - ack["ts"] < RETRY_S:
                    return
                actions.append({"id": aid, "type": kind, **({"match": match["id"]} if match else {}), "why": why,
                                "request": request, **extra})

            if declared_at is None:                         # no sheet yet: asked every time, whatever was acknowledged
                actions.append({"id": _id(team, "sync_cards", "", 0), "type": "sync_cards", "why": NO_SHEET,
                                "request": {"target": "plaza", "method": "PUT", "path": f"/plaza/api/team/{team}",
                                            "auth": "X-Plaza-Token",
                                            "body": {"wants": ["<refs you miss>"], "spares": ["<your duplicates>"],
                                                     "for_sale": ["<refs you would sell>"],
                                                     "have": ["<every ref you hold>"]}}})
            elif now - declared_at > SYNC_EVERY_S:
                add("sync_cards", None, "publish your current duplicates, cards for sale and wants",
                    {"target": "plaza", "method": "PUT", "path": f"/plaza/api/team/{team}", "auth": "X-Plaza-Token",
                     "body": {"wants": ["<refs you miss>"], "spares": ["<your duplicates>"],
                              "for_sale": ["<refs you would sell>"], "have": ["<every ref you hold>"]}},
                    int(declared_at or 0))
            for m in matches:
                mid, kind = m["id"], m["kind"]
                msg = lambda body: {"target": "plaza", "method": "POST", "auth": "X-Plaza-Token",   # noqa: E731
                                    "path": f"/plaza/api/match/{mid}/message", "body": body}
                order = t["orders"].get(mid)
                mode = t["modes"].get(mid, t["default"])
                if kind == "triangle":
                    waiting.append({"match": mid, "why": "three-way swap: agree on the thread first"})
                    continue
                role = "seller" if team == m["seller"] else "buyer"
                price = m.get("price") or 0
                if order and order["action"] == "pass":
                    order["id"] = _id(team, "pass", mid, order["ts"])
                    add("pass", m, "your human passed on this trade", msg({"action": "pass"}), order["ts"])
                    continue
                if order and order["action"] == "counter":
                    order["id"] = _id(team, "counter", mid, order["ts"])
                    add("counter", m, f"your human counters at {order['price']} P",
                        msg({"action": "counter", "price": order["price"]}), order["ts"])
                    continue
                agreed = team in (m.get("agreed") or [])       # its own word, at the price now on the table
                inside = True if kind == "swap" else within(m["ref"], role, price)
                # auto goes ahead only at a price nobody else chose: the market's own suggestion or the team's own
                # counter, and only when the team set a limit that says it takes it. Anything else is the agent's call.
                # A match the host forced was priced by hand, not by the rule: always the agent's call.
                ours = (kind == "swap" or m.get("price_by") in (None, team)) and not m.get("forced")
                go = bool(order and order["action"] == "accept") or (mode == "auto" and (agreed or (inside is True and ours)))
                if not go:
                    if mode == "auto":
                        why = ("you set no limit for this card, so nothing says you take this price: accept, counter or pass"
                               if inside is None else
                               "the price on the table is outside your own limits: counter or pass" if inside is False else
                               "the host proposed this trade by hand: accept, counter or pass" if m.get("forced") else
                               "the other team set this price: accept, counter or pass")
                        add("decide", m, why, msg({"action": "counter", "price": "<your price>"}), m["state"], price,
                            price=price, options=[{"action": "accept"}, {"action": "counter", "price": "<your price>"},
                                                  {"action": "pass"}])
                    else:
                        waiting.append({"match": mid, "why": "ask_me: waiting for your human"})
                    continue
                stamp = order["ts"] if order else 0
                recipe = m.get("recipe") or {}
                first = recipe.get("buyer") if kind == "sale" else recipe.get("first")
                poster = m["buyer"] if kind == "sale" else m["seller"]
                if m["state"] == "proposed":
                    if team == poster:
                        game = {"target": "game", "auth": "your own game key", "method": first["method"],
                                "path": first["path"], "body": first["body"]}
                        aid = _id(team, "post_offer", mid, price, stamp)
                        if order:
                            order["id"] = aid
                        venue = m.get("venue") or first["body"].get("venue")
                        add("post_offer", m, f"post this addressed offer in the game, on venue {venue} and nowhere "
                            f"else: only a sale on {venue} is fee-free and counts for this market", game, price, stamp,
                            then={"target": "plaza", "method": "POST", "auth": "X-Plaza-Token",
                                  "path": f"/plaza/api/me/trade/{mid}",
                                  "body": {"offer_id": "<the id the game gave your offer>"}})
                        wrong = m.get("elsewhere_offer")
                        if wrong and wrong.get("maker") == team:
                            add("move_offer", m, f"your offer {wrong['id']} for this match is on {wrong['venue']}: "
                                f"cancel it and post it on {venue}",
                                {"target": "game", "auth": "your own game key", "method": "DELETE",
                                 "path": f"/api/offers/{wrong['id']}", "body": {}}, wrong["id"])
                    elif not agreed:
                        aid = _id(team, "agree", mid, price, stamp)
                        if order:
                            order["id"] = aid
                        add("agree", m, "tell the other side you take these terms; it then posts the offer",
                            msg({"action": "accept"}), price, stamp)
                    else:
                        waiting.append({"match": mid, "why": "waiting for the other side to post the offer"})
                elif m.get("offer_maker") == team:
                    waiting.append({"match": mid, "why": "your offer is on the venue; waiting for the accept"})
                else:                                          # offer_on_v07 or accepted, and the offer is the other's
                    give = m["ref"] if team == m["seller"] else m.get("ref_back")
                    body = {"assets": [f"<your asset id of {give}>"]} if give and (kind == "swap" or role == "seller") else {}
                    aid = _id(team, "confirm", mid, m["offer"], stamp)
                    if order:
                        order["id"] = aid
                    add("accept_offer", m, f"accept offer {m['offer']} in the game (it is on venue {m.get('venue') or 'v07'})",
                        {"target": "game", "auth": "your own game key", "method": "POST",
                         "path": f"/api/offers/{m['offer']}/accept", "body": body}, m["offer"], stamp, offer=m["offer"])
                    if m["state"] == "offer_on_v07":
                        add("confirm", m, "say on the thread that you accepted", msg({"action": "accept"}), m["offer"], stamp)
                    else:
                        waiting.append({"match": mid, "why": "accepted; waiting for the game to settle it"})
            self._save()
        # ask again within a tick while something is moving; otherwise every couple of ticks is plenty
        one = max(2, min(POLL_S, int(tick_s))) if tick_s else 5
        busy = bool(actions or waiting or matches)
        nxt = (NO_SHEET if declared_at is None else
               "run each action in order and POST /plaza/api/agent/ack for each; then keep polling "
               "GET /plaza/api/agent/next for ever (an agent that stops polling is shown OFFLINE and gets no deals)")
        return {"team": team, "verified": True, "tick": tick, "actions": actions, "waiting": waiting, "failed": failed,
                "poll_after_s": one if busy else min(60, max(POLL_S, 2 * one)), "default_mode": t["default"],
                "next": nxt}
