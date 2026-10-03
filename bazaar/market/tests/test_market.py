"""MarketDomain: only value-gaining trades at private values, fair play, never our own venue."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bazaar.dealers.evaluate import make_catalog, make_ctx
from bazaar.market.domain import MARKET_TOOL, MarketDomain, fee_for, min_gain
from bazaar.market.rivals import RivalModel

AFF = {"LAV": 1.6, "MAL": 1.3, "RET": 1.1, "SAL": 0.9, "CHA": 0.7, "LAT": 0.5}


def card(aid, ref, rarity, value):
    return {"id": aid, "kind": "card", "ref": ref, "rarity": rarity, "set": ref[:3], "your_value": value}


def ask_offer(oid, ref, rarity, cash, maker="m1a2b3c4d", venue="rastro", aid=None):
    return {"id": oid, "maker": maker, "to": None, "venue": venue, "thread": None, "status": "open",
            "give": {"cash": 0, "assets": [{"id": aid or oid + 5000, "kind": "card", "ref": ref, "rarity": rarity}], "types": []},
            "want": {"cash": cash, "assets": [], "types": []}, "expires_tick": 999}


def bid_offer(oid, ref, cash, maker="m9e8d7c6b"):
    return {"id": oid, "maker": maker, "to": None, "venue": "rastro", "thread": None, "status": "open",
            "give": {"cash": cash, "assets": [], "types": []}, "want": {"cash": 0, "cards": [ref], "assets": [], "types": []},
            "expires_tick": 999}


def sit(book=(), assets=(), feed=(), venues=(), my_offers=(), cash=300, venue=None):
    return SimpleNamespace(tick=10, me={"id": "t10", "cash": cash, "affinity": AFF, "assets": list(assets), "venue": venue},
                           rastro_book=list(book), venues=list(venues), my_offers=list(my_offers), threads=[],
                           feed_new=list(feed), limits={})


def dom(llm=None) -> MarketDomain:
    return MarketDomain(rivals=RivalModel(Path(tempfile.mkdtemp()) / "r.json", seed=False), catalog=make_catalog(),
                        llm=llm, use_llm=llm is not None)


class Accepts(unittest.TestCase):
    def test_takes_value_positive_buy_with_fee(self):
        d = dom()
        acts = d.fallback(sit(book=[ask_offer(1, "LAV-09", "rare", 80)]), make_ctx(10))
        acc = [a for a in acts if a.kind == "accept_offer"]
        self.assertEqual(len(acc), 1)
        fee = fee_for({"id": "rastro"}, 80, 1)
        self.assertEqual(fee, 5)
        self.assertAlmostEqual(acc[0].expected["value_gain"], 112 - 80 - fee)
        self.assertEqual(acc[0].params["expect"]["want"]["cash"], 80)

    def test_skips_small_gain(self):
        # LAT rare worth 35 to us: 30 + fee 3 leaves 2 P < max(3, 25 %)
        acts = dom().fallback(sit(book=[ask_offer(1, "LAT-09", "rare", 30)]), make_ctx(10))
        self.assertFalse([a for a in acts if a.kind == "accept_offer"])
        self.assertEqual(min_gain(10), 3)
        self.assertEqual(min_gain(40), 10)

    def test_sells_spare_into_a_bid(self):
        assets = [card(1, "SAL-07", "uncommon", 5.6), card(2, "SAL-07", "uncommon", 5.6)]
        acts = dom().fallback(sit(book=[bid_offer(7, "SAL-07", 20)], assets=assets), make_ctx(10))
        acc = [a for a in acts if a.kind == "accept_offer"]
        self.assertEqual(len(acc), 1)
        self.assertEqual(len(acc[0].params["assets"]), 1)
        self.assertGreater(acc[0].expected["value_gain"], 3)

    def test_never_gives_last_scarce_copy(self):
        assets = [card(1, "LAV-07", "uncommon", 40)]
        acts = dom().fallback(sit(book=[bid_offer(7, "LAV-07", 90)], assets=assets), make_ctx(10))
        self.assertFalse([a for a in acts if a.kind == "accept_offer"])

    def test_never_own_offer_or_own_venue(self):
        own = ask_offer(1, "LAV-09", "rare", 50, maker="t10")
        venue = {"id": "v09", "owner": "t10", "offers": [ask_offer(2, "LAV-10", "rare", 50, venue="v09")]}
        acts = dom().fallback(sit(book=[own], venues=[venue], my_offers=[own], venue="v09"), make_ctx(10))
        self.assertFalse([a for a in acts if a.kind == "accept_offer"])

    def test_other_team_venue_uses_its_fee(self):
        venue = {"id": "v03", "owner": "t13", "fee_bps": 100, "fee_per_card": 0,
                 "offers": [ask_offer(2, "LAV-10", "rare", 80, venue="v03")]}
        acts = dom().fallback(sit(venues=[venue]), make_ctx(10))
        acc = [a for a in acts if a.kind == "accept_offer"]
        self.assertEqual(len(acc), 1)
        self.assertAlmostEqual(acc[0].expected["value_gain"], 112 - 80 - 1)

    def test_fair_play_cap(self):
        d = dom()
        feed = [{"type": "offer.listed", "actor": "t07", "payload": {"offer": ask_offer(1, "LAV-09", "rare", 80)}}]
        for _ in range(4):
            d.rivals.record_deal("t07")
        acts = d.fallback(sit(book=[ask_offer(1, "LAV-09", "rare", 80)], feed=feed), make_ctx(10))
        self.assertFalse([a for a in acts if a.kind == "accept_offer"])

    def test_cautious_breaker_blocks_spending(self):
        ctx = make_ctx(10)
        ctx.cautious = True
        acts = dom().fallback(sit(book=[ask_offer(1, "LAV-09", "rare", 80)]), ctx)
        self.assertFalse([a for a in acts if a.kind == "accept_offer"])


class Posts(unittest.TestCase):
    def test_posts_low_value_cards_above_min_gain(self):
        assets = [card(1, "LAT-09", "rare", 35), card(2, "LAV-01", "common", 16), card(3, "MAL-06", "uncommon", 32.5)]
        d = dom()
        acts = d.fallback(sit(assets=assets), make_ctx(10))
        posts = [a for a in acts if a.kind == "post_offer"]
        self.assertEqual({tuple(a.params["give"].get("assets") or []) for a in posts if a.params["give"].get("assets")},
                         {(1,)})                                  # only the low-affinity card leaves (sell or swap)
        _, cands, _ = d._prepare(sit(assets=assets), make_ctx(10))
        self.assertEqual([c.asset["id"] for c in cands], [1])
        self.assertGreaterEqual(cands[0].ask, 35 + min_gain(35))

    def test_targets_team_that_bids_on_the_set(self):
        d = dom()
        feed = [{"type": "offer.listed", "actor": "t18",
                 "payload": {"offer": bid_offer(50 + i, "LAT-10", 62)}} for i in range(3)]
        assets = [card(1, "LAT-09", "rare", 35)]
        acts = d.fallback(sit(assets=assets, feed=feed), make_ctx(10))
        posts = [a for a in acts if a.kind == "post_offer" and a.params["give"].get("assets")]
        self.assertEqual(posts[0].params.get("to"), "t18")        # the swap of our LAT card is aimed at t18
        _, cands, _ = d._prepare(sit(assets=assets), make_ctx(10))
        self.assertEqual(cands[0].target, "t18")
        self.assertGreaterEqual(cands[0].ask, 44)

    def test_llm_choices_are_clamped(self):
        class LLM:
            def ask(self, **kw):
                self.kw = kw
                return SimpleNamespace(cost_usd=0, tool_calls=[{"name": "market_moves", "input": {
                    "accept": "a99", "accept_reason": "", "note": "",
                    "post": [{"candidate": "p1", "price": 10_000, "to": "t99", "reason": ""}]}}])
        llm = LLM()
        acts = dom(llm).decide(sit(assets=[card(1, "LAT-09", "rare", 35)]), make_ctx(10))
        self.assertFalse([a for a in acts if a.kind == "accept_offer"])
        post = [a for a in acts if a.kind == "post_offer"][0]
        self.assertLessEqual(post.params["want"]["cash"], int(70 * 1.6))
        self.assertNotIn("to", post.params)
        self.assertTrue(MARKET_TOOL["strict"])


class Rivals(unittest.TestCase):
    def test_bids_reveal_affinity_and_asks_lower_it(self):
        r = RivalModel(Path(tempfile.mkdtemp()) / "r.json", seed=False)
        feed = [{"type": "offer.listed", "actor": "t08", "payload": {"offer": bid_offer(1, "SAL-10", 61)}},
                {"type": "offer.listed", "actor": "t08", "payload": {"offer": bid_offer(2, "SAL-09", 60)}},
                {"type": "offer.listed", "actor": "t05", "payload": {"offer": ask_offer(3, "SAL-01", "common", 2)}}]
        r.ingest_feed(feed, "t10")
        self.assertEqual([t for t, _ in r.fans("SAL")], ["t08"])
        self.assertEqual(r.team_of({"id": 2, "maker": "m123456"}), "t08")
        self.assertGreater(r.interest("t08", "SAL"), r.interest("t05", "SAL"))

    def test_friday_seed(self):
        r = RivalModel(Path(tempfile.mkdtemp()) / "r.json")
        self.assertIn("t18", [t for t, _ in r.fans("LAT")])
        self.assertIn("t08", [t for t, _ in r.fans("SAL")])


if __name__ == "__main__":
    unittest.main()
