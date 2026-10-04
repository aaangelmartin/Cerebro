"""The feed reads the recorder's file by offset; the floor orders, filters and bounds what is said."""
import json
import tempfile
import unittest

from bazaar.plaza.floor import PER_TEAM_PER_MIN
from pathlib import Path

from bazaar.plaza import feed as F
from bazaar.plaza.floor import Floor, clean_message
from bazaar.plaza.store import PlazaError


def listed(oid, maker, give, want, to=None, venue="rastro", tick=5, thread=None, kind=None):
    p = {"venue": venue, "offer": {"id": oid, "maker": maker, "to": to, "venue": venue, "thread": thread, "give": give,
                                   "want": want, "created_tick": tick, "expires_tick": tick + 60}}
    if kind:
        p["kind"] = kind
    return {"id": oid, "ts": float(oid), "tick": tick, "type": "offer.listed", "payload": p}


class FeedTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.live, self.record = Path(self.dir.name) / "live", Path(self.dir.name) / "record"
        (self.record / "latest" / "books").mkdir(parents=True)
        self.live.mkdir()
        self.feed = F.Feed(self.live, self.record)

    def tearDown(self):
        self.dir.cleanup()

    def write(self, *events, partial=""):
        with (self.live / "events.jsonl").open("a") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
            f.write(partial)

    def test_norm_offer(self):
        ask = F.norm_offer({"id": 1, "maker": "t03", "give": {"assets": [{"ref": "SAL-09"}]}, "want": {"cash": 60}})
        bid = F.norm_offer({"id": 2, "maker": "t03", "give": {"cash": 50}, "want": {"types": ["card:SAL-09"]}})
        swap = F.norm_offer({"id": 3, "maker": "t03", "give": {"assets": [{"ref": "LAT-01"}]}, "want": {"cards": ["LAT-02"]}})
        self.assertEqual((ask["side"], ask["ref"], ask["price"]), ("ask", "SAL-09", 60))
        self.assertEqual((bid["side"], bid["ref"], bid["price"]), ("bid", "SAL-09", 50))
        self.assertEqual((swap["side"], swap["ref"], swap["ref_back"]), ("swap", "LAT-01", "LAT-02"))
        self.assertIsNone(F.norm_offer({"id": 4, "thread": 9, "give": {"cash": 5}, "want": {"types": ["card:X"]}}))
        self.assertIsNone(F.norm_offer({"id": 5, "give": {}, "want": {}}))

    def test_reads_by_offset_and_waits_for_whole_lines(self):
        self.write(listed(1, "t03", {"assets": [{"ref": "SAL-09"}]}, {"cash": 60}), partial='{"id": 2, "type": "offer.li')
        self.assertEqual(len(self.feed.refresh()), 1)
        self.assertEqual(self.feed.refresh(), [])
        with (self.live / "events.jsonl").open("a") as f:
            f.write('sted", "tick": 6, "ts": 2.0, "payload": {"offer": {"id": 2, "maker": "t04", "venue": "v07", '
                    '"give": {"cash": 9}, "want": {"types": ["card:LAT-01"]}, "expires_tick": 99}}}\n')
        new = self.feed.refresh()
        self.assertEqual([(m["team"], m["side"], m["highlight"]) for m in new], [("t04", "bid", True)])
        self.assertEqual(self.feed.counts["venue_offers"], 1)

    def test_dealer_threads_and_personas_are_not_market_offers(self):
        self.write(listed(1, "pilar", {"cash": 20}, {"types": ["card:SAL-08"]}, thread=7),
                   listed(2, "t03", {"assets": [{"ref": "SAL-09"}]}, {"cash": 60}, kind="persona"),
                   listed(3, "picaros", {"assets": [{"ref": "SAL-09"}]}, {"cash": 60}))
        self.assertEqual(self.feed.refresh(), [])
        self.assertEqual(self.feed.offers, {})

    def test_open_offers_drop_cancelled_expired_sold_and_settled(self):
        ask = {"assets": [{"ref": "SAL-09"}]}
        self.write(listed(1, "t03", ask, {"cash": 60}), listed(2, "t04", ask, {"cash": 61}), listed(3, "t05", ask, {"cash": 62}),
                   listed(4, "t06", ask, {"cash": 63}, to="t07"), listed(5, "t08", ask, {"cash": 64}, tick=1),
                   {"id": 9, "tick": 6, "type": "offer.cancelled", "payload": {"offer": 2}},
                   {"id": 10, "tick": 60, "ts": 10.0, "type": "settlement", "payload": {"venue": "rastro", "price": 63,
                    "parties": ["t06", "t07"], "items": [{"ref": "SAL-09", "frm": "t06", "to": "t07"}]}})
        (self.record / "latest" / "books" / "rastro.json").write_text(json.dumps({"venue": "rastro", "tick": 59, "offers": [{"id": 1}]}))
        self.feed.refresh()
        self.assertEqual([o["id"] for o in self.feed.open_offers()], [1])      # 2 cancelled, 3 gone from the book, 4 settled, 5 expired
        o = self.feed.open_offers()[0]
        self.assertEqual((o["fee"], o["cost"]), (4, 64))
        self.assertEqual(self.feed.sales_of("SAL-09")[0]["price"], 63)
        self.assertEqual(self.feed.counts["team_deals"], 1)

    def test_fees(self):
        (self.record / "latest" / "venues.json").write_text(json.dumps({"venues": [
            {"venue": "v07", "fee_bps": 0, "fee_per_card": 0, "name": "ours"}, {"venue": "v02", "fee_bps": 0, "fee_per_card": 5}]}))
        fees = F.venue_fees(self.record)
        self.assertEqual((F.fee(fees, "rastro", 100), F.fee(fees, "v07", 100), F.fee(fees, "v02", 100), F.fee(fees, "v99", 20)), (6, 0, 5, 2))


class FloorTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.now = [100.0]
        self.path = Path(self.dir.name) / "floor.jsonl"
        self.floor = Floor(self.path, clock=lambda: self.now[0])

    def tearDown(self):
        self.dir.cleanup()

    def test_messages_are_plain_and_bounded(self):
        m = clean_message({"kind": "offer", "ref": "SAL-09", "price": 59.6, "to": "t04", "text": " a\x00b\n c "})
        self.assertEqual(m, {"kind": "offer", "ref": "SAL-09", "price": 60, "to": "t04", "text": "ab c"})
        for bad in ({"kind": "x"}, {"kind": "want"}, {"kind": "note"}, {"kind": "note", "text": "y" * 281}, "text",
                    {"kind": "note", "text": "ok", "ref": "sal-09"}, {"kind": "note", "text": "ok", "to": "team4"},
                    {"kind": "note", "text": "ok", "price": 99999}, {"kind": "note", "text": "ok", "extra": 1}):
            with self.assertRaises(PlazaError):
                clean_message(bad)

    def test_order_filters_and_persistence(self):
        self.floor.load([{"src": "game", "kind": "deal", "ts": 50.0, "team": "t03", "to": "t04", "ref": "LAT-01"}])
        a = self.floor.post("t07", True, {"kind": "want", "ref": "SAL-09"})
        self.now[0] += 1
        self.floor.add_game([{"src": "game", "kind": "offer", "ts": 102.0, "team": "t09", "ref": "SAL-09"}])
        got = self.floor.poll(0)
        self.assertEqual([m["seq"] for m in got["items"]], [1, 2, 3])
        self.assertEqual([m["kind"] for m in self.floor.poll(1)["items"]], ["want", "offer"])
        self.assertEqual(len(self.floor.poll(0, ref="SAL-09")["items"]), 2)
        self.assertEqual(len(self.floor.poll(0, team="t04")["items"]), 1)
        self.assertEqual(len(self.floor.poll(0, kind="agent")["items"]), 1)
        self.assertEqual(self.floor.poll(0, hidden={a["id"]})["items"][-1]["kind"], "offer")
        self.assertEqual(len(self.floor.poll(0, blocked={"t07"})["items"]), 2)
        self.assertTrue(self.floor.poll(0, hidden={a["id"]}, everything=True)["items"][1]["hidden"])
        again = Floor(self.path)
        again.load([])
        self.assertEqual([m["kind"] for m in again.poll(0)["items"]], ["want"])
        self.assertNotEqual(again.epoch, self.floor.epoch)
        self.assertEqual(again.post("t07", False, {"kind": "note", "text": "x"})["id"], a["id"] + 1)

    def test_rate_and_retention(self):
        for i in range(PER_TEAM_PER_MIN):
            self.floor.post("t07", False, {"kind": "note", "text": str(i)})
        with self.assertRaises(PlazaError) as c:
            self.floor.post("t07", False, {"kind": "note", "text": "13"})
        self.assertEqual(c.exception.status, 429)
        self.floor.post("t08", False, {"kind": "note", "text": "other team"})
        self.now[0] += 61
        self.floor.post("t07", False, {"kind": "note", "text": "again"})
        with self.assertRaises(PlazaError):
            self.floor.post("t07", False, {"kind": "note", "text": "x", "to": "t07"})
        self.floor.add_game([{"src": "game", "kind": "offer", "ts": 1.0} for _ in range(1200)])
        self.assertLessEqual(len(self.floor.items), 900)
        self.assertFalse(self.floor.wait(self.floor.seq, 0.01))
        self.assertTrue(self.floor.wait(0, 0.01))


if __name__ == "__main__":
    unittest.main()
