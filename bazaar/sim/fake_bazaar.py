"""A local fake of the Bazaar API for end-to-end bot tests. Never talks to the real game.

    .venv/bin/python -m bazaar.sim.fake_bazaar                    # http://127.0.0.1:8797, a tick every 2 s
    .venv/bin/python -m bazaar.sim.fake_bazaar --manual --seed 7  # ticks only on POST /sim/tick
    Gateway(url="http://127.0.0.1:8797", token="sim", real=True)  # from the bot

Auth: `X-Team-Key: sim` (any other key is a 401 `bad_key`; public reads work without a key) and
`X-Broker-Key: sim-broker` for /api/broker/*. We are t10 (LAV 1.6, MAL 1.3, RET 1.1, SAL 0.9, CHA 0.7, LAT 0.5),
starting with 400 P and 11 commons, 3 uncommons and 1 rare.

What it plays (catalog, dealer menus, schedule and venues come from real snapshots in bazaar/sim/data/):
- Clock and limits: one accept per team per tick (duels and offers share it), one message per conversation per tick,
  12 new offers per tick, 6 threads, 30 open offers; accepts settle at the next tick; real error codes
  (wait_for_tick with next_tick, insufficient_cash, thread_open, persona_quota, cooloff with until_tick, missing_days,
  offer_gone, not_yours, too_many_offers, ...).
- Dealers (bazaar.sim.models.DealerThread): Abuela and El Chato calibrated on Friday, per-hour quotas, offers that
  expire after 2 ticks, final offers, cooloffs. A third dealer, "vault" (La Bóveda), is announced from the start and
  activated at `vault_at_tick` (default 40) to test novelty handling.
- El Rastro: synthetic teams t01..t18 list cards and bids (fee 5 % + 1 P per card, paid out of the cash side) and
  buy our listings below their hidden valuation. They also haggle with dealers, so the public feed looks alive.
- Duels: a price-only session at `duel_at_tick` (default 5, decay 0.06) and a price+days session at
  `days_duel_at_tick` (default 60, decay 0.08), rivals of kinds fixed/stepped/tough/mute/injector.
- Venues and the Market Test: POST /api/venues opens our venue (level 2 needed, bond 250 + 20). A bench session starts
  at `bench_at_tick` (default 20) and lasts `bench_ticks` (16). Without our own `board` venue the starter auto stall
  crosses by quotes each tick.

Bench offers (GET /api/broker/book -> "bench_offers") come from BROKER's generator, bazaar.broker.sim_book.SimSession
(the same traders the broker engine is tuned on), in the shape the SDK's starter_broker.py reads, plus "maker",
"side" and "venue":
    seller: {"id": "b1-3", "maker": "bench", "side": "sell", "venue": <ours>, "created_tick": 0,
             "give": {"cash": 0, "assets": [{"kind": "card", "ref": "LAV-02"}], "types": []},
             "want": {"cash": 14, "assets": [], "types": []}}
    buyer:  {"id": "b1-4", "maker": "bench", "side": "buy", "venue": <ours>, "created_tick": 0,
             "give": {"cash": 11, "assets": [], "types": []},
             "want": {"cash": 0, "assets": [], "types": ["card:LAV-02"]}}
The run is the part of the id before "-". Quotes are shaded away from hidden limits and relax with impatience (firm
traders never do); some traders arrive late or leave early. POST /api/broker/matches {"sell", "buy", "price"} is
refused (409 price_outside / offer_gone) unless the price sits inside both live quotes (World(bench_cross_rule=
"limits") checks the hidden limits instead). On an auto venue (the starter stall) the engine crosses by quotes every
tick. Efficiency = realised gains between true limits / best possible (GET /sim/state -> bench.history).

Sim-only routes: GET /sim/state, POST /sim/tick ({"n": 3} optional), POST /sim/control with any of
{"limits": {...}}, {"tick_seconds": s}, {"paused": bool}, {"activate_level": "vault"}, {"start_duels": {"issues":
["price","days"]}}, {"start_bench": true}, {"cash": n}.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bazaar import config
from bazaar.sim import models
from bazaar.sim.models import DEALER_PROFILES, DealerThread, DuelRival, duel_points, make_duel_scenario

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
TEAM = "t10"
TEAM_KEY = "sim"
BROKER_KEY = "sim-broker"
AFFINITY = {"LAV": 1.6, "MAL": 1.3, "RET": 1.1, "SAL": 0.9, "CHA": 0.7, "LAT": 0.5}
MULTS = [1.6, 1.3, 1.1, 0.9, 0.7, 0.5]
DEFAULT_LIMITS = {"accepts_per_team_per_tick": 1, "messages_per_side_per_tick": 1, "max_open_threads_per_team": 6,
                  "max_open_offers_per_team": 30, "offers_per_team_per_tick": 12}
RIVAL_ALIASES = ["Rival Azul", "Rival Oro", "Rival Plata", "Rival Sol", "Rival Luna", "Rival Noche", "Rival Verde"]


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = "", **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def _load(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text())


def _new_bench_session(seed: int, params: dict, hard: bool, run: str, cross_rule: str):
    """The Market Test book: BROKER's generator (bazaar.broker.sim_book.SimSession) so the broker is tested against the
    same traders it was tuned on. cross_rule "quotes": a match price must sit inside both live quotes; "limits":
    inside the hidden limits."""
    from bazaar.broker.sim_book import SimSession
    return SimSession.generate(seed, params, hard, run=run, cross_rule=cross_rule)


def _stall_plan(bench: list[dict]) -> list[tuple]:
    """What the free auto stall does: highest bid against lowest ask while the bid covers it, at the midpoint."""
    asks = sorted(((o["want"]["cash"], o["id"]) for o in bench if o["want"]["cash"]), key=lambda a: a[0])
    bids = sorted(((o["give"]["cash"], o["id"]) for o in bench if o["give"]["cash"]), key=lambda b: -b[0])
    plan = []
    for (ask, sell), (bid, buy) in zip(asks, bids):
        if bid < ask:
            break
        plan.append((sell, buy, (ask + bid) // 2))
    return plan


class World:
    def __init__(self, seed: int | None = None, tick_seconds: float = 2.0, manual: bool = False, cash: int = 400,
                 vault_at_tick: int = 40, duel_at_tick: int | None = 5, days_duel_at_tick: int | None = 60,
                 bench_at_tick: int | None = 20, bench_ticks: int = 16, chato_open_at_tick: int = 10,
                 ticks_per_hour: int = 120, duels_per_session: int = 6, duel_ticks: int = 16,
                 max_concurrent: int = 3, synthetic_activity: bool = True, bench_cross_rule: str = "quotes"):
        self.rng = random.Random(seed)
        self.lock = threading.RLock()
        self.catalog = _load("catalog")
        self.cards = {c["id"]: {**c, "set": s["id"], "released": s.get("released", False)}
                      for s in self.catalog["sets"] for c in s["cards"]}
        self.tick, self.tick_seconds, self.manual, self.paused = 0, float(tick_seconds), manual, False
        self.next_tick_at = time.time() + self.tick_seconds
        self.ticks_per_hour = ticks_per_hour
        self.limits = dict(DEFAULT_LIMITS)
        self.cash = cash
        self.level, self.unlocked = 1, ["abuela"]
        self.next_id = 1000
        self.assets: dict[int, dict] = {}
        self.threads: dict[int, dict] = {}
        self.models: dict[int, DealerThread] = {}
        self.offers: dict[int, dict] = {}
        self.pending: list = []
        self.accepted_tick = None
        self.said: set = set()
        self.posted_this_tick = 0
        self.events: list[dict] = []
        self.settled: list[dict] = []
        self.flags: list[dict] = []
        self.duels: dict[int, dict] = {}
        self.rivals: dict[int, DuelRival] = {}
        self.duel_queue: list[int] = []
        self.sessions = 0
        self.max_concurrent = max_concurrent
        self.duels_per_session, self.duel_ticks = duels_per_session, duel_ticks
        self.deals_by_hour: dict = {}
        self.cooloff: dict[str, int] = {}
        self.vault_at_tick, self.duel_at_tick, self.days_duel_at_tick = vault_at_tick, duel_at_tick, days_duel_at_tick
        self.bench_at_tick, self.bench_ticks, self.chato_open_at_tick = bench_at_tick, bench_ticks, chato_open_at_tick
        self.synthetic_activity = synthetic_activity
        self.ladder: dict[str, list[float]] = {}
        self.value_gained = 0.0
        self.duel_points_total = 0.0
        self.bench: dict | None = None
        self.bench_cross_rule = bench_cross_rule
        self.bench_history: list[dict] = []
        self.dealers = self._init_dealers()
        self.venues = self._init_venues()
        self.my_venue: str | None = None
        self.fake_teams = [f"t{n:02d}" for n in range(1, 19) if n != 10]
        self.team_aff = {t: dict(zip(list(AFFINITY), self.rng.sample(MULTS, 6))) for t in self.fake_teams}
        self.board = {t: {"score": 0.0, "negotiating": 0.0, "market": 0.0, "deals": 0, "level": 1,
                          "album_filled": 15, "pages_complete": 0, "venue": None} for t in self.fake_teams}
        self.lb_snapshot: dict = {}
        self._deal_starter_hand()
        for _ in range(12):  # the opening book on El Rastro
            self._synthetic_listing()
        self._snapshot_leaderboard()

    # --- helpers ------------------------------------------------------------------------------------------------
    def nid(self) -> int:
        self.next_id += 1
        return self.next_id

    def t_hours(self) -> float:
        return round(self.tick / self.ticks_per_hour, 4)

    def hour(self) -> int:
        return self.tick // self.ticks_per_hour

    def event(self, etype: str, actor: str = "", scope: str = "public", **payload) -> dict:
        e = {"id": len(self.events) + 1, "tick": self.tick, "t": self.t_hours(), "type": etype, "scope": scope,
             "actor": actor, "payload": payload}
        self.events.append(e)
        return e

    def released_refs(self, rarity: str, set_id: str | None = None) -> list[str]:
        return [r for r, c in self.cards.items() if c["released"] and c["rarity"] == rarity
                and (set_id is None or c["set"] == set_id)]

    def pick(self, rarity: str, set_id: str | None = None) -> str:
        refs = self.released_refs(rarity, set_id) or self.released_refs(rarity)
        return self.rng.choice(refs)

    def card_asset(self, ref: str) -> dict:
        c = self.cards[ref]
        return {"id": self.nid(), "kind": "card", "ref": ref, "serial": self.rng.randint(1, c["print_run"]),
                "rarity": c["rarity"], "set": c["set"], "print_run": c["print_run"], "name": c["name"]}

    def give_card(self, ref: str) -> dict:
        a = self.card_asset(ref)
        self.assets[a["id"]] = a
        return a

    def _deal_starter_hand(self):
        for r in ["common"] * 11 + ["uncommon"] * 3 + ["rare"]:
            self.give_card(self.pick(r))

    def value(self, ref: str, copy_index: int | None = None) -> float:
        c = self.cards[ref]
        held = copy_index if copy_index is not None else sum(1 for a in self.assets.values() if a.get("ref") == ref)
        m = self.catalog["values"]["copy_marginals"]
        return round(c["book"] * AFFINITY.get(c["set"], 1.0) * (m[held] if held < len(m) else m[-1]), 2)

    def asset_view(self, a: dict) -> dict:
        if a["kind"] != "card":
            return dict(a)
        same = sorted((x["id"] for x in self.assets.values() if x.get("ref") == a["ref"]))
        return {**a, "your_value": self.value(a["ref"], len(same) - 1)}

    def collection_value(self) -> float:
        total, seen = 0.0, {}
        for a in sorted(self.assets.values(), key=lambda a: a["id"]):
            if a["kind"] == "card":
                n = seen.get(a["ref"], 0)
                total += self.value(a["ref"], n)
                seen[a["ref"]] = n + 1
        return round(total, 2)

    def once_per_tick(self, key) -> None:
        if key in self.said:
            raise ApiError(429, "wait_for_tick", "one message per conversation per tick", next_tick=self.tick + 1)
        self.said.add(key)

    def use_accept(self) -> None:
        if self.accepted_tick == self.tick:
            raise ApiError(429, "wait_for_tick", "one accept per team per tick", next_tick=self.tick + 1)
        self.accepted_tick = self.tick

    # --- dealers / levels ---------------------------------------------------------------------------------------
    def _init_dealers(self) -> dict:
        snap = {p["id"]: p for p in _load("dealers")["personas"]}
        out = {}
        for pid in ("abuela", "chato"):
            p = json.loads(json.dumps(snap[pid]))
            p["open_to_all"] = pid == "abuela"
            out[pid] = p
        out["vault"] = {"id": "vault", "name": "La Bóveda", "status": "announced", "level": None,
                        "title": "a locked room behind the bar", "kind": "dealer", "enabled": False,
                        "bio": "Nobody has seen inside. One legendary per team per hour, they say.",
                        "traits": {"patience": 0.2, "generosity": 0.1, "shrewdness": 0.95, "memory": 0.95,
                                   "strictness": 0.95, "chattiness": 0.1},
                        "unlock": {"always": False, "early_deals_with": "chato", "early_min_deals": 3},
                        "open_to_all": False, "menu": None}
        return out

    def _vault_menu(self) -> dict:
        return {"sells": [{"rarity": "epic", "sets": "released", "list_price": 200},
                          {"rarity": "legendary", "sets": "released", "list_price": 500, "per_team_per_hour": 1}],
                "buys": [{"rarity": "rare", "sets": "released"}], "deals_per_team_per_hour": 4}

    def activate_level(self, pid: str) -> None:
        d = self.dealers.get(pid)
        if not d:
            raise ApiError(404, "unknown_persona", pid)
        if d["status"] == "active" and d.get("open_to_all"):
            return
        d.update(status="active", enabled=True, open_to_all=True, level=DEALER_PROFILES[pid]["level"])
        if pid == "vault":
            d["menu"] = self._vault_menu()
        self.event("persona.open_to_all", persona=pid, name=d["name"], level=d["level"])
        self.event("announcement", actor="calendar", text=f"{d['name']} is open for everyone.")
        self._unlock(pid, "open to everyone now")

    def _unlock(self, pid: str, why: str) -> None:
        if pid in self.unlocked:
            return
        self.unlocked.append(pid)
        self.level = max(self.level, len(self.unlocked))
        self.event("level.unlocked", team=TEAM, name="Team 10", persona=pid, persona_name=self.dealers[pid]["name"],
                   level=self.level, why=why)

    def levels_view(self) -> dict:
        out = []
        for pid in ("chato", "vault"):
            d = self.dealers[pid]
            active = d["status"] == "active"
            out.append({"id": pid, "kind": "persona", "name": d["name"], "state": "active" if active else "announced",
                        "teaser": d.get("bio", ""), "how": (json.dumps(d["menu"]) if active and d.get("menu") else None),
                        "open_to_all": bool(d.get("open_to_all"))})
        return {"levels": out}

    def _quota_used(self, dealer: str, key: str = "deals") -> int:
        return self.deals_by_hour.get((dealer, self.hour(), key), 0)

    def _bump_quota(self, dealer: str, key: str = "deals") -> None:
        k = (dealer, self.hour(), key)
        self.deals_by_hour[k] = self.deals_by_hour.get(k, 0) + 1

    def open_thread(self, body: dict) -> dict:
        dealer, topic = body.get("with"), body.get("topic") or {}
        if dealer in self.fake_teams:
            raise ApiError(400, "not_supported", "team threads are not simulated; use offers")
        d = self.dealers.get(dealer)
        if not d:
            raise ApiError(404, "unknown_persona", str(dealer))
        if dealer not in self.unlocked or d["status"] != "active":
            raise ApiError(403, "locked", f"{dealer} is not open to you yet")
        if self.cooloff.get(dealer, -1) > self.tick:
            raise ApiError(409, "cooloff", f"{dealer} will not talk to you yet", until_tick=self.cooloff[dealer])
        if any(t["with"] == dealer and t["status"] == "open" for t in self.threads.values()):
            raise ApiError(409, "thread_open", "one open thread per dealer")
        if sum(1 for t in self.threads.values() if t["status"] == "open") >= self.limits["max_open_threads_per_team"]:
            raise ApiError(409, "too_many_threads", "")
        prof = DEALER_PROFILES[dealer]
        if self._quota_used(dealer) >= prof["deals_per_hour"]:
            raise ApiError(409, "persona_quota", f"{dealer} has no more deals for you this hour")
        list_price = None
        if "buy" in topic:
            buy = topic["buy"] or {}
            if "pack" in buy:
                key, item, give = f"pack:{buy['pack']}", buy["pack"], {"types": [f"pack:{buy['pack']}"]}
                if key not in prof["sells"]:
                    raise ApiError(400, "not_selling", f"{dealer} does not sell {buy['pack']}")
                if self._quota_used(dealer, "packs") >= prof["packs_per_hour"]:
                    raise ApiError(409, "persona_quota", "no more packs this hour")
                rarity = key
                ref = None
            else:
                ref = buy.get("card")
                if ref and ref not in self.cards:
                    raise ApiError(400, "unknown_card", ref)
                rarity = self.cards[ref]["rarity"] if ref else buy.get("rarity", "common")
                if rarity not in prof["sells"]:
                    raise ApiError(400, "not_selling", f"{dealer} does not sell {rarity}")
                if ref and not self.cards[ref]["released"]:
                    raise ApiError(400, "not_released", ref)
                ref = ref or self.pick(rarity, buy.get("set"))
                if rarity == "legendary" and self._quota_used(dealer, "legendary") >= 1:
                    raise ApiError(409, "sold_out", "one legendary per team per hour")
                item, give = ref, {"types": [f"card:{ref}"]}
            side = "sell"
        elif "sell" in topic:
            ids = (topic["sell"] or {}).get("assets") or []
            a = self.assets.get(ids[0]) if ids else None
            if not a:
                raise ApiError(400, "not_yours", str(ids))
            rarity = a.get("rarity")
            if a["kind"] != "card" or rarity not in prof["buys"]:
                raise ApiError(400, "not_buying", f"{dealer} does not buy {rarity}")
            side, ref, item, give = "buy", a["ref"], a["ref"], {"assets": ids}
        else:
            raise ApiError(400, "bad_topic", "topic needs buy or sell")
        m = DealerThread(dealer, side, rarity, self.rng, item=item, list_price=list_price)
        tid = self.nid()
        t = {"id": tid, "kind": "persona", "team": TEAM, "with": dealer, "venue": None, "topic": topic,
             "status": "open", "created_tick": self.tick, "messages": [], "closed_reason": None, "item": item,
             "_side": side, "_give": give, "_ref": ref, "_rarity": rarity, "_last_team_tick": None}
        self.threads[tid] = t
        self.models[tid] = m
        self.event("thread.opened", thread=tid, kind="persona", team=TEAM, topic=topic, **{"with": dealer})
        self._dealer_speak(t, f"Welcome! {item}, {m.price} P.")
        return self.thread_view(t)

    def _dealer_offer(self, t: dict, price: int, final: bool) -> dict:
        for o in self.offers.values():
            if o["thread"] == t["id"] and o["maker"] == t["with"] and o["status"] == "open":
                o["status"] = "replaced"
        if t["_side"] == "sell":
            give, want = {"types": t["_give"]["types"]}, {"cash": price}
        else:
            give, want = {"cash": price}, {"assets": t["_give"]["assets"]}
        return self.make_offer(t["with"], TEAM, give, want, thread=t["id"], final=final, ttl=2)

    def _dealer_speak(self, t: dict, text: str, final: bool = False) -> None:
        m = self.models[t["id"]]
        o = self._dealer_offer(t, m.price, final)
        msg = {"id": self.nid(), "tick": self.tick, "sender": t["with"], "text": text, "price": m.price, "offer": o}
        t["messages"].append(msg)
        self.event("thread.message", actor=t["with"], thread=t["id"], kind="persona", message=msg["id"],
                   sender=t["with"], text=text, team=TEAM, offer=o, **{"with": t["with"]})

    def say(self, tid: int, body: dict) -> dict:
        t = self.threads.get(tid)
        if not t:
            raise ApiError(404, "unknown_thread", str(tid))
        if t["status"] != "open":
            raise ApiError(409, "thread_closed", t["status"])
        price = body.get("price")
        if price is not None:
            if not isinstance(price, int) or price < 1 or price > 10_000_000:
                raise ApiError(400, "bad_price", "whole primas from 1")
            if t["_side"] == "sell" and price > self.cash:
                raise ApiError(400, "insufficient_cash", "offer above your cash")
        self.once_per_tick(("thread", tid))
        text = str(body.get("text", ""))[:1200]
        msg = {"id": self.nid(), "tick": self.tick, "sender": TEAM, "text": text, "price": price, "offer": None}
        t["messages"].append(msg)
        t["_last_team_tick"] = self.tick
        self.event("thread.message", actor=TEAM, thread=tid, kind="persona", message=msg["id"], sender=TEAM,
                   text=text, team=TEAM, offer=None)
        return {"message": msg["id"], "offer": None, "thread": tid, "next_tick_in": self.next_tick_in()}

    def close_thread(self, tid: int) -> dict:
        t = self.threads.get(tid)
        if not t:
            raise ApiError(404, "unknown_thread", str(tid))
        if t["status"] == "open":
            self._end_thread(t, "closed", "team")
        return self.thread_view(t)

    def _end_thread(self, t: dict, status: str, reason: str) -> None:
        t["status"], t["closed_reason"] = status, reason
        for o in self.offers.values():
            if o["thread"] == t["id"] and o["status"] == "open":
                o["status"] = "withdrawn"
        if reason == "cooloff":
            until = self.tick + DEALER_PROFILES[t["with"]]["cooloff_ticks"]
            self.cooloff[t["with"]] = until
            t["until_tick"] = until

    def _dealer_turn(self, t: dict) -> None:
        if t["_last_team_tick"] != self.tick - 1:
            return
        team = t["messages"][-1] if t["messages"] and t["messages"][-1]["sender"] == TEAM else None
        if not team or team.get("price") is None:
            return
        m = self.models[t["id"]]
        r = m.respond(team["price"], team.get("text", ""))
        if r["deal"]:
            self._settle_thread(t, r["price"])
        elif r["closed"]:
            self._end_thread(t, "walked" if r["reason"] == "walked" else "closed", r["reason"])
        else:
            words = "My last word, cariño:" if r["final"] else ("Ay... for you," if t["with"] == "abuela" else "Fine.")
            self._dealer_speak(t, f"{words} {r['price']} P.", final=r["final"])

    def _settle_thread(self, t: dict, price: int) -> None:
        m = self.models[t["id"]]
        dealer = t["with"]
        if self._quota_used(dealer) >= DEALER_PROFILES[dealer]["deals_per_hour"]:
            self._end_thread(t, "closed", "persona_quota")
            return
        items = []
        if t["_side"] == "sell":
            if self.cash < price:
                self._end_thread(t, "closed", "insufficient_cash")
                return
            self.cash -= price
            ty = t["_give"]["types"][0]
            if ty.startswith("pack:"):
                a = {"id": self.nid(), "kind": "pack", "ref": ty[5:], "name": ty[5:]}
                self.assets[a["id"]] = a
                self._bump_quota(dealer, "packs")
                gain = 0.0
            else:
                gain = self.value(ty[5:]) - price
                a = self.give_card(ty[5:])
                if a["rarity"] == "legendary":
                    self._bump_quota(dealer, "legendary")
            items.append({**a, "frm": dealer, "to": TEAM})
        else:
            for aid in t["_give"]["assets"]:
                a = self.assets.pop(aid, None)
                if a:
                    items.append({**a, "frm": TEAM, "to": dealer})
            self.cash += price
            gain = price - (self.value(items[0]["ref"], self._count(items[0]["ref"])) if items else 0)
        self._bump_quota(dealer)
        m.deal_price, m.closed, m.closed_reason = price, True, "deal"
        cap = m.capture()
        self.ladder.setdefault(dealer, []).append(cap)
        self.value_gained += gain
        t["deal_price"] = price
        self._end_thread(t, "deal", "deal")
        sid = self.nid()
        self.settled.append({"tick": self.tick, "kind": "dealer", "thread": t["id"], "dealer": dealer,
                             "side": t["_side"], "price": price, "open": m.open, "limit": m.limit, "capture": cap,
                             "rounds": m.rounds, "value_gain": round(gain, 2)})
        self.event("settlement", settlement=sid, tick=self.tick, kind="trade", parties=[TEAM, dealer], venue=None,
                   persona=dealer, fee=0, items=items, price=price)
        negotiated = sum(1 for s in self.settled if s.get("dealer") == dealer and s["capture"] > 0)
        if dealer == "abuela" and negotiated >= 3:
            self._unlock("chato", "three negotiated deals with Abuela")

    def _count(self, ref: str) -> int:
        return sum(1 for a in self.assets.values() if a.get("ref") == ref)

    def thread_view(self, t: dict) -> dict:
        standing = [o for o in self.offers.values() if o["thread"] == t["id"] and o["status"] == "open"]
        out = {k: v for k, v in t.items() if not k.startswith("_")}
        out["standing_offers"] = standing
        return out

    # --- offers -------------------------------------------------------------------------------------------------
    def make_offer(self, maker, to, give, want, thread=None, venue=None, final=False, ttl=2) -> dict:
        o = {"id": self.nid(), "maker": maker, "to": to, "venue": venue, "thread": thread, "status": "open",
             "give": {"cash": 0, "assets": [], "types": [], **give}, "want": {"cash": 0, "assets": [], "types": [], **want},
             "expires_tick": self.tick + ttl, "created_tick": self.tick, "final": final}
        self.offers[o["id"]] = o
        return o

    def fee(self, venue: str, price: int, cards: int) -> int:
        v = self.venues.get(venue) or {}
        return math.ceil(v.get("fee_bps", 0) * price / 10000) + v.get("fee_per_card", 0) * cards

    def post_offer(self, body: dict) -> dict:
        venue = body.get("venue") or "rastro"
        v = self.venues.get(venue)
        if not v or v["status"] != "open":
            raise ApiError(404, "unknown_venue", venue)
        if v.get("owner") == TEAM:
            raise ApiError(403, "own_venue", "you cannot trade on your own venue")
        if self.posted_this_tick >= self.limits["offers_per_team_per_tick"]:
            raise ApiError(429, "wait_for_tick", "offers per tick", next_tick=self.tick + 1)
        mine = [o for o in self.offers.values() if o["maker"] == TEAM and o["status"] == "open"]
        if len(mine) >= self.limits["max_open_offers_per_team"]:
            raise ApiError(409, "too_many_offers", "")
        give, want = body.get("give") or {}, body.get("want") or {}
        ids = give.get("assets") or []
        if len(ids) > 50:
            raise ApiError(400, "too_many_items", "")
        reserved = {a["id"] for o in mine for a in o["give"]["assets"]}
        for aid in ids:
            if aid not in self.assets:
                raise ApiError(403, "not_yours", str(aid))
            if aid in reserved:
                raise ApiError(409, "asset_reserved", str(aid))
        cash = int(give.get("cash") or 0)
        if cash > self.cash:
            raise ApiError(400, "insufficient_cash", "")
        self.posted_this_tick += 1
        g = {"cash": cash, "assets": [self.asset_view(self.assets[a]) for a in ids]}
        w = {"cash": int(want.get("cash") or 0), "types": [f"card:{r}" for r in want.get("cards") or []]}
        o = self.make_offer(TEAM, body.get("to"), g, w, venue=venue, ttl=int(body.get("expires_in_ticks") or 40))
        self.event("offer.listed", actor=TEAM, venue=venue, offer=self._public_offer(o))
        return o

    def _public_offer(self, o: dict) -> dict:
        return {k: v for k, v in o.items() if not k.startswith("_")}

    def cancel_offer(self, oid: int) -> dict:
        o = self.offers.get(oid)
        if not o:
            raise ApiError(404, "offer_gone", str(oid))
        if o["maker"] != TEAM:
            raise ApiError(403, "not_yours", "")
        if o["status"] == "open":
            o["status"] = "cancelled"
            self.event("offer.cancelled", offer=oid, venue=o["venue"])
        return {"ok": True, "offer": oid}

    def accept_offer(self, oid: int, body: dict) -> dict:
        o = self.offers.get(oid)
        if not o or o["status"] != "open" or o["expires_tick"] < self.tick:
            raise ApiError(409, "offer_gone", str(oid))
        if o["maker"] == TEAM:
            raise ApiError(400, "own_offer", "")
        if o["to"] not in (None, TEAM):
            raise ApiError(403, "not_for_you", "")
        picked = (body or {}).get("assets") or []
        if o["want"]["types"]:
            need = [ty[5:] for ty in o["want"]["types"] if ty.startswith("card:")]
            have = [self.assets[a]["ref"] for a in picked if a in self.assets]
            if sorted(need) != sorted(have):
                raise ApiError(400, "assets_required", "send the assets that match the wanted cards")
        need_cash = o["want"]["cash"]
        if need_cash > self.cash:
            raise ApiError(400, "insufficient_cash", "")
        self.use_accept()
        o["status"] = "accepted"
        if o["thread"]:
            t = self.threads[o["thread"]]
            price = o["want"]["cash"] if t["_side"] == "sell" else o["give"]["cash"]
            m = self.models[t["id"]]
            self.pending.append(lambda: (t["status"] == "open") and self._settle_thread(t, price))
            m.price = price
        else:
            self.pending.append(lambda: self._settle_market(o, picked))
        return {"queued": True, "offer": oid, "settles_at_tick": self.tick + 1, "next_tick_in": self.next_tick_in()}

    def _settle_market(self, o: dict, picked: list) -> None:
        venue = o["venue"]
        if o.get("_asset"):  # we buy a synthetic team's card
            price = o["want"]["cash"]
            if self.cash < price:
                o["status"] = "failed"
                return
            fee = self.fee(venue, price, 1)
            self.cash -= price
            a = dict(o["_asset"])
            a["id"] = self.nid()
            gain = self.value(a["ref"]) - price
            self.assets[a["id"]] = a
            items = [{**a, "frm": o["maker"], "to": TEAM}]
            parties = [o["maker"], TEAM]
        else:  # we sell into a synthetic bid
            price = o["give"]["cash"]
            fee = self.fee(venue, price, len(picked))
            items = []
            gain = 0.0
            for aid in picked:
                a = self.assets.pop(aid, None)
                if a:
                    gain -= self.value(a["ref"], self._count(a["ref"]))
                    items.append({**a, "frm": TEAM, "to": o["maker"]})
            self.cash += price - fee
            gain += price - fee
            parties = [TEAM, o["maker"]]
        self.value_gained += gain
        o["status"] = "settled"
        sid = self.nid()
        self.settled.append({"tick": self.tick, "kind": "market", "offer": o["id"], "price": price, "fee": fee,
                             "value_gain": round(gain, 2)})
        self.event("settlement", settlement=sid, tick=self.tick, kind="trade", parties=parties, venue=venue,
                   persona=None, fee=fee, items=items, price=price)

    def _synthetic_listing(self) -> None:
        team = self.rng.choice(self.fake_teams)
        if self.rng.random() < 0.75:
            ref = self.pick(self.rng.choice(["common", "common", "uncommon", "rare"]))
            book = self.cards[ref]["book"]
            a = self.card_asset(ref)
            o = self.make_offer(team, None, {"assets": [a]}, {"cash": max(1, round(book * self.rng.uniform(0.5, 1.4)))},
                                venue="rastro", ttl=40)
            o["_asset"] = a
        else:
            ref = self.pick(self.rng.choice(["common", "uncommon", "rare"]))
            book = self.cards[ref]["book"]
            o = self.make_offer(team, None, {"cash": max(1, round(book * self.team_aff[team][self.cards[ref]["set"]]
                                                                  * self.rng.uniform(0.5, 0.9)))},
                                {"types": [f"card:{ref}"]}, venue="rastro", ttl=40)
        self.event("offer.listed", actor=team, venue="rastro", offer=self._public_offer(o))

    def _market_turn(self) -> None:
        for o in list(self.offers.values()):
            if o["maker"] != TEAM or o["status"] != "open" or not o["venue"] or not o["give"]["assets"]:
                continue
            a = o["give"]["assets"][0]
            if a.get("kind") != "card":
                continue
            buyer = self.rng.choice(self.fake_teams)
            hidden = self.cards[a["ref"]]["book"] * self.team_aff[buyer][self.cards[a["ref"]]["set"]] * self.rng.uniform(0.6, 1.1)
            if self.rng.random() < 0.25 and o["want"]["cash"] <= hidden:
                price, fee = o["want"]["cash"], self.fee(o["venue"], o["want"]["cash"], len(o["give"]["assets"]))
                gain = 0.0
                for x in o["give"]["assets"]:
                    if self.assets.pop(x["id"], None):
                        gain -= self.value(x["ref"], self._count(x["ref"]))
                self.cash += price - fee
                gain += price - fee
                self.value_gained += gain
                o["status"] = "settled"
                self.settled.append({"tick": self.tick, "kind": "market", "offer": o["id"], "sold": a["ref"],
                                     "price": price, "fee": fee, "value_gain": round(gain, 2)})
                self.event("settlement", settlement=self.nid(), tick=self.tick, kind="trade", parties=[TEAM, buyer],
                           venue=o["venue"], persona=None, fee=fee, items=[{**a, "frm": TEAM, "to": buyer}], price=price)
        if self.synthetic_activity and self.rng.random() < 0.3:
            self._synthetic_listing()

    def _synthetic_dealer_activity(self) -> None:
        """Other teams haggle with dealers too: public thread.message and settlement events like Friday's."""
        if self.rng.random() > 0.35:
            return
        team = self.rng.choice(self.fake_teams)
        dealer = self.rng.choice([p for p, d in self.dealers.items() if d["status"] == "active" and d.get("open_to_all")])
        prof = DEALER_PROFILES[dealer]
        side = self.rng.choice(["sell", "buy"])
        rarity = self.rng.choice(list(prof["sells" if side == "sell" else "buys"]))
        m = DealerThread(dealer, side, rarity, self.rng)
        tid = self.nid()
        ref = None if rarity.startswith("pack:") else self.pick(rarity)
        item = rarity[5:] if ref is None else ref
        topic = {"buy": {"pack": item}} if ref is None else ({"buy": {"card": ref}} if side == "sell" else {"sell": {"assets": [self.nid()]}})
        self.event("thread.opened", thread=tid, kind="persona", team=team, **{"with": dealer}, topic=topic)
        p = max(1, round(m.open * (0.6 if side == "sell" else 1.6)))
        for _ in range(self.rng.randint(1, 6)):
            r = m.respond(p)
            if r["closed"]:
                break
            self.event("thread.message", actor=dealer, thread=tid, kind="persona", message=self.nid(), sender=dealer,
                       text=f"{r['price']} P.", team=team, **{"with": dealer},
                       offer={"id": self.nid(), "maker": dealer, "to": team, "final": r["final"],
                              "give": {"cash": 0 if side == "sell" else r["price"], "assets": [],
                                       "types": [f"card:{item}" if ref else f"pack:{item}"] if side == "sell" else []},
                              "want": {"cash": r["price"] if side == "sell" else 0, "assets": [], "types": []}})
            p = p + 3 if side == "sell" else max(1, p - 3)
        if m.deal_price is None and self.rng.random() < 0.6:
            m.accept_standing()
        if m.deal_price is not None:
            frm, to = (dealer, team) if side == "sell" else (team, dealer)
            self.event("settlement", settlement=self.nid(), tick=self.tick, kind="trade", parties=[team, dealer],
                       venue=None, persona=dealer, fee=0,
                       items=[{"kind": "card" if ref else "pack", "ref": item, "frm": frm, "to": to,
                               "rarity": None if ref is None else self.cards[ref]["rarity"]}], price=m.deal_price)
            b = self.board[team]
            b["deals"] += 1
            b["negotiating"] = round(b["negotiating"] + self.rng.uniform(-0.5, 2.5), 2)

    # --- venues / market test -----------------------------------------------------------------------------------
    def _init_venues(self) -> dict:
        out = {}
        for v in _load("venues")["venues"]:
            out[v["venue"]] = dict(v)
        out["stall10"] = {"venue": "stall10", "name": "Team 10 stall", "owner": TEAM, "owner_name": "Team 10",
                          "status": "open", "fee_bps": 0, "fee_per_card": 0, "rules": {"mechanism": "auto"}, "bond": 0,
                          "starter": True, "house": False, "description": "Free starter stall", "opened_tick": 0}
        return out

    def open_venue(self, body: dict) -> dict:
        if self.level < 2:
            raise ApiError(403, "level_too_low", "venues open from level 2")
        if self.my_venue:
            raise ApiError(409, "venue_exists", self.my_venue)
        fee_bps, fpc = int(body.get("fee_bps") or 0), int(body.get("fee_per_card") or 0)
        if fee_bps > 1000 or fpc > 5 or fee_bps < 0 or fpc < 0:
            raise ApiError(400, "fee_too_high", "fees are capped at 10 % and 5 P per card")
        if self.cash < 270:
            raise ApiError(400, "insufficient_cash", "bond 250 + 20")
        self.cash -= 270
        vid = f"v{len([v for v in self.venues if v.startswith('v')]) + 1:02d}"
        mech = ((body.get("rules") or {}).get("mechanism")) or body.get("mechanism") or "auto"
        v = {"venue": vid, "name": str(body.get("name", "Team 10"))[:40], "owner": TEAM, "owner_name": "Team 10",
             "status": "open", "fee_bps": fee_bps, "fee_per_card": fpc, "rules": {"mechanism": mech}, "bond": 250,
             "starter": False, "house": False, "description": str(body.get("description", ""))[:400],
             "opened_tick": self.tick, "trades": 0, "volume": 0, "fees": 0, "pending_fee": None}
        self.venues[vid] = v
        self.venues["stall10"]["status"] = "closed"
        self.my_venue = vid
        self.event("venue.opened", actor=TEAM, venue=vid, name=v["name"], owner=TEAM, mechanism=mech)
        return {**v, "broker_key": BROKER_KEY}

    def patch_venue(self, vid: str, body: dict) -> dict:
        v = self.venues.get(vid)
        if not v:
            raise ApiError(404, "unknown_venue", vid)
        if v["owner"] != TEAM:
            raise ApiError(403, "not_yours", vid)
        if "description" in body:
            v["description"] = str(body["description"])[:400]
        if "fee_bps" in body or "fee_per_card" in body:
            fb, fp = int(body.get("fee_bps", v["fee_bps"])), int(body.get("fee_per_card", v["fee_per_card"]))
            if fb > 1000 or fp > 5 or fb < 0 or fp < 0:
                raise ApiError(400, "fee_too_high", "")
            v["pending_fee"] = {"fee_bps": fb, "fee_per_card": fp, "effective_tick": self.tick + 2}
            self.event("venue.fee_announced", venue=vid, fee_bps=fb, fee_per_card=fp, effective_tick=self.tick + 2)
        return v

    def broker_venue(self) -> dict:
        return self.venues[self.my_venue] if self.my_venue else self.venues["stall10"]

    def start_bench(self, traders: int | None = None, ticks: int | None = None, hard: bool = False) -> None:
        self.sessions_bench = getattr(self, "sessions_bench", 0) + 1
        run = f"b{self.sessions_bench}"
        params = {"ticks": ticks or self.bench_ticks}
        if traders:
            params["traders"] = traders
        sess = _new_bench_session(self.rng.randrange(1 << 30), params, hard, run, self.bench_cross_rule)
        self.bench = {"run": run, "ref": self.pick("common"), "session": sess, "start_tick": self.tick,
                      "ends_tick": self.tick + sess.ticks, "best": sess.max_gain(), "auto_seen": None}
        self.event("announcement", actor="calendar", text="The Market Test: every venue gets the same synthetic book")

    def _bench_t(self) -> int:
        return self.tick - self.bench["start_tick"]

    def bench_offers(self) -> list[dict]:
        if not self.bench:
            return []
        vid, ref = self.broker_venue()["venue"], self.bench["ref"]
        out = []
        for o in self.bench["session"].book(self._bench_t()):
            o = json.loads(json.dumps(o).replace("SIM-01", ref))
            side = "sell" if o["want"]["cash"] else "buy"
            if side == "sell":
                o["give"]["assets"], o["give"]["types"] = [{"kind": "card", "ref": ref}], []
            out.append({"maker": "bench", "side": side, "venue": vid, **o})
        return out

    def broker_book(self) -> dict:
        v = self.broker_venue()
        offers = [self._public_offer(o) for o in self.offers.values() if o["venue"] == v["venue"] and o["status"] == "open"]
        return {"venue": v["venue"], "fee_bps": v["fee_bps"], "fee_per_card": v["fee_per_card"],
                "mechanism": v["rules"].get("mechanism", "auto"), "offers": offers, "bench_offers": self.bench_offers(),
                "bench": ({"run": self.bench["run"], "ends_tick": self.bench["ends_tick"]} if self.bench else None),
                "tick": self.tick}

    def broker_match(self, body: dict) -> dict:
        v = self.broker_venue()
        if v["rules"].get("mechanism") != "board":
            raise ApiError(409, "auto_venue", "a broker can only match on a board venue")
        sid, bid, price = str(body.get("sell")), str(body.get("buy")), body.get("price")
        if not isinstance(price, int) or price < 1:
            raise ApiError(400, "bad_price", "")
        if not self.bench or not sid.startswith(self.bench["run"] + "-"):
            raise ApiError(404, "offer_gone", "unknown bench offers")
        r = self.bench["session"].match(self._bench_t(), sid, bid, price)
        if r.get("error"):
            raise ApiError(409, r["error"], "the bench refused that match")
        return {"ok": True, "sell": sid, "buy": bid, "price": price}

    def _bench_turn(self) -> None:
        b = self.bench
        if not b:
            return
        s = b["session"]
        if self._bench_t() >= s.ticks:
            eff = round(s.efficiency(), 3) if b["best"] > 0 else 0.0
            self.bench_history.append({"run": b["run"], "efficiency": eff, "realised": s.realised, "best": b["best"],
                                       "matches": len(s.matches), "refused": s.refused})
            self.bench = None
            return
        if self.broker_venue()["rules"].get("mechanism") == "auto":  # the engine crosses by quotes, like the stall
            for sell, buy, price in _stall_plan(self.bench_offers()):
                s.match(self._bench_t(), sell, buy, price)

    def announce(self, body: dict) -> dict:
        v = self.broker_venue()
        self.event("venue.announcement", actor=v["venue"], venue=v["venue"], name=v["name"],
                   text=str(body.get("text", ""))[:600])
        return {"ok": True}

    # --- duels --------------------------------------------------------------------------------------------------
    def start_duels(self, issues=("price",), decay: float | None = None, n: int | None = None,
                    duel_ticks: int | None = None) -> None:
        self.sessions += 1
        issues = tuple(issues)
        decay = decay if decay is not None else (0.06 if issues == ("price",) else 0.08)
        for i in range(n or self.duels_per_session):
            sc = make_duel_scenario(self.rng, issues)
            did = self.nid()
            d = {"duel": did, "session": self.sessions, "status": "queued", "role": sc["our_role"],
                 "item": self.rng.choice(["Taxi Blanco", "Andén 0", "El Rastro al Amanecer", "Plaza de Olavide"]),
                 "issues": list(issues), "your_days_weight": sc["our_days_weight"],
                 "days_meaning": ("points per delivery day for you" if "days" in issues else None),
                 "your_limit": sc["our_limit"],
                 "limit_meaning": "never sell below your cost" if sc["our_role"] == "seller" else "never pay above your value",
                 "rival": self.rng.choice(RIVAL_ALIASES), "deadline_tick": None, "decay_per_round": decay,
                 "rounds": 0, "your_offer": None, "rival_offer": None, "messages": [], "result": None, "price": None,
                 "days": None, "_kind": sc["kind"], "_rival_limit": sc["rival_limit"], "_ticks": duel_ticks or self.duel_ticks,
                 "_our_last_tick": None, "_n_ours": 0, "_n_rival": 0}
            self.duels[did] = d
            self.rivals[did] = DuelRival(sc["kind"], sc["our_role"], sc["our_limit"], sc["rival_limit"], self.rng,
                                         issues=issues, rival_days_weight=sc["rival_days_weight"], decay=decay,
                                         duel_ticks=d["_ticks"])
            self.duel_queue.append(did)
        self.event("announcement", actor="calendar", text=f"Duels session {self.sessions} starts ({'+'.join(issues)})")
        self._fill_duels()

    def _fill_duels(self) -> None:
        live = sum(1 for d in self.duels.values() if d["status"] == "live")
        while self.duel_queue and live < self.max_concurrent:
            d = self.duels[self.duel_queue.pop(0)]
            d["status"], d["deadline_tick"], d["started_tick"] = "live", self.tick + d["_ticks"], self.tick
            op = self.rivals[d["duel"]].opening()
            if op:
                self._rival_says(d, op)
            live += 1

    def _rival_says(self, d: dict, r: dict) -> None:
        d["_n_rival"] += 1
        off = {"id": self.nid(), "price": r["price"], "tick": self.tick, "days": r.get("days") if "days" in d["issues"] else 0}
        d["rival_offer"] = off
        d["messages"].append({"tick": self.tick, "from": d["rival"], "text": r.get("text", ""), "price": r["price"],
                              "days": r.get("days")})
        self._update_rounds(d)

    def _update_rounds(self, d: dict) -> None:
        # A round is a tick in which someone made a priced offer, after the first; talking alone is free.
        both = d["_n_ours"] > 0 and d["_n_rival"] > 0
        ticks = {m["tick"] for m in d["messages"] if m.get("price") is not None}
        d["rounds"] = max(0, len(ticks) - 1) if both else 0

    def duel_say(self, did: int, body: dict) -> dict:
        d = self.duels.get(did)
        if not d or d["status"] != "live":
            raise ApiError(409, "duel_closed", str(did))
        off = body.get("offer") if isinstance(body.get("offer"), dict) else body
        price, days = off.get("price"), off.get("days")
        if price is not None:
            if not isinstance(price, int) or price < 1:
                raise ApiError(400, "bad_price", "")
            if "days" in d["issues"] and days is None:
                raise ApiError(400, "missing_days", "this session negotiates the delivery day too")
            if days is not None and (not isinstance(days, int) or not 0 <= days <= 10):
                raise ApiError(400, "bad_days", "days 0-10")
        self.once_per_tick(("duel", did))
        d["messages"].append({"tick": self.tick, "from": "you", "text": str(body.get("text", ""))[:1200],
                              "price": price, "days": days})
        if price is not None:
            d["_n_ours"] += 1
            d["your_offer"] = {"id": self.nid(), "price": price, "tick": self.tick, "days": days or 0}
            d["_our_last_tick"] = self.tick
            self._update_rounds(d)
        return {"ok": True, "duel": did, "next_tick_in": self.next_tick_in()}

    def duel_accept(self, did: int) -> dict:
        d = self.duels.get(did)
        if not d or d["status"] != "live" or not d["rival_offer"]:
            raise ApiError(409, "nothing_to_accept", str(did))
        self.use_accept()
        ro = dict(d["rival_offer"])
        self.pending.append(lambda: d["status"] == "live" and self._close_duel(d, ro["price"], ro.get("days")))
        return {"queued": True, "duel": did, "settles_at_tick": self.tick + 1}

    def _close_duel(self, d: dict, price: int | None, days: int | None) -> None:
        if price is None:
            d["status"], d["result"] = "no_deal", 0.0
        else:
            d["status"], d["price"], d["days"] = "deal", price, days if "days" in d["issues"] else 0
            w = d["your_days_weight"] if "days" in d["issues"] else None
            d["result"] = duel_points(d["role"], d["your_limit"], price, d["rounds"], d["decay_per_round"],
                                      days=d["days"] if w is not None else None, days_weight=w)
            self.duel_points_total += d["result"]
        d["closed_tick"] = self.tick
        self.event("duel.closed", duel=d["duel"], session=d["session"], status=d["status"], item=d["item"])

    def _duels_turn(self) -> None:
        for d in list(self.duels.values()):
            if d["status"] != "live":
                continue
            if self.tick > d["deadline_tick"]:
                self._close_duel(d, None, None)
                continue
            if d["_our_last_tick"] == self.tick - 1 and d["your_offer"]:
                r = self.rivals[d["duel"]].respond(d["your_offer"]["price"], d["your_offer"].get("days"))
                if r["accept"]:
                    self._close_duel(d, d["your_offer"]["price"], d["your_offer"].get("days"))
                elif r["price"] is not None:
                    self._rival_says(d, r)
        self._fill_duels()

    def duel_view(self, d: dict) -> dict:
        return {k: v for k, v in d.items() if not k.startswith("_")}

    # --- clock --------------------------------------------------------------------------------------------------
    def next_tick_in(self) -> float:
        return round(max(0.0, self.next_tick_at - time.time()), 2) if not self.manual else self.tick_seconds

    def maybe_tick(self) -> None:
        if self.manual or self.paused:
            return
        with self.lock:
            while time.time() >= self.next_tick_at:
                self.next_tick_at += self.tick_seconds
                self.advance()

    def advance(self) -> None:
        with self.lock:
            self.tick += 1
            self.said.clear()
            self.posted_this_tick = 0
            pend, self.pending = self.pending, []
            for fn in pend:
                fn()
            for o in self.offers.values():
                if o["status"] == "open" and o["expires_tick"] < self.tick:
                    o["status"] = "expired"
            for v in self.venues.values():
                pf = v.get("pending_fee")
                if pf and pf.get("effective_tick", 1 << 30) <= self.tick and v["owner"] == TEAM:
                    v["fee_bps"], v["fee_per_card"], v["pending_fee"] = pf["fee_bps"], pf["fee_per_card"], None
                    self.event("venue.fee_changed", venue=v["venue"], fee_bps=v["fee_bps"], fee_per_card=v["fee_per_card"])
            for t in list(self.threads.values()):
                if t["status"] == "open":
                    self._dealer_turn(t)
            self._market_turn()
            self._duels_turn()
            self._bench_turn()
            self._calendar()
            if self.synthetic_activity:
                self._synthetic_dealer_activity()
            if self.tick % 5 == 0:
                self._snapshot_leaderboard()

    def _calendar(self) -> None:
        if self.tick == self.chato_open_at_tick and not self.dealers["chato"].get("open_to_all"):
            self.activate_level("chato")
        if self.tick == self.vault_at_tick:
            self.activate_level("vault")
        if self.tick == self.duel_at_tick:
            self.start_duels(("price",), decay=0.06)
        if self.tick == self.days_duel_at_tick:
            self.start_duels(("price", "days"), decay=0.08)
        if self.tick == self.bench_at_tick:
            self.start_bench()

    def schedule(self) -> dict:
        tph = self.ticks_per_hour
        up = []
        def add(tick, action, note, params):
            if tick is not None and tick > self.tick:
                up.append({"at_hours": round(tick / tph, 4), "at_tick": tick, "action": action, "note": note,
                           "params": params})
        add(self.chato_open_at_tick, "persona", "El Chato opens for everyone", {"id": "chato", "open_to_all": True})
        add(self.duel_at_tick, "duels", "Duels I: price only", {"name": "Duels I", "rounds": 1, "duel_ticks": self.duel_ticks,
                                                               "decay": 0.06, "max_concurrent": self.max_concurrent})
        add(self.bench_at_tick, "bench", "The Market Test: every venue gets the same synthetic book",
            {"traders": 10, "ticks": self.bench_ticks})
        add(self.vault_at_tick, "level", "A new stall opens", {"id": "vault"})
        add(self.days_duel_at_tick, "duels", "Duels II: price and delivery day",
            {"name": "Duels II", "rounds": 1, "duel_ticks": self.duel_ticks, "decay": 0.08,
             "max_concurrent": self.max_concurrent, "issues": ["price", "days"]})
        up.sort(key=lambda e: e["at_hours"])
        return {"now_hours": self.t_hours(), "upcoming": up}

    def clock(self) -> dict:
        return {"tick": self.tick, "t_hours": self.t_hours(), "tick_seconds": self.tick_seconds, "paused": self.paused,
                "next_tick_in": self.next_tick_in(), "round": 1, "round_name": "Simulated", "min_tick_seconds": 1.0,
                "max_tick_seconds": 60.0, "limits": dict(self.limits), "calendar": True, "calendar_on": True,
                "doors": "closed" if self.paused else "open", "today": "sat", "today_name": "Saturday",
                "days": [{"day": "sat", "name": "Saturday", "tick_seconds": self.tick_seconds}], "sim": True}

    def control(self, body: dict) -> dict:
        if "limits" in body:
            self.limits.update({k: int(v) for k, v in body["limits"].items()})
            self.event("clock.limits_changed", actor="admin", limits=dict(self.limits))
            self.event("announcement", actor="admin", text=f"New limits: {json.dumps(body['limits'])}")
        if "tick_seconds" in body:
            self.tick_seconds = float(body["tick_seconds"])
            self.event("clock.changed", actor="admin", tick_seconds=self.tick_seconds, paused=self.paused)
        if "paused" in body:
            self.paused = bool(body["paused"])
            self.next_tick_at = time.time() + self.tick_seconds
            self.event("clock.changed", actor="admin", tick_seconds=self.tick_seconds, paused=self.paused)
        if body.get("activate_level"):
            self.activate_level(body["activate_level"])
        if body.get("start_duels"):
            sd = body["start_duels"] if isinstance(body["start_duels"], dict) else {}
            self.start_duels(tuple(sd.get("issues", ["price"])), decay=sd.get("decay"), n=sd.get("n"),
                             duel_ticks=sd.get("duel_ticks"))
        if body.get("start_bench"):
            self.start_bench()
        if "cash" in body:
            self.cash = int(body["cash"])
        if "level" in body:
            self.level = int(body["level"])
        return {"ok": True, "tick": self.tick, "limits": self.limits}

    # --- views --------------------------------------------------------------------------------------------------
    def score(self) -> dict:
        # best three captures per dealer, a missing one as zero
        ladder = sum(sum(sorted(v, reverse=True)[:3]) / 3 for v in self.ladder.values())
        neg = round(max(0.0, self.value_gained) + self.duel_points_total, 2)
        eff = [b["efficiency"] for b in self.bench_history]
        market = round(30 * (sum(eff) / len(eff)), 2) if eff else 0.0
        return {"team": TEAM, "neg_points": neg, "ladder_points": round(ladder, 3), "duel_points": round(self.duel_points_total, 2),
                "value_gained": round(self.value_gained, 2), "market": market, "negotiating": None, "score": None,
                "rank": None}

    def me_view(self) -> dict:
        assets = [self.asset_view(a) for a in self.assets.values()]
        return {"id": TEAM, "name": "Team 10", "cash": self.cash, "level": self.level, "unlocked": list(self.unlocked),
                "badges": [], "frozen": False, "affinity": dict(AFFINITY), "assets": assets,
                "collection_value": round(sum(float(a.get("your_value") or 0) for a in assets), 1), "score": self.score(),
                "venue": self.my_venue, "starter_broker_key": BROKER_KEY, "tick": self.tick}

    def _snapshot_leaderboard(self) -> None:
        for t, b in self.board.items():
            b["negotiating"] = round(max(0.0, b["negotiating"] + self.rng.uniform(-0.2, 0.8)), 2)
        mine = self.score()
        raw = dict({t: b["negotiating"] for t, b in self.board.items()}, **{TEAM: mine["neg_points"]})
        top = max(raw.values()) or 1.0
        teams = {}
        for t, v in raw.items():
            b = self.board.get(t, {"deals": len([s for s in self.settled if s.get("kind") == "dealer"]), "level": self.level,
                                   "album_filled": len({a.get("ref") for a in self.assets.values()}),
                                   "pages_complete": 0, "venue": self.my_venue})
            neg = round(30 * v / top, 2)
            teams[t] = {"score": neg + (mine["market"] if t == TEAM else 0.0), "negotiating": neg,
                        "market": mine["market"] if t == TEAM else 0.0, "level": b["level"],
                        "album_filled": b["album_filled"], "pages_complete": b["pages_complete"], "deals": b["deals"],
                        "venue": b["venue"]}
        for rank, t in enumerate(sorted(teams, key=lambda k: -teams[k]["score"]), 1):
            teams[t]["rank"] = rank
        self.lb_snapshot = {"tick": self.tick, "t_hours": self.t_hours(), "round": 1,
                            "rounds": [{"round": 1, "name": "Simulated", "weight": 1, "status": "active"}],
                            "teams": [{"team": t, **teams[t]} for t in sorted(teams, key=lambda k: teams[k]["rank"])]}

    def state(self) -> dict:
        return {"tick": self.tick, "cash": self.cash, "settled": self.settled, "collection_value": self.collection_value(),
                "networth": round(self.cash + self.collection_value(), 2), "assets": len(self.assets),
                "duels": [self.duel_view(d) for d in self.duels.values()], "score": self.score(),
                "bench": {"live": ({k: v for k, v in self.bench.items() if k != "offers"} if self.bench else None),
                          "history": self.bench_history},
                "ladder": self.ladder, "flags": self.flags, "limits": self.limits, "unlocked": self.unlocked}

    def open_pack(self, aid: int) -> dict:
        a = self.assets.get(aid)
        if not a or a["kind"] != "pack":
            raise ApiError(400, "not_a_pack", str(aid))
        pack = next((p for p in self.catalog["packs"] if p["id"] == a["ref"]), None)
        if not pack:
            raise ApiError(400, "not_a_pack", a["ref"])
        self.assets.pop(aid)
        cards = []
        for slot in pack["slots"]:
            rarity = self.rng.choices(list(slot), weights=list(slot.values()))[0]
            cards.append(self.give_card(self.pick(rarity)))
        self.event("pack.opened", team=TEAM, name="Team 10", pack=a["ref"], best=None)
        return {"cards": cards, "luck": 0}

    def flag(self, body: dict) -> dict:
        f = {"id": self.nid(), "message_id": body.get("message_id"), "reason": str(body.get("reason", ""))[:300],
             "tick": self.tick}
        self.flags.append(f)
        return {"ok": True, "flag": f["id"]}


# --- HTTP -------------------------------------------------------------------------------------------------------
ROUTES: list = []


def route(method: str, pattern: str, auth: str = "public"):
    def deco(fn):
        ROUTES.append((method, re.compile(pattern + "$"), auth, fn))
        return fn
    return deco


route("GET", r"/api/health")(lambda w, m, q, b: {"ok": True, "tick": w.tick})
route("GET", r"/api/clock")(lambda w, m, q, b: w.clock())
route("GET", r"/api/catalog")(lambda w, m, q, b: w.catalog)
route("GET", r"/api/schedule")(lambda w, m, q, b: w.schedule())
route("GET", r"/api/levels")(lambda w, m, q, b: w.levels_view())
route("GET", r"/api/leaderboard")(lambda w, m, q, b: w.lb_snapshot)
route("GET", r"/api/dealers")(lambda w, m, q, b: {"personas": list(w.dealers.values())})
route("GET", r"/api/personas")(lambda w, m, q, b: {"personas": list(w.dealers.values())})


@route("GET", r"/api/dealers/([\w-]+)")
def _dealer(w, m, q, b):
    d = w.dealers.get(m[1])
    if not d:
        raise ApiError(404, "unknown_persona", m[1])
    return d


@route("GET", r"/api/feed")
def _feed(w, m, q, b):
    since = int(q.get("since", 0) or 0)
    ev = [e for e in w.events if e["id"] > since and e["scope"] == "public"]
    return {"events": ev[-int(q.get("limit", 500)):]}


route("GET", r"/api/venues")(lambda w, m, q, b: {"venues": [v for v in w.venues.values() if v["status"] == "open"]})


@route("GET", r"/api/venues/([\w-]+)/offers")
def _vbook(w, m, q, b):
    return {"offers": [w._public_offer(o) for o in w.offers.values() if o["venue"] == m[1] and o["status"] == "open"]}


route("GET", r"/api/me", "team")(lambda w, m, q, b: w.me_view())


@route("GET", r"/api/me/value", "team")
def _value(w, m, q, b):
    ref = q.get("card")
    if ref not in w.cards:
        raise ApiError(400, "unknown_card", str(ref))
    return {"card": ref, "your_value": w.value(ref)}


@route("GET", r"/api/me/threads", "team")
def _threads(w, m, q, b):
    return {"threads": [w.thread_view(t) for t in w.threads.values() if not q.get("status") or t["status"] == q["status"]]}


@route("GET", r"/api/me/offers", "team")
def _myoffers(w, m, q, b):
    return {"offers": [w._public_offer(o) for o in w.offers.values()
                       if o["status"] == "open" and (o["maker"] == TEAM or o["to"] == TEAM)]}


@route("GET", r"/api/threads/(\d+)", "team")
def _thread(w, m, q, b):
    t = w.threads.get(int(m[1]))
    if not t:
        raise ApiError(404, "unknown_thread", m[1])
    return w.thread_view(t)


@route("GET", r"/api/cards/(\d+)", "team")
def _card(w, m, q, b):
    a = w.assets.get(int(m[1]))
    if not a:
        raise ApiError(404, "unknown_card", m[1])
    return {**a, "owner": "you", "history": []}


route("POST", r"/api/threads", "team")(lambda w, m, q, b: w.open_thread(b))
route("POST", r"/api/threads/(\d+)/messages", "team")(lambda w, m, q, b: w.say(int(m[1]), b))
route("POST", r"/api/threads/(\d+)/close", "team")(lambda w, m, q, b: w.close_thread(int(m[1])))
route("POST", r"/api/offers", "team")(lambda w, m, q, b: w.post_offer(b))
route("DELETE", r"/api/offers/(\d+)", "team")(lambda w, m, q, b: w.cancel_offer(int(m[1])))
route("POST", r"/api/offers/(\d+)/accept", "team")(lambda w, m, q, b: w.accept_offer(int(m[1]), b))
route("POST", r"/api/packs/(\d+)/open", "team")(lambda w, m, q, b: w.open_pack(int(m[1])))
route("POST", r"/api/flags", "team")(lambda w, m, q, b: w.flag(b))
route("POST", r"/api/venues", "team")(lambda w, m, q, b: w.open_venue(b))
route("PATCH", r"/api/venues/([\w-]+)", "team")(lambda w, m, q, b: w.patch_venue(m[1], b))


@route("GET", r"/api/duels", "team")
def _duels(w, m, q, b):
    done = str(q.get("done", "false")).lower() == "true"
    return {"duels": [w.duel_view(d) for d in w.duels.values()
                      if (d["status"] in ("deal", "no_deal")) == done and d["status"] != "queued"]}


route("POST", r"/api/duels/(\d+)/messages", "team")(lambda w, m, q, b: w.duel_say(int(m[1]), b))
route("POST", r"/api/duels/(\d+)/accept", "team")(lambda w, m, q, b: w.duel_accept(int(m[1])))
route("GET", r"/api/broker/book", "broker")(lambda w, m, q, b: w.broker_book())
route("POST", r"/api/broker/matches", "broker")(lambda w, m, q, b: w.broker_match(b))
route("POST", r"/api/broker/announce", "broker")(lambda w, m, q, b: w.announce(b))
route("GET", r"/sim/state")(lambda w, m, q, b: w.state())
route("POST", r"/sim/control")(lambda w, m, q, b: w.control(b))


@route("POST", r"/sim/tick")
def _tick(w, m, q, b):
    for _ in range(max(1, int((b or {}).get("n", 1)))):
        w.advance()
    return {"tick": w.tick}


def make_handler(world: World):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle_any(self, method: str):
            world.maybe_tick()
            parts = urlsplit(self.path)
            q = {k: v[-1] for k, v in parse_qs(parts.query).items()}
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except ValueError:
                return self.reply(400, {"error": "bad_json", "message": "strict JSON only"})
            team_key = self.headers.get("X-Team-Key")
            if team_key is not None and team_key != TEAM_KEY:
                return self.reply(401, {"error": "bad_key", "message": "unknown team key"})
            for meth, pat, auth, fn in ROUTES:
                m = pat.match(parts.path)
                if meth != method or not m:
                    continue
                if auth == "team" and team_key != TEAM_KEY:
                    return self.reply(401, {"error": "bad_key", "message": "X-Team-Key required"})
                if auth == "broker" and self.headers.get("X-Broker-Key") != BROKER_KEY:
                    return self.reply(401, {"error": "bad_broker_key", "message": "X-Broker-Key required"})
                try:
                    with world.lock:
                        return self.reply(200, fn(world, m, q, body))
                except ApiError as e:
                    return self.reply(e.status, {"error": e.code, "message": e.message, **e.extra})
                except (KeyError, IndexError, TypeError, ValueError) as e:
                    return self.reply(400, {"error": "invalid", "message": repr(e)})
            self.reply(404, {"error": "not_found", "message": parts.path})

        def reply(self, status: int, obj) -> None:
            data = json.dumps(obj, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self): self.handle_any("GET")
        def do_POST(self): self.handle_any("POST")
        def do_DELETE(self): self.handle_any("DELETE")
        def do_PATCH(self): self.handle_any("PATCH")
        def log_message(self, *a): pass
    return H


def serve(port: int = config.SIM_PORT, tick_seconds: float = 2.0, seed: int | None = None, **world_kwargs):
    """Start the fake Bazaar in background threads. Returns (server, world, thread); port=0 picks a free port
    (read server.server_address). Stop with server.shutdown()."""
    world = World(seed=seed, tick_seconds=tick_seconds, **world_kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(world))
    server.daemon_threads = True
    stop = threading.Event()

    def ticker():
        while not stop.is_set():
            world.maybe_tick()
            stop.wait(0.1)
    if not world.manual:
        threading.Thread(target=ticker, daemon=True).start()
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    orig = server.shutdown

    def shutdown():
        stop.set()
        orig()
        server.server_close()
    server.shutdown = shutdown
    return server, world, th


def main() -> None:
    ap = argparse.ArgumentParser(description="Fake Bazaar for end-to-end tests")
    ap.add_argument("--port", type=int, default=config.SIM_PORT)
    ap.add_argument("--tick", type=float, default=2.0, help="seconds per tick")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--manual", action="store_true", help="ticks only on POST /sim/tick")
    ap.add_argument("--vault-at", type=int, default=40)
    ap.add_argument("--duels-at", type=int, default=5)
    ap.add_argument("--days-duels-at", type=int, default=60)
    ap.add_argument("--bench-at", type=int, default=20)
    a = ap.parse_args()
    server, world, th = serve(a.port, a.tick, a.seed, manual=a.manual, vault_at_tick=a.vault_at,
                              duel_at_tick=a.duels_at, days_duel_at_tick=a.days_duels_at, bench_at_tick=a.bench_at)
    print(f"fake Bazaar on http://127.0.0.1:{server.server_address[1]} · tick {a.tick}s"
          f"{' (manual)' if a.manual else ''} · X-Team-Key: {TEAM_KEY}", flush=True)
    try:
        th.join()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
