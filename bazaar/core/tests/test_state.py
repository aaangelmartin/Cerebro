import json
import tempfile
import time
import unittest
from pathlib import Path

from bazaar import config
from bazaar.core import state
from bazaar.core.context import Budget, TickContext
from bazaar.core.tests.coreb_fakes import FakeError, FakeGateway, clock
from bazaar.core.types import Action


def ev(i, typ="thread.message", tick=10):
    return {"id": i, "tick": tick, "type": typ, "scope": "public", "actor": "", "payload": {}}


class PerceiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_tick_reads_everything_and_deadline(self):
        gw = FakeGateway({"/api/feed": {"events": [ev(1), ev(2)]}})
        t0 = 1000.0
        sit = state.perceive(gw, None, live=self.live, now=t0)
        self.assertEqual(sit.tick, 10)
        # 30 s tick, 20 s to the next one -> started 10 s ago; deadline at 55 %.
        self.assertAlmostEqual(sit.tick_start, 990.0)
        self.assertAlmostEqual(sit.deadline, 990.0 + config.DECISION_DEADLINE * 30)
        self.assertEqual(sit.dealers[0]["id"], "abuela")
        self.assertEqual(len(sit.feed_new), 2)
        self.assertIn(("/api/feed", {"limit": 500}), gw.calls)
        self.assertIn(("/api/me/threads", {"status": "open"}), gw.calls)
        self.assertEqual(sit.requests, 12)
        rows = (self.live / "events.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(r)["id"] for r in rows], [1, 2])
        self.assertTrue((self.live / "leaderboard.jsonl").exists())
        self.assertEqual(sit.novelty, [])             # first sight is the baseline, not news

    def test_fast_ticks_use_few_requests_and_dedupe_feed(self):
        feed = {"events": [ev(1), ev(2)]}
        gw = FakeGateway({"/api/feed": lambda p, q: feed})
        s1 = state.perceive(gw, None, live=self.live)
        gw.calls.clear()
        feed["events"] = [ev(2), ev(3)]
        gw.routes["/api/clock"] = clock(tick=11)
        s2 = state.perceive(gw, s1, live=self.live)
        self.assertEqual(len(gw.calls), 6)
        self.assertEqual([e["id"] for e in s2.feed_new], [3])
        self.assertEqual(s2.dealers, s1.dealers)       # carried from the slow read
        ids = [json.loads(r)["id"] for r in (self.live / "events.jsonl").read_text().splitlines()]
        self.assertEqual(ids, [1, 2, 3])

    def test_feed_gap_and_new_event_type_are_novelty(self):
        feed = {"events": [ev(1)]}
        gw = FakeGateway({"/api/feed": lambda p, q: feed})
        s1 = state.perceive(gw, None, live=self.live)
        feed["events"] = [ev(5, "totally.new")]
        gw.routes["/api/clock"] = clock(tick=11)
        s2 = state.perceive(gw, s1, live=self.live)
        kinds = {n["kind"] for n in s2.novelty}
        self.assertIn("feed_gap", kinds)
        self.assertIn("event_type", kinds)
        self.assertTrue((self.live / "novelty.jsonl").read_text())

    def test_limits_levels_dealers_schedule_changes(self):
        gw = FakeGateway()
        s1 = state.perceive(gw, None, live=self.live)
        gw.routes["/api/clock"] = clock(tick=11, limits={"accepts_per_team_per_tick": 2})
        gw.routes["/api/levels"] = {"levels": [{"id": "chato", "state": "active"}, {"id": "vault", "state": "announced"}]}
        gw.routes["/api/dealers"] = {"personas": [{"id": "abuela", "status": "active", "menu": {"sells": [1]}}]}
        gw.routes["/api/schedule"] = {"upcoming": [{"at_hours": 5.0, "action": "bench", "params": {}},
                                                   {"at_hours": 6.0, "action": "duels", "params": {}}]}
        gw.routes["/api/feed"] = {"events": [ev(3, "level.announced")]}   # forces the slow read
        s2 = state.perceive(gw, s1, live=self.live)
        kinds = [n["kind"] for n in s2.novelty]
        for k in ("limits", "level", "dealer_menu", "schedule"):
            self.assertIn(k, kinds)

    def test_closed_thread_fetched_and_read_errors_tolerated(self):
        gw = FakeGateway({"/api/me/threads": {"threads": [{"id": 7, "status": "open", "messages": []}]}})
        s1 = state.perceive(gw, None, live=self.live)
        gw.routes["/api/me/threads"] = {"threads": []}
        gw.routes["/api/threads/*"] = {"id": 7, "status": "deal"}
        gw.routes["/api/duels"] = FakeError("rate_limited")
        gw.routes["/api/clock"] = clock(tick=11)
        s2 = state.perceive(gw, s1, live=self.live)
        self.assertEqual(s2.closed_threads[0]["status"], "deal")
        self.assertEqual(s2.errors[0]["error"], "rate_limited")

    def test_error_codes_from_ledger(self):
        gw = FakeGateway()
        s1 = state.perceive(gw, None, live=self.live)
        with (self.live / "outcomes.jsonl").open("a") as f:
            f.write(json.dumps({"status": "refused", "response": {"error": "weird_new_code"}}) + "\n")
        gw.routes["/api/clock"] = clock(tick=11)
        s2 = state.perceive(gw, s1, live=self.live)
        self.assertIn("weird_new_code", [n["detail"].get("code") for n in s2.novelty if n["kind"] == "error_code"])

    def test_paused_deadline_from_now(self):
        gw = FakeGateway({"/api/clock": clock(paused=True, doors="closed")})
        sit = state.perceive(gw, None, live=self.live, now=500.0)
        self.assertAlmostEqual(sit.deadline, 500.0 + config.DECISION_DEADLINE * 30)

    def test_bad_countdown_starts_the_tick_now(self):
        # None, 0, negative, non-numeric, NaN or longer than the tick: never an already-passed deadline.
        for nti in (None, 0, -3, "soon", float("nan"), 45.0, True):
            gw = FakeGateway({"/api/clock": clock(next_tick_in=nti)})
            sit = state.perceive(gw, None, live=self.live, now=500.0)
            self.assertAlmostEqual(sit.tick_start, 500.0, msg=repr(nti))
            self.assertAlmostEqual(sit.deadline, 500.0 + config.DECISION_DEADLINE * 30, msg=repr(nti))
        gw = FakeGateway({"/api/clock": clock(next_tick_in=30.0)})      # exactly at the start: still valid
        self.assertAlmostEqual(state.perceive(gw, None, live=self.live, now=500.0).tick_start, 500.0)
        gw = FakeGateway({"/api/clock": {**clock(), "next_tick_in": "20", "tick_seconds": "bad"}})  # -> 30 s
        sit = state.perceive(gw, None, live=self.live, now=500.0)
        self.assertEqual(sit.tick_seconds, 30.0)
        self.assertAlmostEqual(sit.tick_start, 490.0)


class BudgetTest(unittest.TestCase):
    def test_counts_reset_per_tick_and_spend_rolls(self):
        with tempfile.TemporaryDirectory() as d:
            b = Budget(Path(d) / "b.json")
            bt = b.for_tick(1, {"accepts_per_team_per_tick": 1})
            self.assertEqual(bt["accepts_left"], 1)
            a = Action("accept_offer", {"offer": 1, "expect": {"maker": "abuela", "want": {"cash": 30}}}, "dealers")
            b.record(a, "sent", now=100.0)
            m = Action("thread_message", {"thread": 4, "price": 3}, "dealers")
            b.record(m, "sent", now=100.0)
            bt = b.for_tick(1, {"accepts_per_team_per_tick": 1}, now=101.0)
            self.assertEqual(bt["accepts_left"], 0)
            self.assertEqual(bt["messages"], {"thread:4": 1})
            self.assertEqual(bt["spend_hour"], 30)
            self.assertEqual(bt["deals_by_team_hour"], {"abuela": 1})
            b.save()
            b2 = Budget(Path(d) / "b.json")
            bt = b2.for_tick(2, {}, now=101.0 + 3600)
            self.assertEqual((bt["accepts_left"], bt["spend_hour"]), (1, 0))

    def test_context_deadline(self):
        ctx = TickContext(tick=1, day="sat", deadline=time.time() + 5)
        self.assertFalse(ctx.expired())
        self.assertTrue(ctx.with_deadline(time.time() - 1).expired())


if __name__ == "__main__":
    unittest.main()
