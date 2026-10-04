"""Duels III: the delivery day follows our own sign (the day prior no longer moves it), a duel's own length drives the time schedule, and
the buyer opens a little closer than the seller."""
from __future__ import annotations

import unittest

from bazaar.duels.model import DAYS_MAX, parse_duel
from bazaar.duels.policy import PARAMS, _target_share, choose_days, joint_days_bonus, plan, rival_cares_more
from bazaar.duels.tests.test_duels import duel, mem

COST = "each delivery day costs you this much cash"
GAIN = "each delivery day adds this much cash to your side"


def live(did, role, w, item="La Sala Pentagrama", session=3, tick=100, deadline=112, **kw):
    meaning = COST if role == "buyer" else GAIN
    return parse_duel(duel(duel=did, role=role, item=item, session=session, issues=["price", "days"],
                           your_days_weight=w, days_meaning=meaning, deadline_tick=deadline,
                           decay_per_round=0.10, **kw), tick)


def memory_with(*legs):
    """legs: (duel id, role, weight) already seen on the same item and session."""
    m = mem()
    for did, role, w in legs:
        m.observe_duel(live(did, role, w))
    return m


class TestRivalDayPrior(unittest.TestCase):
    def test_median_of_the_other_role_on_the_same_item(self):
        m = memory_with((1, "seller", 3.92), (2, "seller", 6.86), (3, "seller", 5.62), (4, "buyer", 2.14))
        self.assertEqual(m.rival_day_prior(live(9, "buyer", 1.54)), 5.62)      # sellers' weights
        self.assertIsNone(m.rival_day_prior(live(9, "seller", 5.0)))           # only one buyer leg so far

    def test_other_items_and_sessions_do_not_count(self):
        m = memory_with((1, "seller", 5.0), (2, "seller", 6.0))
        self.assertIsNone(m.rival_day_prior(live(9, "buyer", 1.5, item="La Vía Láctea")))
        self.assertIsNone(m.rival_day_prior(live(9, "buyer", 1.5, session=4)))
        self.assertIsNone(m.rival_day_prior(parse_duel(duel(duel=9, item="La Sala Pentagrama", session=3), 100)))


class TestDayGoesToWhoCaresMore(unittest.TestCase):
    def test_buyer_keeps_zero_days_even_when_the_seller_gains_more(self):
        # Sunday: giving the seller its ten days and charging them in the price was not paid back (duels
        # 11231 and 11544 closed below zero). Days that cost us stay at 0 whatever the prior says.
        v = live(9, "buyer", 1.54)                       # a day costs us 1.54
        v.rival_w_prior = 5.8                            # and pays the seller about 5.8
        self.assertTrue(rival_cares_more(v))
        self.assertEqual(choose_days(v, pie=40), 0)
        mv = plan(v, mem().assess(v))
        self.assertEqual((mv.action, mv.days), ("offer", 0))
        self.assertGreaterEqual(v.utility(mv.price, mv.days), 1)
        self.assertGreaterEqual(v.surplus(mv.price), 1)

    def test_seller_keeps_ten_days_even_when_the_buyer_loses_more(self):
        v = live(9, "seller", 1.8, item="Fiesta de San Cayetano", your_limit=96)
        v.rival_w_prior = 6.6
        self.assertEqual(choose_days(v, pie=40), DAYS_MAX)
        self.assertEqual(joint_days_bonus(v, DAYS_MAX), 0.0)

    def test_close_weights_or_no_prior_keep_the_old_day(self):
        buyer = live(9, "buyer", 4.31, item="La Vía Láctea")
        buyer.rival_w_prior = 4.53                       # barely more than ours: not worth the risk
        self.assertFalse(rival_cares_more(buyer))
        self.assertEqual(choose_days(buyer, pie=40), 0)
        seller = live(9, "seller", 5.8)
        self.assertEqual(choose_days(seller, pie=40), DAYS_MAX)          # no prior: as before
        seller.rival_w_prior = 1.7                       # the buyer cares less: keep our ten days
        self.assertEqual(choose_days(seller, pie=40), DAYS_MAX)

    def test_ambiguous_sign_ignores_the_prior(self):
        v = parse_duel(duel(duel=9, issues=["price", "days"], your_days_weight=1.5, days_meaning="",
                            deadline_tick=112, decay_per_round=0.10), 100)
        v.rival_w_prior = 6.0
        if v.days_ambiguous:
            self.assertFalse(rival_cares_more(v))
            self.assertEqual(choose_days(v, pie=40), 0)


class TestDuelLengthAndOpening(unittest.TestCase):
    def test_a_twelve_tick_duel_starts_at_the_opening_share(self):
        v = live(9, "seller", 2.0, tick=100, deadline=112)
        v.total_ticks = mem().duel_length(v)
        self.assertEqual((v.total_ticks, v.elapsed), (12, 0))
        self.assertAlmostEqual(_target_share(v), PARAMS["OPEN"])
        late = live(9, "seller", 2.0, tick=111, deadline=112)
        late.total_ticks = 12
        self.assertAlmostEqual(_target_share(late), PARAMS["END"])

    def test_length_comes_from_the_first_tick_we_saw_the_duel(self):
        m = mem()
        m.observe_duel(live(9, "seller", 2.0, tick=100, deadline=112))
        self.assertEqual(m.duel_length(live(9, "seller", 2.0, tick=107, deadline=112)), 12)

    def test_buyer_opens_closer_than_seller(self):
        b, s = live(9, "buyer", 2.0), live(8, "seller", 2.0)
        b.total_ticks = s.total_ticks = 12
        self.assertAlmostEqual(_target_share(b), PARAMS["OPEN_BUYER"])
        self.assertLess(_target_share(b), _target_share(s))


if __name__ == "__main__":
    unittest.main()
