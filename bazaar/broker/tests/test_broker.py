import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from bazaar.broker import engine, sim_book, venue
from bazaar.broker.engine import BenchEngine, estimate_limit, hungarian_max, midpoint_price, public_plan, stall_plan
from bazaar.gateway import GameError


def sell(i, ask, run="b1", **kw):
    return {"id": f"{run}-{i}", "give": {"cash": 0, "assets": [{"kind": "card", "ref": "LAV-02"}], "types": []},
            "want": {"cash": ask, "assets": [], "types": []}, **kw}


def buy(i, bid, run="b1", **kw):
    return {"id": f"{run}-{i}", "give": {"cash": bid, "assets": [], "types": []},
            "want": {"cash": 0, "assets": [], "types": ["card:LAV-02"]}, **kw}


class TestEstimation(unittest.TestCase):
    PROF = engine.DEFAULT_POLICY["profiles"]["normal"]

    def test_geometric_extrapolation_finds_limit(self):
        # seller limit 50, gap halves each tick: 90, 70, 60, 55
        est, st = estimate_limit("sell", [90, 70, 60, 55], 0.2, self.PROF)
        self.assertEqual(st, "geo")
        self.assertAlmostEqual(est, 50, delta=1.5)
        est, st = estimate_limit("buy", [20, 40, 50, 55], 0.2, self.PROF)   # buyer limit 60
        self.assertAlmostEqual(est, 60, delta=1.5)

    def test_static_uses_prior_and_respects_quote_side(self):
        est, st = estimate_limit("sell", [60], 0.2, self.PROF)
        self.assertEqual(st, "static")
        self.assertAlmostEqual(est, 50, delta=0.01)
        est, _ = estimate_limit("buy", [40, 40, 40, 40, 40], 0.2, self.PROF)
        self.assertGreaterEqual(est, 40)

    def test_stopped_means_at_limit(self):
        est, st = estimate_limit("sell", [80, 70, 65, 65, 65], 0.2, self.PROF)
        self.assertEqual(st, "stopped")
        self.assertEqual(est, 65)


class TestMatching(unittest.TestCase):
    def test_hungarian_maximises_weight(self):
        w = [[10, 9], [9, 0]]                # greedy would take (0,0)=10 alone; best is 9+9
        self.assertEqual(sorted(hungarian_max(w)), [(0, 1), (1, 0)])
        self.assertEqual(hungarian_max([[0, 0]]), [])
        self.assertEqual(len(hungarian_max([[5, 1, 2]])), 1)

    def test_midpoint_with_fee(self):
        self.assertEqual(midpoint_price(10, 20), 15)
        self.assertEqual(midpoint_price(10, 20, fee_bps=0, fee_per_card=5), 15)
        self.assertIsNone(midpoint_price(10, 12, fee_per_card=5))

    def test_stall_plan_matches_sdk(self):
        book = [sell(1, 30), sell(2, 50), buy(3, 60), buy(4, 40)]
        plan = stall_plan(book)
        self.assertEqual([(m.sell, m.buy, m.price) for m in plan], [("b1-1", "b1-3", 45)])

    def test_runs_never_mix(self):
        eng = BenchEngine({"cross_rule": "quotes"})
        eng.observe(0, [sell(1, 10, "b1"), buy(1, 90, "b2")])
        self.assertEqual(eng.plan(0), [])

    def test_engine_matches_intramarginal_pair_immediately(self):
        eng = BenchEngine({"cross_rule": "quotes"})
        eng.observe(0, [sell(1, 20), buy(2, 80), sell(3, 95), buy(4, 15)])
        plan = eng.plan(0)
        self.assertEqual([(m.sell, m.buy) for m in plan], [("b1-1", "b1-2")])
        self.assertTrue(20 <= plan[0].price <= 80)

    def test_engine_waits_on_extramarginal_then_matches_in_endgame(self):
        # strong buyer b1-2 relaxes 20 -> 50 -> 65 (limit ~80); weak b1-4 sits at 66 (limit ~69 with a 5 % prior).
        # A lone seller asking 66 appears at tick 2: only the weak buyer crosses, and we must wait for the strong one.
        pol = {"cross_rule": "quotes", "session_ticks": 16, "profiles": {"normal": {"prior_shade": 0.05}}}
        eng = BenchEngine(pol, profile="normal")
        eng.observe(0, [buy(2, 20, created_tick=0), buy(4, 66)])
        eng.observe(1, [buy(2, 50), buy(4, 66)])
        eng.observe(2, [sell(1, 66), buy(2, 65), buy(4, 66)])
        self.assertEqual(eng.plan(2), [])
        eng.observe(3, [sell(1, 66), buy(2, 72), buy(4, 66)])
        self.assertEqual([(m.sell, m.buy) for m in eng.plan(3)], [("b1-1", "b1-2")])
        eng2 = BenchEngine({"cross_rule": "quotes", "session_ticks": 16})
        eng2.observe(0, [sell(1, 50, created_tick=0), buy(4, 50)])
        eng2.observe(15, [sell(1, 50), buy(4, 50)])
        self.assertEqual(len(eng2.plan(15)), 1)   # last tick: every crossing pair

    def test_probe_learns_rule(self):
        eng = BenchEngine({"cross_rule": "probe", "probe_after": 0, "max_probes": 5, "probe_refusals": 2})
        for t, (a, b) in enumerate([(90, 20), (70, 40), (60, 50), (55, 54)]):   # limits ~50 and ~58, never cross
            eng.observe(t, [sell(1, a, created_tick=0), buy(2, b)])
        plan = eng.plan(3)
        self.assertEqual([m.kind for m in plan], ["probe"])
        self.assertTrue(54 <= plan[0].price <= 55)
        eng.note_matched(plan[0].sell, plan[0].buy, 5, "probe")
        self.assertEqual(eng.rule, "limits")
        eng2 = BenchEngine({"cross_rule": "probe", "probe_refusals": 2})
        m = engine.Match("b1-1", "b1-2", 50, "b1", kind="probe")
        eng2.note_refused(m, "price_outside")
        eng2.note_refused(engine.Match("b1-3", "b1-4", 50, "b1", kind="probe"), "price_outside")
        self.assertEqual(eng2.rule, "quotes")

    def test_public_plan_any_copy_and_own_maker(self):
        book = {"fee_bps": 0, "fee_per_card": 0, "offers": [
            {"id": 1, "maker": "a", "give": {"cash": 0, "assets": [{"id": 9, "kind": "card", "ref": "LAV-03"}]},
             "want": {"cash": 30, "assets": [], "types": []}},
            {"id": 2, "maker": "a", "give": {"cash": 50, "assets": []}, "want": {"cash": 0, "types": ["card:LAV-03"]}},
            {"id": 3, "maker": "b", "give": {"cash": 40, "assets": []}, "want": {"cash": 0, "types": ["card:LAV-03"]}},
            {"id": 4, "maker": "c", "give": {"cash": 99, "assets": []}, "want": {"cash": 0, "types": ["card:MAL-01"]}},
        ]}
        plan = public_plan(book)
        self.assertEqual([(m.sell, m.buy, m.price) for m in plan], [(1, 3, 35)])


class TestSim(unittest.TestCase):
    def test_generator_and_evaluator(self):
        s = sim_book.SimSession.generate(3)
        self.assertEqual(len(s.traders), 10)
        self.assertGreaterEqual(s.max_gain(), 0)
        self.assertEqual(len(sim_book.SimSession.generate(3, hard=True).traders), 12)
        eff = sim_book.play(s, sim_book.stall_planner())
        self.assertTrue(0 <= eff <= 1.0 + 1e-9)

    def test_engine_not_worse_than_stall_on_average(self):
        for hard in (False, True):
            r = sim_book.benchmark(60, hard, start=777)
            self.assertGreaterEqual(r["engine"], r["stall"] - 0.005, r)

    def test_limits_rule_refuses_outside_limits(self):
        s = sim_book.SimSession.generate(5, cross_rule="limits")
        sl = next(t for t in s.traders if t.side == "sell")
        bl = next(t for t in s.traders if t.side == "buy" and t.limit > sl.limit)
        t = max(sl.arrive, bl.arrive)
        if sl.present(t) and bl.present(t):
            self.assertIn("error", s.match(t, sl.id, bl.id, bl.limit + 1))


class TestRunLoop(unittest.TestCase):
    def test_sim_loop_records_and_beats_or_ties_stall(self):
        with tempfile.TemporaryDirectory() as d:
            from bazaar.broker import run
            res = run.run_sim(sessions=2, seed=11, out_dir=Path(d) / "bench")
            self.assertEqual(res["errors"], [])
            files = sorted(p.name for p in (Path(d) / "bench").glob("*.jsonl"))
            self.assertIn("results.jsonl", files)
            st = json.loads((Path(d) / "broker_status.json").read_text())
            self.assertIn("matches_total", st)

    def test_engine_exception_falls_back_to_stall(self):
        from bazaar.broker import run
        with tempfile.TemporaryDirectory() as d:
            client = sim_book.SimClient(seed=1, sessions=1)
            loop = run.BrokerLoop(client, Path(d) / "bench", engine.merge_policy(None))
            with mock.patch.object(loop.engine, "plan", side_effect=RuntimeError("boom")):
                for _ in range(client.end_tick):
                    loop.poll()
                    client.advance()
            ref = sim_book.SimSession.generate(1, run="b1")
            self.assertAlmostEqual(client.sessions[0][1].efficiency(), sim_book.play(ref, sim_book.stall_planner()))
            self.assertTrue(any(e["where"] == "engine" for e in loop.errors))

    def test_blocked_writes_send_nothing(self):
        from bazaar.broker import run
        with tempfile.TemporaryDirectory() as d:
            client = sim_book.SimClient(seed=2, sessions=1)
            loop = run.BrokerLoop(client, Path(d) / "bench", writes_allowed=lambda: (False, "test"))
            for _ in range(client.end_tick):
                loop.poll()
                client.advance()
            self.assertEqual(client.sessions[0][1].matches, [])

    def test_live_writes_need_allow_real(self):
        from bazaar.broker import run
        with mock.patch.object(run.config, "ALLOW_REAL", False):
            self.assertFalse(run.live_writes_allowed()[0])


class TestVenue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(venue, "BROKER_FILE", Path(self.tmp.name) / "broker.json")
        self.patch.start()
        self.env = mock.patch.dict(venue.config.ENV, {"BAZAAR_BROKER_KEY": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def test_save_key_private_and_redacted(self):
        rec = venue.save_from_response({"venue": "v09", "name": "x", "broker_key": "bk_secret"})
        self.assertEqual(rec["broker_key"], "<redacted>")
        self.assertEqual(venue.load_key(), "bk_secret")
        mode = stat.S_IMODE(os.stat(venue.BROKER_FILE).st_mode)
        self.assertEqual(mode, 0o600)

    def test_open_venue_is_idempotent(self):
        gw = mock.Mock()
        gw.get.return_value = {"venue": "v07", "cash": 500}
        out = venue.open_venue(gw)
        self.assertTrue(out["reused"])
        gw.post.assert_not_called()

    def test_open_venue_posts_board_fee_zero(self):
        gw = mock.Mock()
        gw.get.return_value = {"venue": None, "cash": 500}
        gw.post.return_value = {"venue": "v08", "broker_key": "bk_x"}
        out = venue.open_venue(gw)
        path, body = gw.post.call_args[0]
        self.assertEqual(path, "/api/venues")
        self.assertEqual(body["rules"], {"mechanism": "board"})
        self.assertEqual((body["fee_bps"], body["fee_per_card"]), (0, 0))
        self.assertEqual(out, {"venue": "v08", "reused": False, "has_key": True})
        self.assertNotIn("bk_x", json.dumps(out))

    def test_should_open(self):
        me = {"cash": 400, "level": 2, "venue": None}
        sit = SimpleNamespace(t_hours=4.06, doors="open", paused=False, me=me)
        self.assertTrue(venue.should_open(sit, reserve=40))
        self.assertFalse(venue.should_open(SimpleNamespace(**{**sit.__dict__, "t_hours": 4.0}), reserve=40))
        self.assertFalse(venue.should_open(SimpleNamespace(**{**sit.__dict__, "me": {**me, "cash": 300}}), reserve=40))
        self.assertFalse(venue.should_open(SimpleNamespace(**{**sit.__dict__, "me": {**me, "venue": "v1"}}), reserve=40))
        a = venue.open_action(sit)
        self.assertEqual(a.kind, "venue_open")
        self.assertEqual(a.params["mechanism"], "board")

    def test_announce_uses_broker_key(self):
        venue.save_from_response({"venue": "v1", "broker_key": "bk_y"})
        gw = mock.Mock()
        venue.announce(gw, "hola")
        self.assertEqual(gw.post.call_args.kwargs["broker_key"], "bk_y")


class TestTune(unittest.TestCase):
    def test_fit_and_replay_from_recorded_sim(self):
        from bazaar.broker import run, tune
        with tempfile.TemporaryDirectory() as d:
            run.run_sim(sessions=3, seed=4, out_dir=Path(d) / "bench")
            sessions = tune.load_sessions([Path(d) / "bench"])
            self.assertEqual(len(sessions), 3)
            p = tune.fit_params(sessions)
            self.assertEqual(p["_evidence"]["sessions"], 3)
            r = tune.replay(next(iter(sessions.values())))
            self.assertGreater(r["ticks"], 0)


if __name__ == "__main__":
    unittest.main()
