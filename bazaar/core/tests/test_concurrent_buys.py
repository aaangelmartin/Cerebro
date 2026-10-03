"""Value rail: a card another open purchase is already bringing in is a spare, and a repeated bid after a
dealer's card switch is valued with the card we asked for."""
import unittest
from unittest import mock

from bazaar.core import rails
from bazaar.core.types import Action

from .test_rails import accept, card, ctx, offer, sit

CATALOG = {"sets": [{"id": "RET", "released": True, "cards": [{"id": "RET-09", "rarity": "rare", "book": 70},
                                                              {"id": "RET-07", "rarity": "uncommon", "book": 25}]}]}
VALUES = {"RET-09": 177.0, "RET-07": 6.9}          # RET-09 completes the page: first copy with its bonus


def me(*extra):
    return {"id": "t10", "cash": 300, "venue": "v99", "affinity": {"RET": 1.1},
            "assets": [card(1, "LAV-03", 120.0), *extra]}


def thread(tid, dealer, ref="RET-09", messages=()):
    return {"id": tid, "with": dealer, "status": "open", "topic": {"buy": {"card": ref}}, "messages": list(messages)}


def bid(tid, price):
    return Action("thread_message", {"thread": tid, "price": price, "text": f"{price} P"}, "dealers")


def check(action, threads, my_offers=(), assets=()):
    c = ctx(control={"armed": True, "max_spend_per_deal": 200}, value=lambda ref: VALUES.get(ref))
    with mock.patch.object(rails, "_catalog", lambda: CATALOG):
        return rails.check(action, sit(me=me(*assets), threads=list(threads), my_offers=list(my_offers), values={}), c)


class ConcurrentBuys(unittest.TestCase):
    def test_single_thread_is_the_first_copy(self):
        self.assertTrue(check(bid(5, 60), [thread(5, "picaros")]).ok)

    def test_second_thread_for_the_same_card_is_a_spare(self):
        threads = [thread(5, "picaros"), thread(9, "chato")]
        self.assertTrue(check(bid(5, 60), threads).ok)                 # the older thread keeps the first copy
        v = check(bid(9, 60), threads)                                 # 70 x 1.1 x 0.25 = 19.25 < 60
        self.assertEqual(v.rail, "value")
        self.assertTrue(check(bid(9, 15), threads).ok)                 # a spare is still worth buying cheap

    def test_accept_in_the_newer_thread_is_a_spare_too(self):
        give = {"types": ["card:RET-09"]}
        threads = [thread(5, "picaros"), thread(9, "chato")]
        a = accept(offer(give, {"cash": 60}, maker="chato", thread=9))
        self.assertEqual(check(a, threads).rail, "value")
        self.assertTrue(check(accept(offer(give, {"cash": 60}, maker="picaros", thread=5)), threads).ok)

    def test_market_accept_and_new_thread_count_every_open_buy_thread(self):
        give = {"assets": [{"id": 50, "ref": "RET-09"}]}
        self.assertEqual(check(accept(offer(give, {"cash": 60})), [thread(5, "picaros")]).rail, "value")
        self.assertTrue(check(accept(offer(give, {"cash": 60})), []).ok)
        opening = Action("open_thread", {"with": "chato", "topic": {"buy": {"card": "RET-09"}}, "price": 60}, "dealers")
        self.assertEqual(check(opening, [thread(5, "picaros")]).rail, "value")
        self.assertTrue(check(opening, []).ok)

    def test_new_bid_counts_our_other_open_offer_for_the_card(self):
        post = Action("post_offer", {"venue": "rastro", "give": {"cash": 60}, "want": {"cards": ["RET-09"]}}, "market")
        self.assertTrue(check(post, []).ok)
        mine = {"id": 3, "maker": "t10", "status": "open", "give": {"cash": 30}, "want": {"types": ["card:RET-09"]}}
        self.assertEqual(check(post, [], my_offers=[mine]).rail, "value")
        self.assertTrue(check(bid(5, 60), [thread(5, "picaros")], my_offers=[mine]).ok)   # a bid never stalls a thread

    def test_closed_or_other_card_threads_do_not_count(self):
        threads = [{**thread(5, "picaros"), "status": "closed"}, thread(6, "chato", "RET-07"), thread(9, "chato")]
        self.assertTrue(check(bid(9, 60), threads).ok)


class CardSwitch(unittest.TestCase):
    SWITCHED = [{"offer": {"maker": "picaros", "give": {"types": ["card:RET-07"]}, "want": {"cash": 64}, "id": 77}}]

    def test_repeated_bid_is_valued_with_the_card_we_asked_for(self):
        self.assertTrue(check(bid(5, 50), [thread(5, "picaros", messages=self.SWITCHED)]).ok)
        self.assertEqual(check(bid(5, 180), [thread(5, "picaros", messages=self.SWITCHED)]).rail, "value")

    def test_accepting_the_switched_card_is_vetoed(self):
        o = offer({"types": ["card:RET-07"]}, {"cash": 64}, maker="picaros", thread=5, oid=77)
        self.assertEqual(check(accept(o), [thread(5, "picaros", messages=self.SWITCHED)]).rail, "value")

    def test_lot_thread_still_values_the_dealers_card(self):
        th = {"id": 4, "with": "picaros", "status": "open", "topic": {"buy": {"rarity": "rare", "set": "RET"}},
              "messages": self.SWITCHED}
        self.assertEqual(check(bid(4, 50), [th]).rail, "value")        # RET-07 is worth 6.9


if __name__ == "__main__":
    unittest.main()
