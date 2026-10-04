"""The blind question the matcher asks about two teams' private limits, and the price that leaks neither.

    quote(seller, buyer, ref, ref_price, floor, salt, ask, bid) -> {"price", "overlap", "value", "basis"}

Only this module reads the vault's numbers on behalf of the matcher, and only a price, a yes/no on the overlap and a
yes/no on "the buyer values it more" ever leave it. Four rules keep a limit from being read from outside:

1. A private limit is only ever compared with the OTHER side's private limit. A public ask or bid never stands in
   for a missing one: a team that publishes prices and watches which matches appear would otherwise find the other
   side's limit in a dozen tries. With one private limit, or none, the quote is the public one and the limit is not
   looked at (the team's own agent queue checks it, for that team alone).
2. The price is the public reference price pulled strictly inside the overlap: a secret share of the overlap and
   at least one step of the price grid away from each end, rounded towards the inside (`matcher.inside`), so it
   never equals either limit. The share comes from the vault's key and from
   BOTH limits, so a team that moves its own limit gets a new, unrelated margin and cannot solve for the other's.
   An overlap narrower than 2 P has no inside: no match.
3. A refusal that looked at private numbers is kept for `HOLD_TICKS`: asking again gives no new answer.
4. A public ask or bid that changes is taken up only `HOLD_TICKS` after its last change: prices published one after
   another to see how the other side's agent reacts are not followed."""
from __future__ import annotations

import hashlib
import hmac
import threading
import time

from . import matcher

HOLD_TICKS = 20
HOLD_S = 300.0                  # the same hold when the game clock stands still
MAX_KEPT = 20000
MIN_SHARE = 0.05                # of the overlap, on each side, at the very least
NO = {"price": None, "overlap": False, "value": None, "basis": None}


class Quoter:
    def __init__(self, vault, hold_ticks: int = HOLD_TICKS, clock=time.time):
        self.vault, self.hold, self.clock = vault, hold_ticks, clock
        self.lock = threading.Lock()
        self.tick = 0
        self.kept: dict[tuple, tuple] = {}                     # (seller, buyer, ref) -> (tick, ts) of its last refusal
        self.public: dict[tuple, dict] = {}                    # (team, ref, side) -> the price in force and since when

    def _fresh(self, tick: int, ts: float) -> bool:
        """Is something that happened at (tick, ts) still inside the hold?"""
        if self.tick != tick:
            return 0 <= self.tick - tick < self.hold
        return self.clock() - ts < HOLD_S

    def at(self, tick: int | None) -> "Quoter":
        with self.lock:
            self.tick = int(tick or 0)
            self.kept = {k: v for k, v in self.kept.items() if self._fresh(*v)}
            if len(self.public) > MAX_KEPT:
                self.public = {k: v for k, v in self.public.items() if self._fresh(v["tick"], v["ts"])}
        return self

    def _share(self, salt: str, lo: int, hi: int) -> float:
        """MIN_SHARE to MAX_MARGIN, unknowable without the vault's key, and new whenever either limit moves."""
        digest = hmac.new(self.vault.key, f"margin|{salt}|{lo}|{hi}".encode(), hashlib.sha256).digest()
        unit = (int.from_bytes(digest[:4], "big") % 1000) / 999.0
        return MIN_SHARE + unit * (matcher.MAX_MARGIN - MIN_SHARE)

    def _limits(self, seller: str, buyer: str, ref: str) -> tuple:
        with self.vault.lock:
            s = dict((self.vault.data.get(seller) or {}).get(ref) or {})
            b = dict((self.vault.data.get(buyer) or {}).get(ref) or {})
        return s.get("min"), b.get("max"), s.get("value"), b.get("value")

    def _steady(self, team: str, ref: str, side: str, price):
        """The public price in force: a change is followed only once the last one is HOLD_TICKS old."""
        price = price or None
        key = (team, ref, side)
        with self.lock:
            cur = self.public.get(key)
            if cur is None:
                if price is not None:
                    self.public[key] = {"price": price, "tick": self.tick, "ts": self.clock()}
                return price
            if price == cur["price"]:
                cur.pop("next", None)
                return price
            if self._fresh(cur["tick"], cur["ts"]):
                return cur["price"]                            # changed again too soon: the one in force stays
            self.public[key] = {"price": price, "tick": self.tick, "ts": self.clock()}
            return price

    def quote(self, seller: str, buyer: str, ref: str, ref_price: float, floor: int = 1, salt: str = "",
              ask=None, bid=None) -> dict:
        key = (seller, buyer, ref)
        ask, bid = self._steady(seller, ref, "ask", ask), self._steady(buyer, ref, "bid", bid)
        with self.lock:
            if key in self.kept:                               # refused a moment ago: the same answer, unasked
                return dict(NO)
        out = self._quote(seller, buyer, ref, ref_price, floor, salt or "|".join(key), ask, bid)
        if out.pop("held", False):
            with self.lock:
                self.kept[key] = (self.tick, self.clock())
        return out

    def _quote(self, seller, buyer, ref, ref_price, floor, salt, ask, bid) -> dict:
        lo, hi, v_sell, v_buy = self._limits(seller, buyer, ref)
        value = None if v_sell is None or v_buy is None else bool(v_buy > v_sell)
        if value is False:                                     # the trade would destroy value: no, and kept
            return {**NO, "value": False, "held": True}
        if lo is None or hi is None:                           # not both private: only what the teams published
            return {**matcher.public_quote(seller, buyer, ref, ref_price, floor, salt, ask, bid), "value": value}
        low, high = max(int(lo), int(floor)), int(hi)
        margin = max(1, int((high - low) * self._share(salt, int(lo), int(hi)))) if high > low else 1
        price = matcher.inside(low, high, ref_price, margin)
        if price is None:                                      # no overlap, or one with no inside
            return {**NO, "value": value, "held": True}
        return {"price": price, "overlap": True, "value": value, "basis": "limits"}

    def prefers(self, team: str, get: str, give: str) -> bool | None:
        """For a swap: is the card the team gets worth more to it than the one it gives? None: it did not say."""
        with self.vault.lock:
            mine = self.vault.data.get(team) or {}
            a, b = (mine.get(get) or {}).get("value"), (mine.get(give) or {}).get("value")
        return None if a is None or b is None else bool(a > b)

    def overlap(self, seller: str, buyer: str, ref: str) -> bool | None:
        """For our panel: do the two limits meet? Yes, no, or not both set. Never a number."""
        lo, hi, _, _ = self._limits(seller, buyer, ref)
        return None if lo is None or hi is None else bool(hi >= lo)
