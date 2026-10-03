import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from bazaar.api import server


class RecEndpointsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.live, cls.lab, cls.rec = root / "live", root / "lab", root / "record"
        for d in (cls.live, cls.lab, cls.rec / "latest" / "books", cls.rec / "feed", cls.rec / "duels", cls.rec / "threads"):
            d.mkdir(parents=True)
        (cls.live / "status.json").write_text(json.dumps({"tick": 9, "updated": 1.0, "breakers": {"cautious": True, "cautious_until": 20},
                                                          "last_errors": [{"where": "breaker", "at": 100.0, "error": "3 refusals"}]}))
        (cls.live / "control.jsonl").write_text(json.dumps({"id": 1, "ts": 5, "change": {"armed": True}}) + "\n")
        (cls.lab / "notices.jsonl").write_text(json.dumps({"ts": 50.0, "kind": "seed", "text": "hola"}) + "\n")
        (cls.rec / "latest" / "me.json").write_text(json.dumps({"id": "t10", "cash": 7}))
        (cls.rec / "latest" / "books" / "v03.json").write_text(json.dumps({"venue": "v03", "offers": []}))
        (cls.rec / "index.json").write_text(json.dumps({"streams": {}}))
        seq = 0
        for day in ("2026-10-02", "2026-10-03"):
            with (cls.rec / "feed" / f"{day}.jsonl").open("w") as f:
                for _ in range(5):
                    seq += 1
                    f.write(json.dumps({"seq": seq, "ts": seq, "type": "x"}) + "\n")
        (cls.rec / "duels" / "7.json").write_text(json.dumps({"duel": 7, "session": 1, "status": "deal", "messages": [{"text": "a"}]}))
        (cls.rec / "duels" / "2026-10-03.jsonl").write_text(json.dumps({"seq": 1, "ts": 60.0, "duel": 7, "status": "live"}) + "\n" +
                                                           json.dumps({"seq": 2, "ts": 70.0, "duel": 7, "status": "deal"}) + "\n")
        (cls.rec / "threads" / "3.json").write_text(json.dumps({"id": 3, "with": "abuela", "messages": []}))
        cls.srv = server.make_server(0, cls.live, cls.lab, record=cls.rec)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def test_latest(self):
        self.assertEqual(self.get("/api/rec/latest/me")[1]["cash"], 7)
        self.assertEqual(self.get("/rec/latest/books/v03")[1]["venue"], "v03")
        self.assertIn("v03", self.get("/rec/latest/books")[1])
        self.assertEqual(self.get("/rec/latest/secret")[0], 404)
        self.assertEqual(self.get("/rec/latest/books/..%2Fme")[0], 404)

    def test_stream_across_days(self):
        st, out = self.get("/api/rec/stream/feed?since_seq=3&limit=4")
        self.assertEqual([r["seq"] for r in out["rows"]], [4, 5, 6, 7])
        self.assertEqual(out["last_seq"], 7)
        self.assertTrue(out["more"])
        self.assertEqual([r["seq"] for r in self.get("/rec/stream/feed?tail=3")[1]["rows"]], [8, 9, 10])
        self.assertEqual([r["seq"] for r in self.get("/rec/stream/feed?tail=7")[1]["rows"]], list(range(4, 11)))
        self.assertEqual(self.get("/rec/stream/feed?since_seq=10")[1]["rows"], [])
        with (self.rec / "feed" / "2026-10-03.jsonl").open("a") as f:
            f.write(json.dumps({"seq": 11, "ts": 11}) + "\n" + '{"seq": 12, "ts"')   # partial line is not served
        self.assertEqual([r["seq"] for r in self.get("/rec/stream/feed?since_seq=10")[1]["rows"]], [11])
        self.assertEqual(self.get("/rec/stream/nope")[0], 404)
        self.assertEqual(self.get("/rec/stream/feed?tail=x")[0], 400)

    def test_duels_threads_index(self):
        items = self.get("/rec/duels")[1]["items"]
        self.assertEqual(items[0]["duel"], 7)
        self.assertNotIn("messages", items[0])
        self.assertEqual(self.get("/rec/duels/7")[1]["messages"][0]["text"], "a")
        self.assertEqual(self.get("/rec/duels/8")[0], 404)
        self.assertEqual(self.get("/rec/threads")[1]["items"][0]["with"], "abuela")
        self.assertEqual(self.get("/rec/threads/3")[1]["id"], 3)
        self.assertEqual(self.get("/rec/index")[1], {"streams": {}})

    def test_notifications(self):
        items = self.get("/api/notifications")[1]["items"]
        types = {i["type"] for i in items}
        self.assertTrue({"lab", "breaker", "duelo"} <= types)
        for i in items:
            self.assertTrue({"id", "ts", "type", "title", "text", "href"} <= set(i))
        newer = self.get("/notifications?since=99")[1]["items"]
        self.assertTrue(all(i["ts"] > 99 for i in newer))
        self.assertEqual(self.get("/notifications?since=abc")[0], 400)

    def test_control_log(self):
        self.assertEqual(self.get("/api/control-log")[1]["items"][0]["change"], {"armed": True})

    def test_screens_static(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/static/ui.js") as r:
            self.assertIn("javascript", r.headers["Content-Type"])
        for bad in ("/screens/../app.js", "/screens/x.py"):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}{bad}")
                self.fail(bad)
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 404)


if __name__ == "__main__":
    unittest.main()
