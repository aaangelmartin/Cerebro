import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bazaar.brain.strategy import sanitize
from bazaar.strategist import analysis as A
from bazaar.strategist.brainio import repair, validate


def ask(i, ref, cash, to=None):
    return {"id": i, "status": "open", "to": to, "give": {"cash": 0, "assets": [{"id": i, "kind": "card", "ref": ref}]},
            "want": {"cash": cash, "assets": [], "types": []}}


def bid(i, ref, cash):
    return {"id": i, "status": "open", "give": {"cash": cash, "assets": [], "types": []},
            "want": {"cash": 0, "assets": [], "types": [f"card:{ref}"]}}


def listed(o, team, venue, ts=100.0):
    return {"type": "offer.listed", "ts": ts, "actor": team, "payload": {"venue": venue, "offer": {**o, "maker": team}}}


class VenueGrowthTest(unittest.TestCase):
    def run_growth(self, books, feed, me=None, venues=None):
        with tempfile.TemporaryDirectory() as d:
            rec = Path(d)
            (rec / "books").mkdir()
            for v, offers in books.items():
                (rec / "books" / f"{v}.json").write_text(json.dumps({"venue": v, "offers": offers}))
            return A.venue_growth(rec, feed, venues or [{"venue": "v07", "owner": "t10", "trades": 2}],
                                  me or {"id": "t10", "score": {"mm_points": 2.8}, "venue": {"value_created": 15.5}},
                                  "v07", now=200.0)

    def test_crossing_pair_on_other_venues_is_found_with_both_teams(self):
        a, b = ask(1, "RET-05", 9), bid(2, "RET-05", 10)
        g = self.run_growth({"rastro": [a], "v02": [b]}, [listed(a, "t03", "rastro"), listed(b, "t12", "v02")])
        p = g["crossing_pairs_elsewhere"][0]
        self.assertEqual((p["seller"], p["buyer"], p["ask"], p["bid"], p["midpoint"]), ("t03", "t12", 9, 10, 9.5))
        self.assertIn("v07", p["how"])
        self.assertEqual(g["ours"]["value_created"], 15.5)
        self.assertEqual(g["ours"]["mm_points"], 2.8)

    def test_bid_on_our_venue_only_needs_an_accept(self):
        a, b = ask(1, "MAL-05", 6), bid(2, "MAL-05", 7)
        g = self.run_growth({"rastro": [a], "v07": [b]}, [listed(a, "t18", "rastro"), listed(b, "t06", "v07")])
        self.assertIn("accept bid #2 on v07", g["crossing_pairs_elsewhere"][0]["how"])
        self.assertEqual(g["ours"]["public_makers_now"], 1)

    def test_our_own_addressed_and_same_team_offers_are_ignored(self):
        mine, theirs, same = ask(1, "SAL-01", 5), ask(2, "SAL-01", 5, to="t04"), ask(3, "LAV-01", 5)
        b1, b2 = bid(4, "SAL-01", 9), bid(5, "LAV-01", 9)
        feed = [listed(mine, "t10", "rastro"), listed(theirs, "t03", "rastro"), listed(same, "t05", "rastro"),
                listed(b1, "t12", "v02"), listed(b2, "t05", "v02")]
        g = self.run_growth({"rastro": [mine, theirs, same], "v02": [b1, b2]}, feed)
        self.assertEqual(g["crossing_pairs_elsewhere"], [])

    def test_pairs_already_on_our_venue_are_left_to_the_broker(self):
        a, b = ask(1, "RET-05", 9), bid(2, "RET-05", 10)
        g = self.run_growth({"v07": [a, b]}, [listed(a, "t03", "v07"), listed(b, "t12", "v07")])
        self.assertEqual(g["crossing_pairs_elsewhere"], [])

    def test_nearly_crossing_and_flow(self):
        a, b = ask(1, "LAT-02", 6), bid(2, "LAT-02", 4)
        feed = [listed(a, "t13", "rastro"), listed(b, "t06", "v07"),
                {"type": "settlement", "ts": 150.0, "payload": {"venue": "v07", "price": 5}},
                {"type": "settlement", "ts": 150.0, "payload": {"venue": "rastro", "price": 30}}]
        g = self.run_growth({"rastro": [a], "v07": [b]}, feed)
        self.assertEqual(g["nearly_crossing"][0]["gap"], 2)
        self.assertEqual(g["ours"]["fills_last_hour"], 1)
        self.assertEqual(g["open_public_offers_on_our_venue"][0]["teams_that_listed_it_today"], {"t13": 6})


class AnnouncementTest(unittest.TestCase):
    def test_plan_field_and_english_check(self):
        self.assertEqual(sanitize({"venue_announcement": " v07: Team 6 bids 4 P for LAT-02. "})["venue_announcement"],
                         "v07: Team 6 bids 4 P for LAT-02.")
        self.assertNotIn("venue_announcement", sanitize({}))
        plan = {"priorities": ["sell at 27 P"], "points_plan": {"x": 1},
                "venue_announcement": "Hola equipos, ¿publicáis en v07?"}
        errs = validate(plan, {})
        self.assertTrue(any(e.startswith("venue_announcement") for e in errs))
        self.assertNotIn("venue_announcement", repair(plan, {}, errs))

    def test_broker_pitch_uses_the_brain_text_when_it_names_the_venue(self):
        from bazaar.market import protocol
        with mock.patch("bazaar.brain.strategy.venue_announcement", return_value="v07: Team 6 bids 4 P for LAT-02."):
            self.assertEqual(protocol.broker_pitch("v07"), "v07: Team 6 bids 4 P for LAT-02.")
        with mock.patch("bazaar.brain.strategy.venue_announcement", return_value="come to our venue"):
            self.assertIn("Team 10 venue v07", protocol.broker_pitch("v07"))


if __name__ == "__main__":
    unittest.main()
