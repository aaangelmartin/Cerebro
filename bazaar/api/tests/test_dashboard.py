import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from bazaar.api import overview, server


def _jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.live, cls.lab, cls.stop = root / "live", root / "lab", root / "STOP"
        cls.live.mkdir()
        cls.lab.mkdir()
        now = time.time()
        (cls.live / "status.json").write_text(json.dumps({
            "updated": now, "state": "running", "armed": False, "allow_real": True, "tick": 300, "doors": "open",
            "paused": False, "tick_seconds": 60.0, "t_hours": 5.0, "cash": 66, "score": 24.6,
            "control": {"armed": False, "mode": "auto"},
            "last_errors": [{"at": now, "where": "breaker", "error": "market paused 10 ticks after 3 refusals"}]}))
        (cls.live / "tick_latest.json").write_text(json.dumps({
            "tick": 300, "tick_start": now - 20, "threads": [{"id": 7, "with": "abuela"}],
            "duels": [{"duel": 1067, "role": "buyer", "rival": "Oro", "your_limit": 158, "rounds": 1,
                       "rival_offer": {"price": 128}, "messages": [{"tick": 299, "from": "Oro", "price": 128}]}]}))
        (cls.live / "known.json").write_text(json.dumps({"schedule": ["4.0|day_opens|a", "6.5|duels|b", "18.0|day_closes|c"]}))
        _jsonl(cls.live / "decisions.jsonl", [
            {"id": 1, "ts": now - 5, "tick": 300, "source": "opus", "verdict": {"ok": True}, "dry_run": False,
             "action": {"id": "a1", "kind": "duel_message", "domain": "duels", "params": {"duel": 1067, "price": 131},
                        "reason": "r"}},
            {"id": 2, "ts": now - 4, "tick": 300, "source": "council", "verdict": {"ok": False, "rail": "council"},
             "dry_run": False, "action": {"id": "a2", "kind": "duel_accept", "domain": "duels",
                                          "params": {"duel": 1067, "expect": {"price": 128}}}},
        ])
        _jsonl(cls.live / "outcomes.jsonl", [{"id": 1, "ts": now - 5, "action_id": "a1", "status": "sent",
                                              "kind": "duel_message", "domain": "duels", "response": {}}])
        _jsonl(cls.live / "council.jsonl", [{"id": 1, "action_id": "a2", "result": "veto", "why": "auditor"}])
        _jsonl(cls.live / "leaderboard.jsonl", [
            {"id": 1, "tick": 230, "teams": {"t10": {"score": 20.0, "rank": 5}}},
            {"id": 2, "tick": 299, "rounds": [{"name": "Sábado", "status": "active"}],
             "teams": {"t10": {"score": 24.6, "rank": 3, "negotiating": 21.3, "market": 3.3}, "t01": {"score": 30}}},
        ])
        (cls.lab / "lessons.jsonl").write_text("")
        _jsonl(cls.lab / "notices.jsonl", [{"ts": now, "kind": "lesson_status", "text": "La lección L1 sube."}])
        overview._gateway_cache.update(at=now + 1e6, value={"ok": True, "code": 401, "latency_ms": 1})
        cls.srv = server.make_server(0, cls.live, cls.lab, stop_file=cls.stop)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        overview._gateway_cache.update(at=0.0, value=None)
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def raw(self, path, method="GET", headers=None, body=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=headers or {},
                                   data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.headers.get("Content-Type"), resp.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.headers.get("Content-Type"), e.read()

    def test_page_and_static(self):
        code, ctype, body = self.raw("/", headers={"Accept": "text/html,*/*"})
        self.assertEqual((code, ctype.split(";")[0]), (200, "text/html"))
        self.assertIn(b"static/app.js", body)
        code, ctype, body = self.raw("/")                       # curl keeps getting JSON health
        self.assertTrue(json.loads(body)["ok"])
        for f, t in (("app.js", "text/javascript"), ("styles.css", "text/css")):
            code, ctype, _ = self.raw(f"/static/{f}")
            self.assertEqual((code, ctype.split(";")[0]), (200, t))
        self.assertEqual(self.raw("/static/nope.js")[0], 404)
        self.assertEqual(self.raw("/static/..%2Fserver.py")[0], 404)

    def test_api_prefix_alias(self):
        a = json.loads(self.raw("/api/status")[2])
        self.assertEqual(a["tick"], 300)
        self.assertEqual(json.loads(self.raw("/api/decisions?since=1")[2])["items"][0]["id"], 2)

    def test_overview(self):
        code, _, body = self.raw("/api/overview")
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertEqual([r["id"] for r in d["activity"]], [1, 2])
        self.assertEqual(d["activity"][0]["outcome"]["status"], "sent")
        self.assertEqual(d["activity"][1]["council"]["result"], "veto")
        self.assertEqual(d["last_id"], 2)
        self.assertEqual((d["team"]["rank"], d["team"]["teams"], d["team"]["delta_1h"]), (3, 2, 4.6))
        self.assertEqual(d["threads"], {"7": "abuela"})
        self.assertAlmostEqual(d["clock"]["next_tick_in"], 40, delta=2)
        self.assertEqual(d["clock"]["next_event"]["action"], "duels")
        self.assertIsNotNone(d["clock"]["closes_at"])
        duel = d["duels"]["live"][0]
        self.assertEqual((duel["margin"], duel["rival_price"]), (30, 128))
        self.assertEqual(d["alerts"][0]["kind"], "breaker")
        self.assertEqual(d["lab"]["notices"][0]["text"], "La lección L1 sube.")
        self.assertEqual([p["name"] for p in d["processes"]], ["Bot", "Broker", "Laboratorio", "Pasarela"])
        self.assertTrue(d["processes"][0]["ok"])
        self.assertFalse(d["status"]["stop_file"])
        d2 = json.loads(self.raw("/overview?since=2")[2])
        self.assertEqual((d2["activity"], d2["last_id"]), ([], 2))

    def test_stop_file(self):
        h = {"Content-Type": "application/json"}
        self.assertEqual(self.raw("/api/stop", "POST", h, {})[0], 403)
        self.assertEqual(self.raw("/api/stop", "DELETE", h)[0], 403)
        self.assertFalse(self.stop.exists())
        h["X-Dashboard"] = "1"
        code, _, body = self.raw("/api/stop", "POST", h, {"by": "test"})
        self.assertEqual(code, 200)
        self.assertTrue(self.stop.exists())
        self.assertFalse(json.loads((self.live / "control.json").read_text())["armed"])
        self.assertTrue(json.loads(self.raw("/health")[2])["stop_file"])
        self.assertEqual(self.raw("/stop", "DELETE", h)[0], 200)
        self.assertFalse(self.stop.exists())
        self.assertEqual(self.raw("/stop", "DELETE", h)[0], 200)   # idempotent
        self.assertEqual(self.raw("/nope", "DELETE", h)[0], 404)


if __name__ == "__main__":
    unittest.main()
