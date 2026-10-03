"""The plaza matcher: sales, swaps and three-way swaps among OTHER teams, never a giveaway, never us."""
import unittest

from bazaar.plaza import matcher as M
from bazaar.plaza import public as P

CAT = {r: {"ref": r, "name": r, "rarity": rar, "set": r[:3]} for r, rar in {
    "LAT-06": "uncommon", "LAT-03": "common", "SAL-09": "rare", "RET-03": "common", "RET-07": "uncommon",
    "MAL-01": "common", "LAV-01": "common", "MAL-11": "epic", "SAL-02": "common"}.items()}


def sheet(team, wants=(), spares=(), sale=(), source="public"):
    return {"team": team, "name": team, "host": team == "t10",
            "wants": [w if isinstance(w, dict) else {"ref": w, "source": source} for w in wants],
            "spares": [{"ref": r, "source": source} for r in spares],
            "for_sale": [s if isinstance(s, dict) else {"ref": s, "source": source} for s in sale]}


def sheets(*rows):
    return {s["team"]: s for s in rows}


class MatcherTest(unittest.TestCase):
    def test_direct_sale_with_recipe(self):
        ms = M.find(sheets(sheet("t09", sale=[{"ref": "LAT-06", "price": 20, "source": "public"}]),
                           sheet("t07", wants=["LAT-06"])), CAT)
        self.assertEqual(len(ms), 1)
        m = ms[0]
        self.assertEqual((m["kind"], m["seller"], m["buyer"], m["ref"], m["price"]), ("sale", "t09", "t07", "LAT-06", 20))
        self.assertEqual(m["recipe"]["buyer"]["body"], {"venue": "v07", "give": {"cash": 20}, "want": {"cards": ["LAT-06"]}, "to": "t09"})
        self.assertEqual(m["saves"], 2)
        self.assertTrue(m["last_of_page"])

    def test_bid_and_ask_meet_in_the_middle_or_not_at_all(self):
        ok = M.find(sheets(sheet("t09", sale=[{"ref": "SAL-09", "price": 60}]),
                           sheet("t07", wants=[{"ref": "SAL-09", "bid": 70}])), CAT)
        self.assertEqual(ok[0]["price"], 65)
        far = M.find(sheets(sheet("t09", sale=[{"ref": "SAL-09", "price": 90}]),
                            sheet("t07", wants=[{"ref": "SAL-09", "bid": 50}])), CAT)
        self.assertEqual(far, [])

    def test_never_a_giveaway(self):
        ms = M.find(sheets(sheet("t09", sale=[{"ref": "SAL-09", "price": 12}]), sheet("t07", wants=["SAL-09"])), CAT)
        self.assertEqual(ms, [])                              # a rare at 12 P destroys value: not proposed

    def test_the_host_is_never_a_party(self):
        ms = M.find(sheets(sheet("t10", wants=["LAT-06"], sale=["RET-03"]), sheet("t09", sale=["LAT-06"], wants=["RET-03"])), CAT)
        self.assertEqual(ms, [])

    def test_mutual_swap_same_rarity_only(self):
        ms = M.find(sheets(sheet("t06", spares=["LAT-06"], wants=["RET-07"]),
                           sheet("t16", spares=["RET-07"], wants=["LAT-06"])), CAT)
        swaps = [m for m in ms if m["kind"] == "swap"]
        self.assertEqual(len(swaps), 1)
        self.assertEqual((swaps[0]["ref"], swaps[0]["ref_back"], swaps[0]["price"]), ("LAT-06", "RET-07", 0))
        uneven = M.find(sheets(sheet("t06", spares=["LAT-06"], wants=["SAL-09"]),
                               sheet("t16", spares=["SAL-09"], wants=["LAT-06"])), CAT)
        self.assertEqual([m for m in uneven if m["kind"] == "swap"], [])

    def test_three_way_swap(self):
        ms = M.find(sheets(sheet("t01", spares=["MAL-01"], wants=["RET-03"]),
                           sheet("t02", spares=["LAV-01"], wants=["MAL-01"]),
                           sheet("t03", spares=["RET-03"], wants=["LAV-01"])), CAT)
        tri = [m for m in ms if m["kind"] == "triangle"]
        self.assertEqual(len(tri), 1)
        self.assertEqual(sorted(tri[0]["teams"]), ["t01", "t02", "t03"])
        self.assertEqual(len(tri[0]["legs"]), 3)

    def test_last_card_of_a_page_goes_first_and_declared_beats_probable(self):
        ms = M.find(sheets(sheet("t01", sale=[{"ref": "LAT-03", "price": 8}, {"ref": "SAL-02", "price": 8}]),
                           sheet("t02", wants=["LAT-03"]),                    # the only LAT card it looks for
                           sheet("t03", wants=["SAL-02", "SAL-09"])), CAT)
        self.assertEqual(ms[0]["buyer"], "t02")
        self.assertTrue(ms[0]["last_of_page"])
        self.assertFalse(M.last_of_page(sheet("t03", wants=["SAL-02", "SAL-09"]), "SAL-02"))
        self.assertFalse(M.last_of_page(sheet("t03", wants=["MAL-11"]), "MAL-11"))   # not a page card
        dec = M.find(sheets(sheet("t01", sale=["LAT-03"], source="agent"), sheet("t02", wants=["LAT-03"], source="agent")), CAT)
        self.assertEqual(dec[0]["confidence"], "declared")

    def test_for_team_and_fee(self):
        ms = M.find(sheets(sheet("t09", sale=[{"ref": "LAT-06", "price": 20}]), sheet("t07", wants=["LAT-06"]),
                           sheet("t08")), CAT)
        self.assertEqual(len(M.for_team(ms, "t07")), 1)
        self.assertEqual(M.for_team(ms, "t08"), [])
        self.assertEqual((M.rastro_fee(100), M.rastro_fee(0)), (6, 0))


class PublicTest(unittest.TestCase):
    def test_public_sheets_from_the_report(self):
        report = {"rivals": {"t04": {"name": "Team 4", "pages": 3, "album": "40/50",
                                     "hunting": {"LAT-06": {"bid": 14, "venue": "v07"}, "SAL-09": {"dealer_threads": 2},
                                                 "RET-03": {"dealer_threads": 1}, "XXX-99": {"bid": 1}},
                                     "selling": {"RET-03": {"ask": 10, "venue": "rastro", "offer": 7}},
                                     "bought": [{"ref": "SAL-09", "price": 55}]}}}
        s = P.public_sheets(report, CAT)
        self.assertEqual(len(s), 18)
        self.assertTrue(s["t10"]["host"])
        self.assertEqual([w["ref"] for w in s["t04"]["wants"]], ["LAT-06"])      # bought SAL-09, sells RET-03, XXX unknown
        self.assertEqual(s["t04"]["wants"][0]["bid"], 14)
        self.assertEqual(s["t04"]["for_sale"], [{"ref": "RET-03", "source": "public", "price": 10, "venue": "rastro", "offer": 7}])

    def test_declared_replaces_public_field_by_field(self):
        pub = P.public_sheets({"rivals": {"t04": {"hunting": {"LAT-06": {"bid": 14}},
                                                  "selling": {"RET-03": {"ask": 10}}}}}, CAT)
        merged = P.merge(pub, {"t04": {"claimed": True, "verified": True,
                                       "declared": {"wants": ["SAL-09"], "spares": ["MAL-01"], "updated": 5.0}},
                               "t10": {"claimed": True, "declared": {"wants": ["SAL-09"]}}})
        t = merged["t04"]
        self.assertEqual(t["wants"], [{"ref": "SAL-09", "source": "agent"}])
        self.assertEqual(t["spares"], [{"ref": "MAL-01", "source": "agent"}])
        self.assertEqual(t["for_sale"][0]["source"], "public")                   # not declared: stays deduced
        self.assertTrue(t["verified"])
        self.assertEqual(merged["t10"]["wants"], [])                             # the host has no sheet


if __name__ == "__main__":
    unittest.main()
