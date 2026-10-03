"""The code poster respects the brain's per-card minimum asks and the per-(card, team) repost cooldown
(outbox request code-a40f9cbc)."""
import unittest

from bazaar.brain.strategy import sanitize
from bazaar.market.domain import REPOST_COOLDOWN_TICKS, MarketDomain, PostCand, capped_ask


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


if __name__ == "__main__":
    unittest.main()
