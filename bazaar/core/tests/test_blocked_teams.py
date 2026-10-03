"""control.json "blocked_teams": the arbiter sends nothing to a vetoed team (Team 6 bought our spare RET-03)."""
import unittest
from types import SimpleNamespace

from bazaar.core import arbiter
from bazaar.core.types import Action


def _sit(threads=()):
    return SimpleNamespace(limits={}, my_offers=[], threads=list(threads))


def _ctx(blocked):
    return SimpleNamespace(control={"blocked_teams": blocked})


def _accept(maker):
    return Action(kind="accept_offer", domain="market", priority=5.0,
                  params={"offer": 1, "expect": {"maker": maker}, "assets": [1062],
                          "give": {"cash": 0, "assets": [1062]}, "want": {"cash": 8, "assets": [], "types": []}})


class BlockedTeams(unittest.TestCase):
    def test_accept_of_a_blocked_teams_bid_is_dropped(self):
        chosen, dropped = arbiter.select([_accept("t06")], _sit(), {}, ctx=_ctx(["t06"]))
        self.assertEqual(chosen, [])
        self.assertIn("blocked_teams", dropped[0][1])

    def test_accept_from_another_team_passes(self):
        chosen, _ = arbiter.select([_accept("t07")], _sit(), {}, ctx=_ctx(["t06"]))
        self.assertEqual(len(chosen), 1)

    def test_offer_addressed_to_a_blocked_team_is_dropped(self):
        post = Action(kind="post_offer", domain="market",
                      params={"venue": "rastro", "to": "T06", "give": {"cash": 0, "assets": [5]}, "want": {"cash": 9}})
        chosen, dropped = arbiter.select([post], _sit(), {}, ctx=_ctx(["t06"]))
        self.assertEqual(chosen, [])
        self.assertEqual(len(dropped), 1)

    def test_thread_with_a_blocked_team_is_dropped(self):
        sit = _sit([{"id": 7, "with": "t06", "status": "open"}])
        acts = [Action(kind="open_thread", domain="market", params={"with": "t06", "venue": "rastro"}),
                Action(kind="thread_message", domain="market", params={"thread": 7, "text": "hi"})]
        chosen, dropped = arbiter.select(acts, sit, {}, ctx=_ctx(["t06"]))
        self.assertEqual(chosen, [])
        self.assertEqual(len(dropped), 2)

    def test_accept_and_offer_inside_a_blocked_teams_thread_are_dropped(self):
        sit = _sit([{"id": 7, "with": "t06", "status": "open"}])
        acc = Action(kind="accept_offer", domain="market", params={"offer": 3, "thread": 7, "expect": {"thread": 7}})
        post = Action(kind="post_offer", domain="market", params={"thread": 7, "give": {"assets": [5]}, "want": {"cash": 9}})
        chosen, dropped = arbiter.select([acc, post], sit, {}, ctx=_ctx(["t06"]))
        self.assertEqual(chosen, [])
        self.assertEqual(len(dropped), 2)

    def test_swap_addressed_to_a_blocked_team_is_dropped(self):
        swap = Action(kind="post_offer", domain="market",
                      params={"venue": "rastro", "to": "t06", "give": {"cash": 0, "assets": [5]},
                              "want": {"cash": 0, "assets": [], "types": ["RET-05"]}})
        chosen, _ = arbiter.select([swap], _sit(), {}, ctx=_ctx(["t06"]))
        self.assertEqual(chosen, [])

    def test_no_list_changes_nothing_and_duels_are_never_blocked(self):
        chosen, _ = arbiter.select([_accept("t06")], _sit(), {}, ctx=_ctx([]))
        self.assertEqual(len(chosen), 1)
        duel = Action(kind="duel_message", domain="duels", params={"duel": 1, "price": 10, "to": "t06"})
        chosen, _ = arbiter.select([duel], _sit(), {}, ctx=_ctx(["t06"]))
        self.assertEqual(len(chosen), 1)


if __name__ == "__main__":
    unittest.main()
