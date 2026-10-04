"""The price board: best public ask and bid per card after fees, usual range, trend, and nothing private."""
import json
import tempfile
import unittest
from pathlib import Path

from bazaar.plaza import prices
from bazaar.plaza.feed import Feed, venue_fees

CAT = {"SAL-10": {"name": "Museo", "rarity": "rare", "set": "SAL", "set_name": "Salamanca", "color": "#2EC4B6", "book": 70},
       "LAV-11": {"name": "Tabacalera", "rarity": "epic", "set": "LAV", "set_name": "Lavapiés", "color": "#E4572E", "book": 180},
       "RET-01": {"name": "Estanque", "rarity": "common", "set": "RET", "set_name": "El Retiro", "color": "#7B8CDE", "book": 10}}
FEES = {"rastro": {"bps": 500, "per_card": 1, "name": "El Rastro"}, "v07": {"bps": 0, "per_card": 0, "name": "v07"},
        "v21": {"bps": 0, "per_card": 0, "name": "Mercado 9"}}


def offer(oid, maker, side, ref, price, venue, to=None, fee=0):
    return {"id": oid, "maker": maker, "to": to, "venue": venue, "side": side, "ref": ref, "price": price, "fee": fee,
            "expires_tick": 99}


def sale(ref, tick, price, frm="t02", to="t03", venue="rastro", dealer=None, n=1):
    return {"ref": ref, "tick": tick, "price": price, "venue": venue, "from": frm, "to": to, "dealer": dealer, "n": n}


class BoardTest(unittest.TestCase):
    def build(self, offers, sales, sheets=None):
        live, hist = prices.build(CAT, offers, sales, sheets or {}, FEES, 50)
        return {c["ref"]: c for c in live["cards"]}, live, hist

    def test_the_best_ask_is_the_cheapest_after_the_fee_and_the_best_bid_nets_most(self):
        cards, live, _ = self.build([offer(1, "t02", "ask", "SAL-10", 60, "rastro", fee=4),      # costs 64
                                     offer(2, "t04", "ask", "SAL-10", 62, "v07"),                # costs 62: cheaper
                                     offer(3, "t05", "bid", "SAL-10", 50, "rastro", fee=4),      # nets 46
                                     offer(4, "t06", "bid", "SAL-10", 48, "v21")], [])           # nets 48: better
        c = cards["SAL-10"]
        self.assertEqual((c["ask"]["offer"], c["ask"]["cost"], c["ask"]["on_v07"], c["ask"]["saves_on_v07"]), (2, 62, True, 0))
        self.assertEqual((c["bid"]["offer"], c["bid"]["nets"], c["asks"], c["bids"]), (4, 48, 2, 2))
        self.assertEqual(live["offers"], 4)
        only = self.build([offer(1, "t02", "ask", "SAL-10", 60, "rastro", fee=4)], [])[0]["SAL-10"]
        self.assertEqual((only["ask"]["cost"], only["ask"]["saves_on_v07"]), (64, 4))       # the same price here pays no fee

    def test_an_addressed_offer_never_shows(self):
        cards, live, _ = self.build([offer(1, "t02", "ask", "LAV-11", 150, "v07", to="t03"),
                                     offer(2, "pilar", "ask", "LAV-11", 10, "rastro")], [])
        self.assertIsNone(cards["LAV-11"]["ask"])
        self.assertEqual(live["offers"], 0)
        self.assertNotIn("150", json.dumps(live))
        feed_live = prices.Live()
        feed_live.update([], [], FEES, 49)
        out = feed_live.update([offer(1, "t02", "ask", "LAV-11", 150, "v07", to="t03")], [], FEES, 50)
        self.assertEqual(out["events"], [])

    def test_range_trend_and_hot_come_from_sales_between_teams_only(self):
        sales = [sale("SAL-10", t, p) for t, p in ((1, 60), (2, 64), (3, 70), (4, 80), (5, 82), (6, 90))]
        sales += [sale("SAL-10", 7, 5, to="pilar", dealer="pilar"), sale("SAL-10", 8, 500, n=2)]   # a dealer; a bundle
        cards, _, hist = self.build([offer(1, "t02", "ask", "SAL-10", 48, "v07")], sales)
        c = cards["SAL-10"]
        self.assertEqual((c["deals"], c["last"], c["last_tick"], c["trend"]), (6, 90, 6, "up"))
        self.assertTrue(c["low"] < c["median"] < c["high"])
        self.assertTrue(c["hot"])                                    # 48 is under 80 % of the low end
        self.assertEqual(c["spark"], [60, 64, 70, 80, 82, 90])
        self.assertEqual(len(hist["cards"]["SAL-10"]["deals"]), 6)
        self.assertEqual(hist["cards"]["SAL-10"]["deals"][0], {"tick": 1, "price": 60, "venue": "rastro", "seller": "t02", "buyer": "t03"})
        few = self.build([offer(1, "t02", "ask", "LAV-11", 1, "v07")], [sale("LAV-11", 1, 150), sale("LAV-11", 2, 100)])[0]["LAV-11"]
        self.assertEqual((few["low"], few["high"], few["hot"], few["trend"]), (None, None, False, "down"))

    def test_who_holds_and_who_wants_and_what_nobody_has_shown(self):
        sheets = {"t02": {"spares": [{"ref": "SAL-10"}], "for_sale": [], "wants": [{"ref": "LAV-11"}]},
                  "t10": {"host": True, "spares": [{"ref": "RET-01"}], "for_sale": [], "wants": []}}
        cards, _, _ = self.build([offer(1, "t05", "bid", "SAL-10", 40, "v21")], [], sheets)
        self.assertEqual((cards["SAL-10"]["holders"], cards["SAL-10"]["seekers"], cards["SAL-10"]["state"]), (["t02"], ["t05"], "in_play"))
        self.assertEqual((cards["LAV-11"]["seekers"], cards["LAV-11"]["state"]), (["t02"], "not_seen"))
        self.assertEqual((cards["RET-01"]["holders"], cards["RET-01"]["state"]), ([], "not_seen"))     # the host is no party

    def test_live_says_what_changed_and_only_that(self):
        live = prices.Live()
        a = offer(1, "t02", "ask", "SAL-10", 60, "rastro", fee=4)
        self.assertEqual(live.update([a], [sale("SAL-10", 40, 55)], FEES, 49)["events"], [])       # the baseline
        out = live.update([offer(2, "t04", "bid", "RET-01", 5, "v21")], [sale("SAL-10", 40, 55), sale("SAL-10", 50, 61)], FEES, 50)
        self.assertEqual(sorted(e["what"] for e in out["events"]), ["gone", "listed", "sold"])
        self.assertEqual(live.update([offer(2, "t04", "bid", "RET-01", 5, "v21")], [sale("SAL-10", 40, 55), sale("SAL-10", 50, 61)], FEES, 50)["events"], out["events"])
        self.assertEqual(live.update([offer(2, "t04", "bid", "RET-01", 5, "v21")], [], FEES, 53)["events"], [])   # two ticks later: old news

    def test_unreleased_sets_are_named_and_their_cards_are_not_listed(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "latest").mkdir()
            (Path(d) / "latest" / "catalog.json").write_text(json.dumps({"sets": [
                {"id": "SAL", "name": "Salamanca", "cards": []}, {"id": "CHA", "name": "Chamberí", "released": False, "cards": [{"id": "CHA-01"}]}]}))
            self.assertEqual([s["id"] for s in prices.unreleased(Path(d))], ["CHA"])
            live, _ = prices.build(CAT, [], [], {}, FEES, 1, Path(d))
            self.assertEqual(live["unreleased_sets"][0]["name"], "Chamberí")
            self.assertNotIn("CHA-01", json.dumps(live))


class RecordedFeedTest(unittest.TestCase):
    """Against Saturday's recorded feed, when this checkout has it."""
    LIVE, RECORD = Path("bazaar/data/live"), Path("bazaar/data/record")

    @unittest.skipUnless((Path("bazaar/data/live") / "events.jsonl").exists(), "no recorded feed in this checkout")
    def test_the_recorded_feed_builds_a_board_with_no_addressed_offer(self):
        from bazaar.plaza import public
        feed = Feed(self.LIVE, self.RECORD)
        feed.refresh()
        fees = venue_fees(self.RECORD)
        offers = feed.open_offers(fees)
        cat = public.catalog(self.RECORD)
        live, hist = prices.build(cat, offers, list(feed.sales), {}, fees, feed.tick, self.RECORD)
        self.assertEqual(live["total"], len(cat))
        addressed = {o["id"] for o in offers if o.get("to")}
        shown = {c[s]["offer"] for c in live["cards"] for s in ("ask", "bid") if c[s]}
        self.assertFalse(addressed & shown)
        for c in live["cards"]:
            if c["ask"]:
                self.assertEqual(c["ask"]["cost"], c["ask"]["price"] + c["ask"]["fee"])
                self.assertTrue(all(o["price"] + o["fee"] >= c["ask"]["cost"] for o in offers
                                    if not o.get("to") and o["side"] == "ask" and o["ref"] == c["ref"]))
            if c["low"] is not None:
                self.assertLessEqual(c["low"], c["high"])
        self.assertTrue(any(h["deals"] for h in hist["cards"].values()))
        self.assertLess(len(json.dumps(live)), 400_000)


if __name__ == "__main__":
    unittest.main()
