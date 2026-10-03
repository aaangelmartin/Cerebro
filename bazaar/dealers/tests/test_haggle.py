"""Guards and the code-only tactic: the invariants the dealers domain must never break."""
from __future__ import annotations

import unittest

from bazaar.dealers import haggle
from bazaar.dealers.threads import parse_thread

DEALER = "abuela"


def offer(oid, price, buying=True, final=False, item="card:LAV-07", assets=(5,)):
    if buying:
        give, want = {"cash": 0, "assets": [], "types": [item]}, {"cash": price, "assets": [], "types": []}
    else:
        give, want = {"cash": price, "assets": [], "types": []}, {"cash": 0, "assets": list(assets), "types": []}
    return {"id": oid, "maker": DEALER, "to": "t10", "status": "open", "give": give, "want": want, "final": final,
            "created_tick": oid}


def thread(theirs, ours, buying=True, final=False, topic=None, last="dealer"):
    """Alternating messages: dealer opening, then (ours[i], theirs[i+1])..."""
    topic = topic or ({"buy": {"card": "LAV-07"}} if buying else {"sell": {"assets": [5]}})
    msgs, offers = [], []
    tick = 1
    for i, p in enumerate(theirs):
        o = offer(100 + i, p, buying, final and i == len(theirs) - 1)
        msgs.append({"id": 1000 + 2 * i, "tick": tick, "sender": DEALER, "text": f"{p} P", "offer": o})
        offers = [o]
        tick += 1
        if i < len(ours):
            msgs.append({"id": 1001 + 2 * i, "tick": tick, "sender": "t10", "text": "", "price": ours[i]})
            tick += 1
    if len(ours) > len(theirs):
        msgs.append({"id": 5000, "tick": tick, "sender": "t10", "text": "", "price": ours[-1]})
    raw = {"id": 7, "kind": "persona", "with": DEALER, "topic": topic, "status": "open", "created_tick": 0,
           "messages": msgs, "standing_offers": offers}
    return parse_thread(raw, {5: {"id": 5, "ref": "SAL-07", "rarity": "uncommon"}})


class Limits(unittest.TestCase):
    def test_buy_max_below_value_with_margin(self):
        for v in (5, 16, 40, 112, 300):
            self.assertLessEqual(haggle.buy_max(v), v - max(3, 0.1 * v))

    def test_sell_min_above_value_with_margin(self):
        for v in (1.25, 5.6, 22.5, 63):
            self.assertGreaterEqual(haggle.sell_min(v), v + max(1, 0.1 * v))


class Parse(unittest.TestCase):
    def test_parse_buy_thread(self):
        v = thread([29, 27, 25], [12, 15])
        self.assertEqual(v.side, "buy")
        self.assertEqual(v.item, "LAV-07")
        self.assertEqual(v.opening, 29)
        self.assertEqual(v.theirs, [29, 27, 25])
        self.assertEqual(v.ours, [12, 15])
        self.assertEqual(v.standing_price, 25)
        self.assertEqual(v.last_sender, "dealer")

    def test_parse_sell_thread(self):
        v = thread([13, 13, 14], [23, 22], buying=False)
        self.assertEqual(v.side, "sell")
        self.assertEqual(v.item, "SAL-07")
        self.assertEqual(v.asset_ids, [5])
        self.assertEqual(v.their_concessions(), [0, 1])

    def test_team_thread_is_ignored(self):
        self.assertIsNone(parse_thread({"id": 1, "kind": "team", "with": "t05", "topic": {}}))


class Guards(unittest.TestCase):
    def test_never_accept_opening_price(self):
        v = thread([24], [])
        ok, why = haggle.acceptable(v, limit=36)
        self.assertFalse(ok)
        self.assertIn("opening", why)
        v = thread([24, 24, 24], [12, 13], final=True)
        self.assertFalse(haggle.acceptable(v, 36)[0])
        self.assertEqual(haggle.fallback_move(v, 36, 20, tick=10).kind, "close")

    def test_never_accept_above_limit(self):
        v = thread([29, 26], [12])
        self.assertFalse(haggle.acceptable(v, limit=25)[0])
        self.assertTrue(haggle.acceptable(v, limit=26)[0])

    def test_sell_never_below_min_or_at_opening(self):
        v = thread([13, 14], [23], buying=False)
        self.assertFalse(haggle.acceptable(v, limit=15)[0])
        self.assertTrue(haggle.acceptable(v, limit=14)[0])
        self.assertFalse(haggle.acceptable(thread([13], [], buying=False), limit=7)[0])

    def test_never_repeat_or_go_back(self):
        v = thread([29, 27], [15])
        self.assertEqual(haggle.guard_price(v, 15, 30), 16)      # repeat -> moved on by 1
        self.assertEqual(haggle.guard_price(v, 10, 30), 16)      # backwards -> clamped
        self.assertEqual(haggle.guard_price(v, 40, 30), 26)      # past their price -> just below it

    def test_no_price_past_our_limit(self):
        v = thread([29, 27], [15])
        self.assertEqual(haggle.guard_price(v, 25, 18), 18)
        v = thread([29, 27], [18])
        self.assertIsNone(haggle.guard_price(v, 25, 18))         # nothing legal left
        self.assertEqual(haggle.fallback_move(v, 18, 20, tick=10).kind, "close")

    def test_wrong_structure_is_not_accepted(self):
        v = thread([29, 25], [12])
        v.standing["give"]["types"] = ["card:LAV-01"]            # dealer swapped the card
        self.assertFalse(haggle.acceptable(v, 36)[0])
        v = thread([29, 25], [12])
        v.standing["want"]["assets"] = [99]                      # dealer asks for a card too
        self.assertFalse(haggle.acceptable(v, 36)[0])


class Tactic(unittest.TestCase):
    def test_anchor_is_below_estimated_limit(self):
        v = thread([29], [])
        p = haggle.plan_next(v, limit=36, limit_est=23, patience=6)
        self.assertLess(p, 23 - 5)

    def test_waits_for_dealer_answer(self):
        v = thread([29], [15])
        self.assertEqual(v.last_sender, "us")
        self.assertEqual(haggle.fallback_move(v, 36, 23, tick=3).kind, "wait")

    def test_accepts_final_inside_limit(self):
        v = thread([29, 26, 24, 22], [12, 16, 19], final=True)
        m = haggle.fallback_move(v, 36, 23, tick=20)
        self.assertEqual((m.kind, m.price), ("accept", 22))

    def test_one_p_steps_after_stall(self):
        v = thread([29, 25, 23, 23, 23], [12, 18, 20, 21])
        self.assertGreaterEqual(haggle.stalled(v), 2)
        m = haggle.fallback_move(v, 22, 23, tick=20)
        # stalled twice and still above our limit: 1 P step to our limit
        self.assertEqual((m.kind, m.price), ("price", 22))


if __name__ == "__main__":
    unittest.main()
