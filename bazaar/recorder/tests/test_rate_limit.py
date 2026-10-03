"""The game's 60 requests/s limit is per address (shared at the venue): a squeeze, not an outage."""
import unittest
from unittest import mock

from bazaar.api.overview import alert_source
from bazaar.gateway import GameError, Gateway
from bazaar.recorder.client import RATE_LIMIT_OUTAGE_AFTER, Lane


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def limited(*a, **k):
    raise GameError("rate_limited", "at most 60 requests per second", 429)


class LaneRateLimitTest(unittest.TestCase):
    def lane(self, fetch):
        c = Clock()
        lane = Lane("public", "http://x", 1000, burst=1000, fetch=fetch, now=c, wall=c)
        lane.rand = lambda: 0.5
        return lane, c

    def test_one_rate_limit_backs_off_but_is_not_an_outage(self):
        lane, c = self.lane(limited)
        with self.assertRaises(GameError):
            lane.get("/api/clock")
        self.assertIsNone(lane.down_since)                      # the lane stays "up"
        self.assertEqual(lane.limited_recently(), 1)
        wait = lane.paused_until - c.t
        self.assertTrue(1.5 <= wait <= 3.0, wait)               # short, jittered
        self.assertFalse(lane.available())
        c.t += 3.1
        self.assertTrue(lane.available())

    def test_backoff_grows_and_persistent_limit_becomes_an_outage(self):
        lane, c = self.lane(limited)
        waits = []
        for _ in range(RATE_LIMIT_OUTAGE_AFTER):
            with self.assertRaises(GameError):
                lane.get("/api/clock")
            waits.append(lane.paused_until - c.t)
            c.t = lane.paused_until
        self.assertTrue(all(b >= a for a, b in zip(waits, waits[1:])))
        self.assertLessEqual(max(waits), 40.0)
        self.assertIsNotNone(lane.down_since)

    def test_success_clears_the_run_and_window_expires(self):
        calls = {"n": 0}

        def fetch(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                limited()
            return {"ok": True}
        lane, c = self.lane(fetch)
        with self.assertRaises(GameError):
            lane.get("/api/clock")
        c.t += 5
        self.assertEqual(lane.get("/api/clock"), {"ok": True})
        self.assertEqual(lane.limited_run, 0)
        self.assertEqual(lane.status()["limited_90s"], 1)
        c.t += 120
        self.assertEqual(lane.limited_recently(), 0)


class GatewayRetryTest(unittest.TestCase):
    def test_rate_limited_read_is_retried_with_spacing(self):
        g = Gateway(url="http://x", token="t")
        seq = [GameError("rate_limited", "at most 60 requests per second", 429),
               GameError("rate_limited", "at most 60 requests per second", 429), {"tick": 1}]

        def req(*a, **k):
            x = seq.pop(0)
            if isinstance(x, Exception):
                raise x
            return x
        with mock.patch.object(g, "_request", side_effect=req), mock.patch("bazaar.gateway.time.sleep") as sl:
            self.assertEqual(g.get("/api/clock"), {"tick": 1})
        self.assertEqual(sl.call_count, 2)
        self.assertTrue(all(0.3 <= c.args[0] <= 1.9 for c in sl.call_args_list))

    def test_gives_up_after_the_retries(self):
        g = Gateway(url="http://x", token="t")
        with mock.patch.object(g, "_request", side_effect=GameError("rate_limited", "x", 429)), \
                mock.patch("bazaar.gateway.time.sleep"):
            with self.assertRaises(GameError):
                g.get("/api/clock")


class AlertSourceTest(unittest.TestCase):
    def test_game_limit_is_not_an_llm_problem(self):
        self.assertEqual(alert_source("clock", "rate_limited: at most 60 requests per second"), "game")
        self.assertEqual(alert_source("lectura", '{"path": "/api/venues/rastro/offers", "error": "rate_limited"}'), "game")

    def test_llm_errors(self):
        self.assertEqual(alert_source("duels", "LLMUnavailable: strategy: Error code: 529 overloaded"), "llm")
        self.assertEqual(alert_source("breaker", "You have reached your specified API usage limits"), "llm")

    def test_other(self):
        self.assertEqual(alert_source("lab", "KeyError: x"), "")


if __name__ == "__main__":
    unittest.main()
