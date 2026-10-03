import unittest
from types import SimpleNamespace as NS

from bazaar.core.arbiter import select
from bazaar.core.types import Action

LIMITS = {"accepts_per_team_per_tick": 1, "messages_per_side_per_tick": 1, "max_open_threads_per_team": 6,
          "max_open_offers_per_team": 30, "offers_per_team_per_tick": 12}


def sit(**kw):
    base = dict(tick=10, limits=dict(LIMITS), threads=[], my_offers=[], duels=[], me={"cash": 300, "assets": []})
    base.update(kw)
    return NS(**base)


def budget(**kw):
    return {"accepts_left": 1, "messages": {}, "offers_left": 12, **kw}


class ArbiterTest(unittest.TestCase):
    def test_duel_accept_wins_the_accept(self):
        acc = Action("accept_offer", {"offer": 1, "expect": {}}, "market", priority=50)
        duel = Action("duel_accept", {"duel": 9, "expect": {}}, "duels", priority=1)
        chosen, dropped = select([acc, duel], sit(), budget())
        self.assertEqual([a.kind for a in chosen], ["duel_accept"])
        self.assertEqual(dropped[0][0].kind, "accept_offer")

    def test_highest_priority_accept(self):
        lo = Action("accept_offer", {"offer": 1, "expect": {}}, "market", priority=2)
        hi = Action("accept_offer", {"offer": 2, "expect": {}}, "dealers", priority=9)
        chosen, _ = select([lo, hi], sit(), budget())
        self.assertEqual(chosen, [hi])
        chosen, _ = select([lo, hi], sit(), budget(accepts_left=0))
        self.assertEqual(chosen, [])

    def test_one_message_per_conversation(self):
        m1 = Action("duel_message", {"duel": 9, "price": 5}, "duels", priority=1)
        m2 = Action("duel_message", {"duel": 9, "price": 6}, "duels", priority=2)
        m3 = Action("thread_message", {"thread": 4, "price": 6}, "dealers")
        chosen, dropped = select([m1, m2, m3], sit(), budget())
        self.assertEqual(chosen, [m2, m3])
        chosen, _ = select([m1, m3], sit(), budget(messages={"9": 1}))
        self.assertEqual(chosen, [m3])

    def test_listing_caps(self):
        offers = [Action("post_offer", {"venue": "rastro", "give": {"assets": [i]}, "want": {"cash": 9}}, "market")
                  for i in range(5)]
        chosen, _ = select(offers, sit(), budget(offers_left=3))
        self.assertEqual(len(chosen), 3)
        chosen, _ = select(offers, sit(my_offers=[{}] * 29), budget())
        self.assertEqual(len(chosen), 1)

    def test_card_promised_once(self):
        a = Action("post_offer", {"venue": "rastro", "give": {"assets": [7]}, "want": {"cash": 9}}, "market", priority=1)
        b = Action("post_offer", {"venue": "v2", "give": {"assets": [7]}, "want": {"cash": 8}}, "market", priority=2)
        chosen, dropped = select([a, b], sit(), budget())
        self.assertEqual(chosen, [b])
        self.assertIn("promised", dropped[0][1])

    def test_threads_and_noop_and_duplicates(self):
        open_ = [{"id": 1, "with": "abuela", "status": "open"}]
        o1 = Action("open_thread", {"with": "abuela", "topic": {}}, "dealers")
        o2 = Action("open_thread", {"with": "chato", "topic": {}}, "dealers")
        o3 = Action("open_thread", {"with": "chato", "topic": {}}, "dealers")
        chosen, dropped = select([o1, o2, o3, Action("noop", {}, "lab")], sit(threads=open_), budget())
        self.assertEqual(chosen, [o2])
        self.assertEqual(len(dropped), 3)

    def test_domain_order(self):
        lab = Action("close_thread", {"thread": 1}, "lab", priority=100)
        d = Action("duel_message", {"duel": 2, "price": 3}, "duels")
        chosen, _ = select([lab, d], sit(), budget())
        self.assertEqual(chosen, [d, lab])


if __name__ == "__main__":
    unittest.main()
