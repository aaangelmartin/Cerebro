import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

from bazaar import supervise

SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]
CRASH = [sys.executable, "-c", "raise SystemExit(3)"]


class SuperviseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name)
        self.clock = [1000.0]

    def tearDown(self):
        self.sup.shutdown()
        self.tmp.cleanup()

    def make(self, services, grace=0.0):
        self.sup = supervise.Supervisor(services, live=self.live, stop_file=self.live / "STOP",
                                        now=lambda: self.clock[0], grace_s=grace)
        return self.sup

    def test_starts_and_restarts_crashed_with_backoff(self):
        s = supervise.Service("x", CRASH)
        sup = self.make([s])
        sup.check()
        s.proc.wait(5)
        sup.check()                                  # notices the exit, schedules a retry
        self.assertIsNone(s.proc)
        self.assertGreater(s.next_try, self.clock[0])
        self.clock[0] = s.next_try + 1
        sup.check()
        self.assertIsNotNone(s.proc)
        self.assertIn("exited with code 3", (self.live / "supervise.log").read_text())

    def test_stop_file_stops_bot_keeps_api(self):
        bot = supervise.Service("bot", SLEEP, obeys_stop=True)
        api = supervise.Service("api", SLEEP)
        sup = self.make([api, bot])
        sup.check()
        self.assertIsNotNone(bot.proc)
        (self.live / "STOP").touch()
        sup.check()
        self.assertIsNone(bot.proc)
        self.assertIsNone(api.proc.poll())

    def test_stale_heartbeat_restarts(self):
        (self.live / "status.json").write_text(json.dumps(
            {"tick_seconds": 30, "doors": "open", "paused": False, "state": "running", "updated": 1000.0}))
        (self.live / "broker_status.json").write_text(json.dumps({"updated": 1000.0}))
        br = supervise.Service("broker", SLEEP, heartbeat="broker_status.json", stale_ticks=2)
        sup = self.make([br])
        sup.check()
        pid = br.proc.pid
        self.clock[0] = 1000.0 + 50
        sup.check()
        self.assertEqual(br.proc.pid, pid)          # 50 s < 2 ticks of 30 s
        self.clock[0] = 1000.0 + 61
        sup.check()                                  # stale: stopped, restart after the backoff
        self.assertIsNone(br.proc)
        self.assertEqual(br.failures, 1)
        self.assertGreater(br.next_try, self.clock[0])
        self.clock[0] = br.next_try
        sup.check()
        self.assertNotEqual(br.proc.pid, pid)

    def test_broker_not_judged_while_closed(self):
        (self.live / "status.json").write_text(json.dumps({"tick_seconds": 30, "doors": "closed", "updated": 0}))
        br = supervise.Service("broker", SLEEP, heartbeat="broker_status.json", stale_ticks=2)
        sup = self.make([br])
        sup.check()
        self.clock[0] += 10_000
        self.assertIsNone(sup.stale(br))


if __name__ == "__main__":
    unittest.main()
