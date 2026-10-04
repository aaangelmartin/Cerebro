"""The step ladders (steps.py) against scripted dealers: the Saturday evening threads, replayed.

Each script is the dealer's side of a real thread; the ladder plays ours. What must hold whatever the dealer does:
one message per answer, never the same price twice, never past our limit, and after a final offer only accept
or close."""
from __future__ import annotations

import unittest

from bazaar.dealers import haggle, steps
from bazaar.dealers.tests import test_domain as T
from bazaar.dealers.threads import parse_thread

SIT, CTX = T.AuditFixes().sit, T.AuditFixes().ctx


def raw(dealer, side, card="SAL-09", asset=7, tid=50):
    topic = {"buy": {"card": card}} if side == "buy" else {"sell": {"assets": [asset]}}
    return {"id": tid, "kind": "persona", "with": dealer, "topic": topic, "status": "open", "created_tick": 1,
            "messages": [], "standing_offers": []}


def dealer_says(th, tick, price, final=False, card="SAL-09", asset=7):
    buying = "buy" in th["topic"]
    offer = {"id": 900 + len(th["messages"]), "maker": th["with"], "to": "t10", "final": final, "status": "open",
             "created_tick": tick,
             **({"give": {"types": [f"card:{card}"]}, "want": {"cash": price}} if buying
                else {"give": {"cash": price}, "want": {"assets": [asset]}})}
    th["messages"].append({"tick": tick, "sender": th["with"], "text": "…", "offer": offer})
    th["standing_offers"] = [offer]


def we_say(th, tick, price):
    th["messages"].append({"tick": tick, "sender": "t10", "text": f"{price} P", "price": price})


def play(dealer, side, script, limit, open_hint=None, budget_bound=False):
    """Run a ladder against the dealer's scripted prices [(price, final), ...]. Returns (moves, thread)."""
    prof = steps.profile_for(dealer, side)
    th, tick, moves = raw(dealer, side), 2, []
    for price, final in script:
        dealer_says(th, tick, price, final)
        v = parse_thread(th, {7: {"id": 7, "ref": "SAL-09"}})
        ok, why = haggle.acceptable(v, limit)
        m = steps.next_move(v, limit, tick + 1, prof, ok, why, open_hint=open_hint, budget_bound=budget_bound)
        moves.append(m)
        if m.kind != "price":
            break
        we_say(th, tick + 1, m.price)
        tick += 2
    return moves, th


class Ladders(unittest.TestCase):
    def assert_clean(self, moves, buying, limit):
        prices = [m.price for m in moves if m.kind == "price"]
        self.assertEqual(len(prices), len(set(prices)), "a price was repeated")
        self.assertEqual(prices, sorted(prices, reverse=not buying), "we went backwards")
        self.assertTrue(all((p <= limit) if buying else (p >= limit) for p in prices), "past our limit")

    def test_picaros_rare_small_steps_then_their_final(self):
        # thread 1693: 73, 66, 62, 58, final 55
        moves, _ = play("picaros", "buy", [(73, False), (66, False), (62, False), (58, False), (55, True)], limit=57)
        prices = [m.price for m in moves if m.kind == "price"]
        self.assertTrue(30 <= prices[0] <= 35, prices)
        self.assertTrue(all(2 <= b - a <= 4 for a, b in zip(prices, prices[1:])), prices)
        self.assertEqual((moves[-1].kind, moves[-1].price), ("accept", 55))
        self.assert_clean(moves, True, 57)

    def test_picaros_final_above_our_cap_closes(self):
        moves, _ = play("picaros", "buy", [(73, False), (66, False), (62, True)], limit=57)
        self.assertEqual(moves[-1].kind, "close")

    def test_pilar_opens_high_steps_of_three_takes_her_final(self):
        # thread 1637: she 70, 72, 75, 78, 81, final 84 against asks 105, 102, 99, 96, 93, 90
        script = [(70, False), (72, False), (75, False), (78, False), (81, False), (84, False), (84, True)]
        moves, _ = play("pilar", "sell", script, limit=72)
        prices = [m.price for m in moves if m.kind == "price"]
        self.assertEqual(prices[:6], [105, 102, 99, 96, 93, 90])
        self.assertEqual((moves[-1].kind, moves[-1].price), ("accept", 84))
        self.assert_clean(moves, False, 72)

    def test_no_counter_offer_after_a_final(self):
        # thread 1671: her final was 77 and a 93 sent after it closed the thread
        moves, th = play("pilar", "sell", [(70, False), (71, False), (77, True)], limit=72)
        self.assertEqual((moves[-1].kind, moves[-1].price), ("accept", 77))
        moves, _ = play("pilar", "sell", [(70, False), (71, True)], limit=72)        # final below our floor
        self.assertEqual(moves[-1].kind, "close")
        self.assertNotIn("price", [m.kind for m in moves[-1:]])

    def test_pilar_one_coin_apart_is_a_deal(self):
        # thread 1684: asks 92..81 against 70, 72, 75, 78, 80: our next step would cross her 80
        moves, _ = play("pilar", "sell", [(70, False), (72, False), (75, False), (78, False), (80, False)],
                        limit=72, open_hint=92)
        self.assertEqual([m.price for m in moves if m.kind == "price"], [92, 89, 86, 83])
        self.assertEqual((moves[-1].kind, moves[-1].price), ("accept", 80))

    def test_chato_never_gets_a_one_peseta_step(self):
        script = [(97, False), (95, False), (92, False), (89, False), (87, False), (86, False), (85, False),
                  (85, False), (85, False)]
        moves, _ = play("chato", "buy", script, limit=86)
        prices = [m.price for m in moves if m.kind == "price"]
        self.assertTrue(all(2 <= b - a <= 4 for a, b in zip(prices, prices[1:])), prices)
        self.assertLessEqual(len(prices), 8)
        self.assertEqual(moves[-1].kind, "accept")
        self.assert_clean(moves, True, 86)

    def test_abuela_uncommon_down_to_her_price(self):
        # thread 1619: she 18, 19, 19 against asks 24, 21, 20: the next step meets her 19
        moves, _ = play("abuela", "sell", [(18, False), (19, False), (19, False), (19, False)], limit=10)
        self.assertEqual([m.price for m in moves if m.kind == "price"], [24, 21, 20])
        self.assertEqual((moves[-1].kind, moves[-1].price), ("accept", 19))

    def test_one_message_per_answer(self):
        th = raw("pilar", "sell")
        dealer_says(th, 2, 70)
        we_say(th, 3, 105)
        v = parse_thread(th, {7: {"id": 7, "ref": "SAL-09"}})
        prof = steps.profile_for("pilar", "sell")
        for tick in (4, 6, 9):
            self.assertEqual(steps.next_move(v, 72, tick, prof, False).kind, "wait")

    def test_cash_short_waits_then_frees_the_thread(self):
        # thread 1600 sat ten ticks on a 45 P bid, its cash cap: now two ticks, then close; never the same price
        th = raw("picaros", "buy")
        dealer_says(th, 2, 73)
        we_say(th, 3, 45)
        dealer_says(th, 4, 60)
        v = parse_thread(th)
        prof = steps.profile_for("picaros", "buy")
        ok, why = haggle.acceptable(v, 45)
        self.assertEqual(steps.next_move(v, 45, 5, prof, ok, why, budget_bound=True).kind, "wait")
        self.assertEqual(steps.next_move(v, 45, 6, prof, ok, why, budget_bound=True).kind, "close")
        self.assertEqual(steps.next_move(v, 48, 5, prof, False, budget_bound=True).price, 48)   # cash for a step

    def test_brain_order_messages(self):
        prof = steps.profile_for("pilar", "sell")
        self.assertEqual(steps.messages_for(prof, None), 8)
        self.assertEqual(steps.messages_for(prof, {"max_messages": 4}), 8)      # never cuts the ladder short
        self.assertEqual(steps.messages_for(prof, {"max_messages": 1}), 1)      # "close fast" is kept


class InTheDomain(unittest.TestCase):
    ASSETS = [{"id": 2, "kind": "card", "ref": "LAT-06", "rarity": "uncommon", "set": "LAT", "your_value": 8.0},
              {"id": 3, "kind": "card", "ref": "LAT-06", "rarity": "uncommon", "set": "LAT", "your_value": 8.0}]

    def sell_thread(self, final):
        th = {"id": 304, "kind": "persona", "with": "abuela", "topic": {"sell": {"assets": [2]}}, "status": "open",
              "created_tick": 1, "messages": [], "standing_offers": []}
        dealer_says(th, 2, 18, asset=2)
        we_say(th, 3, 24)
        dealer_says(th, 4, 19, final=final, asset=2)
        return th

    def test_claude_cannot_counter_a_final_or_leave_the_ladder(self):
        for final, kind in ((True, "accept_offer"), (False, "thread_message")):
            llm = T.FakeLLM({"threads": [{"thread": 304, "move": "price", "price": 30, "text": "30 P.",
                                           "reason": "more"}], "open": [], "note": "", "lesson_ids": []})
            dom = T.domain(llm)
            acts = [a for a in dom.decide(SIT(tick=5, threads=[self.sell_thread(final)], assets=self.ASSETS), CTX(5))
                    if a.kind in ("thread_message", "accept_offer", "close_thread")]
            self.assertEqual([a.kind for a in acts], [kind])
            if not final:
                self.assertEqual(acts[0].params["price"], 21)         # the ladder's step, not Claude's 30

    def test_budget_closed_dealer_is_left_alone_for_an_hour(self):
        dom = T.domain()
        dom.store.data["threads"]["77"] = {"dealer": "abuela", "side": "sell", "item": "LAT-06", "opened_tick": 3}
        sit = SIT(tick=5, assets=self.ASSETS)
        sit.closed_threads = [{"id": 77, "status": "closed", "closed_reason": "persona_budget"}]
        self.assertNotIn("abuela", dom._prepare(sit, CTX(5)).free)
        self.assertTrue(dom.store.budget_blocked("abuela", 100))
        self.assertFalse(dom.store.budget_blocked("abuela", 126))
        self.assertIn("abuela", dom._prepare(SIT(tick=126, assets=self.ASSETS), CTX(126)).free)


class Loop(unittest.TestCase):
    def order(self, **kw):
        return {"dealer": "chato", "action": "buy", "ref": "LAV-09", "open": None, "bound": 90, "max_messages": 8,
                "why": "", "resell_to": "abuela", **kw}

    def plan_with(self, dom, orders, tick=5):
        import bazaar.brain.strategy as S
        old, S.dealer_orders = S.dealer_orders, lambda live=None: list(orders)
        try:
            return dom._prepare(SIT(tick=tick), CTX(tick))
        finally:
            S.dealer_orders = old

    def test_no_proven_resale_no_buy(self):
        dom = T.domain()
        plan = self.plan_with(dom, [self.order()])
        self.assertFalse([c for c in plan.candidates if c.id.startswith("o")])

    def test_proven_resale_caps_the_buy_and_queues_the_sale(self):
        dom = T.domain()
        for price in (99, 104):
            dom.store.record_deal("abuela", 1, "sell:rare", "LAV-10", 80, price, 100.0, False, 60.0)
        plan = self.plan_with(dom, [self.order()])
        cands = [c for c in plan.candidates if c.id.startswith("o")]
        self.assertEqual(len(cands), 1)
        self.assertLessEqual(cands[0].limit, 99 - 15)                 # the worst proven sale minus the margin
        # the buy closes at 80: the card goes to the resale dealer at 95 or more
        dom._finish(9, {"dealer": "chato", "side": "buy", "item": "LAV-09", "accepted": 80, "opening": 97,
                        "theirs": [97, 80], "ours": [60, 76], "kind": "buy:rare"}, None, {}, plan.dealers, 6)
        sells = [o for o in dom._brain_orders() if o.get("loop")]
        self.assertEqual([(o["dealer"], o["action"], o["ref"], o["bound"]) for o in sells],
                         [("abuela", "sell", "LAV-09", 95)])

    def test_plan_keeps_resell_to_only_on_buys(self):
        from bazaar.brain.strategy import _dealer_orders
        out = _dealer_orders([{"dealer": "picaros", "action": "buy", "ref": "SAL-09", "cap": 57, "resell_to": "pilar"},
                              {"dealer": "pilar", "action": "sell", "ref": "SAL-10", "floor": 74, "resell_to": "chato"}])
        self.assertEqual(out[0].get("resell_to"), "pilar")
        self.assertNotIn("resell_to", out[1])


if __name__ == "__main__":
    unittest.main()
