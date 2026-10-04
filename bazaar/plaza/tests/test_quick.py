"""Closing on v07 without connecting: the game call for one offer and the public pairs that would cross."""
import unittest

from bazaar.plaza import quick
from bazaar.plaza.store import PlazaError


def snap(cards):
    cat = {c["ref"]: {"name": c.get("name", c["ref"]), "rarity": c.get("rarity", "rare")} for c in cards}
    return {"tick": 1700, "cat": cat, "board": {"cards": cards}}


def card(ref, ask=None, bid=None, rarity="rare", **kw):
    c = {"ref": ref, "name": ref, "rarity": rarity, "page": True, "seekers": [], "bids": 0, **kw}
    if ask:
        c["ask"] = {"price": ask[0], "team": ask[1], "venue": ask[2] if len(ask) > 2 else "rastro", "saves_on_v07": 4}
    if bid:
        c["bid"] = {"price": bid[0], "team": bid[1], "venue": bid[2] if len(bid) > 2 else "rastro", "saves_on_v07": 0}
    return c


class QuickTest(unittest.TestCase):
    def test_the_body_is_the_games_own_offer_on_v07(self):
        s = snap([card("SAL-10", bid=(60, "t04"))])
        sell = quick.quick(s, "SAL-10", "sell", "60")
        self.assertEqual(sell["body"]["venue"], "v07")
        self.assertEqual(sell["body"]["want"], {"cash": 60})
        self.assertNotIn("to", sell["body"])                          # public: any team may accept it
        buy = quick.quick(s, "SAL-10", "buy", 55)
        self.assertEqual(buy["body"], {"venue": "v07", "give": {"cash": 55}, "want": {"cards": ["SAL-10"]}})
        self.assertEqual((buy["method"], buy["path"]), ("POST", "/api/offers"))

    def test_without_a_price_it_takes_the_best_public_quote(self):
        s = snap([card("SAL-10", ask=(70, "t09"), bid=(60, "t04"))])
        self.assertEqual(quick.quick(s, "SAL-10", "sell", None)["price"], 60)
        self.assertEqual(quick.quick(s, "SAL-10", "buy", None)["price"], 70)

    def test_bad_input_is_refused(self):
        s = snap([card("SAL-10")])
        for args in (("ZZZ-99", "sell", 5), ("SAL-10", "steal", 5), ("SAL-10", "sell", "x"), ("SAL-10", "sell", 0),
                     ("SAL-10", "sell", 99999), ("SAL-10", "sell", None)):
            with self.assertRaises(PlazaError):
                quick.quick(s, *args)

    def test_a_crossing_public_pair_gets_a_call_for_each_side(self):
        s = snap([card("SAL-10", ask=(56, "t09"), bid=(60, "t04"))])
        o = quick.opportunities(s)["opportunities"][0]
        self.assertEqual((o["kind"], o["seller"], o["buyer"], o["price"]), ("cross", "t09", "t04", 60))
        post, take = o["steps"]                                       # the bidder moves its bid, the holder accepts
        self.assertEqual((post["team"], post["body"]["venue"], post["body"]["give"]), ("t04", "v07", {"cash": 60}))
        self.assertEqual((take["team"], take["do"]), ("t09", "accept it on v07"))

    def test_an_offer_already_on_v07_is_one_accept_away(self):
        c = card("SAL-10", bid=(60, "t04", "v07"))
        c["bid"]["offer"] = 4242
        o = quick.opportunities(snap([c]))["opportunities"][0]
        self.assertEqual(len(o["steps"]), 1)
        self.assertEqual(o["steps"][0]["path"], "/api/offers/4242/accept")

    def test_the_host_is_never_one_of_the_two_and_a_giveaway_is_never_pushed(self):
        s = snap([card("LAV-11", ask=(200, "t10"), bid=(210, "t03"), rarity="epic"),
                  card("RET-11", ask=(200, "t05"), bid=(240, "t10"), rarity="epic"),
                  card("SAL-09", bid=(10, "t04")),                     # a rare for 10 is a giveaway
                  card("SAL-08", ask=(20, "t07"), bid=(20, "t07"), rarity="uncommon")])   # one team on both sides
        self.assertEqual(quick.opportunities(s)["opportunities"], [])

    def test_a_lone_bid_or_ask_elsewhere_is_an_invitation_to_v07(self):
        s = snap([card("CHA-11", bid=(222, "t16"), rarity="epic"),
                  card("LAT-09", ask=(90, "t01"), seekers=["t05"]),
                  card("LAT-01", ask=(8, "t06"), rarity="common")])   # nobody wants it: not listed
        kinds = {o["ref"]: o["kind"] for o in quick.opportunities(s)["opportunities"]}
        self.assertEqual(kinds, {"CHA-11": "wanted", "LAT-09": "for_sale"})

    def test_only_what_the_public_board_holds_is_read(self):
        s = snap([card("SAL-10", ask=(56, "t09"), bid=(60, "t04"))])
        s["sheets"] = {"t05": {"wants": [{"ref": "SAL-10", "max": 999}]}}      # private: must not show
        self.assertNotIn("999", str(quick.opportunities(s)))


if __name__ == "__main__":
    unittest.main()
