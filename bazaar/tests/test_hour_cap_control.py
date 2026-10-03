"""The hour's spend budget follows control.max_spend_per_hour (code-643a28c3).

At t1210 the brain's order for SAL-09 at Los Pícaros was skipped with "cash to spend 0" while 573 P sat in
cash: the tick budget sized the hour with the config default (250) although control had raised it to 550, and
our two open market bids (383 P) were then netted out of what was left of the 250."""
import unittest

from bazaar import config
from bazaar.core.context import Budget
from bazaar.dealers.domain import DealersDomain


class Ctx:
    def __init__(self, budget, control):
        self.budget, self.control = budget, control


def _sit(cash, bids):
    offers = [{"id": i, "maker": "t10", "status": "open", "thread": None, "give": {"cash": c}}
              for i, c in enumerate(bids)]
    return {"me": {"id": "t10", "cash": cash}, "my_offers": offers, "threads": [],
            "venues": [{"id": "v07", "owner": "t10", "status": "open"}]}


class HourCapFromControl(unittest.TestCase):
    def _budget(self, spent, hour_cap=None):
        b = Budget.__new__(Budget)
        b.state = {"tick": 1, "accepts": 0, "duel_accepts": 0, "messages": {}, "offers": 0,
                   "spend": [(1000.0, spent)], "deals": []}
        return b.for_tick(1, {}, now=1001.0, hour_cap=hour_cap)

    def test_default_cap_is_the_config_one(self):
        b = self._budget(77)
        self.assertEqual(b["spend_hour_left"], config.MAX_SPEND_PER_HOUR - 77)
        self.assertEqual(b["spend_hour_cap"], config.MAX_SPEND_PER_HOUR)

    def test_control_cap_sizes_the_hour(self):
        b = self._budget(77, hour_cap=550)
        self.assertEqual(b["spend_hour_left"], 473)
        self.assertEqual(b["spend_hour_cap"], 550)

    def test_goal_order_fits_beside_our_open_bids(self):
        # cash 573, 383 P in two open market bids, 77 P spent this hour, reserve 5, caps 210 / 550
        control = {"cash_reserve": 5, "max_spend_per_deal": 210, "max_spend_per_hour": 550, "venue_reserve": False}
        dom = DealersDomain.__new__(DealersDomain)
        sit = _sit(573, [178, 205])
        old = dom._spend_cap(sit, Ctx(self._budget(77), control))
        new = dom._spend_cap(sit, Ctx(self._budget(77, hour_cap=550), control))
        self.assertEqual(old, 0)                               # the reported skip: 250 - 77 - 383 < 0
        self.assertEqual(new, 90)                              # 550 - 77 - 383: SAL-09 at 57 can go out
        self.assertGreaterEqual(new, 57)

    def test_no_real_room_still_skips_and_shows_the_formula(self):
        control = {"cash_reserve": 5, "max_spend_per_deal": 210, "max_spend_per_hour": 550, "venue_reserve": False}
        dom = DealersDomain.__new__(DealersDomain)
        sit = _sit(390, [178, 205])                            # 390 - 5 - 383 = 2 P free
        ctx = Ctx(self._budget(77, hour_cap=550), control)
        self.assertEqual(dom._spend_cap(sit, ctx), 2)
        text = dom._spend_formula(sit, ctx)
        for part in ("cash 390", "reserve 5", "hour left 473 of 550", "market bids 383", "per deal 210"):
            self.assertIn(part, text)


if __name__ == "__main__":
    unittest.main()
