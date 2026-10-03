import unittest

from bazaar.core.goal import goal_buys, pending


class GoalTest(unittest.TestCase):
    def test_pending_lists_missing_goal_cards(self):
        sit = {"me": {"assets": [{"kind": "card", "ref": "MAL-09"}, {"kind": "pack", "ref": None}]}}
        control = {"goal_buys": {"mal-09": 90, "MAL-10": "90"}}
        self.assertEqual(goal_buys(control), {"MAL-09": 90, "MAL-10": 90})
        self.assertEqual(pending(sit, control), {"MAL-10": 90})

    def test_no_goal(self):
        self.assertEqual(pending({"me": {"assets": []}}, {}), {})


class FakeValues:
    def __init__(self, held, value):
        self.held, self.value = held, value

    def released_refs(self, rarity=None):
        return [f"MAL-{i:02d}" for i in range(1, 11)] + [f"RET-{i:02d}" for i in range(1, 13)]

    set_of = staticmethod(lambda r: r.split("-")[0])

    def count(self, r):
        return self.held.get(r, 0)

    def next_copy(self, r):
        return self.value.get(r, 10.0)


class AutoGoalTest(unittest.TestCase):
    def test_nearly_complete_page_with_valuable_cards(self):
        held = {f"MAL-{i:02d}": 1 for i in range(1, 9)}
        held["RET-01"] = 1
        v = FakeValues(held, {"MAL-09": 91.0, "MAL-10": 91.0, "RET-06": 27.5})
        self.assertEqual(pending({"me": {"assets": []}}, {}, v), {"MAL-09": 88, "MAL-10": 88})

    def test_cheap_missing_cards_are_not_goals(self):
        held = {f"MAL-{i:02d}": 1 for i in range(1, 10)}
        self.assertEqual(pending({"me": {"assets": []}}, {}, FakeValues(held, {"MAL-10": 12.0})), {})


class AvoidSetsTest(unittest.TestCase):
    def test_goals_and_rail_skip_avoided_sets(self):
        from bazaar.core import rails
        from bazaar.core.context import TickContext
        from bazaar.core.types import Action
        control = {"avoid_buy_sets": ["ret"], "goal_buys": {"RET-07": 24, "MAL-09": 88}}
        self.assertEqual(pending({"me": {"assets": []}}, control), {"MAL-09": 88})
        ctx = TickContext(tick=1, day="sat", deadline=0.0, control=control)
        sit = {"me": {"id": "t10", "assets": []}}
        bid = Action(kind="post_offer", params={"venue": "rastro", "give": {"cash": 9}, "want": {"cards": ["RET-03"]}},
                     domain="market")
        ok = Action(kind="post_offer", params={"venue": "rastro", "give": {"cash": 9}, "want": {"cards": ["MAL-03"]}},
                    domain="market")
        acc = Action(kind="accept_offer", params={"offer": 1, "expect": {"give": {"assets": [{"id": 5, "ref": "RET-07"}]},
                                                                        "want": {"cash": 23}}}, domain="market")
        self.assertEqual(rails.rail_avoid_sets(bid, sit, ctx).rail, "avoid_sets")
        self.assertFalse(rails.rail_avoid_sets(acc, sit, ctx).ok)
        self.assertTrue(rails.rail_avoid_sets(ok, sit, ctx).ok)
        self.assertTrue(rails.rail_avoid_sets(bid, sit, TickContext(tick=1, day="sat", deadline=0.0, control={})).ok)


class AvoidExceptionTest(unittest.TestCase):
    """control.avoid_buy_exceptions: RET rares may be bought when worth 15 P more than the total price."""
    CONTROL = {"avoid_buy_sets": ["RET"], "avoid_buy_exceptions": {"RET": {"min_rarity": "rare", "min_gain": 15}}}

    class V:
        RAR = {"RET-09": "rare", "RET-10": "rare", "RET-03": "common", "RET-06": "uncommon"}
        VAL = {"RET-09": 77.0, "RET-10": 60.0, "RET-03": 40.0, "RET-06": 50.0}

        def __call__(self, ref):
            return self.VAL.get(ref)

        def rarity(self, ref):
            return self.RAR.get(ref)

    def _check(self, ref, price, control=None, kind="dealer"):
        from bazaar.core import rails
        from bazaar.core.context import TickContext
        from bazaar.core.types import Action
        ctx = TickContext(tick=1, day="sat", deadline=0.0, value=self.V(),
                          control=self.CONTROL if control is None else control)
        sit = {"me": {"id": "t10", "cash": 200, "assets": []}}
        if kind == "dealer":
            a = Action(kind="open_thread", params={"with": "picaros", "topic": {"buy": {"card": ref}}, "price": price},
                       domain="dealers")
        else:
            a = Action(kind="accept_offer", domain="market",
                       params={"offer": 1, "expect": {"give": {"assets": [{"id": 5, "ref": ref}]},
                                                      "want": {"cash": price}}})
        return rails.rail_avoid_sets(a, sit, ctx)

    def test_rare_with_gain_is_allowed(self):
        self.assertTrue(self._check("RET-09", 54).ok)                 # worth 77: gain 23
        self.assertTrue(self._check("RET-09", 54, kind="accept").ok)
        self.assertTrue(self._check("RET-09", 62).ok)                 # gain exactly 15

    def test_rare_with_small_gain_is_blocked(self):
        v = self._check("RET-10", 54)                                 # worth 60: gain 6
        self.assertFalse(v.ok)
        self.assertEqual(v.rail, "avoid_sets")
        self.assertFalse(self._check("RET-09", 63).ok)                # gain 14
        self.assertFalse(self._check("RET-10", 54, kind="accept").ok)

    def test_lower_rarities_stay_blocked_whatever_the_gain(self):
        self.assertFalse(self._check("RET-03", 5).ok)                 # common worth 40
        self.assertFalse(self._check("RET-06", 5, kind="accept").ok)  # uncommon worth 50
        self.assertFalse(self._check("RET-99", 5).ok)                 # unknown rarity

    def test_no_exception_keeps_the_veto(self):
        self.assertFalse(self._check("RET-09", 54, control={"avoid_buy_sets": ["RET"]}).ok)
        bad = {"avoid_buy_sets": ["RET"], "avoid_buy_exceptions": {"RET": {"min_rarity": "shiny"}}}
        self.assertFalse(self._check("RET-09", 54, control=bad).ok)

    def test_planner_helpers(self):
        from bazaar.core.goal import avoided, buy_cap
        self.assertTrue(avoided("RET-09", self.CONTROL))               # rarity unknown: avoided
        self.assertFalse(avoided("RET-09", self.CONTROL, "rare"))
        self.assertFalse(avoided("RET-11", self.CONTROL, "epic"))
        self.assertTrue(avoided("RET-03", self.CONTROL, "common"))
        self.assertEqual(buy_cap("RET-09", self.CONTROL, "rare", 77.0, 76), 62)
        self.assertEqual(buy_cap("RET-09", self.CONTROL, "rare", 77.0, None), 62)
        self.assertEqual(buy_cap("MAL-09", self.CONTROL, "rare", 91.0, 74), 74)


if __name__ == "__main__":
    unittest.main()
