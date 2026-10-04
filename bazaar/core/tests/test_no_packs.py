"""control.no_packs (on by default): a sealed pack is never bought, by any path; a pack given for nothing is taken."""
import unittest

from bazaar.core import rails
from bazaar.core.types import Action


def sit(threads=()):
    return {"me": {"id": "t10", "cash": 400, "assets": [{"id": 1, "kind": "card", "ref": "LAT-02", "your_value": 5.0}]},
            "values": {"pack:sobre_plata": 400.0, "pack:sobre_oro": 900.0}, "venues": [], "duels": [],
            "threads": list(threads), "my_offers": []}


def act(kind, params):
    return Action(kind=kind, params=params, domain="dealers", expected={})


def ctx(**control):
    return {"control": control}


PACK_THREAD = {"id": 9, "with": "chato", "topic": {"buy": {"pack": "sobre_plata"}}, "messages": []}


class NoPacks(unittest.TestCase):
    def veto(self, a, s=None, c=None):
        return rails.rail_no_packs(a, s or sit(), c if c is not None else ctx())

    def test_a_dealer_thread_to_buy_a_pack_is_never_opened_or_bid_on(self):
        v = self.veto(act("open_thread", {"with": "chato", "topic": {"buy": {"pack": "sobre_plata"}}}))
        self.assertEqual((v.ok, v.rail), (False, "no_packs"))
        v = self.veto(act("thread_message", {"thread": 9, "price": 120, "text": "120"}), sit([PACK_THREAD]))
        self.assertFalse(v.ok)

    def test_an_offer_that_hands_us_a_pack_for_cash_is_not_accepted(self):
        exp = {"maker": "banco", "give": {"types": ["pack:sobre_oro"]}, "want": {"cash": 150}}
        self.assertFalse(self.veto(act("accept_offer", {"offer": 5, "expect": exp})).ok)
        exp = {"maker": "t04", "give": {"assets": [{"id": 77, "kind": "pack", "ref": "sobre_barrio"}]},
               "want": {"cards": ["LAT-02"]}}
        self.assertFalse(self.veto(act("accept_offer", {"offer": 6, "expect": exp, "assets": [1]})).ok)

    def test_we_never_post_a_bid_for_a_pack(self):
        a = act("post_offer", {"venue": "rastro", "give": {"cash": 100}, "want": {"types": ["pack:sobre_plata"]}})
        self.assertFalse(self.veto(a).ok)

    def test_a_pack_given_for_nothing_is_taken(self):
        exp = {"maker": "chato", "give": {"types": ["pack:sobre_barrio"]}, "want": {"cash": 0}}
        self.assertTrue(self.veto(act("accept_offer", {"offer": 7, "expect": exp})).ok)

    def test_cards_are_untouched_and_the_team_can_switch_it_off(self):
        exp = {"maker": "picaros", "give": {"types": ["card:LAV-11"]}, "want": {"cash": 150}}
        self.assertTrue(self.veto(act("accept_offer", {"offer": 8, "expect": exp})).ok)
        self.assertTrue(self.veto(act("open_thread", {"with": "abuela", "topic": {"buy": {"card": "SAL-06"}}})).ok)
        a = act("open_thread", {"with": "chato", "topic": {"buy": {"pack": "sobre_plata"}}})
        self.assertTrue(self.veto(a, c=ctx(no_packs=False)).ok)

    def test_it_is_one_of_the_rails_every_action_passes(self):
        self.assertIn(rails.rail_no_packs, rails.RAILS)


if __name__ == "__main__":
    unittest.main()
