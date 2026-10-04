import time
import unittest

from bazaar.brain import council
from bazaar.brain.tests.test_council import FakeLedger, FakeLLM, ok
from bazaar.core.context import TickContext
from bazaar.core.state import Situation
from bazaar.core.types import Action


def mal10(offer=8169):
    card = {"id": 829, "kind": "card", "ref": "MAL-10"}
    return Action("accept_offer", {
        "offer": offer,
        "expect": {"give": {"cash": 0, "assets": [card]}, "want": {"cash": 78}, "maker": "m1", "venue": "rastro"},
        "give": {"cash": 83, "assets": []}, "want": {"cash": 0, "assets": [card]}},
        "market", expected={"value_get": 91, "value_gain": 8.1, "spend": 83}, big=True)


def setup(llm, tick=560, control=None):
    led = FakeLedger()
    ctx = TickContext(tick=tick, day="sat", deadline=time.time() + 5, llm=llm, ledger=led,
                      control=control or {"goal_buys": {"MAL-10": 84}, "cash_reserve": 10, "max_spend_per_deal": 90})
    sit = Situation(tick=tick, day="sat", me={"id": "t10", "cash": 104, "assets": [
        {"kind": "card", "ref": f"MAL-{i:02d}"} for i in range(1, 9)]})
    return ctx, sit, led


class AcceptContextTest(unittest.TestCase):
    def setUp(self):
        council._CACHE.clear()
        council.LAST_WHY.clear()

    def test_brief_explains_fee_and_goal(self):
        ctx, sit, _ = setup(None)
        c = council._context_for(mal10(), sit, ctx.control)
        self.assertEqual(c["accept"]["maker_ask_cash"], 78)
        self.assertEqual(c["accept"]["we_pay_all_in"], 83)
        self.assertEqual(c["accept"]["taker_fee_included"], 5)
        self.assertEqual(c["goal"]["goal_cap_all_in"], 84)
        self.assertTrue(c["goal"]["inside_cap"])
        self.assertEqual((c["cash_reserve"], c["max_spend_per_deal"]), (10, 90))
        self.assertIn("8/10", c["goal"]["page_progress"])

    def test_judge_modify_on_accept_is_approved_as_is(self):
        llm = FakeLLM({r: ok() for r in council.ROLES}, judge=ok("modify", params={"price": 78}))
        ctx, sit, led = setup(llm)
        a = mal10()
        out = council.review(a, sit, ctx)
        self.assertIsNotNone(out)
        self.assertEqual(out.params, a.params)

    def test_same_offer_is_not_asked_again(self):
        llm = FakeLLM({r: ok() for r in council.ROLES}, judge=ok())
        ctx, sit, led = setup(llm)
        self.assertIsNotNone(council.review(mal10(), sit, ctx))
        n = len(llm.calls)
        ctx2, sit2, led2 = setup(llm, tick=561)
        self.assertIsNotNone(council.review(mal10(), sit2, ctx2))
        self.assertEqual(len(llm.calls), n)                       # served from the cache
        self.assertTrue(led2.rows[-1][1].get("cached"))

    def test_veto_is_cached_with_its_reason_then_retried(self):
        votes = {r: ok() for r in council.ROLES}
        votes["auditor"] = ok("reject", rail_risk=True, reason="cash after the buy 21 is below the reserve 30")
        llm = FakeLLM(votes, judge=ok())
        ctx, sit, _ = setup(llm)
        a = mal10()
        self.assertIsNone(council.review(a, sit, ctx))
        self.assertIn("reserve 30", council.LAST_WHY[a.id])
        n = len(llm.calls)
        ctx2, sit2, _ = setup(llm, tick=562)
        b = mal10()
        self.assertIsNone(council.review(b, sit2, ctx2))
        self.assertEqual(len(llm.calls), n)
        self.assertIn("reserve 30", council.LAST_WHY[b.id])
        ctx3, sit3, _ = setup(llm, tick=560 + council.CACHE_TICKS["veto"] + 1)
        council.review(mal10(), sit3, ctx3)
        self.assertGreater(len(llm.calls), n)                     # asked again once the veto expires


if __name__ == "__main__":
    unittest.main()
