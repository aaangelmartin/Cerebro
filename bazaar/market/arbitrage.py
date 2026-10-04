"""Dealer -> team arbitrage, with the buyer secured first.

The leader (Team 5) buys rares from Los Pícaros at ~54 P and resells them to teams at 85-93 P. The team approved
a narrow version: buy one card from a dealer ONLY while another team has an open cash bid for that exact card
on El Rastro whose net (after the taker fee we pay when we accept it) beats our all-in cost by MIN_MARGIN_P,
then accept that bid as soon as the card arrives. One card in transit at a time; never without a buyer in sight.

State (data/live/arbitrage.json), one job at most:
  {"ref", "dealer", "bid": {"id", "cash", "maker", "venue", "expires_tick"}, "resale_net", "cap", "open",
   "stage": "buying" | "selling" | "stock", "started_tick", "seen_tick", "held_before": [asset ids],
   "asset_id", "cost"}
- buying: the dealers domain haggles under `cap` (= resale_net - MIN_MARGIN_P); core.rails.rail_value lets
  that one buy through although the extra copy is worth little to us.
- selling: the card arrived (a new asset of that ref): accept the bid.
- stock: the bid vanished after we bought: accept any team bid >= cost + STOCK_MARGIN_P; no new job until sold.
Every step goes to data/live/arbitrage.jsonl; the brain reads `picture()` and can switch it off (plan.arbitrage).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .. import config
from ..core.types import Action

MIN_MARGIN_P = 15            # resale net - dealer price must be at least this
STOCK_MARGIN_P = 5           # once the card is ours and the buyer left: any bid this much above cost
MIN_BID_LIFE_TICKS = 3       # the rail's floor: the bid must live at least this long when we pay the dealer
START_BID_LIFE_TICKS = 8     # to START a job the bid must still live this long (a haggle takes a few ticks)
MAX_BUY_TICKS = 14           # give up a buy that takes longer (nothing bought: nothing lost)
EST_CLOSE_FRAC = 0.87        # dealers close near this share of their list price (Pícaros: 63 -> ~54)
OPEN_FRAC = 0.80             # our opening bid, as a share of the expected close
RARITIES = ("rare", "epic")
STATE, LOG = "arbitrage.json", "arbitrage.jsonl"


def _live(live: Path | None = None) -> Path:
    return Path(live) if live is not None else config.LIVE


def load(live: Path | None = None) -> dict | None:
    """The job in force, or None."""
    try:
        d = json.loads((_live(live) / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    a = d.get("active") if isinstance(d, dict) else None
    return a if isinstance(a, dict) and a.get("ref") else None


def save(active: dict | None, live: Path | None = None) -> None:
    p = _live(live) / STATE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"active": active, "updated": time.time()}, ensure_ascii=False, default=str),
                       encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def log(row: dict, live: Path | None = None) -> None:
    try:
        p = _live(live) / LOG
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), **row}, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def recent(live: Path | None = None, limit: int = 12) -> list[dict]:
    out = []
    try:
        with open(_live(live) / LOG, encoding="utf-8") as f:
            for line in f.readlines()[-200:]:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out[-limit:]


def picture(live: Path | None = None) -> dict:
    """What the brain sees: the job in force and the last steps."""
    return {"active": load(live), "recent": recent(live, 8),
            "rule": f"buy from a dealer only with an open team bid whose net beats the cost by {MIN_MARGIN_P} P; "
                    "one card at a time; plan field arbitrage: on|off"}


def dealer_order(live: Path | None = None) -> dict | None:
    """The job as a dealer order (same shape as the brain's dealer_orders) while we are still buying."""
    a = load(live)
    if not a or a.get("stage") != "buying":
        return None
    return {"dealer": a["dealer"], "action": "buy", "ref": a["ref"], "open": a.get("open"), "bound": int(a["cap"]),
            "max_messages": 5, "arbitrage": True,
            "why": f"arbitrage: {a['bid'].get('maker')} bids {a['bid'].get('cash')} P for {a['ref']} "
                   f"(net {a.get('resale_net')}); pay at most {a['cap']}"}


def rastro_fee(cash: int, cards: int = 1) -> int:
    """What we pay as the taker when we accept a bid on El Rastro (5 % + 1 P per card)."""
    try:
        from .protocol import taker_fee
        return int(taker_fee({"venue": "rastro", "fee_bps": 500, "fee_per_card": 1}, int(cash), cards))
    except Exception:  # noqa: BLE001
        return int(-(-int(cash) * 5 // 100) + cards)


def _single_card_bid(o: dict) -> str | None:
    """REF when the offer is a plain cash bid for one copy of one card, else None."""
    give, want = o.get("give") or {}, o.get("want") or {}
    types = list(want.get("types") or [])
    if int(give.get("cash") or 0) <= 0 or give.get("assets") or give.get("types"):
        return None
    if len(types) != 1 or want.get("assets") or int(want.get("cash") or 0) > 0:
        return None
    t = str(types[0])
    return t[5:].upper() if t.startswith("card:") else None


class Arbitrage:
    """One instance in the bot process: tracks open bids from the feed and runs the single job."""

    def __init__(self):
        from .bargain import FeedOffers
        self.feed = FeedOffers()

    # ---- bids we could sell into
    def open_bids(self, sit, my_id: str | None) -> dict[Any, dict]:
        """Open cash bids for one card on El Rastro that we may accept, by offer id."""
        tick = int(getattr(sit, "tick", 0) or 0)
        self.feed.ingest(getattr(sit, "feed_new", None) or [], tick)
        mine = {o.get("id") for o in getattr(sit, "my_offers", None) or [] if isinstance(o, dict)}
        out: dict[Any, dict] = {}
        book = getattr(sit, "rastro_book", None) or []
        fresh_book = getattr(sit, "slow_tick", -1) == tick
        for o in [*(book if fresh_book else []), *self.feed.open()]:
            if not isinstance(o, dict) or o.get("id") is None or o.get("id") in mine:
                continue
            if (o.get("venue") or "rastro") != "rastro" or o.get("thread") is not None:
                continue
            if (o.get("status") or "open") != "open" or o.get("maker") == my_id:
                continue
            if o.get("to") not in (None, my_id):
                continue
            ref = _single_card_bid(o)
            if ref is None:
                continue
            exp = o.get("expires_tick")
            if exp is not None and int(exp) <= tick:
                continue
            out[o["id"]] = {"id": o["id"], "ref": ref, "cash": int((o.get("give") or {}).get("cash") or 0),
                            "maker": o.get("maker"), "venue": "rastro", "to": o.get("to"),
                            "expires_tick": int(exp) if exp is not None else None, "raw": o}
        return out

    # ---- one tick
    def step(self, sit, control: dict | None, live: Path | None = None, mode: str = "on") -> list[Action]:
        control = control or {}
        me = getattr(sit, "me", None) or {}
        my_id, tick = me.get("id"), int(getattr(sit, "tick", 0) or 0)
        bids = self.open_bids(sit, my_id)
        active = load(live)
        if active is not None:
            return self._advance(active, sit, bids, live)
        if mode != "on" or getattr(sit, "paused", False) or getattr(sit, "doors", "open") != "open":
            return []
        job = self._find(sit, control, bids)
        if job is not None:
            save(job, live)
            log({"tick": tick, "step": "start", **{k: job[k] for k in ("ref", "dealer", "resale_net", "cap")},
                 "bid": job["bid"]}, live)
        return []                                   # the dealers domain opens the thread from dealer_order()

    def _held(self, me: dict, ref: str) -> list[dict]:
        return [a for a in me.get("assets") or [] if a.get("kind", "card") == "card" and a.get("ref") == ref]

    def _find(self, sit, control: dict, bids: dict) -> dict | None:
        from ..core import rails
        me = getattr(sit, "me", None) or {}
        tick, cash = int(getattr(sit, "tick", 0) or 0), int(me.get("cash") or 0)
        reserve = int(control.get("cash_reserve", config.CASH_RESERVE))
        unlocked = set(me.get("unlocked") or [])
        kept = rails.kept_sets(control)
        best = None
        for b in bids.values():
            ref = b["ref"]
            if b["expires_tick"] is None or b["expires_tick"] - tick < START_BID_LIFE_TICKS:
                continue
            mine = self._held(me, ref)
            set_id = ref.split("-")[0]
            rarity = (mine[0].get("rarity") if mine else None) or self._rarity(ref)
            if rarity not in RARITIES or set_id not in kept or not mine:
                continue        # avoided sets are not bought; a card we lack is our own goal, not stock to flip
            net = b["cash"] - rastro_fee(b["cash"], 1)
            cap = net - MIN_MARGIN_P
            for d in getattr(sit, "dealers", None) or []:
                if not isinstance(d, dict) or not (d.get("open_to_all") or d.get("id") in unlocked):
                    continue
                if d.get("status") not in (None, "active") or d.get("enabled") is False:
                    continue
                for e in (d.get("menu") or {}).get("sells") or []:
                    if e.get("rarity") != rarity or not e.get("list_price"):
                        continue
                    if isinstance(e.get("sets"), list) and set_id not in e["sets"]:
                        continue
                    est = int(round(float(e["list_price"]) * EST_CLOSE_FRAC))
                    if est > cap or cash - reserve < est:
                        continue
                    margin = net - est
                    if best is None or margin > best[0]:
                        best = (margin, {"ref": ref, "dealer": d["id"], "resale_net": net, "cap": int(cap),
                                         "open": max(1, int(round(est * OPEN_FRAC))), "est_close": est,
                                         "bid": {k: b[k] for k in ("id", "cash", "maker", "venue", "expires_tick")},
                                         "stage": "buying", "started_tick": tick, "seen_tick": tick,
                                         "held_before": [a.get("id") for a in mine], "asset_id": None,
                                         "cost": None})
        return best[1] if best else None

    @staticmethod
    def _rarity(ref: str) -> str | None:
        try:
            cat = json.loads((config.DATA / "record" / "latest" / "catalog.json").read_text(encoding="utf-8"))
            cat = cat.get("data", cat)
            for s in cat.get("sets") or []:
                for c in s.get("cards") or []:
                    if c.get("id") == ref:
                        return c.get("rarity")
        except (OSError, ValueError):
            pass
        return None

    def _advance(self, a: dict, sit, bids: dict, live: Path | None) -> list[Action]:
        me = getattr(sit, "me", None) or {}
        tick = int(getattr(sit, "tick", 0) or 0)
        held = self._held(me, a["ref"])
        new = [x for x in held if x.get("id") not in set(a.get("held_before") or [])]
        bid_open = a["bid"]["id"] in bids
        if bid_open:
            a["seen_tick"] = tick
            a["bid"]["expires_tick"] = bids[a["bid"]["id"]]["expires_tick"]
        if a["stage"] == "buying":
            if new:                                         # the card is really ours: sell it
                a.update(stage="selling", asset_id=new[0].get("id"), bought_tick=tick,
                         cost=a.get("cost") or self._paid(sit, a))
                log({"tick": tick, "step": "bought", "ref": a["ref"], "asset": a["asset_id"], "cost": a["cost"]}, live)
            elif not bid_open or (a["bid"].get("expires_tick") or 0) - tick < MIN_BID_LIFE_TICKS \
                    or tick - int(a.get("started_tick") or tick) > MAX_BUY_TICKS:
                why = "bid gone" if not bid_open else "bid about to expire" \
                    if (a["bid"].get("expires_tick") or 0) - tick < MIN_BID_LIFE_TICKS else "buy took too long"
                log({"tick": tick, "step": "aborted", "ref": a["ref"], "why": why}, live)
                save(None, live)
                return []
        if a["stage"] in ("selling", "stock"):
            if a.get("asset_id") is not None and not any(x.get("id") == a["asset_id"] for x in held):
                log({"tick": tick, "step": "sold", "ref": a["ref"], "asset": a["asset_id"], "cost": a.get("cost"),
                     "bid": a.get("selling_bid") or a["bid"]}, live)
                save(None, live)
                return []
            cost = int(a.get("cost") or a["cap"])
            target = bids.get(a["bid"]["id"])
            if target is None:                              # the buyer left: any bid above cost + a little
                if a["stage"] != "stock":
                    a["stage"] = "stock"
                    log({"tick": tick, "step": "stock", "ref": a["ref"], "cost": cost,
                         "why": "the bid vanished after we bought"}, live)
                alts = [b for b in bids.values() if b["ref"] == a["ref"]
                        and b["cash"] - rastro_fee(b["cash"], 1) >= cost + STOCK_MARGIN_P]
                target = max(alts, key=lambda b: b["cash"]) if alts else None
            save(a, live)
            if target is None:
                return []
            a["selling_bid"] = {k: target[k] for k in ("id", "cash", "maker", "venue", "expires_tick")}
            save(a, live)
            return [self._accept(a, target, cost)]
        save(a, live)
        return []

    @staticmethod
    def _paid(sit, a: dict) -> int:
        """What the dealer deal cost: its last standing price in the thread that just closed, else the cap."""
        for t in [*(getattr(sit, "closed_threads", None) or []), *(getattr(sit, "threads", None) or [])]:
            if not isinstance(t, dict) or t.get("with") != a["dealer"]:
                continue
            card = ((t.get("topic") or {}).get("buy") or {}).get("card")
            if str(card or "").upper() != a["ref"]:
                continue
            for m in reversed(t.get("messages") or []):
                o = m.get("offer") if isinstance(m, dict) else None
                c = int(((o or {}).get("want") or {}).get("cash") or 0) or int(((o or {}).get("give") or {}).get("cash") or 0)
                if o and c and (o.get("status") in ("accepted", "filled", "deal", None, "open")):
                    return c
        return int(a["cap"])

    @staticmethod
    def _accept(a: dict, b: dict, cost: int) -> Action:
        o = b.get("raw") or {}
        fee = rastro_fee(b["cash"], 1)
        expect = {"give": o.get("give") or {"cash": b["cash"], "assets": [], "types": []},
                  "want": o.get("want") or {"cash": 0, "assets": [], "types": [f"card:{a['ref']}"]},
                  "maker": b.get("maker"), "venue": "rastro"}
        gain = b["cash"] - fee - cost
        return Action(kind="accept_offer",
                      params={"offer": b["id"], "expect": expect, "assets": [a["asset_id"]],
                              "give": {"cash": fee, "assets": [a["asset_id"]]},
                              "want": {"cash": b["cash"], "assets": [], "types": []}, "arbitrage": True},
                      domain="market", source="code",
                      reason=f"arbitrage: sell {a['ref']} (cost {cost}) into bid #{b['id']} at {b['cash']} "
                             f"(fee {fee}): +{gain} P",
                      expected={"points": float(gain), "value_gain": float(gain), "spend": fee,
                                "counterparty": b.get("maker"), "kind": "arbitrage"},
                      priority=95.0)
