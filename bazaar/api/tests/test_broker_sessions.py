import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from bazaar.api import server


class BrokerSessionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.live = Path(cls.tmp.name) / "live"
        bench = cls.live / "bench"
        bench.mkdir(parents=True)
        res = {"type": "result", "tick": 218, "run": "b7", "session": "2026-10-03-b7", "t": 1000.0,
               "score": {"bench_efficiency": 0.899}, "est_efficiency": 0.81, "stall_efficiency": 0.89,
               "stats": {"start_tick": 202, "matches": 5}, "vs_stall": {"basis": "replay"}}
        (bench / "results.jsonl").write_text(json.dumps(res) + "\n")
        with (bench / "2026-10-03-b7.jsonl").open("w") as f:
            f.write(json.dumps({"type": "start", "tick": 201, "t": 900.0}) + "\n")
            for t in range(202, 206):
                f.write(json.dumps({"type": "tick", "tick": t, "t": 900.0 + t, "traders": list(range(100))}) + "\n")
        with (bench / "2026-10-03-b25.jsonl").open("w") as f:
            f.write(json.dumps({"type": "start", "tick": 441, "t": 2000.0}) + "\n")
            f.write(json.dumps({"type": "tick", "tick": 442, "t": 2030.0}) + "\n")
        (bench / "2026-10-03-evil.jsonl").write_text("{}\n")
        cls.srv = server.make_server(0, cls.live, Path(cls.tmp.name) / "lab")
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}")

    def test_sessions(self):
        code, body = self.get("/api/broker/sessions")
        self.assertEqual(code, 200)
        items = body["items"]
        self.assertEqual([i["run"] for i in items], ["b7", "b25"])
        self.assertEqual(items[0]["status"], "done")
        self.assertEqual(items[0]["score"]["bench_efficiency"], 0.899)
        self.assertEqual(items[0]["start_tick"], 202)
        self.assertEqual(items[1]["status"], "live")
        self.assertEqual(items[1]["start_tick"], 441)

    def test_session_rows(self):
        code, body = self.get("/broker/session/b7?since_tick=203&limit=10")
        self.assertEqual(code, 200)
        self.assertEqual([r["tick"] for r in body["rows"]], [204, 205])
        self.assertEqual(len(body["rows"][0]["traders"]), server.TRADERS_MAX)
        self.assertEqual(body["rows"][0]["traders_trimmed"], 100)
        self.assertEqual(self.get("/broker/session/b99")[0], 404)
        self.assertEqual(self.get("/broker/session/..%2Fx")[0], 400)
        self.assertEqual(self.get("/broker/session/b7?limit=x")[0], 400)


if __name__ == "__main__":
    unittest.main()
