import json
import tempfile
import unittest
from pathlib import Path

from bazaar.dealers import ladder
from bazaar.dealers.domain import DealersDomain
from bazaar.dealers.profiles import ProfileStore


class SaturdaySeedTest(unittest.TestCase):
    def test_seed_is_appended_once(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "dealer_memory.json"
            s = ProfileStore(p)
            n = len(s.data["profiles"]["chato"]["sell:uncommon"]["open"])
            self.assertIn("sat-feed-1", s.data["seeds_applied"])
            s.save()
            s2 = ProfileStore(p)
            self.assertEqual(len(s2.data["profiles"]["chato"]["sell:uncommon"]["open"]), n)

    def test_chato_and_pilar_have_a_range_to_capture(self):
        with tempfile.TemporaryDirectory() as d:
            s = ProfileStore(Path(d) / "m.json")
            o = s.expect_opening("chato", "sell:uncommon", None)
            self.assertEqual(o, 13)
            self.assertGreaterEqual(s.expect_limit("chato", "sell:uncommon", o) - o, 1)     # 13 -> ~14.5
            o = s.expect_opening("pilar", "sell:uncommon:loved", None)
            self.assertEqual(o, 22)
            self.assertGreater(s.expect_limit("pilar", "sell:uncommon:loved", o), 25)
            # a loved kind with no samples falls back to the plain kind
            self.assertEqual(s.expect_opening("pilar", "sell:rare:loved", None), s.expect_opening("pilar", "sell:rare", None))


class CollectorIsADealerTest(unittest.TestCase):
    def test_pilar_is_kept_and_loved_sets_are_known(self):
        with tempfile.TemporaryDirectory() as d:
            dom = DealersDomain.__new__(DealersDomain)
            dom.store = ProfileStore(Path(d) / "m.json")
            pilar = {"id": "pilar", "kind": "collector", "level": 3, "status": "active", "open_to_all": True,
                     "menu": {"buys": [{"rarity": "uncommon", "sets": ["SAL", "RET"]},
                                       {"rarity": "uncommon", "sets": "released"}]}}
            radio = {"id": "radio", "kind": "radio", "status": "active", "open_to_all": True}
            out = dom._dealers({"me": {"unlocked": ["abuela"]}, "dealers": [pilar, radio]})
            self.assertEqual(list(out), ["pilar"])
            self.assertTrue(dom._loved("pilar", "uncommon", "SAL"))
            self.assertFalse(dom._loved("pilar", "uncommon", "MAL"))


class LadderReportTest(unittest.TestCase):
    def test_slots_and_points_missing(self):
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            (live / "dealer_memory.json").write_text(json.dumps({"deals": [
                {"level": 1, "negotiated": True, "capture": 1.0, "item": "RET-06", "side": "buy", "opening": 29, "price": 23},
                {"level": 1, "negotiated": False, "capture": 0.0, "item": "X", "side": "buy", "opening": 29, "price": 29}]}))
            personas = [{"id": "abuela", "kind": "dealer", "level": 1, "open_to_all": True},
                        {"id": "pilar", "kind": "collector", "level": 3, "menu": {"buys": [{"rarity": "uncommon"}]}}]
            feed = [{"type": "thread.opened", "tick": 5, "payload": {"thread": 1, "kind": "persona", "with": "pilar",
                                                                    "topic": {"sell": {"assets": [1]}}}},
                    {"type": "thread.message", "tick": 6, "payload": {"thread": 1, "kind": "persona", "with": "pilar",
                     "sender": "pilar", "offer": {"give": {"cash": 16}, "want": {"cash": 0}}}},
                    {"type": "thread.message", "tick": 9, "payload": {"thread": 1, "kind": "persona", "with": "pilar",
                     "sender": "pilar", "offer": {"give": {"cash": 19}, "want": {"cash": 0}, "final": True}}}]
            r = ladder.report(live, {"score": {"ladder_points": 0.02}, "unlocked": ["abuela"]}, personas, feed)
            self.assertEqual(r["levels"]["1"]["best3_capture_est"], [1.0, 0.0, 0.0])
            self.assertEqual(r["levels"]["3"]["empty_slots"], 3)
            self.assertFalse(r["levels"]["3"]["dealers"][0]["open_to_us"])
            self.assertAlmostEqual(r["levels"]["3"]["ladder_points_missing"], 0.2, places=2)
            self.assertEqual(r["dealer_prices_seen_today"]["pilar"]["team_sells"]["16"]["best"], 19)
            self.assertEqual(r["score_components_now"]["ladder_points"], 0.02)


if __name__ == "__main__":
    unittest.main()
