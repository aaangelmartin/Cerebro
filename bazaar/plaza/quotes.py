"""The blind question the matcher asks about two teams' private limits, and the price that leaks neither.

    quote(seller, buyer, ref, ref_price, floor, salt, ask, bid) -> {"price", "overlap", "value", "basis"}

Only this module reads the vault's numbers on behalf of the matcher, and only a price, a yes/no on the overlap and a
yes/no on "the buyer values it more" ever leave it. The price is the public reference price pulled inside the
overlap with a margin drawn in secret (from the vault's key, never from anything a team can compute), so a team
that knows its own limit cannot work out the other's: see `matcher.rule_price`.

The margin is fixed per pair and card, so asking again gives the same price: there is nothing to average out. A
refusal (the limits do not meet) is kept for `HOLD_TICKS`: a team that moves its limit step by step to find where
the other side's lies gets no new answer until the hold ends, on top of the cooldown the vault puts on edits."""
from __future__ import annotations

import hashlib
import hmac
import threading

from . import matcher

HOLD_TICKS = 20


class Quoter:
    def __init__(self, vault, hold_ticks: int = HOLD_TICKS):
        self.vault, self.hold = vault, hold_ticks
        self.lock = threading.Lock()
        self.tick = 0
        self.kept: dict[tuple, int] = {}                       # (seller, buyer, ref) -> tick of its last refusal

    def at(self, tick: int | None) -> "Quoter":
        with self.lock:
            self.tick = int(tick or 0)
            self.kept = {k: v for k, v in self.kept.items() if self.tick - v < self.hold}
        return self

    def _share(self, salt: str) -> float:
        """0 to MAX_MARGIN, fixed per pair and card, unknowable without the vault's key."""
        digest = hmac.new(self.vault.key, b"margin|" + salt.encode(), hashlib.sha256).digest()
        return (int.from_bytes(digest[:4], "big") % 1000) / 1000.0 * matcher.MAX_MARGIN

    def _limits(self, seller: str, buyer: str, ref: str) -> tuple:
        with self.vault.lock:
            s = dict((self.vault.data.get(seller) or {}).get(ref) or {})
            b = dict((self.vault.data.get(buyer) or {}).get(ref) or {})
        return s.get("min"), b.get("max"), s.get("value"), b.get("value")

    def quote(self, seller: str, buyer: str, ref: str, ref_price: float, floor: int = 1, salt: str = "",
              ask=None, bid=None) -> dict:
        key = (seller, buyer, ref)
        with self.lock:
            if key in self.kept:                               # refused a moment ago: the same answer, unasked
                return {"price": None, "overlap": False, "value": None, "basis": None}
        out = self._quote(seller, buyer, ref, ref_price, floor, salt or "|".join(key), ask, bid)
        if out["overlap"] is False and out.get("held"):
            with self.lock:
                self.kept[key] = self.tick
        out.pop("held", None)
        return out

    def _quote(self, seller, buyer, ref, ref_price, floor, salt, ask, bid) -> dict:
        lo, hi, v_sell, v_buy = self._limits(seller, buyer, ref)
        value = None if v_sell is None or v_buy is None else bool(v_buy > v_sell)
        no = {"price": None, "overlap": False, "value": value, "basis": None, "held": lo is not None and hi is not None}
        if lo is None and hi is None:                          # nothing private: what the teams published
            return {**matcher.public_quote(seller, buyer, ref, ref_price, floor, salt, ask, bid), "value": value}
        low = lo if lo is not None else ask                    # a public ask or bid stands in for a missing limit
        high = hi if hi is not None else bid
        if low is not None and high is not None:
            price = matcher.rule_price(low, high, ref_price, floor, self._share(salt))
            return {"price": price, "overlap": True, "value": value, "basis": "limits"} if price is not None else no
        price = max(int(floor), matcher.grid(ref_price or 0))  # one limit only: the public price passes or not
        if (low is not None and price < low) or (high is not None and price > high):
            return no
        return {"price": price, "overlap": None, "value": value, "basis": None}

    def overlap(self, seller: str, buyer: str, ref: str) -> bool | None:
        """For our panel: do the two limits meet? Yes, no, or not both set. Never a number."""
        lo, hi, _, _ = self._limits(seller, buyer, ref)
        return None if lo is None or hi is None else bool(hi >= lo)
