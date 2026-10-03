"""Operational robustness: singletons, signals, supervisor counters, gateway_down, stuck domains, broker pacing."""
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from bazaar import config, run, supervise
from bazaar.broker import run as broker_run
from bazaar.core.tests.coreb_fakes import clock
from bazaar.tests.test_run import Dom, Exe, Led, rails_ok, sit_at

REPO = Path(__file__).resolve().parents[2]
SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]
# Child processes that must never reach the real game: closed port, no real writes.
SAFE_ENV = {"BAZAAR_GATEWAY_URL": "http://127.0.0.1:9", "BAZAAR_ALLOW_REAL": "0"}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class SingletonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.live = self.data / "live"

    def tearDown(self):
        for n in ("t-one", "run-live", "broker"):
            supervise.release(n)
        self.tmp.cleanup()

    def test_second_holder_refused(self):
        p = supervise.singleton("t-one", self.live)
        self.assertEqual(p.read_text(), str(os.getpid()))
        with self.assertRaises(supervise.AlreadyRunning) as cm:
            supervise.singleton("t-one", self.live)
        self.assertIn(f"pid {os.getpid()}", str(cm.exception))
        supervise.release("t-one")
        supervise.singleton("t-one", self.live)          # free again once released

    def _second(self, args):
        env = {**os.environ, **SAFE_ENV, "BAZAAR_DATA_DIR": str(self.data)}
        return subprocess.run([sys.executable, "-m", *args], cwd=REPO, env=env, capture_output=True, text=True,
                              timeout=60)

    def test_second_live_bot_and_broker_refuse_to_start(self):
        supervise.singleton("run-live", self.live)
        supervise.singleton("broker", self.live)
        r = self._second(["bazaar.run", "--live", "--once"])
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("already running", r.stderr)
        r = self._second(["bazaar.broker.run"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already running", r.stderr)


class SignalTest(unittest.TestCase):
    def test_sigterm_and_sighup_stop_children(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with tempfile.TemporaryDirectory() as d:
                script = textwrap.dedent(f"""
                    import sys
                    from pathlib import Path
                    from bazaar import supervise
                    live = Path({d!r})
                    sup = supervise.Supervisor([supervise.Service("child", {SLEEP!r})], live=live,
                                               stop_file=live / "STOP")
                    supervise.serve(sup, every=0.2)
                """)
                env = {**os.environ, **SAFE_ENV, "BAZAAR_DATA_DIR": d}
                p = subprocess.Popen([sys.executable, "-c", script], cwd=REPO, env=env)
                logf = Path(d) / "supervise.log"
                child = None
                for _ in range(100):
                    m = re.search(r"started child \(pid (\d+)\)", logf.read_text() if logf.exists() else "")
                    if m:
                        child = int(m.group(1))
                        break
                    time.sleep(0.1)
                self.assertIsNotNone(child)
                self.assertTrue(_alive(child))
                p.send_signal(sig)
                self.assertEqual(p.wait(20), 0)
                for _ in range(50):
                    if not _alive(child):
                        break
                    time.sleep(0.1)
                self.assertFalse(_alive(child), f"child survived {sig!r}")
                self.assertIn("stopping child: supervisor exiting", logf.read_text())


class SupervisorCountersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name)
        self.clock = [1000.0]
        self.sup = None

    def tearDown(self):
        if self.sup:
            self.sup.shutdown()
        self.tmp.cleanup()

    def make(self, services):
        self.sup = supervise.Supervisor(services, live=self.live, stop_file=self.live / "STOP",
                                        now=lambda: self.clock[0], grace_s=0.0)
        return self.sup

    def test_failures_reset_after_ten_healthy_minutes(self):
        s = supervise.Service("api", SLEEP)
        sup = self.make([s])
        sup.check()
        s.failures = 5
        self.clock[0] += 300
        sup.check()
        self.assertEqual(s.failures, 5)
        self.clock[0] += supervise.HEALTHY_RESET_S
        sup.check()
        self.assertEqual(s.failures, 0)

    def test_gateway_down_is_not_stale(self):
        st = {"tick_seconds": 30, "doors": "open", "paused": False, "state": "gateway_down", "updated": 1000.0}
        (self.live / "status.json").write_text(json.dumps(st))
        bot = supervise.Service("bot", SLEEP, heartbeat="status.json", stale_ticks=3)
        sup = self.make([bot])
        sup.check()
        self.clock[0] = 1000.0 + 200                    # > 3 ticks and > 60 s, but the bot says gateway_down
        self.assertIsNone(sup.stale(bot))
        self.clock[0] = 1000.0 + supervise.GATEWAY_DOWN_MAX_S + 1
        self.assertIn("gateway_down", sup.stale(bot) or "")


class _SeqGW:
    """GET /api/clock answers from a list (Exception items are raised)."""

    def __init__(self, seq):
        self.seq = list(seq)

    def get(self, path, **params):
        item = self.seq.pop(0) if len(self.seq) > 1 else self.seq[0]
        if isinstance(item, Exception):
            raise item
        return item


class RunnerRobustnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name)
        self.stop = mock.patch.object(config, "STOP_FILE", self.live / "STOP")
        self.stop.start()

    def tearDown(self):
        self.stop.stop()
        self.tmp.cleanup()

    def runner(self, gw, domains=()):
        return run.Runner(gw, domains=list(domains), mode="sim", live=self.live, make_write_gw=lambda: "W",
                          ledger=Led(), rails=rails_ok(), executor=Exe())

    def test_gateway_down_heartbeat_and_bad_countdown(self):
        states = []
        r = self.runner(_SeqGW([ConnectionError("down"), {**clock(tick=4), "next_tick_in": "soon"},
                                {**clock(tick=4), "next_tick_in": None}, clock(tick=5)]))
        r.last_tick = 4
        sleeps = []

        def fake_sleep(s):
            sleeps.append(s)
            if (self.live / "status.json").exists():
                states.append(json.loads((self.live / "status.json").read_text())["state"])

        with mock.patch.object(run.time, "sleep", fake_sleep):
            c, is_open = r.wait_for_tick()
        self.assertEqual((c["tick"], is_open), (5, True))
        self.assertEqual(states[0], "gateway_down")
        self.assertEqual(sleeps[0], run.GATEWAY_RETRY_S)
        self.assertEqual(sleeps[1:], [1.15, 1.15])         # non-numeric/None countdown -> 1 s fallback

    def test_domain_busy_three_ticks_exits(self):
        gate = threading.Event()
        dom = Dom("dealers")
        dom.decide = lambda sit, ctx: gate.wait(30) and []
        r = self.runner(_SeqGW([clock()]), [dom])
        exits = []

        def fake_exit(code):                                # os._exit never returns
            exits.append(code)
            raise SystemExit(code)

        r.exit_fn = fake_exit
        try:
            for t in (5, 6, 7):
                r.step(sit_at(tick=t, seconds=0.2))
            self.assertEqual(exits, [])
            with self.assertRaises(SystemExit):
                r.step(sit_at(tick=8, seconds=0.2))
            self.assertEqual(exits, [run.STUCK_EXIT_CODE])
            self.assertEqual(r.dom_status["dealers"]["state"], "stuck")
            st = json.loads((self.live / "status.json").read_text())
            self.assertEqual(st["domains"]["dealers"]["state"], "stuck")
        finally:
            gate.set()


class BrokerPacingTest(unittest.TestCase):
    def test_next_sleep(self):
        ns = broker_run.next_sleep
        self.assertAlmostEqual(ns({"doors": "open", "next_tick_in": 12.0}), 11.7)
        self.assertEqual(ns({"doors": "open", "next_tick_in": 0.1}), 0.5)
        self.assertAlmostEqual(ns({"doors": "open", "next_tick_in": 12.0}, clock_at=100.0, now=104.0), 7.7)
        self.assertEqual(ns({"doors": "closed", "next_tick_in": 3}), broker_run.CLOSED_SLEEP_S)
        self.assertEqual(ns({"doors": "open", "paused": True}), broker_run.CLOSED_SLEEP_S)
        self.assertTrue(10 <= broker_run.CLOSED_SLEEP_S <= 30)
        self.assertEqual(ns(None), broker_run.ERROR_SLEEP_S)
        self.assertEqual(ns({"doors": "open", "next_tick_in": "x"}), 1.0)
        self.assertEqual(ns({"doors": "open", "next_tick_in": 900}), broker_run.MAX_SLEEP_S)


if __name__ == "__main__":
    unittest.main()
