"""Our private values: what a card or a pack is worth to Team 10.

Exact figures come from the game: `/api/me` gives `your_value` for every card we hold (the value of the
last copy, i.e. what we lose by giving one away) and `/api/me/value?card=` the value of one more copy of
any card. Between those reads we estimate: book x our set multiplier x the copy marginal
(1st copy 1.0, 2nd 0.25, 3rd 0.1). The estimate ignores page bonuses, so it is conservative for buys.
"""
from __future__ import annotations

import time
from typing import Any

# Friday: 42 opened packs gave 128 cards: 3.05 per pack, 77% common, 21% uncommon, 2% rare (seed L14).
FRIDAY_PACK_STATS = {"cards": 3.05, "mix": {"common": 0.77, "uncommon": 0.21, "rare": 0.02}}
DEFAULT_BOOK = {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}
DEFAULT_MARGINALS = [1.0, 0.25, 0.1]
EXACT_TTL_S = 1800


class Values:
    def __init__(self, me: dict, catalog: dict | None = None, exact: dict | None = None):
        self.me = me or {}
        self.catalog = catalog or {}
        self.exact = exact if exact is not None else {}       # ref -> {"count", "value", "at"}
        self.affinity: dict[str, float] = dict(self.me.get("affinity") or {})
        self.marginals = (self.catalog.get("values") or {}).get("copy_marginals") or DEFAULT_MARGINALS
        books = {r: (v.get("book") if isinstance(v, dict) else v)
                 for r, v in (self.catalog.get("rarities") or {}).items()}
        self.book_by_rarity = {**DEFAULT_BOOK, **{k: v for k, v in books.items() if v}}
        self.cards: dict[str, dict] = {}
        for s in self.catalog.get("sets") or []:
            for c in s.get("cards") or []:
                self.cards[c["id"]] = {**c, "set": s["id"], "released": bool(s.get("released"))}
        self.assets: dict[int, dict] = {}
        self.held: dict[str, list[dict]] = {}
        for a in self.me.get("assets") or []:
            self.assets[a.get("id")] = a
            if a.get("kind", "card") == "card" and a.get("ref"):
                self.held.setdefault(a["ref"], []).append(a)

    # --- cards -----------------------------------------------------------------
    @staticmethod
    def set_of(ref: str) -> str:
        return str(ref).split("-")[0]

    def rarity(self, ref: str) -> str | None:
        c = self.cards.get(ref)
        if c:
            return c.get("rarity")
        for a in self.held.get(ref, []):
            return a.get("rarity")
        return None

    def book(self, ref: str) -> float:
        c = self.cards.get(ref)
        if c and c.get("book"):
            return float(c["book"])
        return float(self.book_by_rarity.get(self.rarity(ref) or "common", 10))

    def count(self, ref: str) -> int:
        return len(self.held.get(ref, []))

    def marginal(self, i: int) -> float:
        m = self.marginals
        return m[i] if i < len(m) else m[-1]

    def estimate_next(self, ref: str) -> float:
        return self.book(ref) * self.affinity.get(self.set_of(ref), 1.0) * self.marginal(self.count(ref))

    def next_copy(self, ref: str) -> float:
        """Value to us of ONE MORE copy of `ref` (exact when a fresh /api/me/value read matches our count)."""
        ex = self.exact.get(ref)
        if ex and ex.get("count") == self.count(ref) and time.time() - ex.get("at", 0) < EXACT_TTL_S:
            return float(ex["value"])
        return self.estimate_next(ref)

    def is_exact(self, ref: str) -> bool:
        ex = self.exact.get(ref)
        return bool(ex and ex.get("count") == self.count(ref) and time.time() - ex.get("at", 0) < EXACT_TTL_S)

    def remember_exact(self, ref: str, response: Any) -> float | None:
        v = None
        if isinstance(response, dict):
            v = response.get("your_value", response.get("value"))
        elif isinstance(response, (int, float)):
            v = response
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        self.exact[ref] = {"count": self.count(ref), "value": v, "at": time.time()}
        return v

    def asset_value(self, asset_id: int) -> float:
        """What we lose by giving this asset away (your_value from /api/me, else the estimate)."""
        a = self.assets.get(asset_id) or {}
        if a.get("your_value") is not None:
            return float(a["your_value"])
        if a.get("ref"):
            ref = a["ref"]
            return self.book(ref) * self.affinity.get(self.set_of(ref), 1.0) * self.marginal(max(0, self.count(ref) - 1))
        return 0.0

    def released_refs(self, rarity: str | None = None) -> list[str]:
        return [r for r, c in self.cards.items() if c.get("released") and not c.get("hidden")
                and (rarity is None or c.get("rarity") == rarity)]

    # --- packs -----------------------------------------------------------------
    def mean_value(self, rarity: str) -> float:
        refs = self.released_refs(rarity)
        if refs:
            return sum(self.next_copy(r) for r in refs) / len(refs)
        aff = list(self.affinity.values()) or [1.0]
        return self.book_by_rarity.get(rarity, 10) * sum(aff) / len(aff)


def pack_value(pack_id: str, values: Values, catalog: dict | None = None) -> float:
    """Expected value to us of a sealed pack.

    With the catalog: each slot draws a rarity with its probability, then a card of that rarity uniformly
    from the released sets, valued as one more copy for us. Without it: Friday's measured pack stats.
    """
    catalog = catalog or values.catalog
    pack = next((p for p in (catalog.get("packs") or []) if p.get("id") == pack_id), None)
    if pack and pack.get("slots"):
        return round(sum(p * values.mean_value(r) for slot in pack["slots"] for r, p in slot.items()), 2)
    st = FRIDAY_PACK_STATS
    return round(st["cards"] * sum(share * values.mean_value(r) for r, share in st["mix"].items()), 2)
