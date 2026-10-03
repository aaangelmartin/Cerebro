"""Bounds on what a broker can gain over the stall, and the stall matcher that the overlay can switch on."""
import unittest

from bazaar.broker import policy_overlay
from bazaar.broker.engine import BenchEngine, merge_policy, stall_plan
from bazaar.broker.headroom import (best_gain, guess_limit, oracle_lookahead, oracle_now, real_session,
                                    structured_session)
from bazaar.broker.sim_book import SimSession, SimTrader, play, stall_planner


def trader(i, side, limit, q0, arrive=0, leave=4, step=0.0):
    return SimTrader(id=f"b1-{i}", side=side, limit=limit, q0=q0, firm=step == 0, patience=0, mode="lin", rate=0.3,
                     step=step, arrive=arrive, leave=leave)


def diagonal():
    """Bids 10 and 6, asks 5 and 9: the stall pairs 10 with 5 and strands the other two; 10 with 9 and 6 with 5
    closes both. The true limits make the second pair worth having (buyer 8, seller 7)."""
    return SimSession([trader(0, "buy", 12, 10), trader(1, "buy", 8, 6), trader(2, "sell", 4, 5),
                       trader(3, "sell", 7, 9)], ticks=4)


def book(bids, asks, run="b1"):
    out = [{"id": f"{run}-b{i}", "give": {"cash": q}, "want": {"cash": 0}} for i, q in enumerate(bids)]
    return out + [{"id": f"{run}-s{i}", "give": {"cash": 0}, "want": {"cash": q}} for i, q in enumerate(asks)]


class TestBounds(unittest.TestCase):
    def test_all_is_the_sorted_pairing(self):
        s = diagonal()
        self.assertEqual(best_gain(s, "all"), s.max_gain())
        self.assertEqual(best_gain(s, "all"), (12 - 4) + (8 - 7))

    def test_cross_needs_quotes_that_cross(self):
        s = SimSession([trader(0, "buy", 90, 60), trader(1, "sell", 50, 70)], ticks=4)     # limits cross, quotes never
        self.assertEqual(best_gain(s, "copresent"), 40)
        self.assertEqual(best_gain(s, "cross"), 0)

    def test_copresent_needs_a_shared_tick(self):
        s = SimSession([trader(0, "buy", 90, 80, arrive=0, leave=2), trader(1, "sell", 50, 60, arrive=2, leave=4)], ticks=4)
        self.assertEqual(best_gain(s, "all"), 40)
        self.assertEqual(best_gain(s, "copresent"), 0)

    def test_cross_counts_a_pair_that_crosses_later(self):
        s = SimSession([trader(0, "buy", 80, 50, step=10), trader(1, "sell", 60, 70)], ticks=4)   # 50, 60, 70 >= 70
        self.assertEqual(best_gain(s, "cross"), 20)

    def test_bounds_are_ordered_on_random_sessions(self):
        for seed in range(15):
            s = structured_session(seed)
            self.assertGreaterEqual(best_gain(s, "all") + 1e-9, best_gain(s, "copresent"))
            self.assertGreaterEqual(best_gain(s, "copresent") + 1e-9, best_gain(s, "cross"))
            play(s, stall_planner())
            self.assertGreaterEqual(best_gain(structured_session(seed), "cross") + 1e-9, s.realised)


class TestOracles(unittest.TestCase):
    def test_the_stall_strands_the_diagonal_pair(self):
        s = diagonal()
        play(s, stall_planner())
        self.assertEqual(len(s.matches), 1)
        self.assertEqual(s.realised, 8)

    def test_oracle_now_closes_both_pairs(self):
        s = diagonal()
        play(s, oracle_now(s))
        self.assertEqual(len(s.matches), 2)
        self.assertEqual(s.realised, 9)
        self.assertEqual(s.realised, best_gain(diagonal(), "cross"))

    def test_lookahead_waits_for_the_better_partner_it_can_see(self):
        # the seller at 30 crosses the weak buyer now and the strong one a tick later; both buyers stay
        mk = lambda: SimSession([trader(0, "buy", 40, 32), trader(1, "buy", 90, 20, step=35), trader(2, "sell", 25, 30)], ticks=4)
        now, look = mk(), mk()
        play(now, oracle_now(now))
        play(look, oracle_lookahead(look))
        self.assertEqual(now.realised, 15)
        self.assertEqual(look.realised, 65)
        self.assertEqual(look.matches[0]["t"], 1)

    def test_structured_sessions_look_like_the_recordings(self):
        pairs = []
        for seed in range(60):
            s = structured_session(seed)
            self.assertEqual(len(s.traders), 20)
            self.assertTrue(all(0 <= t.arrive <= 11 and t.arrive < t.leave <= 16 for t in s.traders))
            play(s, stall_planner())
            pairs.append(len(s.matches))
        self.assertTrue(4.0 <= sum(pairs) / len(pairs) <= 7.0)


class TestStallMatcher(unittest.TestCase):
    def test_default_matcher_is_the_engine(self):
        self.assertEqual(merge_policy(None)["matcher"], "engine")

    def test_stall_matcher_pairs_like_the_stall(self):
        for seed in range(40):
            ours, ref = structured_session(seed), structured_session(seed)
            eng = BenchEngine(merge_policy({"matcher": "stall"}))

            def plan(t, bk, eng=eng):
                eng.observe(t, bk)
                return eng.plan(t)
            play(ours, plan, eng)
            play(ref, stall_planner())
            self.assertEqual(sorted((m["t"], m["sell"], m["buy"]) for m in ours.matches),
                             sorted((m["t"], m["sell"], m["buy"]) for m in ref.matches), seed)
            self.assertEqual(ours.refused, 0)

    def test_stall_matcher_one_tick(self):
        bk = book([10, 6], [5, 9])
        eng = BenchEngine(merge_policy({"matcher": "stall"}))
        eng.observe(1, bk)
        got = [(m.sell, m.buy, m.price) for m in eng.plan(1)]
        self.assertEqual(got, [(m.sell, m.buy, m.price) for m in stall_plan(bk)])
        self.assertEqual(got, [("b1-s0", "b1-b0", 7)])

    def test_overlay_accepts_the_matcher_and_rejects_a_typo(self):
        clean, rejected = policy_overlay.validate({"matcher": "stall"})
        self.assertEqual((clean, rejected), ({"matcher": "stall"}, []))
        clean, rejected = policy_overlay.validate({"matcher": "greedy"})
        self.assertEqual(clean, {})
        self.assertEqual(rejected, ["matcher='greedy'"])
        self.assertEqual(policy_overlay.apply(merge_policy(None), {"matcher": "stall"})["matcher"], "stall")


class TestRealSession(unittest.TestCase):
    def rows(self):
        def tick(t, bids, asks, results=()):
            return {"type": "tick", "tick": t, "results": list(results),
                    "bench": [{"id": k, "give": {"cash": q}, "want": {"cash": 0}} for k, q in bids]
                    + [{"id": k, "give": {"cash": 0}, "want": {"cash": q}} for k, q in asks]}
        ok = {"sell": "b9-11", "buy": "b9-1", "price": 60, "status": "ok"}
        return [{"type": "start", "tick": 10},
                tick(10, [("b9-0", 50)], [("b9-10", 100)]),
                tick(11, [("b9-0", 55), ("b9-1", 80)], [("b9-10", 100), ("b9-11", 40)], [ok]),
                tick(12, [("b9-0", 60)], [("b9-10", 100)]),
                tick(13, [], [("b9-10", 100)])]

    def test_counts_pairs_and_matches_the_stall(self):
        r = real_session(self.rows())
        self.assertEqual((r["traders"], r["pairs"], r["stall_pairs"], r["same_as_stall"]), (4, 1, 1, True))
        self.assertEqual(r["share_cross"], 1.0)

    def test_a_trader_that_never_crossed_shows_as_lost_to_all_only(self):
        r = real_session(self.rows())
        self.assertLessEqual(r["best_cross"], r["best_copresent"])
        self.assertLessEqual(r["best_copresent"], r["best_all"])

    def test_guess_limit(self):
        self.assertEqual(guess_limit("sell", [100], False), 80.0)                    # fresh ask: 25 % above the cost
        self.assertEqual(guess_limit("buy", [70], False), 100.0)                     # fresh bid: 30 % below the value
        self.assertEqual(guess_limit("sell", [130, 125, 119, 114], True), 114.0)     # ran its course and left
        self.assertEqual(guess_limit("buy", [41, 46, 51], False), 56.0)              # still moving: one more step
        self.assertEqual(guess_limit("buy", [51, 51, 51], False), 51.0)              # firm

    def test_empty(self):
        self.assertEqual(real_session([]), {})


if __name__ == "__main__":
    unittest.main()
