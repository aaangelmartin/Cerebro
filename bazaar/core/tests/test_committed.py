"""Cash promised in open bids is shared between the market and the dealers: together they never promise more
than cash - reserve - venue bond, and a filled market bid counts against the hourly spend cap."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bazaar.core.context import Budget, committed_cash, dealer_committed, market_committed, record_spend
from bazaar.dealers.evaluate import make_ctx
import bazaar.dealers.tests.test_domain as dt      # module import: its TestCases are not collected twice
from bazaar.dealers.tests.test_domain import buy_thread, domain
from bazaar.market.tests.test_market import dom as market_dom, sit as market_sit


def own_bid(oid, cash, maker="t10", status="open", thread=None, to=None):
    return {"id": oid, "maker": maker, "to": to, "venue": "rastro", "thread": thread, "status": status,
            "give": {"cash": cash, "assets": [], "types": []}, "want": {"cards": ["LAV-09"]}, "expires_tick": 999}


class Helper(unittest.TestCase):
    def test_sums_our_open_market_bids_and_dealer_buy_bids(self):
        s = market_sit(my_offers=[own_bid(1, 30), own_bid(2, 20, status="accepted"),
                                  own_bid(3, 50, maker="t07", to="t10"),            # addressed to us: theirs
                                  own_bid(4, 40, thread=9)])                        # inside a thread: not market
        s.threads = [buy_thread(10, ours=((3, 25),)), buy_thread(11, theirs=((2, 50),)),   # no bid of ours yet
                     buy_thread(12, ours=((3, 18),), status="closed")]
        self.assertEqual(market_committed(s), 30)
        self.assertEqual(dealer_committed(s), 25)
        self.assertEqual(committed_cash(s), 55)

    def test_record_spend_reaches_the_persisted_hour_window(self):
        b = Budget(Path(tempfile.mkdtemp()) / "budget.json")
        tick = b.for_tick(5, now=1000.0)
        ctx = make_ctx(5)
        ctx.budget = tick
        left = tick["spend_hour_left"]
        record_spend(ctx, 60, now=1001.0)
        self.assertEqual(ctx.budget["spend_hour"], 60)
        self.assertEqual(ctx.budget["spend_hour_left"], left - 60)
        self.assertEqual(b.for_tick(6, now=1002.0)["spend_hour"], 60)        # survives into the next tick


class CrossDomain(unittest.TestCase):
    def test_market_bid_room_nets_dealer_bids(self):
        ctx = make_ctx(10)
        ctx.control = {"venue_reserve": False}
        _, _, free = market_dom()._prepare(market_sit(cash=300), ctx)
        s = market_sit(cash=300)
        s.threads = [buy_thread(10, ours=((3, 200),))]
        _, _, held = market_dom()._prepare(s, ctx)
        # cash 300 - reserve 40 = 260, hour left 250: the dealer's 200 leaves 50 for market bids
        self.assertEqual(held["bid_cash_room"], max(0, min(free["bid_cash_room"], 250 - 200)))
        self.assertLess(held["bid_cash_room"], free["bid_cash_room"])

    def test_dealer_limit_nets_market_bids(self):
        f = dt.AuditFixes()
        c = f.ctx(5)
        c.control = {"venue_reserve": False}
        a = buy_thread(10, card="LAV-07", theirs=((2, 27), (4, 26)), ours=((3, 20),))
        free = domain()._prepare(f.sit(cash=120, threads=[a]), c)
        s = f.sit(cash=120, threads=[a])
        s.my_offers = [own_bid(1, 60)]
        held = domain()._prepare(s, c)
        lim_free = {i.view.id: i.limit for i in free.infos}[10]
        lim_held = {i.view.id: i.limit for i in held.infos}[10]
        self.assertLessEqual(lim_held, 120 - 40 - 60)              # cash - reserve - market bid
        self.assertLess(lim_held, lim_free)

    def test_filled_market_bid_counts_as_hour_spend(self):
        d = market_dom()
        d._posted["77"] = {"action": "a1", "lessons": [], "value_gain": 5.0, "spend": 45, "expires_tick": 999}
        ctx = make_ctx(10)
        before = ctx.budget["spend_hour_left"]
        d._close_posted(market_sit(my_offers=[own_bid(77, 45, status="accepted")]), ctx)
        self.assertEqual(ctx.budget["spend_hour_left"], before - 45)
        self.assertNotIn("77", d._posted)


if __name__ == "__main__":
    unittest.main()


# These tests check the logic with the original numbers; the live policy values (round-4 strategy) differ.
_PINS = []


def setUpModule():
    from unittest import mock as _m
    from bazaar import config as _c
    from bazaar.market import protocol as _p
    _PINS.extend([_m.patch.object(_c, "CASH_RESERVE", 40), _m.patch.object(_p, "BID_COMMIT_MAX", 150),
                  _m.patch.object(_p, "MAX_OWN_BIDS", 6)])
    for p in _PINS:
        p.start()


def tearDownModule():
    for p in _PINS:
        p.stop()
    _PINS.clear()
