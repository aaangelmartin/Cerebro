import json
import tempfile
import time
import unittest
from pathlib import Path

from bazaar.strategist import brainio as B
from bazaar.strategist import winmath as W


def _lb(us_neg=16.0, us_mkt=12.0, lead_neg=22.0, lead_mkt=11.0):
    return {"teams": [{"team": "t14", "score": lead_neg + lead_mkt, "negotiating": lead_neg, "market": lead_mkt},
                      {"team": "t10", "score": us_neg + us_mkt, "negotiating": us_neg, "market": us_mkt}]}


class ComponentsTest(unittest.TestCase):
    def test_gap_pace_and_min_target(self):
        board = {"teams": {"t14": {"d1h": {"negotiating": 1.0, "score": 1.0, "market": 0.0}},
                           "t10": {"d1h": {"negotiating": 0.5, "score": 0.5, "market": 0.0}}}}
        c = W.components(_lb(), board, hours_left=10.0)
        n = c["negotiating"]
        self.assertEqual((n["gap"], n["required_per_hour"], n["min_target_next_hour"]), (6.0, 1.6, 17.6))
        self.assertTrue(n["behind_pace"])
        m = c["market"]                                  # we lead the market: hold it
        self.assertEqual((m["required_per_hour"], m["min_target_next_hour"], m["behind_pace"]), (0.0, 12.0, False))

    def test_target_never_above_leader(self):
        c = W.components(_lb(us_neg=21.5), {}, hours_left=0.25)
        self.assertEqual(c["negotiating"]["min_target_next_hour"], 22.0)


class ConversionTest(unittest.TestCase):
    def test_isolated_change_gives_the_ratio(self):
        base = {"negotiating": 10.0, "market": 5.0, "neg_points": 10.0, "duel_points": 1.0, "ladder_points": 0.05,
                "bench_points": 0.5, "mm_points": 1.0}
        pts = [dict(base), {**base, "duel_points": 3.0}, {**base, "duel_points": 3.0, "negotiating": 11.4}]
        conv = W.conversions(pts)
        self.assertEqual(conv["duel_points"], {"points_per_unit": 0.7, "samples": 1, "basis": "measured"})
        self.assertEqual(conv["neg_points"]["basis"], "guess")

    def test_score_points_reads_the_me_stream(self):
        with tempfile.TemporaryDirectory() as d:
            rec = Path(d) / "record" / "latest"
            (rec.parent / "me").mkdir(parents=True)
            rec.mkdir()
            now = time.time()
            day = time.strftime("%Y-%m-%d", time.localtime(now))
            rows = [{"ts": now - 60, "tick": 1, "data": {"score": {"negotiating": 10, "market": 5, "duel_points": 1}}},
                    {"ts": now - 30, "tick": 2, "data": {"score": {"negotiating": 10, "market": 5, "duel_points": 1}}},
                    {"ts": now, "tick": 3, "data": {"score": {"negotiating": 11, "market": 5, "duel_points": 2}}}]
            (rec.parent / "me" / f"{day}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
            self.assertEqual([p["tick"] for p in W.score_points(rec, now)], [1, 3])


class MenuTest(unittest.TestCase):
    def menu(self, cash=104):
        needs = {"opportunities": [
            {"kind": "buy_below_value", "ref": "MAL-10", "team": "t03", "offer": 8435, "venue": "rastro", "price": 74,
             "cost": 78.7, "our_value": 91.0, "gain": 12.3},
            {"kind": "buy_below_value", "ref": "SAL-03", "team": "t06", "offer": 7973, "venue": "v07", "price": 7,
             "cost": 7.0, "our_value": 9.0, "gain": 2.0},                       # our own venue: cannot trade there
            {"kind": "buy_below_value", "ref": "RET-09", "team": "t02", "offer": 1, "venue": "rastro", "price": 5,
             "cost": 6.0, "our_value": 30.0, "gain": 24.0},                     # a set we avoid
            {"kind": "swap", "team": "t18", "give": "RET-01", "get": "LAT-06", "gain": 1.5}]}
        ladder = {"levels": {"2": {"empty_slots": 3, "slot_worth_ladder_points": 0.044,
                                   "dealers": [{"id": "chato", "open_to_us": True}]}}}
        sched = {"upcoming": [{"at_hours": 7.0, "action": "bench"},
                              {"at_hours": 11.65, "action": "duels", "params": {"name": "Duels II", "rounds": 2}},
                              {"at_hours": 16.15, "action": "day_closes"}]}
        conv = {k: {"points_per_unit": v} for k, v in W.DEFAULT_CONV.items()}
        return W.action_menu(cash=cash, conv=conv, needs=needs, goals={}, sets={}, ladder=ladder, schedule=sched,
                             clock={"t_hours": 6.2}, points=[], duel_sessions={2: {"duels": 29, "closed": 26, "deals": 22}},
                             our_venue="v07", venue_growth={}, hours_left=9.95, avoid={"RET"})

    def test_menu_ranks_and_filters(self):
        neg = self.menu()["negotiating"]
        text = " | ".join(a["action"] for a in neg)
        self.assertIn("8435", text)
        self.assertNotIn("7973", text)                   # own venue
        self.assertNotIn("RET-09", text)                 # avoided set
        self.assertTrue(all(a["id"].startswith("N") for a in neg))
        duels = next(a for a in neg if "Duels II" in a["action"])
        self.assertFalse(duels["next_hour"])             # hours away: not part of this hour's target
        buy = next(a for a in neg if "8435" in a["action"])
        self.assertEqual((buy["how"], buy["cash"], buy["feasible"], buy["offer"]), ("accept_offers", 78.7, True, 8435))

    def test_cash_short_is_flagged(self):
        buy = next(a for a in self.menu(cash=50)["negotiating"] if "8435" in a["action"])
        self.assertFalse(buy["feasible"])
        self.assertEqual(buy["cash_short"], 33.7)


def _win():
    return {"mission": "pass the leader", "hours_left_today": 10, "hours_tomorrow": 6,
            "components": {"negotiating": {"now": 16.0, "leader": "t18", "leader_score": 22.0, "gap": 6.0,
                                           "required_per_hour": 1.6, "min_target_next_hour": 17.6},
                           "market": {"now": 12.0, "leader": "t06", "leader_score": 11.6, "gap": -0.4,
                                      "required_per_hour": 0.0, "min_target_next_hour": 12.0}},
            "action_menu": {"negotiating": [
                {"id": "N1", "action": "Accept offer 8435: buy MAL-10", "expected_points": 1.2, "cash": 78.7,
                 "feasible": True, "next_hour": True, "how": "accept_offers", "offer": 8435},
                {"id": "N2", "action": "Duels II at h11.65", "expected_points": 12.0, "cash": 0, "feasible": True,
                 "next_hour": False, "how": "guidance.duels"},
                {"id": "N3", "action": "Goal MAL-09 at 84", "expected_points": 1.9, "cash": 300, "feasible": False,
                 "next_hour": True, "how": "goal_buys"}], "market": []}}


class ValidateTest(unittest.TestCase):
    def test_timid_target_is_rejected(self):
        plan = {"points_plan": {"negotiating": {"now": 16.0, "target": 16.5, "actions": [
            {"action": "sell spares", "expected_points": 0.3}]}, "market": {"now": 12.0, "target": 12.0, "actions": []}}}
        errs = B.win_errors(plan, _win())
        self.assertTrue(any("below the pace" in e for e in errs))
        self.assertTrue(any("[N1]" in e and "N2" not in e and "N3" not in e for e in errs))   # only feasible, this hour

    def test_ambitious_plan_using_the_menu_passes(self):
        plan = {"points_plan": {"negotiating": {"now": 16.0, "target": 17.6, "actions": [
            {"action": "[N1] accept 8435", "expected_points": 1.2}, {"action": "ladder with Chato", "expected_points": 0.5}]},
            "market": {"now": 12.0, "target": 12.0, "actions": []}}}
        self.assertEqual(B.win_errors(plan, _win()), [])

    def test_constraint_with_numbers_allows_a_lower_target_if_the_menu_is_used(self):
        plan = {"points_plan": {"negotiating": {"now": 16.0, "target": 17.2, "constraint": "cash 104 P: all gains sum +1.2",
                                                "actions": [{"action": "[N1] accept 8435", "expected_points": 1.2}]},
                                "market": {"now": 12.0, "target": 12.0, "actions": []}}}
        self.assertEqual(B.win_errors(plan, _win()), [])
        plan["points_plan"]["negotiating"]["actions"] = [{"action": "wait", "expected_points": 0.0}]
        self.assertTrue(any("unused" in e for e in B.win_errors(plan, _win())))

    def test_no_win_math_means_no_extra_errors(self):
        self.assertEqual(B.win_errors({"points_plan": {}}, None), [])

    def test_repair_fills_the_menu_and_lifts_the_target(self):
        plan = {"points_plan": {"negotiating": {"now": 16.0, "target": 16.2, "actions": []}}, "accept_offers": []}
        errs = B.win_errors(plan, _win())
        fixed = B.repair({**plan, "goal_buys": {}, "cancel_offers": []}, {"win_math": _win()}, errs)
        neg = fixed["points_plan"]["negotiating"]
        self.assertIn("[N1]", neg["actions"][0]["action"])
        self.assertEqual(fixed["accept_offers"], [8435])
        self.assertEqual(neg["target"], 17.2)             # what the feasible actions add up to
        self.assertIn("+1.20", neg["constraint"])


class ReviewPaceTest(unittest.TestCase):
    def test_review_flags_behind_pace(self):
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            now = time.time()
            (live / "strategy.jsonl").write_text(json.dumps(
                {"updated": now - 3700, "tick": 1, "plan": {"expected_next_hour": {"score_delta": 1.0}},
                 "score_at_plan": {"score": 27.0, "negotiating": 15.0, "market": 12.0}}) + "\n")
            row = B.hourly_review(live, {"us_now": {"score": 27.5, "negotiating": 15.5, "market": 12.0}, "tick": 9}, now,
                                  win={"components": {"score": {"required_per_hour": 2.6}}})
            self.assertTrue(row["pace"]["score"]["behind"])
            self.assertIn("BEHIND", row["verdict"])


if __name__ == "__main__":
    unittest.main()
