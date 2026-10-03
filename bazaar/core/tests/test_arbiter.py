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
    def test_duel_accept_does_not_take_the_trade_accept(self):
        # the game limits offer accepts (1 per tick) and duel accepts separately: both go out in the same tick
        acc = Action("accept_offer", {"offer": 1, "expect": {}}, "market", priority=50)
        duel = Action("duel_accept", {"duel": 9, "expect": {}}, "duels", priority=1)
        chosen, dropped = select([acc, duel], sit(), budget())
        self.assertEqual(sorted(a.kind for a in chosen), ["accept_offer", "duel_accept"])
        self.assertEqual(dropped, [])

    def test_each_accept_budget_is_enforced_on_its_own(self):
        accs = [Action("accept_offer", {"offer": i, "expect": {}}, "market", priority=10 + i) for i in (1, 2)]
        duels = [Action("duel_accept", {"duel": i, "expect": {}}, "duels", priority=1) for i in (7, 8)]
        chosen, dropped = select(accs + duels, sit(), budget(duel_accepts_left=1))
        self.assertEqual(sorted(a.kind for a in chosen), ["accept_offer", "duel_accept"])
        whys = sorted(w for _, w in dropped)
        self.assertTrue(whys[0].startswith("accept already used this tick (cap 1 "))      # the number that blocked
        self.assertTrue(whys[1].startswith("duel accepts already used this tick (cap "))

    def test_spent_trade_accept_leaves_duel_accepts_alone(self):
        duel = Action("duel_accept", {"duel": 9, "expect": {}}, "duels", priority=1)
        chosen, _ = select([duel], sit(), budget(accepts_left=0))
        self.assertEqual([a.kind for a in chosen], ["duel_accept"])

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
        chosen, _ = select([m1, m3], sit(), budget(messages={"duel:9": 1}))
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


class AcceptScale(unittest.TestCase):
    def test_dealer_final_beats_a_duel_that_can_wait_but_not_an_urgent_one(self):
        final = Action("accept_offer", {"offer": 5, "expect": {}}, "dealers", priority=140)
        calm = Action("duel_accept", {"duel": 9, "expect": {}}, "duels", priority=110)
        urgent = Action("duel_accept", {"duel": 8, "expect": {}}, "duels", priority=152)
        self.assertEqual(select([calm, final], sit(), budget())[0][0].priority, 140)
        self.assertEqual(select([calm, final, urgent], sit(), budget())[0][0].priority, 152)


class AcceptFallbackMessage(unittest.TestCase):
    """An accept that loses the single slot is replaced by its fallback_message, not silence."""

    def acc(self, duel, prio, price=100):
        fm = {"duel": duel, "price": price, "text": f"Your terms work: {price} P."}
        return Action("duel_accept", {"duel": duel, "expect": {"price": price}, "fallback_message": fm}, "duels",
                      priority=prio)

    def test_loser_sends_its_alternative(self):
        a, b = self.acc(1, 160), self.acc(2, 120, price=90)
        chosen, dropped = select([b, a], sit(), budget(duel_accepts_left=1))
        self.assertEqual([(x.kind, x.params["duel"]) for x in chosen], [("duel_accept", 1), ("duel_message", 2)])
        alt = chosen[1]
        self.assertEqual(alt.params["price"], 90)
        self.assertEqual(alt.expected["alt_for"], b.id)
        self.assertEqual(dropped[0][0], b)

    def test_alternative_respects_one_message_per_conversation(self):
        a, b = self.acc(1, 160), self.acc(2, 120)
        chosen, _ = select([a, b], sit(), budget(duel_accepts_left=1, messages={"duel:2": 1}))
        self.assertEqual([x.kind for x in chosen], ["duel_accept"])
        other = Action("duel_message", {"duel": 2, "price": 95}, "duels", priority=500)
        chosen, dropped = select([a, b, other], sit(), budget(duel_accepts_left=1))
        self.assertEqual(sum(1 for x in chosen if x.params.get("duel") == 2), 1)

    def test_no_alternative_when_accepts_are_exhausted_without_one(self):
        x = Action("accept_offer", {"offer": 1, "expect": {}}, "market", priority=2)
        chosen, dropped = select([self.acc(1, 160), x], sit(), budget(accepts_left=0))
        self.assertEqual([c.kind for c in chosen], ["duel_accept"])
        self.assertEqual([d.kind for d, _ in dropped], ["accept_offer"])
