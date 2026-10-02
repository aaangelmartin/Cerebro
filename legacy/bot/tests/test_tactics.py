"""Unit tests of the pure negotiation helpers: python3 -m unittest bot.tests.test_tactics"""

from __future__ import annotations

import unittest

from bot import tactics as tx


class Curves(unittest.TestCase):
    def test_alpha_endpoints_and_shapes(self):
        for e in tx.CURVES.values():
            self.assertAlmostEqual(tx.faratin_alpha(0, e), 0.0)
            self.assertAlmostEqual(tx.faratin_alpha(1, e), 1.0)
        mid = {name: tx.faratin_alpha(0.5, e) for name, e in tx.CURVES.items()}
        self.assertLess(mid["hardheaded"], mid["boulware"])
        self.assertLess(mid["boulware"], mid["linear"])
        self.assertLess(mid["linear"], mid["conceder"])
        self.assertAlmostEqual(mid["linear"], 0.5)

    def test_alpha_clamps_and_k(self):
        self.assertEqual(tx.faratin_alpha(-1, 1), 0.0)
        self.assertEqual(tx.faratin_alpha(2, 1), 1.0)
        self.assertAlmostEqual(tx.faratin_alpha(0, 1, k=0.2), 0.2)
        with self.assertRaises(ValueError):
            tx.faratin_alpha(0.5, 0)

    def test_target_both_directions(self):
        self.assertAlmostEqual(tx.concession_target(10, 30, 0.5, 1.0), 20)   # buyer goes up
        self.assertAlmostEqual(tx.concession_target(60, 40, 0.5, 1.0), 50)   # seller goes down
        self.assertLess(tx.concession_target(10, 30, 0.5, 0.3), 20)          # Boulware holds
        self.assertAlmostEqual(tx.utility_target(50, 10, 1.0), 10)

    def test_monotonic(self):
        prev = -1
        for i in range(11):
            a = tx.faratin_alpha(i / 10, 0.3)
            self.assertGreaterEqual(a, prev)
            prev = a


class Reading(unittest.TestCase):
    def test_concessions_direction(self):
        self.assertEqual(tx.concessions([50, 45, 43], they_sell=True), [5, 2])
        self.assertEqual(tx.concessions([10, 14, 15], they_sell=False), [4, 1])
        self.assertEqual(tx.concessions([50, 52], they_sell=True), [-2])

    def test_mirror_ratio(self):
        self.assertIsNone(tx.mirror_ratio([], []))
        self.assertAlmostEqual(tx.mirror_ratio([10, 10, 10], [8, 8, 8]), 0.8)
        self.assertAlmostEqual(tx.mirror_ratio([10, 10, 10, 10], [8, 8, 0, 0]), 0.0)  # hit its limit
        self.assertIsNone(tx.mirror_ratio([0, 0], [3, 3]))

    def test_reservation_geometric(self):
        # Seller asks 100, 80, 70: steps 20, 10, q=0.5, remaining 10 -> ~60.
        r = tx.estimate_reservation([100, 80, 70], they_sell=True)
        self.assertAlmostEqual(r["estimate"], 60)
        self.assertFalse(r["stalled"])
        # Buyer bids 10, 20, 25 -> ~30.
        self.assertAlmostEqual(tx.estimate_reservation([10, 20, 25], they_sell=False)["estimate"], 30)

    def test_reservation_q_cap(self):
        r = tx.estimate_reservation([100, 90, 81], they_sell=True, q_cap=0.75)
        self.assertLessEqual(r["q"], 0.75)
        r = tx.estimate_reservation([100, 95, 90], they_sell=True, q_cap=0.75)  # equal steps: capped
        self.assertAlmostEqual(r["q"], 0.75)
        self.assertAlmostEqual(r["estimate"], 90 - 15)

    def test_reservation_stall_and_empty(self):
        r = tx.estimate_reservation([100, 80, 80, 80], they_sell=True)
        self.assertTrue(r["stalled"])
        self.assertEqual(r["estimate"], 80)
        self.assertIsNone(tx.estimate_reservation([], True)["estimate"])
        self.assertIsNone(tx.estimate_reservation([50], True)["estimate"])

    def test_reservation_single_step(self):
        r = tx.estimate_reservation([100, 90], they_sell=True, q_cap=0.5)
        self.assertAlmostEqual(r["estimate"], 80)


class Steps(unittest.TestCase):
    def test_reciprocal_matches_and_caps(self):
        self.assertEqual(tx.reciprocal_step(4, gap=40), 4)
        self.assertEqual(tx.reciprocal_step(4, gap=40, ratio=0.5), 2)
        self.assertEqual(tx.reciprocal_step(30, gap=40), 14)        # capped at 35 % of the gap
        self.assertEqual(tx.reciprocal_step(None, gap=40), 1)       # nothing to match: minimum
        self.assertEqual(tx.reciprocal_step(-3, gap=40), 1)         # they went back: minimum
        self.assertEqual(tx.reciprocal_step(5, gap=2), 1)
        self.assertEqual(tx.reciprocal_step(5, gap=0), 0)

    def test_next_offer_bounds(self):
        self.assertEqual(tx.next_offer(20, 40, 35, True, 5), 25)
        self.assertEqual(tx.next_offer(33, 40, 35, True, 5), 35)    # capped by our limit
        self.assertIsNone(tx.next_offer(35, 40, 35, True, 5))       # at limit: never repeat
        self.assertEqual(tx.next_offer(38, 40, 50, True, 5), 40)    # never past their price
        self.assertEqual(tx.next_offer(60, 40, 45, False, 5), 55)
        self.assertEqual(tx.next_offer(48, 40, 45, False, 5), 45)
        self.assertIsNone(tx.next_offer(45, 40, 45, False, 5))
        with self.assertRaises(ValueError):
            tx.next_offer(None, 40, 45, False, 5)

    def test_anchor(self):
        self.assertEqual(tx.anchor(50, 40, True, 0.4), 20)
        self.assertEqual(tx.anchor(50, 40, True, 0.05), 12)        # clamped to 25 %
        self.assertEqual(tx.anchor(100, 20, True, 0.4), 20)        # never above our limit
        self.assertEqual(tx.anchor(10, 5, False, 2.2), 22)
        self.assertEqual(tx.anchor(10, 40, False, 2.2), 40)        # never below our limit
        self.assertEqual(tx.anchor(10, 5, False, 9), 30)           # clamped to 3x

    def test_blended_step(self):
        s = tx.blended_step(ours=20, theirs=50, limit=40, buying=True, t=0.5, start=20, their_step=4,
                            e=1.0, w_time=0.5)
        self.assertEqual(s, 7)  # time step 10, reciprocal 4 -> 7
        s = tx.blended_step(ours=49, theirs=50, limit=60, buying=True, t=0.9, start=20, their_step=10)
        self.assertEqual(s, 1)  # tiny gap: one prima
        s = tx.blended_step(ours=80, theirs=40, limit=50, buying=False, t=0.0, start=80, their_step=None)
        self.assertEqual(s, 1)  # nothing on the curve yet and nothing to match


class Acceptance(unittest.TestCase):
    def test_reservation_first(self):
        ok, _ = tx.should_accept(-1, 0, final=True, ticks_left=0)
        self.assertFalse(ok)

    def test_final_inside_limit(self):
        self.assertTrue(tx.should_accept(2, 50, final=True)[0])

    def test_ac_next_discounted(self):
        self.assertTrue(tx.should_accept(10, 10)[0])
        self.assertFalse(tx.should_accept(9, 10)[0])
        # 9 >= 10 * 0.94^2 = 8.84
        self.assertTrue(tx.should_accept(9, 10, decay=0.06, lookahead=2)[0])
        self.assertFalse(tx.should_accept(8, 10, decay=0.06, lookahead=2)[0])

    def test_ac_time_and_combi(self):
        self.assertTrue(tx.should_accept(3, 20, ticks_left=1, last_ticks=1)[0])
        self.assertFalse(tx.should_accept(3, 20, ticks_left=3, last_ticks=1)[0])
        self.assertTrue(tx.should_accept(6, 20, t=0.9, late_frac=0.8, best_seen_u=6)[0])
        self.assertFalse(tx.should_accept(6, 20, t=0.5, late_frac=0.8, best_seen_u=6)[0])
        self.assertFalse(tx.should_accept(5, 20, t=0.9, late_frac=0.8, best_seen_u=6)[0])

    def test_discounted_and_rubinstein(self):
        self.assertAlmostEqual(tx.discounted(100, 0.1, 2), 81)
        self.assertAlmostEqual(tx.discounted(100, 0.1, -1), 100)
        self.assertAlmostEqual(tx.rubinstein_share(0.0), 0.5)
        self.assertAlmostEqual(tx.rubinstein_share(0.06), 1 / 1.94)
        self.assertGreater(tx.rubinstein_share(0.5), tx.rubinstein_share(0.1))


class Issues(unittest.TestCase):
    def test_joint_day(self):
        self.assertEqual(tx.joint_day(2, -1), 10)
        self.assertEqual(tx.joint_day(1, -3), 0)
        self.assertEqual(tx.joint_day(1, -1), 5)

    def test_equivalent_packages_same_utility(self):
        for role, limit, w in (("seller", 50, 1.5), ("buyer", 100, -2.0), ("seller", 50, -1.0)):
            pk = tx.equivalent_packages(role, limit, u=20, w=w)
            self.assertTrue(pk)
            for price, d in pk:
                s = price - limit if role == "seller" else limit - price
                self.assertLessEqual(abs(s + w * d - 20), 0.5 + 1e-9)  # rounding to whole primas

    def test_equivalent_packages_min_surplus(self):
        pk = tx.equivalent_packages("seller", 50, u=5, w=2, days_options=(0, 10))
        self.assertEqual(pk, [(55, 0), (51, 10)])  # 5 - 20 would be below our limit: keep 1


class Tone(unittest.TestCase):
    def test_tones(self):
        self.assertEqual(tx.tone(0.1, their_step=3), "warm")
        self.assertEqual(tx.tone(0.1, their_step=0), "firm")
        self.assertEqual(tx.tone(0.1, their_step=0, kind_counterpart=True), "warm")
        self.assertEqual(tx.tone(0.85, their_step=0), "closing")
        self.assertEqual(tx.tone(0.1, final=True), "closing")
        self.assertEqual(tx.tone(0.1, their_step=2, gap=3, our_step=2), "closing")
        for t in tx.TONES:
            self.assertIn(t, tx.TONE_HINTS)


if __name__ == "__main__":
    unittest.main()
