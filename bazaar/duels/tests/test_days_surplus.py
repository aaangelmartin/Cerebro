"""Sunday, Duels III: an offer inside the price limit can still lose once the delivery days count.

Duel 11544 (buyer, limit 105, each day costs 5.83): "75 P with 10 days" was accepted -> 75 + 58.3 > 105 = -28.3.
Duel 11231 (buyer, limit 50, each day costs 3.37): "33 P with 10 days" -> -15.1 after one round.
"""
import json
import os
import unittest

from bazaar.core.types import Action
from bazaar.core.rails import rail_duel
from bazaar.duels.model import MIN_SURPLUS, parse_duel
from bazaar.duels.policy import Move, choose_days, guard, plan, replace_losing_offer

COSTS = "each delivery day costs you this much cash"
ADDS = "each delivery day adds this much cash to your side"
RECORD = os.path.join(os.path.dirname(__file__), "..", "..", "data", "record", "duels", "2026-10-04.jsonl")


def raw(did=11544, role="buyer", limit=105, w=5.83, meaning=COSTS, your_offer=None, rival_offer=None, messages=None):
    return {"duel": did, "session": 4, "status": "live", "role": role, "item": "Cine Doré",
            "issues": ["price", "days"], "your_days_weight": w, "days_meaning": meaning, "your_limit": limit,
            "rival": "Rival Oro", "deadline_tick": 1955, "decay_per_round": 0.1, "rounds": 0,
            "your_offer": your_offer, "rival_offer": rival_offer, "result": None, "messages": messages or []}


def view(**kw):
    return parse_duel(raw(**kw), 1943)


class Sit:
    def __init__(self, duel):
        self.duels = [duel]


class TestDaysSurplus(unittest.TestCase):
    def test_11544_claude_opening_with_ten_days_never_goes_out_at_a_loss(self):
        v = view()
        mv, notes = guard(v, Move("offer", 75, 10, text="Offering 75 primas with 10 delivery days.", source="opus"))
        self.assertEqual((mv.action, mv.price, mv.days), ("offer", 75, 0))
        self.assertGreaterEqual(v.utility(mv.price, mv.days), MIN_SURPLUS)
        self.assertIn("in 0 days", mv.text)
        self.assertNotIn("10", mv.text)
        self.assertTrue(notes)

    def test_11231_counter_with_ten_days(self):
        v = view(did=11231, limit=50, w=3.37, rival_offer={"id": 12966, "price": 39, "tick": 1916, "days": 10})
        mv, _ = guard(v, Move("offer", 33, 10, text="33 primas with 10 delivery days.", source="opus"))
        self.assertEqual((mv.action, mv.days), ("offer", 0))
        self.assertGreaterEqual(v.utility(mv.price, mv.days), MIN_SURPLUS)

    def test_accepting_a_rival_package_that_loses_with_days_is_refused(self):
        v = view(did=11231, limit=50, w=3.37, rival_offer={"id": 12966, "price": 39, "tick": 1916, "days": 10})
        mv, notes = guard(v, Move("accept", source="opus"))
        self.assertNotEqual(mv.action, "accept")
        self.assertTrue(notes)

    def test_days_follow_the_sign_the_game_gives_not_the_role(self):
        self.assertEqual(choose_days(view()), 0)
        self.assertEqual(choose_days(view(role="seller", limit=70, w=4.78, meaning=ADDS)), 10)
        # the wording decides, even in the unusual role
        self.assertEqual(choose_days(view(role="seller", limit=70, w=4.78, meaning=COSTS)), 0)
        self.assertEqual(choose_days(view(role="buyer", limit=105, w=4.78, meaning=ADDS)), 10)

    def test_day_prior_no_longer_gives_days_away(self):
        v = view()
        v.rival_w_prior = 9.0                        # the rival is thought to care more: still 0 days for us
        self.assertEqual(choose_days(v, 40.0), 0)
        s = view(role="seller", limit=70, w=4.78, meaning=ADDS)
        s.rival_w_prior = 9.0
        self.assertEqual(choose_days(s, 40.0), 10)

    def test_seller_offer_is_raised_to_ten_days(self):
        v = view(role="seller", limit=70, w=4.78, meaning=ADDS)
        mv, _ = guard(v, Move("offer", 88, 0, text="88 P.", source="opus"))
        self.assertEqual((mv.price, mv.days), (88, 10))

    def test_code_plan_is_positive_with_days(self):
        for v in (view(), view(did=11231, limit=50, w=3.37,
                               rival_offer={"id": 1, "price": 39, "tick": 1943, "days": 10}),
                  view(role="seller", limit=70, w=4.78, meaning=ADDS)):
            v.rival_w_prior = 9.0
            mv, _ = guard(v, plan(v, {"pie_estimate": 36.8}))
            if mv.action == "offer":
                self.assertGreaterEqual(v.utility(mv.price, mv.days), MIN_SURPLUS)

    def test_losing_standing_offer_is_replaced(self):
        v = view(did=11628, limit=109, w=6.42, your_offer={"id": 9, "price": 50, "tick": 1961, "days": 10},
                 messages=[{"tick": 1961, "from": "you", "text": "50 P with 10 days", "price": 50, "days": 10}])
        self.assertLess(v.utility(50, 10), MIN_SURPLUS)
        mv, notes = replace_losing_offer(v, Move("wait", source="fallback"))
        self.assertEqual((mv.action, mv.price, mv.days), ("offer", 50, 0))
        self.assertTrue(notes)
        ok = view(your_offer={"id": 9, "price": 75, "tick": 1943, "days": 0})
        self.assertEqual(replace_losing_offer(ok, Move("wait"))[0].action, "wait")

    def test_rail_vetoes_message_and_accept_that_lose_with_days(self):
        d = raw()
        bad = Action(kind="duel_message", params={"duel": 11544, "price": 75, "days": 10, "text": "75"}, domain="duels")
        self.assertFalse(rail_duel(bad, Sit(d)).ok)
        good = Action(kind="duel_message", params={"duel": 11544, "price": 75, "days": 0, "text": "75"}, domain="duels")
        self.assertTrue(rail_duel(good, Sit(d)).ok)
        acc = Action(kind="duel_accept", params={"duel": 11544, "expect": {"id": 1, "price": 80, "days": 10}},
                     domain="duels")
        self.assertFalse(rail_duel(acc, Sit(d)).ok)
        s = raw(role="seller", limit=70, w=4.78, meaning=ADDS)
        sell = Action(kind="duel_message", params={"duel": 11544, "price": 88, "days": 10, "text": "88"}, domain="duels")
        self.assertTrue(rail_duel(sell, Sit(s)).ok)

    @unittest.skipUnless(os.path.exists(RECORD), "no recorded duels on this machine")
    def test_recorded_sunday_duels_no_message_of_ours_survives_at_a_loss(self):
        """Every priced message we sent on Sunday, replayed through the guard and the rail: what comes out is
        worth >= MIN_SURPLUS with its days, and the rail refuses the original whenever it lost."""
        heads, n, lost = {}, 0, 0
        with open(RECORD, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r.get("head"), dict):
                heads.setdefault(r["duel"], r["head"])
            h = heads.get(r.get("duel"))
            for m in r.get("messages_new") or []:
                if h is None or m.get("from") != "you" or m.get("price") is None:
                    continue
                d = {**h, "status": "live", "result": None, "your_offer": None, "rival_offer": None, "rounds": 0}
                v = parse_duel(d, int(m.get("tick") or 0))
                if v is None or not v.uses_days or v.surplus(m["price"]) < MIN_SURPLUS:
                    continue
                n += 1
                u = v.utility(m["price"], m.get("days"))
                act = Action(kind="duel_message", domain="duels",
                             params={"duel": r["duel"], "price": m["price"], "days": m.get("days"), "text": "x"})
                if u < MIN_SURPLUS:
                    lost += 1
                    self.assertFalse(rail_duel(act, Sit(d)).ok, m)
                mv, _ = guard(v, Move("offer", m["price"], m.get("days"), text=m.get("text") or ""))
                if mv.action == "offer":
                    self.assertGreaterEqual(v.utility(mv.price, mv.days), MIN_SURPLUS, m)
                    self.assertGreaterEqual(v.utility(mv.price, mv.days), u, m)
        self.assertGreater(n, 50)
        self.assertGreaterEqual(lost, 2)


if __name__ == "__main__":
    unittest.main()
