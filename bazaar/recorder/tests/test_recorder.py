"""Recorder: store, feed dedupe and gaps, books, transcripts, outages, card sweep, sim end to end."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from bazaar import supervise
from bazaar.gateway import GameError
from bazaar.recorder import client as rclient
from bazaar.recorder import core
from bazaar.recorder.client import Lane
from bazaar.recorder.core import Recorder
from bazaar.recorder.store import Store, iter_records, last_record


def rows(store: Store, stream: str) -> list[dict]:
    out = []
    for p in store.files(stream):
        out.extend(iter_records(p))
    return out


class FakeAPI:
    """Routes GET paths to scripted responses (a dict, a callable, or a GameError to raise)."""

    def __init__(self):
        self.routes: dict = {}
        self.calls: list = []

    def __call__(self, base, path, params, headers, timeout):
        self.calls.append((path, dict(params or {}), headers.get("X-Team-Key")))
        key = path + ("?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items())) if params else "")
        r = self.routes.get(key, self.routes.get(path))
        if r is None:
            raise GameError("not_found", path, 404)
        if callable(r):
            r = r()
        if isinstance(r, GameError):
            raise r
        return r


def make(root: Path, api: FakeAPI, cards=False, keyed=True) -> Recorder:
    pub = Lane("public", "http://pub", 1000, burst=1000, fetch=api)
    key = Lane("keyed", "http://gw", 1000, headers={"X-Team-Key": "k"}, burst=1000, fetch=api) if keyed else None
    return Recorder(Store(root), pub, key, cards=cards)


def ev(i, tick=1, type_="offer.listed", **payload):
    return {"id": i, "tick": tick, "t": 0.1, "type": type_, "scope": "public", "actor": "t03", "payload": payload}


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rec-store-"))

    def test_seq_continues_across_restarts_and_days(self):
        day = ["2026-10-03"]
        s = Store(self.root, day_fn=lambda: day[0])
        s.append("feed", {"a": 1})
        s.append("feed", {"a": 2})
        day[0] = "2026-10-04"
        s2 = Store(self.root, day_fn=lambda: day[0])
        r = s2.append("feed", {"a": 3})
        self.assertEqual(r["seq"], 3)
        self.assertEqual([p.name for p in s2.files("feed")], ["2026-10-03.jsonl", "2026-10-04.jsonl"])

    def test_torn_last_line_is_skipped(self):
        s = Store(self.root)
        s.append("x", {"v": 1})
        p = s.files("x")[0]
        with p.open("a") as f:
            f.write('{"seq": 2, "v": ')          # a crash mid-write
        self.assertEqual(last_record(p)["v"], 1)
        self.assertEqual(Store(self.root).append("x", {"v": 2})["seq"], 2)

    def test_index_lists_streams(self):
        s = Store(self.root)
        s.append("feed", {"tick": 4})
        s.put("latest/me.json", {"cash": 1})
        idx = s.write_index({"links": {"broker_bench": "x"}})
        self.assertEqual(idx["streams"]["feed"]["last_seq"], 1)
        self.assertEqual(idx["streams"]["feed"]["last_tick"], 4)
        self.assertIn("latest/me.json", idx["latest"])
        self.assertEqual(json.loads((self.root / "index.json").read_text())["links"]["broker_bench"], "x")


class FeedTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rec-feed-"))
        self.api = FakeAPI()

    def test_dedupe_and_resume_without_duplicates(self):
        rec = make(self.root, self.api)
        rec.on_feed({"events": [ev(i) for i in range(1, 6)]})
        rec.on_feed({"events": [ev(i) for i in range(1, 8)]})
        self.assertEqual([r["id"] for r in rows(rec.store, "feed")], list(range(1, 8)))
        # Restart, even with the state file gone: the stream itself is the offset.
        (self.root / "state.json").unlink()
        rec2 = make(self.root, self.api)
        self.assertEqual(rec2.state["last_event_id"], 7)
        rec2.on_feed({"events": [ev(i) for i in range(3, 10)]})
        self.assertEqual([r["id"] for r in rows(rec2.store, "feed")], list(range(1, 10)))
        self.assertFalse([g for g in rows(rec2.store, "gaps") if g["kind"] == "feed_gap"])

    def test_late_event_with_lower_id_is_kept(self):
        rec = make(self.root, self.api)
        rec.on_feed({"events": [ev(1), ev(2), ev(4)]})
        rec.on_feed({"events": [ev(1), ev(2), ev(3), ev(4)]})
        self.assertEqual(sorted(r["id"] for r in rows(rec.store, "feed")), [1, 2, 3, 4])

    def test_full_page_after_our_last_id_is_a_gap(self):
        rec = make(self.root, self.api)
        rec.on_feed({"events": [ev(i) for i in range(1, 501)]})          # learns the page size: 500
        rec.on_feed({"events": [ev(i) for i in range(900, 1400)]})       # 399 events never seen
        gaps = [g for g in rows(rec.store, "gaps") if g["kind"] == "feed_gap"]
        self.assertEqual(len(gaps), 1)
        self.assertEqual((gaps[0]["after_id"], gaps[0]["before_id"], gaps[0]["missing_at_most"]), (500, 900, 399))
        self.assertEqual(rec.state["last_event_id"], 1399)

    def test_short_page_is_not_a_gap(self):
        rec = make(self.root, self.api)
        rec.on_feed({"events": [ev(i) for i in range(1, 501)]})
        rec.on_feed({"events": [ev(i) for i in range(510, 520)]})        # holes are private events
        self.assertFalse([g for g in rows(rec.store, "gaps") if g["kind"] == "feed_gap"])

    def test_refresh_types_trigger_meta_and_busy_feed_polls_faster(self):
        rec = make(self.root, self.api)
        rec.timers["meta"] = time.time() + 999
        rec.on_feed({"events": [ev(1, type_="level.unlocked")] + [ev(i) for i in range(2, 200)]})
        self.assertEqual(rec.timers["meta"], 0.0)
        self.assertTrue(rec.feed_busy)

    def test_the_catalog_is_read_again_when_a_round_starts_or_a_set_is_released(self):
        rec = make(self.root, self.api)
        rec.on_clock({"tick": 1445, "doors": "open", "paused": True, "round": 2, "tick_seconds": 15})
        rec.timers["catalog"] = time.time() + 999
        rec.on_clock({"tick": 1445, "doors": "open", "paused": True, "round": 2, "tick_seconds": 15})
        self.assertGreater(rec.timers["catalog"], time.time())            # nothing changed: no extra read
        rec.on_clock({"tick": 1466, "doors": "open", "paused": False, "round": 3, "tick_seconds": 15})
        self.assertLessEqual(rec.timers.get("catalog", 0.0), time.time())  # round 3 and the doors: read it now
        rec.timers["catalog"] = time.time() + 999
        rec.on_feed({"events": [ev(1, type_="set.released", set="CHA")]})
        self.assertEqual(rec.timers["catalog"], 0.0)
        rec.timers["catalog"] = time.time() + 999
        rec.on_feed({"events": [ev(2, type_="offer.listed")]})
        self.assertGreater(rec.timers["catalog"], time.time())            # ordinary events do not

    def test_an_open_game_reads_the_catalog_every_few_minutes(self):
        now = [1000.0]
        pub = Lane("public", "http://pub", 1000, burst=1000, fetch=self.api)
        rec = Recorder(Store(self.root), pub, None, now=lambda: now[0], cards=False)
        cha = {"sets": [{"id": "CHA", "released": False, "cards": []}]}
        self.api.routes.update({"/api/clock": {"tick": 1470, "doors": "open", "paused": False, "round": 3,
                                               "tick_seconds": 15, "next_tick_in": 5},
                                "/api/feed": {"events": []}, "/api/catalog": lambda: cha,
                                "/api/leaderboard": {}, "/api/venues": {"venues": []}, "/api/dealers": {},
                                "/api/levels": {}, "/api/schedule": {}})
        for _ in range(30):
            rec.step()
        self.assertFalse(json.loads((self.root / "latest" / "catalog.json").read_text())["sets"][0]["released"])
        cha = {"sets": [{"id": "CHA", "released": True, "cards": [{"id": "CHA-01"}]}]}
        self.api.routes["/api/catalog"] = lambda: cha
        now[0] += 181
        for _ in range(30):
            rec.step()
        self.assertTrue(json.loads((self.root / "latest" / "catalog.json").read_text())["sets"][0]["released"])


class BooksTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rec-books-"))
        self.api = FakeAPI()

    def test_diffs_snapshots_and_removed_venue(self):
        rec = make(self.root, self.api)
        rec.tick = 10
        o1 = {"id": 1, "maker": "t03", "venue": "v01", "want": {"cash": 10}}
        o2 = {"id": 2, "maker": "t04", "venue": "v01", "want": {"cash": 12}}
        rec.on_venues({"venues": [{"venue": "v01", "trades": 0}]})
        keys = [j.key for j in rec.queues["public"]]
        self.assertIn("book:v01", keys)
        self.assertIn("book:rastro", keys)                               # El Rastro is always read
        rec.on_book("v01", {"offers": [o1, o2]})
        rec.tick = 11
        rec.on_book("v01", {"offers": [o1]})                              # o2 taken
        rec.tick = 12
        rec.on_book("v01", {"offers": [{**o1, "want": {"cash": 9}}]})     # repriced
        rec.on_book("v01", {"offers": [{**o1, "want": {"cash": 9}}]})     # no change: nothing written
        b = rows(rec.store, "books")
        self.assertEqual(len(b), 3)
        self.assertEqual([x["id"] for x in b[0]["added"]], [1, 2])
        self.assertEqual(b[1]["removed"], ["2"])
        self.assertEqual(b[2]["changed"][0]["want"]["cash"], 9)
        self.assertEqual(len(rows(rec.store, "book_snapshots")), 1)
        rec.tick = 12 + core.BOOK_SNAPSHOT_EVERY
        rec.on_book("v01", {"offers": [{**o1, "want": {"cash": 9}}]})
        self.assertEqual(len(rows(rec.store, "book_snapshots")), 2)
        rec.on_venues({"venues": []})                                      # v01 closed
        self.assertTrue(rows(rec.store, "books")[-1]["venue_gone"])
        self.assertEqual(len(rows(rec.store, "venues")), 2)
        self.assertEqual(rec.store.get("latest/books/v01.json")["offers"][0]["want"]["cash"], 9)

    def test_restart_writes_snapshot_and_downtime_diff(self):
        rec = make(self.root, self.api)
        rec.tick = 5
        rec.on_book("rastro", {"offers": [{"id": 1}]})
        rec.save_state(force=True)
        rec2 = make(self.root, self.api)
        rec2.tick = 6
        rec2.on_book("rastro", {"offers": [{"id": 2}]})
        last = rows(rec2.store, "books")[-1]
        self.assertTrue(last["after_restart"])
        self.assertEqual(len(rows(rec2.store, "book_snapshots")), 2)


class PrivateTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rec-priv-"))
        self.api = FakeAPI()

    @staticmethod
    def duel(msgs, status="live", **kw):
        return {"duel": 7, "status": status, "role": "buyer", "rival": "Rival Azul", "your_limit": 90,
                "messages": msgs, **kw}

    def test_duel_transcript_accumulates_past_the_server_window(self):
        rec = make(self.root, self.api)
        m = [{"tick": t, "from": "you" if t % 2 else "rival", "text": f"m{t}", "price": 50 + t, "days": None}
             for t in range(1, 11)]
        rec.tick = 6
        rec.on_duels({"duels": [self.duel(m[:6])]})
        rec.tick = 10
        rec.on_duels({"duels": [self.duel(m[4:10], rounds=5)]})          # the server shows only the last 6
        rec.tick = 11
        rec.on_duels({"duels": []})                                       # left the live list
        self.assertIn("duels_done", rec.queued)
        rec.on_duels({"duels": [self.duel(m[4:10], status="deal", price=58, result=0.4)]}, done=True)
        doc = rec.store.get("duels/7.json")
        self.assertEqual([x["text"] for x in doc["messages"]], [f"m{t}" for t in range(1, 11)])
        self.assertEqual(doc["status"], "deal")
        self.assertEqual([h["status"] for h in doc["status_history"]], ["live", "deal"])
        d = rows(rec.store, "duels")
        self.assertEqual(len(d), 3)
        self.assertEqual(len(d[1]["messages_new"]), 4)
        self.assertEqual(d[2]["changed"]["status"], ["live", "deal"])

    def test_thread_transcript_and_closed_thread_detail(self):
        rec = make(self.root, self.api)
        t = {"id": 24, "kind": "persona", "with": "abuela", "status": "open",
             "messages": [{"id": 1, "tick": 1, "sender": "abuela", "text": "17 P", "offer": {"id": 9, "status": "open"}}]}
        rec.tick = 1
        rec.on_threads({"threads": [t]}, open_only=True)
        rec.tick = 2
        t2 = {**t, "messages": [{**t["messages"][0], "offer": {"id": 9, "status": "cancelled"}},
                                {"id": 2, "tick": 2, "sender": "t10", "text": "10?"}]}
        rec.on_threads({"threads": [t2]}, open_only=True)
        rec.on_threads({"threads": [t2]}, open_only=True)                 # unchanged: nothing new
        rec.tick = 3
        rec.on_threads({"threads": []}, open_only=True)                   # closed since
        self.assertIn("thread:24", rec.queued)
        rec.on_thread({"thread": {**t2, "status": "deal"}})
        doc = rec.store.get("threads/24.json")
        self.assertEqual(doc["message_count"], 2)
        self.assertEqual(doc["messages"][0]["offer"]["status"], "cancelled")
        self.assertEqual(doc["status"], "deal")
        tr = rows(rec.store, "threads")
        self.assertEqual(len(tr), 3)
        self.assertEqual(len(tr[1]["messages_updated"]), 1)
        self.assertEqual(tr[2]["status_from"], "open")

    def test_me_and_my_offers_only_when_changed(self):
        rec = make(self.root, self.api)
        me = {"id": "t10", "cash": 10, "assets": [{"id": 41, "kind": "card", "ref": "LAV-01"}]}
        rec.on_me(me)
        rec.on_me(me)
        rec.on_me({**me, "cash": 11})
        self.assertEqual(len(rows(rec.store, "me")), 2)
        self.assertEqual(rec.state["max_asset"], 41)
        rec.on_my_offers({"offers": [{"id": 5}]})
        rec.on_my_offers({"offers": [{"id": 5}]})
        rec.on_my_offers({"offers": []})
        self.assertEqual(len(rows(rec.store, "my_offers")), 2)


class RobustnessTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rec-rob-"))
        self.api = FakeAPI()

    def test_outage_markers_and_no_crash(self):
        rec = make(self.root, self.api)
        self.api.routes["/api/clock"] = {"tick": 3, "doors": "open", "paused": False, "tick_seconds": 30}
        self.api.routes["/api/feed"] = GameError("network", "down")
        rec.step()
        lane = rec.lanes["public"]
        self.assertIsNotNone(lane.down_since)
        self.assertEqual(rec.status()["state"], "public_down")
        lane.paused_until = 0
        self.api.routes["/api/feed"] = {"events": [ev(1)]}
        rec.timers["feed"] = 0
        for _ in range(5):
            lane.paused_until = 0
            rec.step()
        kinds = [g["kind"] for g in rows(rec.store, "gaps")]
        self.assertIn("outage_start", kinds)
        self.assertIn("outage_end", kinds)
        self.assertEqual(len(rows(rec.store, "feed")), 1)

    def test_handler_bug_is_logged_not_raised(self):
        rec = make(self.root, self.api)
        self.api.routes["/api/feed"] = {"events": "not a list"}
        self.api.routes["/api/clock"] = {"tick": "x"}
        for _ in range(3):
            rec.step()
        rec.status()

    def test_closed_doors_idle_slowly(self):
        rec = make(self.root, self.api)
        self.api.routes["/api/clock"] = {"tick": 159, "doors": "closed", "paused": True, "tick_seconds": 60}
        self.api.routes["/api/feed"] = {"events": []}
        for _ in range(40):
            rec.step()
        n = len(self.api.calls)
        for _ in range(40):
            rec.step()
        self.assertEqual(len(self.api.calls), n)                          # nothing more until the slow timers
        self.assertEqual(rec.status()["state"], "closed")
        paths = {c[0] for c in self.api.calls}
        self.assertTrue({"/api/clock", "/api/feed", "/api/leaderboard", "/api/venues", "/api/me"} <= paths)

    def test_keyed_reads_carry_the_key_public_reads_do_not(self):
        rec = make(self.root, self.api)
        self.api.routes["/api/clock"] = {"tick": 1, "doors": "closed", "paused": True}
        self.api.routes["/api/feed"] = {"events": []}
        self.api.routes["/api/me"] = {"id": "t10"}
        for _ in range(30):
            rec.step()
        for path, _, key in self.api.calls:
            if path in ("/api/me", "/api/duels", "/api/me/offers", "/api/me/threads"):
                self.assertEqual(key, "k")
            if path in ("/api/clock", "/api/feed", "/api/venues", "/api/leaderboard"):
                self.assertIsNone(key)

    def test_client_is_read_only(self):
        self.assertFalse(any(hasattr(Lane, v) for v in ("post", "delete", "patch", "put")))
        src = Path(rclient.__file__).read_text()
        self.assertNotIn('method="POST"', src)

    def test_card_sweep(self):
        rec = make(self.root, self.api, cards=True)
        rec.cards_bucket = rclient.Bucket(1000, 1000)
        rec.state["max_asset"] = 2
        self.api.routes["/api/cards/1"] = {"id": 1, "ref": "LAV-01", "history": [{"tick": 0}]}
        self.api.routes["/api/cards/2"] = {"id": 2, "ref": "LAV-02", "history": []}
        self.api.routes["/api/clock"] = {"tick": 1, "doors": "closed", "paused": True}
        self.api.routes["/api/feed"] = {"events": []}
        for _ in range(80):
            rec.step()
        c = rec.state["cards"]
        self.assertFalse(c["active"])
        self.assertEqual(len(rows(rec.store, "cards")), 2)
        self.assertEqual(c["cursor"], 2 + core.CARD_PROBE_BEYOND)
        # next hour: only what changed is written
        self.api.routes["/api/cards/1"] = {"id": 1, "ref": "LAV-01", "history": [{"tick": 0}, {"tick": 9}]}
        c["started"] = 0
        for _ in range(80):
            rec.step()
        cards = rows(rec.store, "cards")
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[-1]["history_len"], 2)
        self.assertEqual(rec.store.get("latest/cards.json")["1"]["history"][-1]["tick"], 9)


class SupervisorTest(unittest.TestCase):
    def test_recorder_is_a_supervised_service_with_heartbeat(self):
        s = {x.name: x for x in supervise.default_services()}["recorder"]
        self.assertEqual(s.heartbeat, "recorder_status.json")
        self.assertIn("bazaar.recorder.run", s.cmd)
        self.assertFalse(s.obeys_stop)


class SimEndToEndTest(unittest.TestCase):
    def test_against_fake_bazaar(self):
        from bazaar.sim import fake_bazaar
        server, world, _ = fake_bazaar.serve(port=0, tick_seconds=0.5, seed=3, duel_at_tick=2)
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            root = Path(tempfile.mkdtemp(prefix="rec-sim-"))
            pub = Lane("public", url, 40, burst=5)
            key = Lane("keyed", url, 20, headers={"X-Team-Key": "sim"}, burst=3)
            rec = Recorder(Store(root), pub, key, cards=False)
            t_end = time.time() + 8
            while time.time() < t_end:
                rec.step()
                time.sleep(min(0.02, rec.next_wait()))
            ids = [r["id"] for r in rows(rec.store, "feed")]
            self.assertTrue(ids)
            self.assertEqual(len(ids), len(set(ids)))
            public = [e["id"] for e in world.events if e["scope"] == "public" and e["id"] <= max(ids)]
            self.assertEqual(sorted(ids), public)                          # every public event, once
            for stream in ("clock", "leaderboard", "venues", "book_snapshots", "me", "duels"):
                self.assertTrue(rows(rec.store, stream), stream)
            self.assertTrue(list((root / "duels").glob("*.json")))
            self.assertFalse(rec.errors, list(rec.errors))
            self.assertEqual(list(rec.lanes["public"].errors), [])
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
