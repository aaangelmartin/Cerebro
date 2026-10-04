import time
import unittest
from unittest import mock

from bazaar.brain import council
from bazaar.brain.tests.test_council import FakeLedger, FakeLLM, ok
from bazaar.core.context import TickContext
from bazaar.core.state import Situation
from bazaar.core.types import Action

ORDERS = [{"dealer": "abuela", "action": "buy", "ref": "SAL-07", "open": 16, "bound": 21, "max_messages": 4}]


def accept(price=21, value=22.5, ref="SAL-07", dealer="abuela", offer=16854):
    """The dealers domain's accept of a dealer's standing offer (the real t1121 case: SAL-07 at 21, value 22.5)."""
    return Action("accept_offer", {"offer": offer, "expect": {
        "give": {"cash": 0, "assets": [], "types": [f"card:{ref}"]},
        "want": {"cash": price, "assets": [], "types": []}, "maker": dealer, "thread": 1679}},
        "dealers", expected={"points": 1.5, "value_gain": round(value - price, 2), "capture": 1.0, "price": price,
                             "dealer": dealer, "level": 1, "value_get": value, "spend": price}, big=True)


def setup(llm, tick=1121, control=None):
    led = FakeLedger()
    ctx = TickContext(tick=tick, day="sat", deadline=time.time() + 5, llm=llm, ledger=led, control=control or {})
    sit = Situation(tick=tick, day="sat", me={"id": "t10", "cash": 44, "assets": []})
    return ctx, sit, led


def plan(orders=(), goals=None):
    return (mock.patch("bazaar.brain.strategy.dealer_orders", return_value=list(orders)),
            mock.patch("bazaar.brain.strategy.goal_buys", return_value=dict(goals or {})))


class OrderedDealerAccept(unittest.TestCase):
    def setUp(self):
        council._CACHE.clear()
        council.LAST_WHY.clear()
        self.veto = {r: ok() for r in council.ROLES}
        self.veto["auditor"] = ok("reject", rail_risk=True, reason="looks like a sale below value")

    def run_review(self, action, llm, orders=(), goals=None, control=None, tick=1121):
        ctx, sit, led = setup(llm, tick, control)
        a, b = plan(orders, goals)
        with a, b:
            return council.review(action, sit, ctx), led

    def test_accept_inside_a_dealer_order_needs_no_vote(self):
        llm = FakeLLM(self.veto, judge=ok("reject"))
        a = accept()
        out, led = self.run_review(a, llm, orders=ORDERS)
        self.assertIsNotNone(out)
        self.assertEqual(out.params, a.params)
        self.assertEqual(llm.calls, [])                              # no model call: same tick
        self.assertTrue(led.rows[-1][1].get("ordered"))
        self.assertIn("dealer order", led.rows[-1][1]["why"])

    def test_accept_at_the_plan_goal_price_needs_no_vote(self):
        llm = FakeLLM(self.veto, judge=ok("reject"))
        out, _ = self.run_review(accept(), llm, goals={"SAL-07": 21})
        self.assertIsNotNone(out)
        self.assertEqual(llm.calls, [])

    def test_control_goal_counts_too(self):
        llm = FakeLLM(self.veto, judge=ok("reject"))
        out, _ = self.run_review(accept(), llm, control={"goal_buys": {"SAL-07": 22}})
        self.assertIsNotNone(out)
        self.assertEqual(llm.calls, [])

    def test_an_earlier_cached_veto_does_not_hold_an_ordered_accept(self):
        llm = FakeLLM(self.veto, judge=ok())
        self.assertIsNone(self.run_review(accept(), llm)[0])          # no order yet: voted and vetoed
        n = len(llm.calls)
        out, _ = self.run_review(accept(), llm, orders=ORDERS, tick=1122)
        self.assertIsNotNone(out)
        self.assertEqual(len(llm.calls), n)

    def test_above_the_cap_still_goes_to_the_vote(self):
        llm = FakeLLM(self.veto, judge=ok())
        out, _ = self.run_review(accept(price=22), llm, orders=ORDERS)
        self.assertIsNone(out)                                        # voted as today (the auditor vetoes here)
        self.assertTrue(llm.calls)

    def test_no_order_and_no_goal_goes_to_the_vote(self):
        llm = FakeLLM({r: ok() for r in council.ROLES}, judge=ok())
        out, _ = self.run_review(accept(), llm)
        self.assertIsNotNone(out)
        self.assertTrue(llm.calls)

    def test_another_dealers_order_does_not_cover_it(self):
        llm = FakeLLM({r: ok() for r in council.ROLES}, judge=ok())
        self.run_review(accept(dealer="chato"), llm, orders=ORDERS)
        self.assertTrue(llm.calls)

    def test_no_value_gain_goes_to_the_vote(self):
        llm = FakeLLM({r: ok() for r in council.ROLES}, judge=ok())
        self.run_review(accept(price=21, value=21), llm, orders=ORDERS)
        self.assertTrue(llm.calls)
        self.assertIsNone(council.ordered_dealer_accept(accept(price=21, value=18)))

    def test_a_price_that_is_not_the_offers_ask_goes_to_the_vote(self):
        a = accept()
        a.expected["spend"] = 15                                      # we judged 15, the offer asks 21
        with plan(ORDERS)[0], plan(ORDERS)[1]:
            self.assertIsNone(council.ordered_dealer_accept(a))

    def test_market_accepts_and_sales_are_untouched(self):
        a = accept()
        a.domain = "market"
        sale = Action("accept_offer", {"offer": 1, "expect": {"give": {"cash": 80}, "want": {"types": ["card:SAL-10"]},
                                                              "maker": "pilar"}}, "dealers",
                      expected={"value_gain": 17, "price": 80, "dealer": "pilar"}, big=True)
        a1, b1 = plan(ORDERS, {"SAL-07": 30, "SAL-10": 90})
        with a1, b1:
            self.assertIsNone(council.ordered_dealer_accept(a))
            self.assertIsNone(council.ordered_dealer_accept(sale))

    def test_brief_tells_the_sides_of_a_dealer_accept(self):
        ctx, sit, _ = setup(None, control={"goal_buys": {"SAL-07": 21}})
        c = council._context_for(accept(), sit, ctx.control)
        self.assertEqual(c["accept"]["we_pay_all_in"], 21)
        self.assertEqual(c["accept"]["we_receive"]["types"], ["card:SAL-07"])
        self.assertEqual(c["accept"]["we_hand_over"]["cash"], 21)
        self.assertEqual(c["goal"]["card"], "SAL-07")
        self.assertTrue(c["goal"]["inside_cap"])


if __name__ == "__main__":
    unittest.main()
