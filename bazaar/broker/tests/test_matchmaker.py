"""The matchmaker pairs OTHER teams for our venue: it finds the pair, prices it, and stays polite."""
import json
import tempfile
import unittest
from pathlib import Path

from bazaar.broker import matchmaker as M

RARITY = {"LAT-06": "uncommon", "LAT-03": "common", "SAL-09": "rare", "RET-03": "common", "RET-01": "common",
          "MAL-11": "epic", "LAT-10": "rare", "RET-10": "rare"}


def rival(score=20.0, hunting=None, selling=None, bought=None, focus=()):
    return {"score": score, "hunting": hunting or {}, "selling": selling or {}, "bought": bought or [],
            "set_focus": list(focus)}


def report(**teams):
    return {"us": "t10", "rivals": teams}


class FindPairs(unittest.TestCase):
    def test_crossing_bid_and_ask_meet_at_the_midpoint(self):
        r = report(t06=rival(hunting={"LAT-06": {"bid": 22, "venue": "rastro", "offer": 1}}),
                   t09=rival(selling={"LAT-06": {"ask": 18, "venue": "rastro", "offer": 2}}))
        (p,) = M.find_pairs(r, RARITY)
        self.assertEqual((p["kind"], p["seller"], p["buyer"], p["ref"], p["price"]), ("cross", "t09", "t06", "LAT-06", 20))
        self.assertEqual(p["saves"], 2.0)                       # 5 % of 20 + 1 P at El Rastro

    def test_a_near_miss_is_proposed_and_a_wide_gap_is_not(self):
        near = report(t06=rival(hunting={"SAL-09": {"bid": 60, "venue": "rastro"}}),
                      t12=rival(selling={"SAL-09": {"ask": 66, "venue": "rastro"}}))
        wide = report(t06=rival(hunting={"SAL-09": {"bid": 40, "venue": "rastro"}}),
                      t12=rival(selling={"SAL-09": {"ask": 66, "venue": "rastro"}}))
        self.assertEqual(M.find_pairs(near, RARITY)[0]["kind"], "near")
        self.assertEqual(M.find_pairs(wide, RARITY), [])

    def test_we_are_never_a_party_and_excluded_rivals_are_left_out(self):
        r = report(t10=rival(selling={"LAT-06": {"ask": 10, "venue": "rastro"}}),
                   t06=rival(hunting={"LAT-06": {"bid": 22, "venue": "rastro"}}),
                   t09=rival(selling={"LAT-06": {"ask": 18, "venue": "rastro"}}))
        self.assertEqual([p["seller"] for p in M.find_pairs(r, RARITY)], ["t09"])
        self.assertEqual(M.find_pairs(r, RARITY, exclude=("t06",)), [])

    def test_giveaway_prices_are_never_pushed(self):
        r = report(t06=rival(hunting={"SAL-09": {"bid": 12, "venue": "rastro"}}),          # a rare for 11 P
                   t12=rival(selling={"SAL-09": {"ask": 10, "venue": "rastro"}}))
        self.assertEqual(M.find_pairs(r, RARITY), [])

    def test_the_last_card_of_a_page_goes_first(self):
        r = report(t06=rival(hunting={"LAT-06": {"bid": 22, "venue": "rastro"}, "LAT-03": {"bid": 9, "venue": "rastro"}},
                             focus=["LAT"]),
                   t07=rival(hunting={"RET-03": {"bid": 9, "venue": "rastro"}}, focus=["RET"]),
                   t09=rival(selling={"LAT-06": {"ask": 18, "venue": "rastro"}, "RET-03": {"ask": 8, "venue": "rastro"}}))
        first = M.find_pairs(r, RARITY)[0]
        self.assertEqual((first["buyer"], first["ref"], first["maybe_last"]), ("t07", "RET-03", True))

    def test_a_mutual_need_becomes_a_card_for_card_swap(self):
        r = report(t01=rival(hunting={"RET-10": {"bid": 0, "dealer_threads": 1}}, selling={"LAT-10": {"ask": 86, "venue": "rastro"}}),
                   t04=rival(hunting={"LAT-10": {"bid": 0, "dealer_threads": 2}}, selling={"RET-10": {"ask": 84, "venue": "rastro"}}))
        swaps = [p for p in M.find_pairs(r, RARITY) if p["kind"] == "swap"]
        self.assertEqual(len(swaps), 1)
        self.assertEqual({swaps[0]["ref"], swaps[0]["ref_back"]}, {"LAT-10", "RET-10"})
        texts = M.thread_texts(swaps[0])
        self.assertEqual(set(texts), {"t01", "t04"})
        self.assertIn("card for card", texts["t01"])

    def test_a_dealer_hunt_only_counts_when_the_team_ask_beats_the_dealer_list(self):
        cheap = report(t07=rival(hunting={"LAT-06": {"bid": 0, "dealer_threads": 2}}),
                       t09=rival(selling={"LAT-06": {"ask": 20, "venue": "rastro"}}))
        dear = report(t04=rival(hunting={"MAL-11": {"bid": 0, "dealer_threads": 3}}),
                      t18=rival(selling={"MAL-11": {"ask": 245, "venue": "rastro"}}))
        self.assertEqual(M.find_pairs(cheap, RARITY)[0]["kind"], "wanted")
        self.assertEqual(M.find_pairs(dear, RARITY), [])

    def test_both_sides_already_in_our_book_need_no_invitation(self):
        r = report(t06=rival(hunting={"LAT-06": {"bid": 22, "venue": "v07"}}),
                   t09=rival(selling={"LAT-06": {"ask": 18, "venue": "v07"}}))
        self.assertEqual(M.find_pairs(r, RARITY), [])


class Runner(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.control = {}
        self.announced, self.messages = [], []
        self.report = report(t06=rival(score=10, hunting={"LAT-06": {"bid": 22, "venue": "rastro"}}),
                             t09=rival(score=9, selling={"LAT-06": {"ask": 18, "venue": "rastro"}}),
                             t05=rival(score=30), t14=rival(score=29))

    def mm(self):
        return M.MatchMaker(self.dir / "matchmaker.json", lambda: self.report, lambda: self.control,
                            announce=self.announced.append, message=lambda team, text: self.messages.append((team, text)),
                            rarity_fn=lambda: RARITY)

    def test_announces_once_per_window_and_writes_the_brain_file(self):
        m = self.mm()
        self.assertTrue(m.step(100)["announced"])
        self.assertFalse(m.step(105)["announced"])                # the venue limit: one per 20 ticks
        self.assertTrue(m.step(120)["announced"])
        self.assertIn("LAT-06", self.announced[0])
        s = M.summary(self.dir)
        self.assertTrue(s["active"])
        self.assertEqual(s["proposals"][0]["ref"], "LAT-06")

    def test_someone_elses_announcement_on_our_venue_counts_for_the_limit(self):
        self.assertFalse(self.mm().step(100, last_venue_announce=95)["announced"])

    def test_control_switch_stops_everything(self):
        self.control = {"matchmaker": "off"}
        self.assertEqual(self.mm().step(100), {"skipped": "control matchmaker=off"})
        self.assertEqual(self.announced, [])

    def test_threads_are_off_by_default_and_rate_limited_when_on(self):
        m = self.mm()
        m.step(100)
        self.assertEqual(self.messages, [])
        self.control = {"matchmaker_threads": True}
        self.assertEqual(m.step(105)["messages"], 2)              # one to each side
        self.assertEqual(m.step(110)["messages"], 0)              # the same pair: not again for 60 ticks
        self.assertEqual({t for t, _ in self.messages}, {"t06", "t09"})
        self.assertEqual(m.step(170)["messages"], 2)

    def test_the_two_best_placed_rivals_are_not_helped_by_default(self):
        self.report = report(t05=rival(score=30, hunting={"LAT-06": {"bid": 22, "venue": "rastro"}}),
                             t14=rival(score=29), t09=rival(score=9, selling={"LAT-06": {"ask": 18, "venue": "rastro"}}))
        self.assertFalse(self.mm().step(100)["announced"])
        self.control = {"matchmaker_exclude": []}
        self.assertTrue(self.mm().step(100)["announced"])

    def test_a_trade_after_the_proposal_is_recorded(self):
        m = self.mm()
        m.step(100)
        self.report["rivals"]["t06"]["bought"] = [{"ref": "LAT-06", "price": 20, "from": "t09"}]
        m.step(105)
        self.assertEqual(M.summary(self.dir)["traded_after_proposal"], ["sale:t09>t06:LAT-06"])

    def test_an_announce_error_does_not_break_the_pass(self):
        def boom(text):
            raise RuntimeError("rate_limited: one announcement per 20 ticks")
        m = M.MatchMaker(self.dir / "m2.json", lambda: self.report, lambda: {}, announce=boom, rarity_fn=lambda: RARITY)
        self.assertFalse(m.step(100)["announced"])
        self.assertEqual(json.loads((self.dir / "m2.json").read_text())["log"][-1]["what"], "announce_failed")


if __name__ == "__main__":
    unittest.main()


class LoopHook(unittest.TestCase):
    """The broker only matchmakes between Market Tests, and a failure there never reaches the loop."""

    def loop(self):
        from bazaar.broker.run import BrokerLoop
        d = Path(tempfile.mkdtemp())
        lp = BrokerLoop(object(), d / "bench", {"session_ticks": 16}, status_file=d / "status.json",
                        state_file=d / "state.json", notices_file=d / "notices.jsonl")
        calls = []

        class Stub:
            venue = "v07"

            def step(self, tick, last_venue_announce=None):
                calls.append(tick)
                return {"announced": True, "messages": 0, "pairs": 1}
        lp.matchmaker = Stub()
        return lp, calls

    def test_runs_every_five_ticks_outside_sessions(self):
        lp, calls = self.loop()
        for t in (100, 101, 105):
            lp._matchmake(t, {"tick_seconds": 30.0}, True, False)
        self.assertEqual(calls, [100, 105])

    def test_quiet_during_a_session_before_one_and_when_writes_are_off(self):
        lp, calls = self.loop()
        lp._matchmake(100, {"tick_seconds": 30.0}, True, True)        # bench offers in the book
        lp._matchmake(100, {"tick_seconds": 30.0}, False, False)       # writes off
        lp.t_hours, lp.bench_hours = 12.95, [13.0]                      # 6 ticks before the Market Test
        lp._matchmake(100, {"tick_seconds": 30.0}, True, False)
        self.assertEqual(calls, [])
        lp.t_hours = 12.5                                               # 60 ticks before: fine
        lp._matchmake(100, {"tick_seconds": 30.0}, True, False)
        self.assertEqual(calls, [100])

    def test_a_matchmaker_error_is_logged_not_raised(self):
        lp, _ = self.loop()

        class Bad:
            venue = "v07"

            def step(self, tick, last_venue_announce=None):
                raise ValueError("boom")
        lp.matchmaker = Bad()
        lp._matchmake(100, {"tick_seconds": 30.0}, True, False)
        self.assertEqual(lp.errors[-1]["where"], "matchmaker")
