import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from bazaar.core import rails
from bazaar.core.types import Action

LIMITS = {"accepts_per_team_per_tick": 1, "messages_per_side_per_tick": 1, "max_open_threads_per_team": 6,
          "max_open_offers_per_team": 30, "offers_per_team_per_tick": 12}


def card(i, ref, value):
    return {"id": i, "kind": "card", "ref": ref, "set": ref[:3], "your_value": value}


def sit(**kw):
    base = dict(tick=10, limits=dict(LIMITS), threads=[], my_offers=[], duels=[], values={"LAV-09": 150.0},
                me={"cash": 300, "venue": "v99", "assets": [card(1, "LAV-03", 120.0), card(2, "SAL-01", 9.0), card(3, "SAL-01", 2.0),
                                            card(4, "MAL-02", 13.0), card(5, "LAT-04", 5.0)]})
    base.update(kw)
    return NS(**base)


def ctx(**kw):
    base = dict(tick=10, control={"armed": True}, budget={"accepts_left": 1, "messages": {}, "offers_left": 12,
                                                         "spend_hour": 0, "deals_by_team_hour": {}}, ledger=None)
    base.update(kw)
    return NS(**base)


def offer(give, want, maker="t3", oid=7, **kw):
    return {"id": oid, "maker": maker, "status": "open", "venue": "rastro", "give": give, "want": want, **kw}


def accept(o, **extra):
    return Action("accept_offer", {"offer": o["id"], "expect": o, **extra}, "market")


class ArmedRail(unittest.TestCase):
    def test_disarmed_vetoes_writes_not_noop(self):
        c = ctx(control={"armed": False})
        self.assertFalse(rails.check(Action("close_thread", {"thread": 1}, "dealers"), sit(), c).ok)
        self.assertTrue(rails.check(Action("noop", {}, "dealers"), sit(), c).ok)

    def test_stop_file(self):
        with tempfile.TemporaryDirectory() as d:
            stop = Path(d) / "STOP"
            with mock.patch.object(rails, "STOP_FILE", stop):
                self.assertTrue(rails.check(Action("close_thread", {"thread": 1}, "dealers"), sit(), ctx()).ok)
                stop.touch()
                v = rails.check(Action("close_thread", {"thread": 1}, "dealers"), sit(), ctx())
                self.assertEqual((v.ok, v.rail), (False, "armed"))

    def test_unknown_kind_and_flags(self):
        v = rails.check(Action("flag", {"message_id": 3}, "dealers"), sit(), ctx())
        self.assertEqual(v.rail, "fair_play")


class FreshRail(unittest.TestCase):
    def test_accept_needs_expect(self):
        v = rails.check(Action("accept_offer", {"offer": 7}, "market"), sit(), ctx())
        self.assertEqual(v.rail, "fresh")

    def test_verify_fresh_offer(self):
        o = offer({"cash": 0, "assets": [{"id": 50, "ref": "LAV-09"}], "types": []}, {"cash": 40, "assets": [], "types": []})
        a = accept(o)
        self.assertTrue(rails.verify_fresh(a, dict(o)).ok)
        self.assertFalse(rails.verify_fresh(a, None).ok)
        self.assertFalse(rails.verify_fresh(a, {**o, "want": {"cash": 41}}).ok)
        self.assertFalse(rails.verify_fresh(a, {**o, "give": {"assets": [51]}}).ok)
        self.assertFalse(rails.verify_fresh(a, {**o, "status": "taken"}).ok)
        self.assertFalse(rails.verify_fresh(a, {**o, "maker": "t4"}).ok)
        self.assertTrue(rails.verify_fresh(a, {**o, "give": {"assets": [50], "cash": 0}}).ok)   # ids vs dicts

    def test_verify_fresh_duel(self):
        duel = {"duel": 9, "status": "live", "rival_offer": {"id": 1, "price": 130, "days": 0, "tick": 5},
                "your_offer": {"id": 2, "price": 120, "tick": 4}}
        a = Action("duel_accept", {"duel": 9, "expect": {"id": 1, "price": 130}}, "duels")
        self.assertTrue(rails.verify_fresh(a, duel).ok)
        self.assertFalse(rails.verify_fresh(a, {**duel, "rival_offer": {"id": 3, "price": 140, "tick": 6}}).ok)
        self.assertFalse(rails.verify_fresh(a, {**duel, "your_offer": {"id": 4, "price": 125, "tick": 6}}).ok)
        self.assertFalse(rails.verify_fresh(a, {**duel, "status": "deal"}).ok)


class CardsRail(unittest.TestCase):
    def test_only_our_cards(self):
        a = Action("post_offer", {"venue": "rastro", "give": {"assets": [99]}, "want": {"cash": 50}}, "market")
        self.assertEqual(rails.check(a, sit(), ctx()).rail, "cards")

    def test_last_copy_of_scarce_set(self):
        a = Action("post_offer", {"venue": "rastro", "give": {"assets": [1]}, "want": {"cash": 500}}, "market")
        v = rails.check(a, sit(), ctx())
        self.assertEqual((v.rail, "last copy" in v.detail), ("cards", True))
        a.params["human_ok"] = True
        self.assertTrue(rails.check(a, sit(), ctx()).ok)
        # a spare of a non-scarce set is fine; the last SAL too (only LAV/MAL/RET are kept)
        ok = Action("post_offer", {"venue": "rastro", "give": {"assets": [3]}, "want": {"cash": 10}}, "market")
        self.assertTrue(rails.check(ok, sit(), ctx()).ok)

    def test_protected(self):
        a = Action("post_offer", {"venue": "rastro", "give": {"assets": [5]}, "want": {"cash": 20}}, "market")
        self.assertTrue(rails.check(a, sit(), ctx()).ok)
        self.assertEqual(rails.check(a, sit(), ctx(control={"armed": True, "protected": ["LAT-04"]})).rail, "cards")
        self.assertEqual(rails.check(a, sit(), ctx(control={"armed": True, "protected": [5]})).rail, "cards")

    def test_accept_wanting_a_type_we_lack(self):
        o = offer({"cash": 30}, {"types": ["card:CHA-01"]})
        self.assertEqual(rails.check(accept(o), sit(), ctx()).rail, "cards")

    def test_sell_thread_last_copy(self):
        th = {"id": 4, "with": "chato", "status": "open", "topic": {"sell": {"assets": [4]}}, "messages": []}
        a = Action("thread_message", {"thread": 4, "price": 30, "text": "30?"}, "dealers")
        self.assertEqual(rails.check(a, sit(threads=[th]), ctx()).rail, "cards")


class DuelRail(unittest.TestCase):
    def s(self, role, limit, issues=("price",)):
        return sit(duels=[{"duel": 9, "status": "live", "role": role, "your_limit": limit, "issues": list(issues)}])

    def test_seller_and_buyer_limits(self):
        sell = self.s("seller", 100)
        self.assertFalse(rails.check(Action("duel_message", {"duel": 9, "price": 100}, "duels"), sell, ctx()).ok)
        self.assertTrue(rails.check(Action("duel_message", {"duel": 9, "price": 101}, "duels"), sell, ctx()).ok)
        buy = self.s("buyer", 158)
        self.assertFalse(rails.check(Action("duel_message", {"duel": 9, "price": 158}, "duels"), buy, ctx()).ok)
        self.assertTrue(rails.check(Action("duel_message", {"duel": 9, "price": 157}, "duels"), buy, ctx()).ok)

    def test_accept_uses_rival_price(self):
        buy = self.s("buyer", 158)
        bad = Action("duel_accept", {"duel": 9, "expect": {"id": 1, "price": 160}}, "duels")
        good = Action("duel_accept", {"duel": 9, "expect": {"id": 1, "price": 150}}, "duels")
        self.assertEqual(rails.check(bad, buy, ctx()).rail, "duel")
        self.assertTrue(rails.check(good, buy, ctx()).ok)

    def test_days(self):
        s2 = self.s("seller", 50, ("price", "days"))
        self.assertEqual(rails.check(Action("duel_message", {"duel": 9, "price": 60}, "duels"), s2, ctx()).rail, "duel")
        self.assertEqual(rails.check(Action("duel_message", {"duel": 9, "price": 60, "days": 11}, "duels"), s2, ctx()).rail,
                         "duel")
        self.assertTrue(rails.check(Action("duel_message", {"duel": 9, "price": 60, "days": 10}, "duels"), s2, ctx()).ok)

    def test_unknown_duel(self):
        self.assertEqual(rails.check(Action("duel_message", {"duel": 1, "price": 5}, "duels"), sit(), ctx()).rail, "duel")


class ValueRail(unittest.TestCase):
    def test_buy_card_below_value(self):
        give = {"assets": [{"id": 50, "ref": "LAV-09"}]}
        self.assertTrue(rails.check(accept(offer(give, {"cash": 100})), sit(), ctx()).ok)
        self.assertEqual(rails.check(accept(offer(give, {"cash": 150})), sit(), ctx()).rail, "value")

    def test_value_from_ctx_function(self):
        give = {"assets": [{"id": 50, "ref": "MAL-09"}]}
        a = accept(offer(give, {"cash": 30}))
        self.assertEqual(rails.check(a, sit(), ctx()).rail, "value")             # unknown value -> veto
        self.assertTrue(rails.check(a, sit(), ctx(value=lambda ref: 40.0)).ok)

    def test_sell_above_value(self):
        sell = lambda p: Action("post_offer", {"venue": "rastro", "give": {"assets": [2]}, "want": {"cash": p}}, "market")
        self.assertEqual(rails.check(sell(9), sit(), ctx()).rail, "value")
        self.assertTrue(rails.check(sell(10), sit(), ctx()).ok)

    def test_dealer_pack_uses_hint(self):
        th = {"id": 4, "with": "abuela", "status": "open", "topic": {"buy": {"pack": "sobre_barrio"}}, "messages": []}
        a = Action("thread_message", {"thread": 4, "price": 22, "text": "22?"}, "dealers")
        self.assertEqual(rails.check(a, sit(threads=[th]), ctx()).rail, "value")
        a.expected["value_get"] = 30
        self.assertTrue(rails.check(a, sit(threads=[th]), ctx()).ok)

    def test_dealer_item_from_its_offer(self):
        th = {"id": 4, "with": "abuela", "status": "open", "topic": {"buy": {"rarity": "rare", "set": "LAV"}},
              "messages": [{"offer": {"maker": "abuela", "give": {"types": ["card:LAV-09"]}, "want": {"cash": 160}}}]}
        mk = lambda p: Action("thread_message", {"thread": 4, "price": p, "text": "?"}, "dealers")
        c = ctx(control={"armed": True, "max_spend_per_deal": 200})
        self.assertTrue(rails.check(mk(140), sit(threads=[th]), c).ok)
        self.assertEqual(rails.check(mk(155), sit(threads=[th]), c).rail, "value")


class CashRail(unittest.TestCase):
    def buy(self, p):
        return accept(offer({"assets": [{"id": 50, "ref": "LAV-09"}]}, {"cash": p}))

    def test_reserve(self):
        s = sit(me={**sit().me, "cash": 120}, values={"LAV-09": 500.0})
        self.assertEqual(rails.check(self.buy(90), s, ctx()).rail, "cash")
        self.assertTrue(rails.check(self.buy(80), s, ctx()).ok)

    def test_per_deal_and_hour(self):
        s = sit(me={**sit().me, "cash": 1000}, values={"LAV-09": 500.0})
        self.assertEqual(rails.check(self.buy(121), s, ctx()).rail, "cash")
        c = ctx()
        c.budget["spend_hour"] = 200
        self.assertEqual(rails.check(self.buy(60), s, c).rail, "cash")
        self.assertTrue(rails.check(self.buy(50), s, c).ok)
        c.control["max_spend_per_hour"] = 1000
        self.assertTrue(rails.check(self.buy(60), s, c).ok)

    def test_hour_from_ledger(self):
        s = sit(me={**sit().me, "cash": 1000}, values={"LAV-09": 500.0})
        c = ctx(budget={"accepts_left": 1}, ledger=NS(spend_last_hour=lambda: 240, deals_with=lambda t, h: 0))
        self.assertEqual(rails.check(self.buy(20), s, c).rail, "cash")


class PaceRail(unittest.TestCase):
    def test_one_accept(self):
        o = offer({"assets": [{"id": 50, "ref": "LAV-09"}]}, {"cash": 10})
        c = ctx()
        c.budget["accepts_left"] = 0
        self.assertEqual(rails.check(accept(o), sit(), c).rail, "pace")

    def test_one_message_per_conversation(self):
        s = sit(duels=[{"duel": 9, "status": "live", "role": "seller", "your_limit": 10}])
        c = ctx()
        c.budget["messages"] = {"duel:9": 1}
        self.assertEqual(rails.check(Action("duel_message", {"duel": 9, "price": 50}, "duels"), s, c).rail, "pace")

    def test_thread_limits(self):
        threads = [{"id": i, "with": f"d{i}", "status": "open"} for i in range(6)]
        a = Action("open_thread", {"with": "abuela", "topic": {"buy": {"pack": "x"}}}, "dealers")
        self.assertEqual(rails.check(a, sit(threads=threads), ctx()).rail, "pace")
        self.assertEqual(rails.check(a, sit(threads=[{"id": 1, "with": "abuela", "status": "open"}]), ctx()).rail, "pace")
        self.assertTrue(rails.check(a, sit(), ctx()).ok)


class FairRail(unittest.TestCase):
    def test_deals_per_team(self):
        o = offer({"assets": [{"id": 50, "ref": "LAV-09"}]}, {"cash": 10}, maker="t3")
        c = ctx()
        c.budget["deals_by_team_hour"] = {"t3": 4}
        self.assertEqual(rails.check(accept(o), sit(), c).rail, "fair_play")
        c.budget["deals_by_team_hour"] = {"t3": 3}
        self.assertTrue(rails.check(accept(o), sit(), c).ok)

    def test_dealers_are_not_teams(self):
        o = offer({"types": ["card:LAV-09"]}, {"cash": 10}, maker="abuela")
        c = ctx()
        c.budget["deals_by_team_hour"] = {"abuela": 40}
        self.assertTrue(rails.check(accept(o), sit(), c).ok)

    def test_broken_rail_vetoes(self):
        with mock.patch.object(rails, "RAILS", [lambda a, s, c: 1 / 0]):
            self.assertFalse(rails.check(Action("noop", {}, "x"), sit(), ctx()).ok)


if __name__ == "__main__":
    unittest.main()


class VenueReserve(unittest.TestCase):
    def test_buys_keep_the_bond_until_the_venue_is_open(self):
        s = sit()
        s.me = {**s.me, "venue": None, "cash": 336}
        buy = Action("accept_offer", {"offer": 1, "expect": offer({"types": ["card:LAV-04"]}, {"cash": 30})}, "dealers")
        self.assertEqual(rails.rail_cash(buy, s, ctx()).rail, "cash")          # 336 - 30 < 40 + 270
        opening = Action("venue_open", {"name": "x"}, "broker")
        self.assertTrue(rails.rail_cash(opening, s, ctx()).ok)                 # 336 - 270 >= 40


class AcceptWithChosenCopy(unittest.TestCase):
    def test_chosen_copy_counts_as_given(self):
        a = Action("accept_offer", {"offer": 7, "assets": [1],
                                    "expect": offer({"cash": 200}, {"types": ["card:LAV-03"]})}, "market")
        give, _ = rails.flows(a, sit())
        self.assertIn(1, give["assets"])
