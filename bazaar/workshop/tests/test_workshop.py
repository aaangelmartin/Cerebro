import tempfile
import unittest
from pathlib import Path

from bazaar.core import rails
from bazaar.core.executor import _call
from bazaar.core.types import Action
from bazaar.workshop import planner as W


class FakeValues:
    """25 P for any uncommon, 70 for a rare: expected value of a pull."""
    def __init__(self, by_rarity=None):
        self.by = by_rarity or {"uncommon": {"U-1": 12.0, "U-2": 10.0}, "rare": {"R-1": 60.0}}

    def released_refs(self, rarity=None):
        return list(self.by.get(rarity, {}))

    def next_copy(self, ref):
        for d in self.by.values():
            if ref in d:
                return d[ref]
        return 0.0


def card(i, ref, rarity="common", value=1.3):
    return {"id": i, "kind": "card", "ref": ref, "rarity": rarity, "your_value": value}


def sit(assets, offers=(), threads=()):
    return {"me": {"id": "t10", "assets": list(assets)}, "my_offers": list(offers), "threads": list(threads)}


def ask(oid, aid, ref, cash):
    return {"id": oid, "maker": "t10", "status": "open", "give": {"cash": 0, "assets": [{"id": aid, "ref": ref}]},
            "want": {"cash": cash, "assets": [], "types": []}}


THREE = [card(1, "MAL-02"), card(2, "MAL-02"), card(3, "MAL-02"), card(4, "MAL-01", value=3.2), card(5, "MAL-01", value=3.2)]


class PlannerTest(unittest.TestCase):
    def test_crafts_three_cheapest_spares_and_keeps_one_of_each(self):
        a = W.plan(sit(THREE), {}, "auto", FakeValues())
        self.assertEqual(a.kind, "taller")
        self.assertEqual(sorted(a.params["assets"]), [1, 2, 4])          # two MAL-02 + one MAL-01; one of each stays
        self.assertAlmostEqual(a.expected["value_give"], 5.8)
        self.assertAlmostEqual(a.expected["value_get"], 11.0)

    def test_no_craft_without_three_spares_or_without_gain(self):
        self.assertIsNone(W.plan(sit(THREE[:3]), {}, "auto", FakeValues()))         # only two spares
        dear = [card(i, r, value=5.0) for i, r in ((1, "A"), (2, "A"), (3, "B"), (4, "B"), (5, "C"), (6, "C"))]
        self.assertIsNone(W.plan(sit(dear), {}, "auto", FakeValues()))              # 15 given for 11 expected

    def test_promised_copies_are_not_spares(self):
        s = sit(THREE, offers=[ask(9, 4, "MAL-01", 5)])                              # one MAL-01 is in an open ask
        pool = W.spare_pool(s)
        self.assertEqual({(x["ref"], x["usable"]) for x in pool["common"]}, {("MAL-02", 2)})
        self.assertIsNone(W.plan(s, {}, "auto", FakeValues()))

    def test_protected_and_brain_floor(self):
        self.assertNotIn("common", W.spare_pool(sit(THREE[:3]), {"protected": ["MAL-02"]}))
        pool = W.spare_pool(sit(THREE), {"min_asks": {"MAL-02": 8}})
        self.assertEqual({x["value"] for x in pool["common"] if x["ref"] == "MAL-02"}, {8.0})

    def test_an_ordered_craft_frees_its_copies_from_our_open_offers(self):
        """Outbox request code-f84c0c91: the market's code listed a copy the brain ordered crafted."""
        s = sit(THREE + [card(6, "LAT-01")], offers=[ask(9, 4, "MAL-01", 12), ask(8, 6, "LAT-01", 12)])
        acts = W.plan_actions(s, {}, [[1, 2, 4]], FakeValues())
        self.assertEqual([(a.kind, a.params) for a in acts], [("cancel_offer", {"offer": 9})])   # only the ordered copy
        self.assertEqual(W.plan_actions(sit(THREE), {}, [[1, 2, 4]], FakeValues())[0].kind, "taller")
        in_thread = {**ask(9, 4, "MAL-01", 12), "thread": 77}
        self.assertEqual(W.plan_actions(sit(THREE, offers=[in_thread]), {}, [[1, 2, 4]], FakeValues()), [])
        self.assertEqual(W.plan_actions(sit(THREE[:3], offers=[ask(9, 3, "MAL-02", 12)]), {}, [[1, 2, 3]],
                                        FakeValues()), [])                      # freeing it would not make the craft run

    def test_cancels_cheap_asks_to_free_spares_but_not_good_ones(self):
        s = sit(THREE, offers=[ask(9, 4, "MAL-01", 5)])
        acts = W.plan_actions(s, {}, "auto", FakeValues())
        self.assertEqual([(a.kind, a.params) for a in acts], [("cancel_offer", {"offer": 9})])
        good = sit(THREE, offers=[ask(9, 4, "MAL-01", 13)])                          # +9.8 if it fills: keep it
        self.assertEqual(W.plan_actions(good, {}, "auto", FakeValues()), [])

    def test_orders(self):
        self.assertEqual(W.plan_actions(sit(THREE), {}, "off", FakeValues()), [])
        a = W.plan(sit(THREE), {}, [[2, 3, 5]], FakeValues())
        self.assertEqual(sorted(a.params["assets"]), [2, 3, 5])
        self.assertIsNone(W.plan(sit(THREE), {}, [[1, 2, 3]], FakeValues()))         # would leave no MAL-02

    def test_results_are_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            a = W.plan(sit(THREE), {}, "auto", FakeValues())
            out = {"status": "sent", "response": {"card": {"id": 900, "ref": "SAL-06", "rarity": "uncommon"}}}
            W.record_result(a, out, 700, Path(d))
            self.assertEqual(W.results(Path(d))[0]["got"]["ref"], "SAL-06")


class RailTest(unittest.TestCase):
    def setUp(self):
        self._lv = W.load_values
        W.load_values = lambda me: FakeValues()

    def tearDown(self):
        W.load_values = self._lv

    def check(self, ids, s=None, control=None):
        a = Action(kind="taller", params={"assets": ids}, domain="workshop", expected={"value_get": 999})
        return rails.rail_taller(a, s or sit(THREE), {"control": control or {}})

    def test_valid_triple_passes(self):
        self.assertTrue(self.check([1, 2, 4]).ok)

    def test_last_copy_and_foreign_assets_are_vetoed(self):
        self.assertFalse(self.check([1, 2, 3]).ok)                                   # all three MAL-02
        self.assertFalse(self.check([4, 5, 1]).ok)                                   # both MAL-01
        self.assertFalse(self.check([1, 2, 77]).ok)
        self.assertFalse(self.check([1, 2]).ok)

    def test_promised_copy_is_vetoed(self):
        self.assertFalse(self.check([1, 2, 4], sit(THREE, offers=[ask(9, 5, "MAL-01", 5)])).ok)

    def test_mixed_rarity_and_no_gain_are_vetoed(self):
        mixed = THREE + [card(6, "X", "uncommon", 2.0), card(7, "X", "uncommon", 2.0)]
        self.assertFalse(self.check([1, 2, 6], sit(mixed)).ok)
        dear = [card(i, r, value=5.0) for i, r in ((1, "A"), (2, "A"), (3, "B"), (4, "B"), (5, "C"), (6, "C"))]
        v = self.check([1, 3, 5], sit(dear))                                         # the proposer's 999 is ignored
        self.assertFalse(v.ok)
        self.assertEqual(v.rail, "taller")

    def test_known_kind_and_executor_mapping(self):
        a = Action(kind="taller", params={"assets": [1, 2, 4]}, domain="workshop")
        self.assertTrue(rails.rail_known(a).ok)
        self.assertEqual(_call(a, None)[:3], ("post", "/api/taller", {"assets": [1, 2, 4]}))


if __name__ == "__main__":
    unittest.main()
