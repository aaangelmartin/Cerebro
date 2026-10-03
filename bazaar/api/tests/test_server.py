import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from bazaar.api import server
from bazaar.core.types import Lesson


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.live, cls.lab = root / "live", root / "lab"
        cls.live.mkdir()
        cls.lab.mkdir()
        (cls.live / "status.json").write_text(json.dumps({"tick": 9, "updated": 1.0, "cash": 5}))
        (cls.live / "tick_latest.json").write_text(json.dumps({"tick": 9, "duels": [{"duel": 1}]}))
        with (cls.live / "decisions.jsonl").open("w") as f:
            for i in range(1, 6):
                f.write(json.dumps({"id": i, "ts": i, "tick": i}) + "\n")
        from dataclasses import asdict
        (cls.lab / "lessons.jsonl").write_text(json.dumps(asdict(Lesson(id="L1", scope="duel", rule="r"))) + "\n")
        cls.srv = server.make_server(0, cls.live, cls.lab)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def req(self, path, body=None, headers=None, method=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers or {},
                                   method=method or ("POST" if data is not None else "GET"))
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, json.loads(resp.read() or b"{}"), resp.headers
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}"), e.headers

    def test_health_status_tick(self):
        self.assertTrue(self.req("/health")[1]["ok"])
        self.assertEqual(self.req("/status")[1]["tick"], 9)
        self.assertEqual(self.req("/tick/latest")[1]["tick"], 9)
        self.assertEqual(self.req("/duels")[1]["duels"], [{"duel": 1}])

    def test_journal_since(self):
        code, body, _ = self.req("/decisions?since=3")
        self.assertEqual([r["id"] for r in body["items"]], [4, 5])
        self.assertEqual(self.req("/outcomes")[1]["items"], [])
        self.assertEqual(self.req("/decisions?since=x")[0], 400)
        self.assertEqual(self.req("/nope")[0], 404)

    def test_control_needs_header_and_validates(self):
        self.assertEqual(self.req("/control", {"armed": True})[0], 403)
        h = {"X-Dashboard": "1", "Content-Type": "application/json"}
        self.assertEqual(self.req("/control", {"armed": "yes"}, h)[0], 400)
        code, body, _ = self.req("/control", {"armed": True, "protected": [12], "paused_domains": ["market"]}, h)
        self.assertEqual(code, 200)
        saved = json.loads((self.live / "control.json").read_text())
        self.assertEqual((saved["armed"], saved["protected"], saved["mode"]), (True, [12], "auto"))
        self.assertEqual(self.req("/control")[1]["paused_domains"], ["market"])

    def test_lessons_get_and_set(self):
        self.assertEqual(self.req("/lessons")[1]["lessons"][0]["id"], "L1")
        h = {"X-Dashboard": "1"}
        self.assertEqual(self.req("/lessons/L1", {"status": "bogus"}, h)[0], 400)
        self.assertEqual(self.req("/lessons/NOPE", {"status": "active"}, h)[0], 404)
        code, body, _ = self.req("/lessons/L1", {"status": "active"}, h)
        self.assertEqual((code, body["status"]), (200, "active"))

    def test_cors_localhost_only(self):
        _, _, h = self.req("/status", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(h.get("Access-Control-Allow-Origin"), "http://localhost:5173")
        _, _, h = self.req("/status", headers={"Origin": "https://evil.example"})
        self.assertIsNone(h.get("Access-Control-Allow-Origin"))


if __name__ == "__main__":
    unittest.main()
