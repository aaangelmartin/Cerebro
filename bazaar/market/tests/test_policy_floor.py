"""The code poster respects the brain's per-card minimum asks and the per-(card, team) repost cooldown
(outbox request code-a40f9cbc)."""
import unittest

from bazaar.brain.strategy import sanitize
from bazaar.market.domain import REPOST_COOLDOWN_TICKS, AcceptCand, MarketDomain, PostCand, below_min_ask, capped_ask


def cand(ask=24, max_ask=30, fans=("t03",), target="t03", ref="SAL-08", aid=540):
    return PostCand(id="p1", asset={"id": aid, "ref": ref}, value=22.5, min_ask=24, max_ask=max_ask, ask=ask,
                    target=target, fans=list(fans), venue="v10")


def state(tick, min_asks=None):
    return {"tick": tick, "posts_left_this_tick": 5, "_avail": {}, "_min_asks": min_asks or {}}


class PolicyFloorTest(unittest.TestCase):
    def setUp(self):
        self.d = MarketDomain(use_llm=False)
        self.d._targeted = {}                    # no file state from other tests

    def emit(self, c, st):
        return self.d._emit([("sell", c, None)], st, "fallback")

    def test_price_is_raised_to_the_brain_minimum(self):
        out = self.emit(cand(), state(356, {"SAL-08": 27}))
        self.assertEqual(out[0].params["want"]["cash"], 27)

    def test_not_listed_when_the_minimum_is_above_what_the_market_pays(self):
        self.assertEqual(self.emit(cand(max_ask=25), state(356, {"SAL-08": 27})), [])

    def test_same_card_same_team_waits_for_the_cooldown(self):
        self.assertEqual(self.emit(cand(), state(356))[0].params.get("to"), "t03")
        soon = self.emit(cand(), state(365))                                      # 9 ticks later: not to t03 again
        self.assertIsNone(soon[0].params.get("to"))                               # listed publicly instead
        again = self.emit(cand(), state(356 + REPOST_COOLDOWN_TICKS))
        self.assertEqual(again[0].params.get("to"), "t03")

    def test_another_interested_team_is_tried_instead(self):
        self.emit(cand(fans=("t03", "t15")), state(356))
        out = self.emit(cand(fans=("t03", "t15")), state(360))
        self.assertEqual(out[0].params.get("to"), "t15")

    def test_plan_min_asks_are_sanitised(self):
        p = sanitize({"min_asks": {"sal-08": 27, "bad": 5}})
        self.assertEqual(p["min_asks"], {"SAL-08": 27})
        self.assertNotIn("min_asks", sanitize({}))


class CappedAskTest(unittest.TestCase):
    """The code poster does not ask three times our value (outbox request code-7285742c)."""

    def test_spare_is_capped_near_our_value_when_the_market_is_cheap(self):
        # LAV-05 spare: worth 4 to us, a fan's bid level pushed the ask to 13, others sell it at 6
        self.assertEqual(capped_ask(13, 4.0, 6, 6, 10), 6)

    def test_market_ask_above_value_plus_two_is_matched(self):
        self.assertEqual(capped_ask(13, 4.0, 6, 9, 10), 9)

    def test_book_stands_in_when_no_ask_is_live(self):
        self.assertEqual(capped_ask(13, 4.0, 6, None, 10), 10)

    def test_never_below_our_floor(self):
        self.assertEqual(capped_ask(30, 22.5, 25, 20, 25), 25)

    def test_an_ask_already_under_the_cap_is_kept(self):
        self.assertEqual(capped_ask(24, 22.5, 24, 30, 25), 24)



def bid(cash_in, out_refs=("CHA-11",), fee=0, value_in=0.0, cash_out=0):
    return AcceptCand(id="a1", offer={"id": 1}, venue="v17", team="t05", in_refs=[], in_assets=[], out_ids=[1],
                      out_refs=list(out_refs), cash_in=cash_in, cash_out=cash_out, fee=fee, value_in=value_in,
                      loss=126.0, gain=cash_in - 126.0, cost=126.0)


class AcceptFloorTest(unittest.TestCase):
    """A bid under control.min_asks is never accepted, however good it looks against our value (CHA-11 went at
    190 P to t05 on Sunday when the price to hold was 200)."""

    def test_bid_under_the_floor_is_left(self):
        self.assertTrue(below_min_ask(bid(190), {"CHA-11": 200}))

    def test_bid_at_the_floor_is_fine(self):
        self.assertFalse(below_min_ask(bid(200), {"CHA-11": 200}))

    def test_fee_counts_against_the_floor(self):
        self.assertTrue(below_min_ask(bid(200, fee=11), {"CHA-11": 200}))

    def test_no_floor_no_veto(self):
        self.assertFalse(below_min_ask(bid(130), {}))
        self.assertFalse(below_min_ask(bid(130), {"RET-11": 228}))

    def test_floor_key_case_and_bad_value(self):
        self.assertTrue(below_min_ask(bid(100, out_refs=("ret-11",)), {"RET-11": 228}))
        self.assertFalse(below_min_ask(bid(100), {"CHA-11": "x"}))

if __name__ == "__main__":
    unittest.main()
