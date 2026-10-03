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


if __name__ == "__main__":
    unittest.main()
