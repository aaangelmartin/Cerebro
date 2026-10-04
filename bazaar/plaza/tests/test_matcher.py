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


def agent(team, wants=(), spares=(), sale=()):
    """A sheet the team's own agent declared."""
    return sheet(team, wants=wants, spares=spares, sale=sale, source="agent")


class GateTest(unittest.TestCase):
    """Only trades that create value are proposed: the venue is scored by the value its trades create."""

    def test_a_declared_duplicate_to_a_declared_want(self):
        ms = M.find(sheets(agent("t09", spares=["LAT-06"]), agent("t07", wants=["LAT-06"])), CAT)
        self.assertEqual(len(ms), 1)
        m = ms[0]
        self.assertEqual((m["kind"], m["seller"], m["buyer"], m["ref"], m["price"], m["confidence"]),
                         ("sale", "t09", "t07", "LAT-06", 25, "declared"))
        self.assertEqual(m["recipe"]["buyer"]["body"],
                         {"venue": "v07", "give": {"cash": 25}, "want": {"cards": ["LAT-06"]}, "to": "t09"})
        self.assertEqual(m["saves"], 2)
        self.assertTrue(m["last_of_page"])

    def test_what_is_only_deduced_is_not_proposed(self):
        deduced = sheets(sheet("t09", sale=[{"ref": "LAT-06", "price": 20, "source": "public"}]),
                         sheet("t07", wants=["LAT-06"]))
        self.assertEqual(M.find(deduced, CAT), [])                               # nothing says both sides gain
        self.assertEqual(len(M.find(deduced, CAT, strict=False)), 1)             # the old, permissive list
        half = sheets(agent("t09", spares=["LAT-06"]), sheet("t07", wants=["LAT-06"]))
        self.assertEqual(M.find(half, CAT), [])                                  # only one side declared
        for_sale = sheets(agent("t09", sale=["LAT-06"]), agent("t07", wants=["LAT-06"]))
        self.assertEqual(M.find(for_sale, CAT), [])                              # for sale is not a duplicate

    def test_a_public_ask_and_bid_that_cross(self):
        ok = M.find(sheets(sheet("t09", sale=[{"ref": "SAL-09", "price": 60}]),
                           sheet("t07", wants=[{"ref": "SAL-09", "bid": 70}])), CAT)
        self.assertEqual(len(ok), 1)
        self.assertTrue(60 <= ok[0]["price"] <= 70)
        self.assertEqual(ok[0]["basis"], "public")
        far = M.find(sheets(sheet("t09", sale=[{"ref": "SAL-09", "price": 90}]),
                            sheet("t07", wants=[{"ref": "SAL-09", "bid": 50}])), CAT)
        self.assertEqual(far, [])                                                # they do not meet: no match

    def test_never_a_giveaway(self):
        ms = M.find(sheets(sheet("t09", sale=[{"ref": "SAL-09", "price": 12}]),
                           sheet("t07", wants=[{"ref": "SAL-09", "bid": 30}])), CAT)
        self.assertEqual(ms, [])                              # a rare under 40 P destroys value: never proposed
        up = M.find(sheets(sheet("t09", sale=[{"ref": "SAL-09", "price": 12}]),
                           sheet("t07", wants=[{"ref": "SAL-09", "bid": 55}])), CAT)
        self.assertGreaterEqual(up[0]["price"], M.FLOOR["rare"])

    def test_the_host_is_never_a_party(self):
        ms = M.find(sheets(agent("t10", wants=["LAT-06"], spares=["RET-03"]),
                           agent("t09", spares=["LAT-06"], wants=["RET-03"])), CAT)
        self.assertEqual(ms, [])

    def test_a_paused_team_gets_no_new_match(self):
        sh = sheets(agent("t09", spares=["LAT-06"]), agent("t07", wants=["LAT-06"]), agent("t08", wants=["LAT-06"]))
        self.assertEqual({m["buyer"] for m in M.find(sh, CAT)}, {"t07", "t08"})
        self.assertEqual({m["buyer"] for m in M.find(sh, CAT, paused={"t07"})}, {"t08"})
        self.assertEqual(M.find(sh, CAT, paused={"t09"}), [])

    def test_the_reference_price_is_the_last_sales_between_teams(self):
        sh = sheets(agent("t09", spares=["SAL-09"]), agent("t07", wants=["SAL-09"]))
        self.assertEqual((M.find(sh, CAT)[0]["price"], M.find(sh, CAT)[0]["basis"]), (70, "book"))
        m = M.find(sh, CAT, refprice={"SAL-09": 58})[0]
        self.assertEqual((m["price"], m["basis"]), (60, "reference"))            # on the grid: 5 P above 20
        low = M.find(sh, CAT, refprice={"SAL-09": 8})[0]
        self.assertEqual(low["price"], M.FLOOR["rare"])

    def test_the_blind_quote_decides(self):
        sh = sheets(agent("t09", spares=["SAL-09"]), agent("t07", wants=["SAL-09"]))
        no_value = lambda *a, **k: {"price": 70, "overlap": None, "value": False, "basis": None}    # noqa: E731
        self.assertEqual(M.find(sh, CAT, quote=no_value), [])                    # the buyer values it less
        no_overlap = lambda *a, **k: {"price": None, "overlap": False, "value": None, "basis": None}   # noqa: E731
        self.assertEqual(M.find(sh, CAT, quote=no_overlap), [])
        limits = lambda *a, **k: {"price": 85, "overlap": True, "value": True, "basis": "limits"}   # noqa: E731
        m = M.find(sheets(sheet("t09", sale=["SAL-09"]), sheet("t07", wants=["SAL-09"])), CAT, quote=limits)[0]
        self.assertEqual((m["price"], m["basis"]), (85, "limits"))               # limits that overlap are enough


class MatcherTest(unittest.TestCase):
    def test_mutual_swap_same_rarity_and_declared_only(self):
        ms = M.find(sheets(agent("t06", spares=["LAT-06"], wants=["RET-07"]),
                           agent("t16", spares=["RET-07"], wants=["LAT-06"])), CAT)
        swaps = [m for m in ms if m["kind"] == "swap"]
        self.assertEqual(len(swaps), 1)
        self.assertEqual((swaps[0]["ref"], swaps[0]["ref_back"], swaps[0]["price"]), ("LAT-06", "RET-07", 0))
        self.assertEqual(ms[0]["kind"], "swap")                                  # before the two sales it replaces
        uneven = M.find(sheets(agent("t06", spares=["LAT-06"], wants=["SAL-09"]),
                               agent("t16", spares=["SAL-09"], wants=["LAT-06"])), CAT)
        self.assertEqual([m for m in uneven if m["kind"] == "swap"], [])
        deduced = M.find(sheets(sheet("t06", spares=["LAT-06"], wants=["RET-07"]),
                                sheet("t16", spares=["RET-07"], wants=["LAT-06"])), CAT)
        self.assertEqual(deduced, [])

    def test_three_way_swap(self):
        ms = M.find(sheets(agent("t01", spares=["MAL-01"], wants=["RET-03"]),
                           agent("t02", spares=["LAV-01"], wants=["MAL-01"]),
                           agent("t03", spares=["RET-03"], wants=["LAV-01"])), CAT)
        tri = [m for m in ms if m["kind"] == "triangle"]
        self.assertEqual(len(tri), 1)
        self.assertEqual(sorted(tri[0]["teams"]), ["t01", "t02", "t03"])
        self.assertEqual(len(tri[0]["legs"]), 3)

    def test_dear_cards_first(self):
        ms = M.find(sheets(agent("t01", spares=["MAL-11", "SAL-09", "LAT-03", "RET-03"]),
                           agent("t02", wants=["LAT-03"]),                       # the only LAT card it looks for
                           agent("t03", wants=["MAL-11", "SAL-09", "SAL-02", "RET-03", "RET-07"])), CAT)
        self.assertEqual([(m["priority"], m["ref"]) for m in ms],
                         [(1, "LAT-03"), (2, "MAL-11"), (3, "SAL-09"), (4, "RET-03")])
        self.assertTrue(ms[0]["last_of_page"])
        self.assertFalse(M.last_of_page(agent("t03", wants=["SAL-02", "SAL-09"]), "SAL-02"))
        self.assertFalse(M.last_of_page(agent("t03", wants=["MAL-11"]), "MAL-11"))   # not a page card

    def test_a_pair_that_has_not_traded_here_goes_first(self):
        sh = sheets(agent("t01", spares=["RET-03"]), agent("t02", wants=["RET-03", "RET-07"]),
                    agent("t03", wants=["RET-03", "RET-07"]))
        self.assertEqual(M.find(sh, CAT)[0]["buyer"], "t02")
        ms = M.find(sh, CAT, traded={frozenset(("t01", "t02"))})
        self.assertEqual((ms[0]["buyer"], ms[0]["pair_traded"], ms[1]["pair_traded"]), ("t03", False, True))

    def test_for_team_and_fee(self):
        ms = M.find(sheets(agent("t09", spares=["LAT-06"]), agent("t07", wants=["LAT-06"]), agent("t08")), CAT)
        self.assertEqual(len(M.for_team(ms, "t07")), 1)
        self.assertEqual(M.for_team(ms, "t08"), [])
        self.assertEqual((M.rastro_fee(100), M.rastro_fee(0)), (6, 0))


class PriceRuleTest(unittest.TestCase):
    def test_reference_inside_the_overlap_is_the_price(self):
        self.assertEqual(M.rule_price(60, 100, 80, 40, 0.25), 80)
        self.assertEqual(M.rule_price(60, 100, 80, 40, 0.0), 80)

    def test_reference_outside_is_pulled_in_with_the_margin(self):
        self.assertEqual(M.rule_price(60, 100, 200, 40, 0.0), 100)
        self.assertEqual(M.rule_price(60, 100, 200, 40, 0.25), 90)
        self.assertEqual(M.rule_price(60, 100, 10, 40, 0.25), 70)
        self.assertEqual(M.rule_price(60, 100, 10, 40, 9.0), 70)                 # the margin is capped

    def test_always_inside_the_overlap_and_over_the_floor(self):
        for lo, hi, ref, floor in ((60, 62, 10, 1), (61, 63, 500, 1), (5, 9, 7, 4), (30, 80, 50, 40), (41, 41, 90, 40)):
            for share in (0.0, 0.1, 0.25):
                p = M.rule_price(lo, hi, ref, floor, share)
                self.assertTrue(max(lo, floor) <= p <= hi, (lo, hi, ref, floor, share, p))
        self.assertIsNone(M.rule_price(90, 50, 70))
        self.assertIsNone(M.rule_price(10, 30, 20, floor=40))

    def test_grid(self):
        self.assertEqual([M.grid(x) for x in (7.4, 19.4, 22, 23, 58, 101)], [7, 19, 20, 25, 60, 100])


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
