"""Offline tests for the market strategy: a fake client, no network.

    python3 -m unittest bot.tests.test_market
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bot import core
from bot.core import Ctx, Journal, TickBudget, Values
from bot.strategies.market import Strategy

CATALOG = {"values": {"copy_marginals": [1.0, 0.25, 0.1]}, "sets": [
    {"id": "LAV", "released": True, "cards": [{"id": f"LAV-0{i}", "book": 10, "rarity": "common"} for i in range(1, 6)]},
    {"id": "LAT", "released": True, "cards": [{"id": f"LAT-0{i}", "book": 10, "rarity": "common"} for i in range(1, 6)]},
]}


def card(aid, ref, serial=1):
    return {"id": aid, "kind": "card", "ref": ref, "serial": serial}


def offer(oid, give_assets=(), give_cash=0, want_cash=0, want_types=(), maker="mX", give_types=()):
    return {"id": oid, "maker": maker, "to": None, "venue": "rastro", "thread": None, "status": "open",
            "give": {"cash": give_cash, "assets": list(give_assets), "types": list(give_types)},
            "want": {"cash": want_cash, "assets": [], "types": list(want_types)}, "expires_tick": 99}


class FakeB:
    def __init__(self, board, team_offers=()):
        self._board, self._team = board, list(team_offers)
        self.calls = []

    def my_offers(self):
        return {"offers": self._team}

    def venues(self):
        return {"venues": [{"venue": "rastro", "status": "open", "fee_bps": 500, "fee_per_card": 1, "owner": "world"}]}

    def board(self, venue):
        return {"offers": self._board}

    def value(self, ref):
        raise core.BazaarError("not_needed")

    def accept(self, oid, assets=None):
        self.calls.append(("accept", oid, assets))
        return {"ok": True}

    def list_offer(self, give, want, venue=None, expires_in_ticks=40):
        self.calls.append(("list", give, want))
        return {"id": 1000 + len(self.calls)}

    def cancel(self, oid):
        self.calls.append(("cancel", oid))
        return {}


def make_ctx(b, assets, cash=400, memory=None):
    me = {"id": "t10", "cash": cash, "affinity": {"LAV": 1.6, "LAT": 0.5}, "assets": assets}
    clock = {"tick": 5, "limits": {}}
    j = Journal()
    return Ctx(b=b, me=me, clock=clock, catalog=CATALOG, values=Values(me, CATALOG), budget=TickBudget(clock),
               journal=j, dry_run=False, env={}, memory=memory if memory is not None else {})


class MarketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        core.DATA = Path(self.tmp.name)  # keep the journal out of bot/data

    def tearDown(self):
        self.tmp.cleanup()

    def accepts(self, b):
        return [c for c in b.calls if c[0] == "accept"]

    def test_buys_underpriced_card_we_lack(self):
        b = FakeB([offer(1, [card(500, "LAV-04")], want_cash=10)])
        ctx = make_ctx(b, [card(1, "LAV-01")])
        ctx.memory["exact"] = {"LAV-04": {"count": 0, "value": 16.0}}
        Strategy().tick(ctx)
        self.assertEqual(self.accepts(b), [("accept", 1, None)])
        self.assertIn("1", ctx.memory["pending"])

    def test_skips_own_team_offer_and_low_margin(self):
        own = offer(2, [card(501, "LAV-05")], want_cash=5, maker="t10")
        b = FakeB([offer(2, [card(501, "LAV-05")], want_cash=5, maker="mSelf"),
                   offer(3, [card(502, "LAT-02")], want_cash=4)], team_offers=[own])
        ctx = make_ctx(b, [card(1, "LAV-01")])
        Strategy().tick(ctx)
        self.assertEqual(self.accepts(b), [])
        self.assertIn("mSelf", ctx.memory["aliases"])

    def test_cash_reserve(self):
        b = FakeB([offer(1, [card(500, "LAV-04")], want_cash=10)])
        ctx = make_ctx(b, [card(1, "LAV-01")], cash=125)
        ctx.memory["exact"] = {"LAV-04": {"count": 0, "value": 16.0}}
        Strategy().tick(ctx)
        self.assertEqual(self.accepts(b), [])

    def test_swaps_spare_into_cash_bid_but_never_protected_first_copy(self):
        bid_lav = offer(4, give_cash=12, want_types=["card:LAV-01"])  # we hold one LAV-01: protected
        bid_lat = offer(5, give_cash=9, want_types=["card:LAT-03"])   # we hold two LAT-03: spare
        b = FakeB([bid_lav, bid_lat])
        ctx = make_ctx(b, [card(1, "LAV-01"), card(2, "LAT-03", 1), card(3, "LAT-03", 2)])
        Strategy().tick(ctx)
        self.assertEqual(self.accepts(b), [("accept", 5, [3])])
        listed = [c[1]["assets"][0] for c in b.calls if c[0] == "list"]
        self.assertNotIn(3, listed)               # the copy we just swapped away

    def test_lists_spares_undercutting_but_not_below_floor(self):
        b = FakeB([offer(7, [card(600, "LAT-03")], want_cash=6), offer(8, [card(601, "LAV-02")], want_cash=40)])
        ctx = make_ctx(b, [card(1, "LAV-01"), card(2, "LAV-01", 2), card(3, "LAT-03", 1), card(4, "LAT-03", 2)])
        Strategy().tick(ctx)
        lists = {c[1]["assets"][0]: c[2]["cash"] for c in b.calls if c[0] == "list"}
        self.assertEqual(lists[4], 5)            # rival at 6 -> 5 (floor max(1.25+3, 4) = 5)
        self.assertEqual(lists[2], 10)           # no rival: book
        self.assertNotIn(1, lists)               # first copy of a 1.6 set never listed
        self.assertNotIn(3, lists)               # one listing per card

    def test_reconcile_records_sale(self):
        mem = {"listings": {"77": {"asset": 4, "ref": "LAT-03", "price": 9, "floor": 5, "loss": 1.25, "tick": 1}}}
        b = FakeB([])
        ctx = make_ctx(b, [card(3, "LAT-03")], memory=mem)
        Strategy().tick(ctx)
        sold = [t for t in mem["trades"] if t["kind"] == "sold"]
        self.assertEqual(sold[0]["gain"], 7.75)
        # The last LAT-03 is a first copy in a 0.5 set: listable, but only above 1.25x its value (5).
        lists = [c[2]["cash"] for c in b.calls if c[0] == "list"]
        self.assertEqual(lists, [10])
        self.assertEqual(mem["listings"]["1001"]["floor"], 8)


if __name__ == "__main__":
    unittest.main()
