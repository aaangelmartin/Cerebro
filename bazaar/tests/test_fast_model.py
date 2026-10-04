"""On Sunday's 15 s ticks a per-tick Opus call is cut off about half the time; market and team talk use Sonnet,
dealers use it only when Opus would not finish before the deadline. Long ticks keep the configured model."""
import unittest

from bazaar import config
from bazaar.core import fastmodel


class FastModelTest(unittest.TestCase):
    def test_long_ticks_keep_the_configured_model(self):
        self.assertIsNone(fastmodel.pick(None, 30.0, 1000.0, always_fast=True, now=999.0))
        self.assertEqual(fastmodel.pick(config.OPUS, 30.0, 1000.0, now=999.0), config.OPUS)
        self.assertIsNone(fastmodel.pick(None, None, None))

    def test_market_is_always_fast_on_short_ticks(self):
        self.assertEqual(fastmodel.pick(None, 15.0, 1000.0, always_fast=True, now=980.0), config.SONNET)
        self.assertEqual(fastmodel.pick(config.OPUS, 15.0, None, always_fast=True), config.SONNET)

    def test_dealers_keep_opus_only_when_it_has_time_to_finish(self):
        self.assertIsNone(fastmodel.pick(None, 15.0, 1000.0, now=1000.0 - 8.0))
        self.assertEqual(fastmodel.pick(None, 15.0, 1000.0, now=1000.0 - 7.4), config.SONNET)
        self.assertEqual(fastmodel.pick(None, 15.0, 1000.0, now=1001.0), config.SONNET)
        self.assertIsNone(fastmodel.pick(None, 15.0, None))

    def test_a_cheaper_model_already_chosen_is_kept(self):
        self.assertEqual(fastmodel.pick(config.HAIKU, 15.0, 1000.0, always_fast=True, now=999.0), config.HAIKU)

    def test_the_three_callers_ask_for_it(self):
        import inspect
        from bazaar.dealers import domain as dealers
        from bazaar.market import domain as market
        from bazaar.teamtalk import talk
        self.assertIn("fastmodel.pick(self.model", inspect.getsource(market))
        self.assertIn("always_fast=True", inspect.getsource(market))
        self.assertIn("fastmodel.pick(self.model", inspect.getsource(dealers))
        self.assertNotIn("always_fast=True", inspect.getsource(dealers))
        self.assertIn("fastmodel.pick(self.model", inspect.getsource(talk))


if __name__ == "__main__":
    unittest.main()
