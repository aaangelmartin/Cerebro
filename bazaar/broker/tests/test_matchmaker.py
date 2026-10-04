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


class BigTicketsAndWording(unittest.TestCase):
    """What settled on other teams' venues on Saturday night: an addressed offer the other side accepts, and
    the rare-or-better trades that paid the El Rastro fee."""

    RAR = {**RARITY, "MAL-11": "epic", "LAT-10": "rare", "RET-09": "rare"}

    def test_a_public_epic_bid_on_the_house_market_gets_a_relist_line(self):
        r = report(t17=rival(hunting={"MAL-11": {"bid": 150, "venue": "rastro", "offer": 5, "to": None}}))
        (p,) = M.big_tickets(r, self.RAR)
        self.assertEqual((p["kind"], p["side"], p["buyer"], p["seller"], p["price"]), ("relist", "bid", "t17", None, 150))
        self.assertEqual(p["saves"], M.rastro_fee(150))
        text = M.announcement([p])
        self.assertIn("t17 bids 150 on El Rastro", text)
        self.assertIn("keep the full 150", text)

    def test_a_rare_ask_on_the_house_market_gets_a_relist_line(self):
        r = report(t18=rival(selling={"LAT-10": {"ask": 72, "venue": "rastro", "offer": 9}}))
        (p,) = M.big_tickets(r, self.RAR)
        self.assertEqual((p["side"], p["seller"], p["buyer"]), ("ask", "t18", None))
        self.assertIn("pay 0", M.announcement([p]))

    def test_commons_giveaways_other_venues_addressed_offers_us_and_excluded_teams_are_left_out(self):
        r = report(
            t09=rival(selling={"RET-03": {"ask": 10, "venue": "rastro", "offer": 1},          # a common
                               "RET-09": {"ask": 20, "venue": "rastro", "offer": 2}}),          # a giveaway
            t12=rival(hunting={"MAL-11": {"bid": 150, "venue": "v21", "offer": 3, "to": None}}),   # not a fee venue
            t13=rival(hunting={"LAT-10": {"bid": 72, "venue": "rastro", "offer": 4, "to": "t09"}}),  # addressed
            t10=rival(hunting={"MAL-11": {"bid": 195, "venue": "rastro", "offer": 6, "to": None}}),  # us
            t06=rival(selling={"RET-09": {"ask": 84, "venue": "rastro", "offer": 7}}))            # excluded
        self.assertEqual(M.big_tickets(r, self.RAR, exclude=("t06",)), [])

    def test_the_announcement_tells_one_side_to_post_addressed_and_the_other_to_accept(self):
        r = report(t07=rival(hunting={"LAT-06": {"bid": 20, "venue": "rastro", "offer": 1}}),
                   t09=rival(selling={"LAT-06": {"ask": 18, "venue": "rastro", "offer": 2}}))
        text = M.announcement(M.find_pairs(r, RARITY))
        self.assertIn("t09: post it on v07 to t07 at 19; t07: accept it", text)
        self.assertNotIn("PUBLIC", text)

    def test_a_relist_message_goes_to_the_one_team_and_is_not_a_trade_request(self):
        r = report(t17=rival(hunting={"MAL-11": {"bid": 150, "venue": "rastro", "offer": 5, "to": None}}))
        (p,) = M.big_tickets(r, self.RAR)
        texts = M.thread_texts(p)
        self.assertEqual(list(texts), ["t17"])
        self.assertIn("not a trade request", texts["t17"])
        self.assertTrue(M.pair_key(p).startswith("relist:bid:t17:MAL-11"))

    def test_the_runner_puts_a_big_ticket_ahead_of_a_cheap_common_pair(self):
        import tempfile
        from pathlib import Path
        r = report(t03=rival(hunting={"LAT-03": {"bid": 0, "dealer_threads": 2}}),
                   t09=rival(selling={"LAT-03": {"ask": 8, "venue": "rastro", "offer": 2}}),
                   t17=rival(hunting={"MAL-11": {"bid": 150, "venue": "rastro", "offer": 5, "to": None}}))
        said = []
        with tempfile.TemporaryDirectory() as d:
            m = M.MatchMaker(Path(d) / "m.json", lambda: r, lambda: {"matchmaker_exclude": []},
                             announce=said.append, rarity_fn=lambda: self.RAR)
            done = m.step(100)
        self.assertTrue(done["announced"])
        self.assertLess(said[0].index("MAL-11"), said[0].index("LAT-03"))

    def test_a_named_pair_always_makes_the_announcement_next_to_the_big_tickets(self):
        tickets = [{"kind": "relist", "ref": f"X{i}", "score": 5.0 - i} for i in range(4)]
        pairs = [{"kind": "wanted", "ref": "P0", "score": 1.4}, {"kind": "wanted", "ref": "P1", "score": 1.2}]
        self.assertEqual([p["ref"] for p in M.mix(pairs, tickets)], ["X0", "P0", "X1", "X2", "X3", "P1"])
        self.assertEqual([p["ref"] for p in M.mix(pairs, [])], ["P0", "P1"])
        self.assertEqual([p["ref"] for p in M.mix([], tickets[:2])], ["X0", "X1"])


class PlazaLinkTest(unittest.TestCase):
    """The venue's announcements point at the plaza, and pairs both agents declared there go first."""

    def test_announcement_carries_the_page_and_fits(self):
        pair = {"kind": "wanted", "seller": "t09", "buyer": "t07", "ref": "LAT-06", "rarity": "uncommon",
                "price": 20, "ask": 20.0, "bid": 0, "saves": 2}
        text = M.announcement([pair], page="https://example.org/plaza")
        self.assertTrue(text.endswith("https://example.org/plaza/"))
        self.assertLessEqual(len(text), M.MAX_TEXT)
        self.assertNotIn("example.org", M.announcement([pair]))
        long = M.announcement([dict(pair, ref=f"LAT-{i:02d}") for i in range(1, 9)], limit=8, page="https://example.org/plaza")
        self.assertLessEqual(len(long), M.MAX_TEXT)
        self.assertTrue(long.endswith("https://example.org/plaza/"))

    def test_declared_pairs_lead_and_respect_the_exclusions(self):
        with tempfile.TemporaryDirectory() as d:
            said = []
            declared = [{"kind": "wanted", "seller": "t03", "buyer": "t04", "ref": "LAT-03", "rarity": "common",
                         "price": 8, "ask": 8.0, "bid": 0.0, "saves": 1, "maybe_last": False, "score": 9.0, "why": "x"},
                        {"kind": "wanted", "seller": "t06", "buyer": "t04", "ref": "RET-03", "rarity": "common",
                         "price": 8, "ask": 8.0, "bid": 0.0, "saves": 1, "maybe_last": False, "score": 9.0, "why": "x"}]
            mm = M.MatchMaker(Path(d) / "mm.json", lambda: report(), lambda: {"matchmaker_exclude": ["t06"]},
                              announce=said.append, rarity_fn=lambda: RARITY,
                              page_fn=lambda: "https://example.org/plaza", declared_fn=lambda: declared)
            done = mm.step(100)
            self.assertEqual(done["pairs"], 1)                      # the pair with the excluded team is dropped
            self.assertTrue(done["announced"])
            self.assertIn("LAT-03", said[0])
            self.assertNotIn("RET-03", said[0])
            self.assertIn("https://example.org/plaza/", said[0])


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


class ThePlazaCannotHurtTheBroker(unittest.TestCase):
    """The plaza's helpers run with a deadline and are left alone after a miss: a slow or broken plaza costs
    the pass its extras, never the broker's tick (the supervisor restarts a broker that stops reporting)."""

    PAIR = {"kind": "wanted", "seller": "t03", "buyer": "t04", "ref": "LAT-03", "rarity": "common", "price": 8,
            "ask": 8.0, "bid": 0.0, "saves": 1, "maybe_last": False, "score": 9.0, "why": "x"}

    def maker(self, d, said, **kw):
        team = {"t03": rival(selling={"LAT-06": {"price": 20, "venue": "rastro"}}),
                "t04": rival(hunting={"LAT-06": {"bid": 22, "venue": "rastro"}})}
        return M.MatchMaker(Path(d) / "mm.json", lambda: report(**team), lambda: {"matchmaker_exclude": []},
                            announce=said.append, rarity_fn=lambda: RARITY, **kw)

    def test_a_hung_helper_is_dropped_after_its_deadline_and_not_called_again(self):
        import threading
        import time
        release, calls = threading.Event(), []

        def hung():
            calls.append(1)
            release.wait(5)
            return [self.PAIR]
        with tempfile.TemporaryDirectory() as d:
            said = []
            mm = self.maker(d, said, declared_fn=hung, page_fn=lambda: "https://example.org/plaza")
            old, M.HELPER_TIMEOUT_S = M.HELPER_TIMEOUT_S, 0.2
            try:
                t0 = time.time()
                mm.step(100)
                self.assertLess(time.time() - t0, 1.0)                # the pass did not wait for it
                mm.step(120)                                          # and does not stack a second call
                self.assertEqual(len(calls), 1)
                self.assertIn("helper_failed", [e["what"] for e in mm.state["log"]])
            finally:
                M.HELPER_TIMEOUT_S = old
                release.set()

    def test_a_helper_that_raises_or_returns_rubbish_leaves_the_pass_whole(self):
        def boom():
            raise RuntimeError("plaza down")
        with tempfile.TemporaryDirectory() as d:
            said = []
            mm = self.maker(d, said, declared_fn=boom, page_fn=lambda: {"not": "a url"})
            done = mm.step(100)
            self.assertNotIn("skipped", done)
            if said:
                self.assertNotIn("{'not'", said[0])

    def test_the_helpers_answer_is_used_when_it_comes_in_time(self):
        with tempfile.TemporaryDirectory() as d:
            said = []
            mm = self.maker(d, said, declared_fn=lambda: [self.PAIR], page_fn=lambda: "https://example.org/plaza")
            self.assertTrue(mm.step(100)["announced"])
            self.assertIn("LAT-03", said[0])
            self.assertTrue(said[0].endswith("https://example.org/plaza/"))


class TheBrokerReportsBeforeTheSlowWork(unittest.TestCase):
    def test_heartbeat_is_written_before_the_book_is_read_and_before_the_side_job(self):
        from bazaar.broker.run import BrokerLoop
        d = Path(tempfile.mkdtemp())
        seen = []

        class Client:
            has_key = True

            def book(self_inner):
                seen.append(("book", json.loads((d / "status.json").read_text())["tick"]))
                return {"offers": [], "bench_offers": []}

        lp = BrokerLoop(Client(), d / "bench", {"session_ticks": 16}, status_file=d / "status.json",
                        state_file=d / "state.json", notices_file=d / "notices.jsonl")

        class Slow:
            venue = "v07"

            def step(self_inner, tick, last_venue_announce=None):
                seen.append(("matchmaker", json.loads((d / "status.json").read_text())["tick"]))
                return {}
        lp.matchmaker = Slow()
        lp.on_tick(300, {"tick_seconds": 15.0})
        self.assertEqual(seen, [("book", 300), ("matchmaker", 300)])


class TheBrokerSurvivesTheGame(unittest.TestCase):
    def test_a_failed_book_read_is_logged_and_the_next_tick_plays(self):
        from bazaar.broker.run import BrokerLoop
        from bazaar.gateway import GameError
        d = Path(tempfile.mkdtemp())

        class Client:
            has_key = True
            fail = True

            def clock(self):
                return {"tick": self.tick, "t_hours": 17.0, "tick_seconds": 15.0, "doors": "open"}

            def schedule(self):
                return {"upcoming": []}

            def book(self):
                if self.fail:
                    raise GameError("upstream", "game is slow")
                return {"offers": [], "bench_offers": []}

            def me(self):
                return {}

            def feed(self):
                return {"events": []}

        c = Client()
        lp = BrokerLoop(c, d / "bench", {"session_ticks": 16}, status_file=d / "status.json",
                        state_file=d / "state.json", notices_file=d / "notices.jsonl")
        c.tick = 400
        lp.poll()
        self.assertEqual(lp.errors[-1]["where"], "book")
        self.assertEqual(json.loads((d / "status.json").read_text())["tick"], 400)      # still reporting
        c.fail, c.tick = False, 401
        n = len(lp.errors)
        lp.poll()
        self.assertEqual(len(lp.errors), n)
        self.assertEqual(json.loads((d / "status.json").read_text())["tick"], 401)


class TheBrokerStartsWithoutThePlaza(unittest.TestCase):
    def test_a_plaza_that_does_not_import_leaves_the_broker_with_no_helpers(self):
        import sys
        from unittest import mock
        import bazaar.plaza as pkg
        from bazaar.broker import run
        had = pkg.__dict__.pop("server", None)              # `from pkg import server` would find it there first
        try:
            with mock.patch.dict(sys.modules, {"bazaar.plaza.server": None}), mock.patch("builtins.print"):
                self.assertEqual(run.plaza_helpers(), (None, None))
        finally:
            if had is not None:
                pkg.server = had

    def test_with_the_plaza_in_place_the_helpers_answer(self):
        from bazaar.broker import run
        page, declared = run.plaza_helpers()
        self.assertTrue(callable(page) and callable(declared))
        self.assertIsInstance(declared(), list)
