import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bazaar.gateway import Gateway, GameError


class _Fake(BaseHTTPRequestHandler):
    hits: dict = {}

    def log_message(self, *a):
        pass

    def _send(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _route(self):
        n = self.hits[self.path] = self.hits.get(self.path, 0) + 1
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"null") if length else None
        if self.headers.get("X-Team-Key") != "tok":
            return self._send(401, {"error": "unauthorized", "message": "bad token"})
        if self.path.startswith("/api/me/value"):
            return self._send(200, {"card": "LAV-03", "your_value": 4.0})
        if self.path == "/api/me":
            return self._send(200, {"id": "t10", "cash": 400})
        if self.path == "/api/flaky":
            return self._send(502, {"error": "upstream"}) if n == 1 else self._send(200, {"ok": True})
        if self.path == "/api/busy":
            return self._send(429, {"error": "wait_for_tick", "message": "one per tick", "next_tick_in": 3.5})
        if self.path == "/api/valid":
            return self._send(422, {"detail": [{"msg": "field required"}]})
        if self.path == "/api/list":
            raw = b"[1, 2]"
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            return self.wfile.write(raw)
        return self._send(200, {"method": self.command, "path": self.path, "body": body,
                                "broker": self.headers.get("X-Broker-Key")})

    do_GET = do_POST = do_DELETE = do_PATCH = _route


class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        _Fake.hits.clear()

    def test_get_and_helpers(self):
        gw = Gateway(self.url, "tok")
        self.assertEqual(gw.me()["cash"], 400)
        self.assertEqual(gw.value("LAV-03"), 4.0)
        self.assertEqual(gw.get("/api/x", a=1, b=None)["path"], "/api/x?a=1")

    def test_writes_blocked_unless_real(self):
        gw = Gateway(self.url, "tok")
        for call in (lambda: gw.post("/api/offers", {}), lambda: gw.delete("/api/offers/1")):
            with self.assertRaises(GameError) as cm:
                call()
            self.assertEqual(cm.exception.code, "not_real")
        self.assertEqual(_Fake.hits, {})

    def test_real_post_with_broker_key(self):
        gw = Gateway(self.url, "tok", real=True)
        r = gw.post("/api/broker/matches", {"sell": 1, "buy": 2, "price": 5}, broker_key="bk")
        self.assertEqual((r["method"], r["body"]["price"], r["broker"]), ("POST", 5, "bk"))
        self.assertEqual(gw.delete("/api/offers/9")["method"], "DELETE")
        self.assertEqual(gw.patch("/api/venues/v", {"fee_bps": 1})["method"], "PATCH")

    def test_game_error_and_no_write_retry(self):
        gw = Gateway(self.url, "tok", real=True)
        with self.assertRaises(GameError) as cm:
            gw.post("/api/busy", {})
        e = cm.exception
        self.assertEqual((e.code, e.status, e.next_tick_in), ("wait_for_tick", 429, 3.5))
        self.assertEqual(_Fake.hits["/api/busy"], 1)

    def test_read_retries_once(self):
        gw = Gateway(self.url, "tok")
        self.assertEqual(gw.get("/api/flaky"), {"ok": True})
        self.assertEqual(_Fake.hits["/api/flaky"], 2)

    def test_error_codes(self):
        gw = Gateway(self.url, "tok")
        with self.assertRaises(GameError) as cm:
            gw.get("/api/valid")
        self.assertEqual(cm.exception.code, "validation")
        with self.assertRaises(GameError) as cm:
            Gateway(self.url, "bad").get("/api/me")
        self.assertEqual((cm.exception.code, cm.exception.status), ("unauthorized", 401))
        self.assertEqual(gw.get("/api/list"), {"items": [1, 2]})

    def test_network_error(self):
        with self.assertRaises(GameError) as cm:
            Gateway("http://127.0.0.1:9", "tok", timeout=1).get("/api/me")
        self.assertEqual(cm.exception.code, "network")


if __name__ == "__main__":
    unittest.main()
