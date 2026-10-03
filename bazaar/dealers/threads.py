"""A structured view of one dealer conversation, built from the raw `/api/me/threads` item.

Raw shape (Friday): {"id", "kind": "persona", "with": "abuela", "topic": {"buy": {...}} | {"sell": {"assets": [..]}},
"status", "created_tick", "messages": [{"id", "tick", "sender", "text", "price"?, "offer"?}],
"standing_offers": [{"id", "maker", "to", "give", "want", "final", "status", "expires_tick", ...}], "closed_reason"}.
A dealer offer when we buy: give = {"types": ["card:LAV-09"]} | assets, want = {"cash": p}.
A dealer offer when we sell: give = {"cash": p}, want = {"assets": [ids]}.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ThreadView:
    id: int
    dealer: str
    side: str                     # "buy" (we buy from the dealer) | "sell" (we sell to it)
    topic: dict
    item: str                     # card ref, pack id or "rarity:set"; sells: the ref of the asset
    status: str = "open"
    created_tick: int = 0
    ours: list[int] = field(default_factory=list)          # our prices, in order
    theirs: list[int] = field(default_factory=list)        # dealer prices, in order
    their_ticks: list[int] = field(default_factory=list)
    our_ticks: list[int] = field(default_factory=list)
    opening: int | None = None                             # dealer's first price
    standing: dict | None = None                           # the dealer's open offer, if any
    standing_price: int | None = None
    final: bool = False
    last_sender: str | None = None                         # "us" | "dealer"
    last_dealer_text: str = ""
    dealer_msg_ids: list[Any] = field(default_factory=list)
    closed_reason: str | None = None
    is_pack: bool = False
    asset_ids: list[int] = field(default_factory=list)

    @property
    def buying(self) -> bool:
        return self.side == "buy"

    @property
    def last_ours(self) -> int | None:
        return self.ours[-1] if self.ours else None

    @property
    def last_theirs(self) -> int | None:
        if self.standing_price is not None:
            return self.standing_price
        return self.theirs[-1] if self.theirs else None

    def their_concessions(self) -> list[int]:
        """How much the dealer moved in our favour at each step (buy: price drops; sell: price rises)."""
        t = self.theirs
        return [(a - b) if self.buying else (b - a) for a, b in zip(t, t[1:])]

    def our_concessions(self) -> list[int]:
        o = self.ours
        return [(b - a) if self.buying else (a - b) for a, b in zip(o, o[1:])]

    def to_prompt(self) -> dict:
        return {"thread": self.id, "dealer": self.dealer, "we": self.side, "item": self.item,
                "dealer_opening": self.opening, "dealer_prices": self.theirs[-8:], "our_prices": self.ours[-8:],
                "standing_offer": self.standing_price, "final": self.final, "waiting_for": (
                    "dealer" if self.last_sender == "us" else "us")}


def _cash(side: dict | None) -> int | None:
    if not isinstance(side, dict):
        return None
    c = side.get("cash")
    try:
        return int(c) if c not in (None, 0, "0") else None
    except (TypeError, ValueError):
        return None


def dealer_price(offer: dict | None, buying: bool) -> int | None:
    if not offer:
        return None
    return _cash(offer.get("want")) if buying else _cash(offer.get("give"))


def our_price(msg: dict, buying: bool) -> int | None:
    if msg.get("price") is not None:
        try:
            return int(msg["price"])
        except (TypeError, ValueError):
            return None
    o = msg.get("offer") or {}
    return _cash(o.get("give")) if buying else _cash(o.get("want"))


def item_of(topic: dict, assets_by_id: dict[int, dict] | None = None, standing: dict | None = None) -> tuple[str, bool, list[int]]:
    if "buy" in topic:
        b = topic.get("buy") or {}
        if b.get("pack"):
            return str(b["pack"]), True, []
        if b.get("card"):
            return str(b["card"]), False, []
        # rarity/set request: the dealer's offer names the card
        for ty in ((standing or {}).get("give") or {}).get("types") or []:
            if str(ty).startswith("card:"):
                return str(ty)[5:], False, []
        return f"{b.get('rarity', '?')}:{b.get('set', '*')}", False, []
    ids = [int(i) for i in ((topic.get("sell") or {}).get("assets") or [])]
    refs = [(assets_by_id or {}).get(i, {}).get("ref") for i in ids]
    return (refs[0] if refs and refs[0] else (f"asset:{ids[0]}" if ids else "?")), False, ids


def parse_thread(raw: dict, assets_by_id: dict[int, dict] | None = None) -> ThreadView | None:
    """None for anything that is not a conversation with a dealer."""
    if not isinstance(raw, dict) or raw.get("kind", "persona") != "persona" or not raw.get("with"):
        return None
    topic = raw.get("topic") or {}
    side = "buy" if "buy" in topic else "sell" if "sell" in topic else None
    if side is None:
        return None
    buying = side == "buy"
    dealer = str(raw["with"])
    open_offers = [o for o in raw.get("standing_offers") or []
                   if o.get("maker") == dealer and o.get("status", "open") == "open"]
    standing = max(open_offers, key=lambda o: (o.get("created_tick") or 0, o.get("id") or 0)) if open_offers else None
    item, is_pack, ids = item_of(topic, assets_by_id, standing)
    v = ThreadView(id=int(raw["id"]), dealer=dealer, side=side, topic=topic, item=item,
                   status=raw.get("status", "open"), created_tick=int(raw.get("created_tick") or 0),
                   closed_reason=raw.get("closed_reason"), is_pack=is_pack, asset_ids=ids)
    for m in raw.get("messages") or []:
        tick = int(m.get("tick") or 0)
        if m.get("sender") == dealer:
            p = dealer_price(m.get("offer"), buying)
            if p is not None:
                v.theirs.append(p)
                v.their_ticks.append(tick)
                if (m.get("offer") or {}).get("final"):
                    v.final = True
            v.last_dealer_text = m.get("text") or v.last_dealer_text
            v.dealer_msg_ids.append(m.get("id"))
            v.last_sender = "dealer"
        else:
            p = our_price(m, buying)
            if p is not None:
                v.ours.append(p)
                v.our_ticks.append(tick)
            v.last_sender = "us"
    if standing:
        v.standing = standing
        v.standing_price = dealer_price(standing, buying)
        v.final = v.final or bool(standing.get("final"))
        if v.standing_price is not None and (not v.theirs or v.theirs[-1] != v.standing_price):
            v.theirs.append(v.standing_price)
            v.their_ticks.append(int(standing.get("created_tick") or 0))
    else:
        v.final = False if not v.theirs else v.final
    v.opening = v.theirs[0] if v.theirs else None
    return v


def offer_matches(view: ThreadView, offer: dict) -> tuple[bool, str]:
    """Structure check before accepting: the words may lie, the offer may not.

    Buy: the dealer gives exactly the item of the topic and wants only cash.
    Sell: the dealer gives only cash and wants exactly the assets we put in the topic.
    """
    if not offer or offer.get("maker") != view.dealer:
        return False, "not the dealer's offer"
    if offer.get("status", "open") != "open":
        return False, "offer not open"
    give, want = offer.get("give") or {}, offer.get("want") or {}
    if view.buying:
        if _cash(give) or want.get("assets") or want.get("types"):
            return False, "dealer asks for more than cash"
        types = list(give.get("types") or [])
        assets = list(give.get("assets") or [])
        if len(types) + len(assets) != 1:
            return False, "dealer gives more or less than one item"
        generic = (not view.is_pack) and ":" in view.item        # a rarity/set request: any card fits
        if types:
            ty = str(types[0])
            if view.is_pack and ty != f"pack:{view.item}":
                return False, f"dealer gives {ty}, not pack:{view.item}"
            if not view.is_pack and not generic and ty != f"card:{view.item}":
                return False, f"dealer gives {ty}, not card:{view.item}"
            if generic and not ty.startswith("card:"):
                return False, f"dealer gives {ty}, not a card"
        else:
            a = assets[0] if isinstance(assets[0], dict) else {}
            ref = a.get("ref")
            if view.is_pack and a.get("kind") not in (None, "pack"):
                return False, "dealer gives a card, not the pack"
            if not view.is_pack and not generic and ref != view.item:
                return False, f"dealer gives {ref}, not {view.item}"
        if not _cash(want):
            return False, "no price"
        return True, "ok"
    if give.get("assets") or give.get("types") or _cash(want) or want.get("types"):
        return False, "dealer offer is not cash for our card"
    wanted = sorted(int(a["id"] if isinstance(a, dict) else a) for a in want.get("assets") or [])
    if wanted != sorted(view.asset_ids):
        return False, "dealer wants other assets than the topic"
    if not _cash(give):
        return False, "no price"
    return True, "ok"
