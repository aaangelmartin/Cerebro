"""Each round scores from zero and the rounds are averaged: the win math counts the round in play only, and the
hourly review follows the game hour (30 real minutes on Sunday's 15 s ticks)."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from bazaar.strategist import brainio as B
from bazaar.strategist import run as srun
from bazaar.strategist import winmath as W


def _pt(tick, ts, neg, duel_p, comp_neg, mm=1.0):
    return {"ts": ts, "tick": tick, "negotiating": comp_neg, "market": 12.5, "neg_points": neg, "duel_points": duel_p,
            "ladder_points": 0.3, "bench_points": 0.5, "mm_points": mm}


class RoundTest(unittest.TestCase):
    CLOCK = {"t_hours": 16.8, "tick_seconds": 15.0, "round": 3, "round_name": "Sunday · Chamberí", "today": "sun"}
    SCHED = {"upcoming": [{"at_hours": 18.65, "action": "duels"},
                          {"at_hours": 20.072, "action": "day_closes", "params": {"day": "sun"}},
                          {"at_hours": 22.65, "action": "end_round"}]}
    LB = {"round": 3, "rounds": [{"round": 1, "name": "Friday", "weight": 0.5, "status": "closed"},
                                 {"round": 2, "name": "Saturday", "weight": 1.0, "status": "closed"},
                                 {"round": 3, "name": "Sunday · Chamberí", "weight": 1.0, "status": "active"}],
          "teams": [{"team": "t06", "score": 4.0, "negotiating": 2.0, "market": 2.0},
                    {"team": "t10", "score": 3.0, "negotiating": 1.0, "market": 2.0}]}

    def test_points_before_the_restart_are_dropped(self):
        pts = [_pt(1900, 10.0, 99.6, 9.9, 21.5), _pt(1950, 20.0, 104.0, 9.9, 21.8),
               _pt(2010, 30.0, 0.0, 0.0, 0.0, mm=0.0), _pt(2020, 40.0, 4.0, 0.0, 0.3, mm=0.0)]
        cur, start = W.round_points(pts)
        self.assertEqual([p["tick"] for p in cur], [2010, 2020])
        self.assertEqual(start["tick"], 2010)
        self.assertGreater(start["raw_before"], 100)
        conv = W.conversions(cur)                                        # Saturday's ratios do not leak in
        self.assertEqual(conv["neg_points"], {"points_per_unit": 0.075, "samples": 1, "basis": "measured"})

    def test_no_restart_keeps_every_point(self):
        pts = [_pt(1, 10.0, 10.0, 1.0, 10.0), _pt(2, 20.0, 12.0, 1.0, 10.2), _pt(3, 30.0, 11.5, 1.0, 10.2)]
        cur, start = W.round_points(pts)
        self.assertEqual(len(cur), 3)
        self.assertIsNone(start)

    def test_round_info_and_pace_to_the_end_of_the_round(self):
        info = W.round_info(self.CLOCK, self.SCHED, self.LB, {"tick": 2010, "ts": 100.0}, now=700.0)
        self.assertEqual((info["round"], info["weight"]), (3, 1.0))
        self.assertEqual(info["hours_left_in_round"], 5.85)              # to "Scores freeze", past the day's close
        self.assertEqual(info["game_hour_real_minutes"], 60.0)              # t_hours follows the wall clock
        self.assertEqual(info["ticks_per_game_hour"], 240)
        self.assertEqual(info["started_minutes_ago"], 10.0)
        self.assertEqual([r["round"] for r in info["closed_rounds"]], [1, 2])

    def test_next_round_is_announced_while_the_old_one_runs(self):
        clock = {"t_hours": 15.0, "tick_seconds": 15.0, "round": 2, "round_name": "Saturday · Gran Vía"}
        sched = {"upcoming": [{"at_hours": 16.65, "action": "round", "params": {"name": "Sunday · Chamberí", "weight": 1}},
                              {"at_hours": 22.65, "action": "end_round"}]}
        info = W.round_info(clock, sched, {"round": 2, "rounds": []})
        self.assertEqual(info["hours_left_in_round"], 1.65)
        self.assertEqual(info["next_round"]["name"], "Sunday · Chamberí")

    def test_build_reports_the_round_and_uses_its_hours(self):
        with tempfile.TemporaryDirectory() as d:
            rec = Path(d) / "record" / "latest"
            (rec.parent / "me").mkdir(parents=True)
            rec.mkdir()
            now = time.time()
            day = time.strftime("%Y-%m-%d", time.localtime(now))
            rows = [{"ts": now - 900, "tick": 1950, "data": {"score": {"negotiating": 21.8, "market": 12.5,
                                                                        "neg_points": 104.0, "duel_points": 9.9}}},
                    {"ts": now - 600, "tick": 2010, "data": {"score": {"negotiating": 0.0, "market": 0.0,
                                                                        "neg_points": 0.0, "duel_points": 0.0}}},
                    {"ts": now - 60, "tick": 2040, "data": {"score": {"negotiating": 1.0, "market": 2.0,
                                                                       "neg_points": 8.0, "duel_points": 0.0}}}]
            (rec.parent / "me" / f"{day}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
            win = W.build(record=rec, me={"cash": 150, "score": {"neg_points": 8.0}}, leaderboard=self.LB,
                          clock=self.CLOCK, schedule=self.SCHED, now=now)
        self.assertEqual(win["round"]["started"]["tick"], 2010)
        self.assertIn("round", win["mission"])
        n = win["components"]["negotiating"]                             # gap 1.0 over the 5.85 h left in the round
        self.assertEqual(n["required_per_hour"], round(1.0 / 5.85, 2))
        text = B.win_text(win)
        self.assertIn("round 3", text)
        self.assertIn("60 real minutes (240 ticks of 15 s)", text)
        self.assertIn("this round only", text)


class ReviewTest(unittest.TestCase):
    def test_review_follows_the_game_hour(self):
        self.assertEqual(srun.review_every_s({"tick_seconds": 30.0}), 3600.0)
        self.assertEqual(srun.review_every_s({"tick_seconds": 15.0}), 3600.0)     # 240 ticks of 15 s
        self.assertEqual(srun.review_every_s({"tick_seconds": 60.0}), 3600.0)
        self.assertEqual(srun.review_every_s({"tick_seconds": 5.0}), 3600.0)
        self.assertEqual(srun.review_every_s({}), 3600.0)
        self.assertEqual(srun.review_every_s(None), 3600.0)

    def test_no_comparison_across_a_round_restart(self):
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            now = 10_000.0
            plan = {"updated": now - 1800, "tick": 1950, "plan": {"expected_next_hour": {"score_delta": 0.5}},
                    "score_at_plan": {"score": 34.0, "negotiating": 21.5, "market": 12.5}}
            (live / "strategy.jsonl").write_text(json.dumps(plan) + "\n")
            board = {"tick": 2040, "us_now": {"score": 3.0, "negotiating": 1.0, "market": 2.0}}
            win = {"round": {"started": {"tick": 2010, "ts": now - 600}}, "components": {}}
            row = B.hourly_review(live, board, now, window_s=1800, win=win)
            self.assertTrue(row["round_restarted"])
            self.assertEqual(row["realised"], {})
            self.assertIn("new round", row["verdict"])
            same = B.hourly_review(live, board, now, window_s=1800, win={"round": {}, "components": {}})
            self.assertEqual(same["realised"]["score"], -31.0)           # without the restart it compares as before


if __name__ == "__main__":
    unittest.main()
