"""The board protocol: filling bids and swaps (book and addressed), posting our own, limits and protections."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bazaar.core import rails
from bazaar.dealers.evaluate import make_catalog, make_ctx
from bazaar.dealers.values import Values
from bazaar.market import protocol as proto
from bazaar.market.domain import MarketDomain, broker_pitch
from bazaar.market.rivals import RivalModel

AFF = {"LAV": 1.6, "MAL": 1.3, "RET": 1.1, "SAL": 0.9, "CHA": 0.7, "LAT": 0.5}
V03 = {"venue": "v03", "owner": "t13", "status": "open", "fee_bps": 100, "fee_per_card": 0,
       "rules": {"mechanism": "board"}, "trades": 0}
V02 = {"venue": "v02", "owner": "t12", "status": "open", "fee_bps": 0, "fee_per_card": 0,
       "rules": {"mechanism": "board"}, "trades": 0}
V04 = {"venue": "v04", "owner": "t02", "status": "open", "fee_bps": 0, "fee_per_card": 0,
       "rules": {"mechanism": "auto"}, "trades": 0}
OURS = {"venue": "v09", "owner": "t10", "status": "open", "fee_bps": 0, "fee_per_card": 0,
        "rules": {"mechanism": "board"}}
RASTRO = {"venue": "rastro", "owner": "world", "status": "open", "fee_bps": 500, "fee_per_card": 1, "house": True,
          "trades": 45}


def card(aid, ref, value, rarity=None):
    n = int(ref[4:])
    rarity = rarity or ("common" if n <= 5 else "uncommon" if n <= 8 else "rare")
    return {"id": aid, "kind": "card", "ref": ref, "rarity": rarity, "set": ref[:3], "your_value": value}


def offer(oid, give, want, maker="m1a2b3c4d", venue="rastro", to=None, thread=None):
    return {"id": oid, "maker": maker, "to": to, "venue": venue, "thread": thread, "status": "open",
            "give": {"cash": 0, "assets": [], "types": [], **give}, "want": {"cash": 0, "assets": [], "types": [], **want},
            "expires_tick": 999}


def theirs(aid, ref):
    return {"id": aid, "kind": "card", "ref": ref, "rarity": "common", "set": ref[:3]}


def sit(assets=(), book=(), venues=(), my_offers=(), cash=300, venue="v09", tick=10, slow_tick=None):
    s = SimpleNamespace(tick=tick, me={"id": "t10", "cash": cash, "affinity": AFF, "assets": list(assets), "venue": venue},
                        rastro_book=list(book), venues=list(venues), my_offers=list(my_offers), threads=[],
                        feed_new=[], limits={})
    if slow_tick is not None:
        s.slow_tick = slow_tick
    return s


def dom(gw=None) -> MarketDomain:
    return MarketDomain(rivals=RivalModel(Path(tempfile.mkdtemp()) / "r.json", seed=False), catalog=make_catalog(),
                        gw=gw, use_llm=False)


def kinds(acts, kind):
    return [a for a in acts if a.kind == kind]


def sells(acts):
    return [a for a in kinds(acts, "post_offer") if "cash" in a.params["want"]]


def bids(acts):
    return [a for a in kinds(acts, "post_offer") if a.params["give"].get("cash")]


def swaps(acts):
    return [a for a in kinds(acts, "post_offer") if a.params["give"].get("assets") and "cards" in a.params["want"]]


class FakeGW:
    def __init__(self, books: dict):
        self.books, self.calls = books, []

    def get(self, path, **kw):
        self.calls.append(path)
        vid = path.split("/")[3]
        return {"offers": self.books.get(vid, [])}


class FillBids(unittest.TestCase):
    def test_fills_api_shaped_bid_on_team_venue_with_a_duplicate(self):
        assets = [card(1, "SAL-07", 5.6), card(2, "SAL-07", 5.6)]
        bid = offer(30, {"cash": 20}, {"types": ["card:SAL-07"]}, venue="v02")
        gw = FakeGW({"v02": [bid]})
        acts = dom(gw).fallback(sit(assets=assets, venues=[V02, RASTRO]), make_ctx(10))
        acc = kinds(acts, "accept_offer")
        self.assertEqual(len(acc), 1)
        self.assertEqual(acc[0].params["assets"], [1])
        self.assertAlmostEqual(acc[0].expected["value_gain"], 20 - 5.6 - 7)        # team venue priced at the max fee
        self.assertEqual(acc[0].expected["kind"], "bid")
        self.assertEqual(gw.calls, ["/api/venues/v02/offers"])

    def test_low_bid_declined(self):
        assets = [card(1, "SAL-07", 5.6), card(2, "SAL-07", 5.6)]
        venue = dict(V02, offers=[offer(30, {"cash": 8}, {"types": ["card:SAL-07"]}, venue="v02")])
        acts = dom().fallback(sit(assets=assets, venues=[venue]), make_ctx(10))
        self.assertFalse(kinds(acts, "accept_offer"))                               # 2.4 P < 3 P


class FillSwaps(unittest.TestCase):
    def test_swap_our_low_affinity_duplicate_for_a_card_we_lack(self):
        assets = [card(1, "LAT-02", 1.25), card(2, "LAT-02", 1.25)]
        venue = dict(V03, offers=[offer(40, {"assets": [theirs(900, "LAV-03")]}, {"types": ["card:LAT-02"]}, venue="v03")])
        s = sit(assets=assets, venues=[venue])
        acts = dom().fallback(s, make_ctx(10))
        acc = kinds(acts, "accept_offer")
        self.assertEqual(len(acc), 1)
        self.assertIn(acc[0].params["assets"][0], (1, 2))
        self.assertAlmostEqual(acc[0].expected["value_gain"], 16 - 1.25 - 10)       # max fee: 5 P x 2 cards
        self.assertEqual(acc[0].expected["kind"], "swap")
        s.values = {"LAV-03": 16.0}
        self.assertTrue(rails.rail_cards(acc[0], s, make_ctx(10)).ok)
        self.assertTrue(rails.rail_value(acc[0], s, make_ctx(10)).ok)

    def test_swap_that_does_not_gain_enough_is_declined(self):
        assets = [card(1, "MAL-04", 3.25), card(2, "MAL-04", 3.25)]
        venue = dict(V03, offers=[offer(41, {"assets": [theirs(901, "LAT-03")]}, {"types": ["card:MAL-04"]}, venue="v03")])
        acts = dom().fallback(sit(assets=assets, venues=[venue]), make_ctx(10))
        self.assertFalse(kinds(acts, "accept_offer"))                               # 5 - 3.25 < 3

    def test_rastro_per_card_fee_counts(self):
        assets = [card(1, "LAT-02", 1.25), card(2, "LAT-02", 1.25)]
        book = [offer(42, {"assets": [theirs(902, "LAV-03")]}, {"types": ["card:LAT-02"]})]
        acc = kinds(dom().fallback(sit(assets=assets, book=book), make_ctx(10)), "accept_offer")
        self.assertAlmostEqual(acc[0].expected["value_gain"], 16 - 1.25 - 2)        # 1 P per card, both cards

    def test_never_gives_last_scarce_copy_in_a_swap(self):
        assets = [card(1, "LAV-07", 40)]
        venue = dict(V03, offers=[offer(43, {"assets": [theirs(903, "MAL-09")]}, {"types": ["card:LAV-07"]}, venue="v03")])
        self.assertFalse(kinds(dom().fallback(sit(assets=assets, venues=[venue]), make_ctx(10)), "accept_offer"))

    def test_page_completion_bonus_counts(self):
        # we hold every LAV page card but LAV-10; a swap for it completes the page
        assets = [card(i, f"LAV-{i:02d}", 16 if i <= 5 else 40 if i <= 8 else 112) for i in range(1, 10)]
        assets += [card(20, "LAT-09", 35)]
        d = dom()
        values = Values({"affinity": AFF, "assets": assets}, make_catalog())
        bonus = proto.page_bonus(values, "LAV")
        self.assertAlmostEqual(bonus, 0.25 * 1.6 * (5 * 10 + 3 * 25 + 2 * 70))
        venue = dict(V03, offers=[offer(44, {"assets": [theirs(904, "LAV-10")]}, {"types": ["card:LAT-09"]}, venue="v03")])
        acc = kinds(d.fallback(sit(assets=assets, venues=[venue]), make_ctx(10)), "accept_offer")
        self.assertAlmostEqual(acc[0].expected["value_gain"], 112 - 35 + bonus - 10)   # max fee: 5 P x 2 cards


class Addressed(unittest.TestCase):
    def test_accepts_offer_addressed_to_us_and_ignores_others(self):
        assets = [card(1, "SAL-07", 5.6), card(2, "SAL-07", 5.6)]
        mine = [offer(900, {"cash": 20}, {"types": ["card:SAL-07"]}, maker="t07", venue="v03", to="t10"),
                offer(901, {"cash": 40}, {"assets": [card(1, "SAL-07", 5.6)]}, maker="chato", venue=None, to="t10",
                      thread=304)]
        book = [offer(902, {"cash": 60}, {"types": ["card:SAL-07"]}, to="t05")]
        acts = dom().fallback(sit(assets=assets, book=book, venues=[V03], my_offers=mine), make_ctx(10))
        acc = kinds(acts, "accept_offer")
        self.assertEqual([a.params["offer"] for a in acc], [900])
        self.assertTrue(acc[0].expected["addressed"])
        self.assertAlmostEqual(acc[0].expected["value_gain"], 20 - 5.6 - 7)          # team venue priced at the max: 10 % + 5 P

    def test_addressed_offer_for_a_specific_copy_of_ours(self):
        assets = [card(1, "SAL-07", 5.6), card(2, "SAL-07", 5.6)]
        mine = [offer(905, {"cash": 20}, {"assets": [card(2, "SAL-07", 5.6)]}, maker="t07", venue="v02", to="t10")]
        acc = kinds(dom().fallback(sit(assets=assets, venues=[V02], my_offers=mine), make_ctx(10)), "accept_offer")
        self.assertEqual(acc[0].params["assets"], [2])

    def test_never_on_our_own_venue(self):
        assets = [card(1, "SAL-07", 5.6), card(2, "SAL-07", 5.6)]
        mine = [offer(906, {"cash": 30}, {"types": ["card:SAL-07"]}, maker="t07", venue="v09", to="t10")]
        acts = dom().fallback(sit(assets=assets, venues=[OURS], my_offers=mine), make_ctx(10))
        self.assertFalse(kinds(acts, "accept_offer"))


class Posting(unittest.TestCase):
    def test_bids_for_missing_core_page_cards_below_value(self):
        acts = dom().fallback(sit(assets=[], venues=[V02, V03, RASTRO], cash=400), make_ctx(10))
        b = bids(acts)
        self.assertTrue(b)
        for a in b:
            ref = a.params["want"]["cards"][0]
            self.assertIn(ref[:3], proto.CORE_SETS)
            self.assertEqual(a.params["venue"], "rastro")                           # never feed a rival's venue
            self.assertEqual(a.params["expires_in_ticks"], proto.BID_EXPIRES)
            v = a.expected["value_get"]
            price = a.params["give"]["cash"]
            self.assertGreaterEqual(v - price, proto.min_gain(price))

    def test_no_bids_while_the_venue_bond_is_reserved_or_cautious(self):
        self.assertFalse(bids(dom().fallback(sit(venue=None, cash=300, venues=[V02]), make_ctx(10))))
        ctx = make_ctx(10)
        ctx.cautious = True
        self.assertFalse(bids(dom().fallback(sit(cash=400, venues=[V02]), ctx)))

    def test_swaps_give_duplicates_first_and_target_fans(self):
        d = dom()
        for i in range(3):
            d.rivals._add("bids", "t08", "MAL", 0.9)
        assets = [card(1, "MAL-02", 3.25), card(2, "MAL-02", 3.25), card(3, "LAT-01", 5)]
        acts = d.fallback(sit(assets=assets, venues=[V03, V04, RASTRO], cash=60), make_ctx(10))
        sw = swaps(acts)
        self.assertTrue(sw)
        self.assertIn(sw[0].params["give"]["assets"][0], (1, 2))                      # a duplicate first
        self.assertEqual(sw[0].params.get("to"), "t08")
        self.assertEqual(sw[0].params["venue"], "rastro")                            # never feed a rival's venue
        given = [a.params["give"]["assets"][0] for a in kinds(acts, "post_offer") if a.params["give"].get("assets")]
        self.assertLessEqual(len([x for x in given if x in (1, 2)]), 1)              # never both MAL-02 copies

    def test_never_offers_last_scarce_copy_across_ticks(self):
        assets = [card(1, "MAL-02", 3.25), card(2, "MAL-02", 3.25)]
        listed = offer(500, {"assets": [card(1, "MAL-02", 3.25)]}, {"cards": ["LAV-01"]}, maker="t10", venue="v03")
        acts = dom().fallback(sit(assets=assets, venues=[V03], my_offers=[listed], cash=60), make_ctx(10))
        given = [a.params["give"]["assets"] for a in kinds(acts, "post_offer") if a.params["give"].get("assets")]
        self.assertNotIn([2], given)

    def test_posting_limits(self):
        assets = [card(1, "LAT-02", 1.25), card(2, "LAT-02", 1.25), card(3, "LAT-03", 5), card(4, "CHA-01", 7)]
        ctx = make_ctx(10)
        ctx.budget["offers_left"] = 1
        self.assertEqual(len(kinds(dom().fallback(sit(assets=assets, venues=[V03], cash=400), ctx), "post_offer")), 1)
        acts = dom().fallback(sit(assets=assets, venues=[V03], cash=400), make_ctx(10))
        self.assertLessEqual(len(kinds(acts, "post_offer")), 3)                      # POSTS_PER_TICK
        full = [offer(600 + i, {"cash": 5}, {"cards": [f"RET-0{i % 5 + 1}"]}, maker="t10", venue="v03")
                for i in range(proto.MAX_OWN_OPEN)]
        acts = dom().fallback(sit(assets=assets, venues=[V03], my_offers=full, cash=400), make_ctx(10))
        self.assertFalse(kinds(acts, "post_offer"))
        six = [offer(700 + i, {"cash": 5}, {"cards": [f"MAL-0{i + 1}"]}, maker="t10", venue="v03") for i in range(6)]
        acts = dom().fallback(sit(venues=[V03], my_offers=six, cash=400), make_ctx(10))
        self.assertFalse(bids(acts))                                                 # MAX_OWN_BIDS reached

    def test_bid_cash_room_caps_commitment(self):
        acts = dom().fallback(sit(venues=[V02], cash=80), make_ctx(10))               # 80 - 40 reserve = 40
        self.assertLessEqual(sum(a.params["give"]["cash"] for a in bids(acts)), 40)

    def test_stale_bid_cancelled_once_we_hold_the_card(self):
        mine = [offer(800, {"cash": 10}, {"types": ["card:LAV-01"]}, maker="t10", venue="v02")]
        acts = dom().fallback(sit(assets=[card(1, "LAV-01", 16)], venues=[V02], my_offers=mine), make_ctx(10))
        self.assertEqual([a.params["offer"] for a in kinds(acts, "cancel_offer")], [800])

    def test_llm_bid_price_is_clamped(self):
        class LLM:
            def ask(self, **kw):
                return SimpleNamespace(cost_usd=0, tool_calls=[{"name": "market_moves", "input": {
                    "accept": None, "accept_reason": "", "note": "", "post": [], "swaps": [],
                    "bids": [{"candidate": "b1", "price": 500, "reason": "x"}, {"candidate": "zz", "price": 1, "reason": ""}]}}])
        d = MarketDomain(rivals=RivalModel(Path(tempfile.mkdtemp()) / "r.json", seed=False), catalog=make_catalog(),
                         llm=LLM(), use_llm=True)
        acts = d.decide(sit(venues=[V02], cash=400), make_ctx(10))
        b = bids(acts)
        self.assertEqual(len(b), 1)
        self.assertLessEqual(b[0].params["give"]["cash"], proto.MAX_BID_P)
        self.assertGreaterEqual(b[0].expected["value_gain"], proto.min_gain(b[0].params["give"]["cash"]))
        self.assertEqual(b[0].source, "opus")


class Venues(unittest.TestCase):
    def test_reads_one_venue_book_per_tick_stalest_first_never_ours(self):
        gw = FakeGW({})
        d = dom(gw)
        venues = [V02, V03, OURS, RASTRO]
        for t in range(3):
            d.fallback(sit(venues=venues, tick=10 + t, slow_tick=10), make_ctx(10 + t))
        # perception read El Rastro at tick 10: only the two team venues are due, one per tick
        self.assertEqual(gw.calls, ["/api/venues/v02/offers", "/api/venues/v03/offers"])
        gw2 = FakeGW({})
        d2 = dom(gw2)
        d2.fallback(sit(venues=venues, tick=15, slow_tick=10), make_ctx(15))         # El Rastro read is 5 ticks old
        self.assertEqual(len(gw2.calls), 1)
        self.assertNotIn("/api/venues/v09/offers", gw.calls + gw2.calls)

    def test_choose_venue_and_fees(self):
        self.assertEqual(proto.choose_venue([RASTRO, V03, V04], 0, 2), "rastro")   # team decision: El Rastro only
        self.assertEqual(proto.choose_venue([RASTRO], 10, 1), "rastro")
        pending = dict(V03, pending_fee={"fee_bps": 1000, "fee_per_card": 5, "effective_tick": 200})
        self.assertEqual(proto.taker_fee(pending, 0, 2), 10)                          # worse of now and announced

    def test_broker_pitch(self):
        self.assertIsNone(broker_pitch(None))
        text = broker_pitch(OURS)
        self.assertIn("v09", text)
        self.assertIn("no fee", text)
        self.assertLessEqual(len(text), 1200)


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
