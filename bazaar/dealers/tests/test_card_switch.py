"""Outbox request code-87136b11: a trickster dealer (Los Pícaros) slips another card into some of its offers.
We never accept such an offer and never walk at the first switch: we repeat our bid naming the card we asked
for, and close only after two switches in a row or once our messages are used."""
from __future__ import annotations

import unittest

from bazaar.dealers.tests import test_domain as T
from bazaar.dealers.threads import parse_thread

domain = T.domain
SIT, CTX = T.AuditFixes().sit, T.AuditFixes().ctx
CARD, OTHER = "LAV-07", "LAV-06"


def thread(rows, tid=10, dealer="abuela", final=False):
    """rows in time order: ("d", tick, price, card) for a dealer offer, ("u", tick, price) for our bid."""
    msgs, standing, n = [], [], 0
    for r in rows:
        if r[0] == "d":
            n += 1
            offer = {"id": 900 + n, "maker": dealer, "to": "t10", "give": {"types": [f"card:{r[3]}"]},
                     "want": {"cash": r[2]}, "final": final, "status": "open", "created_tick": r[1]}
            msgs.append({"tick": r[1], "sender": dealer, "text": "look!", "offer": offer})
            standing = [offer]
        else:
            msgs.append({"tick": r[1], "sender": "t10", "text": f"{r[2]} P", "price": r[2]})
    return {"id": tid, "kind": "persona", "with": dealer, "topic": {"buy": {"card": CARD}}, "status": "open",
            "created_tick": 1, "messages": msgs, "standing_offers": standing}


def acts_for(dom, th, tick):
    return [a for a in dom.fallback(SIT(tick=tick, threads=[th]), CTX(tick))
            if a.kind in ("thread_message", "close_thread", "accept_offer")]


class ParseSwitch(unittest.TestCase):
    def test_other_card_is_not_a_price_for_ours(self):
        v = parse_thread(thread([("d", 2, 27, CARD), ("u", 3, 12), ("d", 4, 20, OTHER)]))
        self.assertEqual((v.theirs, v.standing, v.switched, v.switched_to), ([27], None, 1, OTHER))

    def test_right_card_resets_the_count(self):
        v = parse_thread(thread([("d", 2, 27, OTHER), ("u", 3, 12), ("d", 4, 22, CARD)]))
        self.assertEqual((v.theirs, v.standing_price, v.switched, v.switched_to), ([22], 22, 0, ""))

    def test_asked_card_wins_over_a_topic_the_dealer_changed(self):
        raw = thread([("d", 2, 27, OTHER)])
        raw["topic"] = {"buy": {"card": OTHER}}
        v = parse_thread(raw, asked=CARD)
        self.assertEqual((v.item, v.switched), (CARD, 1))


class SwitchedCard(unittest.TestCase):
    def test_rebids_and_neither_accepts_nor_closes(self):
        dom = domain()
        acts = acts_for(dom, thread([("d", 2, 27, CARD), ("u", 3, 12), ("d", 4, 13, OTHER)]), 5)
        self.assertEqual([a.kind for a in acts], ["thread_message"])
        self.assertEqual(acts[0].params["price"], 12)                       # the same bid, no concession
        self.assertIn(CARD, acts[0].params["text"])
        self.assertIn(OTHER, acts[0].reason)

    def test_claude_cannot_close_or_accept_it(self):
        dom = domain()
        plan = dom._prepare(SIT(tick=5, threads=[thread([("d", 2, 27, CARD), ("u", 3, 12), ("d", 4, 13, OTHER)])]), CTX(5))
        for mv in ("close", "accept"):
            acts = dom._apply_llm(plan, CTX(5), {"threads": [{"thread": 10, "move": mv, "reason": "x"}]})
            self.assertEqual([(a.kind, a.params.get("price")) for a in acts], [("thread_message", 12)])

    def test_wrong_card_on_the_opening(self):
        dom = domain()
        acts = acts_for(dom, thread([("d", 2, 27, OTHER)]), 3)
        self.assertEqual([a.kind for a in acts], ["thread_message"])
        info = dom._prepare(SIT(tick=3, threads=[thread([("d", 2, 27, OTHER)])]), CTX(3)).infos[0]
        self.assertTrue(1 <= acts[0].params["price"] <= info.limit)
        self.assertIn(CARD, acts[0].params["text"])

    def test_waits_for_the_answer_to_our_rebid(self):
        dom = domain()
        th = thread([("d", 2, 27, CARD), ("u", 3, 12), ("d", 4, 13, OTHER), ("u", 5, 12)])
        self.assertFalse(acts_for(dom, th, 6))

    def test_back_to_our_card_is_accepted_inside_the_cap(self):
        dom = domain()
        rows = [("d", 2, 27, CARD), ("u", 3, 12), ("d", 4, 13, OTHER), ("u", 5, 12), ("d", 6, 13, CARD)]
        info = dom._prepare(SIT(tick=7, threads=[thread(rows, final=True)]), CTX(7)).infos[0]
        self.assertGreaterEqual(info.limit, 13)
        acts = acts_for(dom, thread(rows, final=True), 7)
        self.assertEqual([a.kind for a in acts], ["accept_offer"])
        self.assertEqual(acts[0].params["offer"], 903)                      # the offer for our card, not 902

    def test_final_offer_for_another_card_is_never_accepted(self):
        dom = domain()
        acts = acts_for(dom, thread([("d", 2, 27, CARD), ("u", 3, 12), ("d", 4, 13, OTHER)], final=True), 5)
        self.assertNotIn("accept_offer", [a.kind for a in acts])

    def test_two_switches_in_a_row_close(self):
        dom = domain()
        th = thread([("d", 2, 27, CARD), ("u", 3, 12), ("d", 4, 20, OTHER), ("u", 5, 12), ("d", 6, 18, OTHER)])
        acts = acts_for(dom, th, 7)
        self.assertEqual([a.kind for a in acts], ["close_thread"])
        self.assertIn("in a row", acts[0].reason)

    def test_closes_once_the_messages_are_used(self):
        dom = domain()
        rows = [("d", 2, 27, CARD)]
        for i in range(5):
            rows += [("u", 3 + 2 * i, 8 + i), ("d", 4 + 2 * i, 26 - i, CARD)]
        rows[-1] = ("d", 12, 20, OTHER)
        self.assertEqual([a.kind for a in acts_for(dom, thread(rows), 13)], ["close_thread"])


if __name__ == "__main__":
    unittest.main()
