"""The duel as plain numbers: parsing the server's duel dict, surplus, rounds and points.

Score per duel (confirmed on Friday, to the decimal): points = margin x (1 - decay) ^ rounds.
margin = price - cost (seller) or value - price (buyer); no deal = 0; a deal outside the limit is negative.

Rounds, as the server counts them (fits every Friday duel we saw whole): a round is completed when
BOTH sides have made a priced offer, i.e. rounds ~= min(our priced messages, their priced messages).
Consequences the policy relies on:
  - accepting never adds a round;
  - a message from us while the rival has not answered our last one costs nothing (min unchanged);
  - answering a fresh rival offer with a counter costs one round.
The server's `rounds` field is always the truth; our counts only predict the next step.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

DAYS_MAX = 10
TICKS_PER_DUEL = 16          # Saturday's sessions: 16 ticks per duel
MIN_SURPLUS = 1              # never sign a price that leaves us less than this (rails re-check)
PRICE_MAX = 10_000_000
OUR_SENDERS = {"you", "us", "me", "self"}


def _num(x) -> float | None:
    try:
        if x is None or isinstance(x, bool):
            return None
        v = float(x)
        return v if v == v and abs(v) != float("inf") else None
    except (TypeError, ValueError):
        return None


@dataclass
class Offer:
    price: int
    days: int | None = None
    tick: int | None = None
    id: Any = None

    def key(self) -> tuple:
        return (self.price, self.days)

    def as_expect(self) -> dict:
        d = {"id": self.id, "price": self.price, "tick": self.tick}
        if self.days is not None:
            d["days"] = self.days
        return d


def parse_offer(x) -> Offer | None:
    """An Offer from {"price", "days", "tick", "id"} (or nested in "offer"); None if unusable."""
    if not isinstance(x, dict):
        return None
    if isinstance(x.get("offer"), dict):
        inner = parse_offer({**x["offer"], "tick": x.get("tick"), "id": x.get("id")})
        if inner:
            return inner
    p = _num(x.get("price"))
    if p is None or p != int(p) or not (1 <= p <= PRICE_MAX):
        return None
    d = _num(x.get("days"))
    days = int(d) if d is not None and d == int(d) and 0 <= d <= DAYS_MAX else None
    t = _num(x.get("tick"))
    return Offer(price=int(p), days=days, tick=None if t is None else int(t), id=x.get("id"))


@dataclass
class Msg:
    tick: int
    ours: bool
    price: int | None
    days: int | None
    text: str


@dataclass
class DuelView:
    """Everything the negotiator needs about one live duel, already structured."""
    id: int
    session: Any
    role: str                  # "seller" | "buyer"
    item: str
    limit: int                 # seller: cost, buyer: value
    rival: str                 # alias, e.g. "Rival Azul"
    tick: int                  # current game tick
    deadline_tick: int
    decay: float
    rounds: int
    uses_days: bool
    w: float                   # your_days_weight (0 when the duel is price-only)
    days_meaning: str
    our_offer: Offer | None
    rival_offer: Offer | None
    messages: list[Msg] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    # --- derived -------------------------------------------------------------------------------
    @property
    def q(self) -> float:
        return 1.0 - self.decay

    @property
    def ticks_left(self) -> int:
        """Ticks we can still act in, this one included."""
        return max(0, self.deadline_tick - self.tick)

    @property
    def elapsed(self) -> int:
        return max(0, TICKS_PER_DUEL - self.ticks_left)

    def rival_msgs(self) -> list[Msg]:
        return [m for m in self.messages if not m.ours and m.price is not None]

    def our_msgs(self) -> list[Msg]:
        return [m for m in self.messages if m.ours and m.price is not None]

    def rival_offers(self) -> list[Offer]:
        out = [Offer(m.price, m.days, m.tick) for m in self.rival_msgs()]
        if not out and self.rival_offer:
            out = [self.rival_offer]
        return out

    def our_offers(self) -> list[Offer]:
        out = [Offer(m.price, m.days, m.tick) for m in self.our_msgs()]
        if not out and self.our_offer:
            out = [self.our_offer]
        return out

    def sent_this_tick(self) -> bool:
        return any(m.ours and m.tick == self.tick for m in self.messages)

    def surplus(self, price: float) -> float:
        return surplus(self.role, self.limit, price)

    def utility(self, price: float, days: int | None) -> float:
        """Our margin in points before decay: price surplus plus the value of the delivery days."""
        u = self.surplus(price)
        if self.uses_days and days is not None:
            u += self.w * days
        return u

    def rounds_if_we_send(self) -> int:
        """Rounds after a new priced message from us (no change while they owe us an answer)."""
        n_our, n_riv = len(self.our_msgs()), len(self.rival_msgs())
        return self.rounds + (1 if n_our < n_riv else 0)

    def unanswered_rival_offer(self) -> bool:
        """The rival spoke after our last priced message (a counter now costs a round)."""
        priced = [m for m in self.messages if m.price is not None]
        if priced:
            return not priced[-1].ours
        return self.rival_offer is not None and self.our_offer is None


def surplus(role: str, limit: float, price: float) -> float:
    return (price - limit) if role == "seller" else (limit - price)


def price_for(role: str, limit: float, s: float) -> int:
    """Whole-prima price that gives us surplus `s`, rounded in our favour, never outside the limit."""
    s = max(float(MIN_SURPLUS), s)
    if role == "seller":
        return max(1, int(math.ceil(limit + s)))
    return max(1, int(math.floor(limit - s)))


def points(margin: float, decay: float, rounds: int) -> float:
    return margin * (1.0 - decay) ** max(0, rounds)


def parse_duel(d: dict, tick: int) -> DuelView | None:
    """DuelView from one /api/duels entry; None when it is not a live, well-formed duel."""
    if not isinstance(d, dict) or d.get("status", "live") != "live" or d.get("result") not in (None, ""):
        return None
    role = d.get("role")
    limit = _num(d.get("your_limit"))
    did = _num(d.get("duel", d.get("id")))
    if role not in ("seller", "buyer") or limit is None or did is None:
        return None
    issues = d.get("issues") or ["price"]
    w = _num(d.get("your_days_weight"))
    uses_days = "days" in issues or w is not None
    rival = str(d.get("rival") or "rival")
    msgs: list[Msg] = []
    for m in d.get("messages") or []:
        if not isinstance(m, dict):
            continue
        who = str(m.get("from", m.get("sender", "")))
        off = parse_offer(m)
        t = _num(m.get("tick"))
        msgs.append(Msg(tick=int(t) if t is not None else -1, ours=who.lower() in OUR_SENDERS,
                        price=off.price if off else None, days=off.days if off else None,
                        text=str(m.get("text") or "")))
    dl = _num(d.get("deadline_tick"))
    return DuelView(
        id=int(did), session=d.get("session"), role=role, item=str(d.get("item") or ""),
        limit=int(limit), rival=rival, tick=int(tick),
        deadline_tick=int(dl) if dl is not None else int(tick) + TICKS_PER_DUEL,
        decay=_num(d.get("decay_per_round")) or 0.06, rounds=int(_num(d.get("rounds")) or 0),
        uses_days=bool(uses_days), w=float(w or 0.0) if uses_days else 0.0,
        days_meaning=str(d.get("days_meaning") or ""),
        our_offer=parse_offer(d.get("your_offer")), rival_offer=parse_offer(d.get("rival_offer")),
        messages=msgs, raw=d,
    )
