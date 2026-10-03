"""JSON API for the new dashboard, on 127.0.0.1:config.API_PORT.

    python -m bazaar.api.server            # [--port 8791] [--live data/live]

GET  /                (the supervisor dashboard for browsers; JSON health otherwise)  /static/<file>
GET  /overview?since=  (everything the dashboard shows, in one read)
GET  /health /status /control /tick/latest /spend /broker /duels /lessons
GET  /decisions /outcomes /council /events /novelty /attribution /leaderboard   (?since=<id>&limit=)
GET  /rec/latest/<name>  /rec/latest/books/<venue>  /rec/stream/<stream>?since_seq=&limit=&tail=
GET  /rec/duels /rec/duels/<id> /rec/threads /rec/threads/<id> /rec/index      (the recorder's files, read-only)
GET  /notifications?since=<ts>   (bell / toasts)        GET /screens/<id>.js|css  (dashboard screens)
POST /control          {"armed", "mode", "caps", "protected", "paused_domains", "duel_claude_mode", "duel_days_sign"}   header X-Dashboard: 1
POST /lessons/{id}     {"status": "proposed|shadow|canary|active|retired"}         header X-Dashboard: 1
POST /stop             creates bazaar/STOP and disarms;  DELETE /stop removes it      header X-Dashboard: 1
Every path also answers under /api/... (the dashboard calls api/<path>, so it works behind the gateway's /v2/).

It only reads files under data/live (and data/lab); the bot reads control.json every tick.
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import config

JOURNALS = {"control", "decisions", "outcomes", "council", "events", "novelty", "attribution", "leaderboard", "llm"}
MODES = {"auto", "observe", "manual"}
LESSON_STATUSES = {"proposed", "shadow", "canary", "active", "retired"}
DASHBOARD_DIR = config.ROOT / "dashboard"
STATIC_RX = re.compile(r"/static/([\w-]+\.(js|css|svg|png|ico))")
SCREEN_RX = re.compile(r"(?:/static)?/screens/([a-z0-9_-]+\.(js|css))")
STATIC_TYPES = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8", "svg": "image/svg+xml",
                "png": "image/png", "ico": "image/x-icon", "html": "text/html; charset=utf-8"}
CORS_RX = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")
_control_lock = threading.Lock()


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _tail(path: Path, since: int | None, limit: int) -> list[dict]:
    try:
        from ..core.ledger import Ledger
        return Ledger(path.parent).tail(path.stem, since_id=since, limit=limit)
    except ImportError:
        rows = []
        try:
            for line in path.read_text().splitlines()[-limit * 2:]:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if since is None or int(r.get("id", 0)) > since:
                    rows.append(r)
        except OSError:
            pass
        return rows[-limit:]


def apply_control(live: Path, body: dict) -> dict:
    """Validate and merge a control change into control.json; returns the new control."""
    from ..run import DEFAULT_CONTROL, load_control
    change: dict = {}
    if "armed" in body:
        if not isinstance(body["armed"], bool):
            raise ValueError("armed must be true or false")
        change["armed"] = body["armed"]
    if "mode" in body:
        if body["mode"] not in MODES:
            raise ValueError(f"mode must be one of {sorted(MODES)}")
        change["mode"] = body["mode"]
    if "caps" in body:
        if not isinstance(body["caps"], dict) or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                         for v in body["caps"].values()):
            raise ValueError("caps must be an object of numbers")
        change["caps"] = body["caps"]
    for key, options in (("duel_claude_mode", {"bounded", "full", "code"}), ("duel_days_sign", {"value", "cost", "auto"})):
        if key in body:
            if body[key] not in options:
                raise ValueError(f"{key} must be one of {sorted(options)}")
            change[key] = body[key]
    for key in ("protected", "paused_domains"):
        if key in body:
            if not isinstance(body[key], list) or not all(isinstance(x, (str, int)) for x in body[key]):
                raise ValueError(f"{key} must be a list")
            change[key] = body[key]
    if not change:
        raise ValueError("nothing to change")
    with _control_lock:
        cur = load_control(live, DEFAULT_CONTROL)
        cur.update(change)
        cur["updated"] = time.time()
        tmp = live / "control.tmp"
        tmp.write_text(json.dumps(cur, indent=1))
        tmp.replace(live / "control.json")
    try:
        from ..core.ledger import Ledger
        Ledger(live).append("control", {"change": change, "by": "dashboard"})
    except Exception:  # noqa: BLE001
        pass
    return cur


class Handler(BaseHTTPRequestHandler):
    server_version = "bazaar-api/1"
    live: Path = config.LIVE
    lab: Path = config.LAB
    record: Path = config.DATA / "record"
    stop_file: Path = config.STOP_FILE
    dashboard: Path = DASHBOARD_DIR

    def log_message(self, fmt, *args):  # quiet
        pass

    # --- plumbing ---
    def _cors(self):
        origin = self.headers.get("Origin") or ""
        if CORS_RX.match(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Dashboard")

    def _send(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, ctype: str):
        try:
            body = path.read_bytes()
        except OSError:
            return self._send(404, {"error": "not_found", "message": path.name})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _route(raw: str) -> str:
        path = urlparse(raw).path
        if path == "/api" or path.startswith("/api/"):
            path = path[4:]
        return path.rstrip("/") or "/"

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # --- GET ---
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(u.query).items()}
        path = self._route(self.path)
        if path in ("/", "/index.html") and ("text/html" in (self.headers.get("Accept") or "")
                                             or path == "/index.html"):
            return self._send_file(self.dashboard / "index.html", STATIC_TYPES["html"])
        if path == "/static/cards.json":                         # official card art (tools/fetch_cards.py)
            return self._send_file(self.dashboard / "cards.json", "application/json; charset=utf-8")
        m = STATIC_RX.fullmatch(path)
        if m:
            return self._send_file(self.dashboard / m.group(1), STATIC_TYPES[m.group(2)])
        m = SCREEN_RX.fullmatch(path)
        if m:
            return self._send_file(self.dashboard / "screens" / m.group(1), STATIC_TYPES[m.group(2)])
        if path.startswith("/rec/") or path == "/notifications":
            try:
                return self._get_rec(path, q)
            except ValueError:
                return self._send(400, {"error": "bad_query", "message": "since/since_seq/limit/tail must be numbers"})
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": "server_error", "message": str(e)[:200]})
        try:
            since = int(q["since"]) if q.get("since") not in (None, "") else None
            limit = max(1, min(2000, int(q.get("limit") or 200)))
        except ValueError:
            return self._send(400, {"error": "bad_query", "message": "since and limit must be integers"})
        try:
            return self._get(path, since, limit)
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": "server_error", "message": str(e)[:200]})

    def _get(self, path: str, since, limit):
        live = self.live
        if path in ("/", "/health"):
            st = _read_json(live / "status.json", {}) or {}
            age = time.time() - float(st.get("updated") or 0) if st else None
            return self._send(200, {"ok": True, "time": time.time(), "bot_status_age_s": age,
                                    "stop_file": self.stop_file.exists()})
        if path == "/status":
            st = _read_json(live / "status.json", {}) or {}
            return self._send(200, {**st, "stop_file": self.stop_file.exists(),
                                    "age_s": time.time() - float(st.get("updated") or 0) if st else None})
        if path == "/control":
            from ..run import DEFAULT_CONTROL, load_control
            return self._send(200, load_control(live, DEFAULT_CONTROL))
        if path == "/tick/latest":
            return self._send(200, _read_json(live / "tick_latest.json", {}) or {})
        if path == "/duels":
            t = _read_json(live / "tick_latest.json", {}) or {}
            return self._send(200, {"tick": t.get("tick"), "duels": t.get("duels", [])})
        if path == "/broker":
            return self._send(200, _read_json(live / "broker_status.json", {}) or {})
        if path == "/spend":
            try:
                from ..llm import client
                return self._send(200, client.spend_today())
            except Exception as e:  # noqa: BLE001
                st = _read_json(live / "status.json", {}) or {}
                return self._send(200, {**(st.get("spend") or {}), "note": f"from status.json ({type(e).__name__})"})
        if path == "/lessons":
            return self._send(200, self._lessons())
        if path == "/overview":
            from . import overview
            return self._send(200, overview.build(live, self.lab, self.stop_file, since))
        name = path.lstrip("/")
        if name == "control-log":
            name = "control"
        if name in JOURNALS:
            return self._send(200, {"items": _tail(live / f"{name}.jsonl", since, limit)})
        return self._send(404, {"error": "not_found", "message": path})

    def _get_rec(self, path: str, q: dict):
        from . import rec
        record = self.record
        if path == "/notifications":
            since = float(q["since"]) if q.get("since") not in (None, "", "null", "undefined") else None
            return self._send(200, rec.notifications(self.live, self.lab, record, since))
        if path == "/rec/index":
            return self._send(200, _read_json(record / "index.json", {}) or {})
        if path.startswith("/rec/latest/"):
            doc = rec.latest(record, path[len("/rec/latest/"):])
            return self._send(200, doc) if doc is not None else self._send(404, {"error": "not_found", "message": path})
        m = re.fullmatch(r"/rec/stream/([a-z_]+)", path)
        if m:
            def num(k):
                v = q.get(k)
                return int(v) if v not in (None, "", "null", "undefined") else None
            limit = max(1, min(5000, num("limit") or 500))
            tail = num("tail")
            out = rec.stream(record, m.group(1), num("since_seq"), limit, max(1, tail) if tail else None)
            return self._send(200, out) if out is not None else self._send(404, {"error": "no_such_stream", "message": m.group(1)})
        if path == "/rec/duels":
            return self._send(200, rec.duels(record))
        if path == "/rec/threads":
            return self._send(200, rec.threads(record))
        m = re.fullmatch(r"/rec/(duels|threads)/([^/]+)", path)
        if m:
            doc = (rec.duel if m.group(1) == "duels" else rec.thread)(record, m.group(2))
            return self._send(200, doc) if doc is not None else self._send(404, {"error": "not_found", "message": path})
        return self._send(404, {"error": "not_found", "message": path})

    def _lessons(self) -> dict:
        try:
            from dataclasses import asdict
            from ..lab.store import LessonStore
            store = LessonStore(self.lab / "lessons.jsonl")
            lessons = [asdict(l) for l in store.all()]
        except ImportError:
            lessons = _tail(self.lab / "lessons.jsonl", None, 1000)
        notices = _tail(self.lab / "notices.jsonl", None, 50)
        return {"lessons": lessons, "notices": notices}

    # --- STOP file ---
    def do_DELETE(self):
        if self.headers.get("X-Dashboard") != "1":
            return self._send(403, {"error": "forbidden", "message": "writes need the X-Dashboard: 1 header"})
        if self._route(self.path) != "/stop":
            return self._send(404, {"error": "not_found", "message": self.path})
        try:
            self.stop_file.unlink(missing_ok=True)
        except OSError as e:
            return self._send(500, {"error": "server_error", "message": str(e)[:200]})
        self._log_stop(False)
        return self._send(200, {"stop_file": False, "armed": False,
                                "note": "STOP removed; the bot stays disarmed until someone arms it"})

    def _stop(self, body: dict):
        """Create bazaar/STOP and disarm: no write leaves the bot until both are undone."""
        self.stop_file.write_text(f"stopped by {str(body.get('by') or 'dashboard')[:40]} at {time.ctime()}\n")
        control = None
        try:
            control = apply_control(self.live, {"armed": False})
        except Exception as e:  # noqa: BLE001 - the file alone already stops every write
            control = {"error": str(e)[:200]}
        self._log_stop(True)
        return self._send(200, {"stop_file": True, "armed": False, "control": control})

    def _log_stop(self, on: bool):
        try:
            from ..core.ledger import Ledger
            Ledger(self.live).append("control", {"change": {"stop_file": on}, "by": "dashboard"})
        except Exception:  # noqa: BLE001
            pass

    # --- POST ---
    def do_POST(self):
        if self.headers.get("X-Dashboard") != "1":
            return self._send(403, {"error": "forbidden", "message": "writes need the X-Dashboard: 1 header"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 64 * 1024:
                return self._send(413, {"error": "too_large"})
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._send(400, {"error": "bad_json"})
        path = self._route(self.path)
        try:
            if path == "/stop":
                return self._stop(body)
            if path == "/control":
                return self._send(200, apply_control(self.live, body))
            m = re.fullmatch(r"/lessons/([A-Za-z0-9_.:\-]+)", path)
            if m:
                status = body.get("status")
                if status not in LESSON_STATUSES:
                    return self._send(400, {"error": "bad_status", "message": f"one of {sorted(LESSON_STATUSES)}"})
                from dataclasses import asdict
                from ..lab.store import LessonStore
                store = LessonStore(self.lab / "lessons.jsonl")
                try:
                    lesson = store.set_status(m.group(1), status, by="human", why=str(body.get("why", ""))[:200])
                except KeyError:
                    return self._send(404, {"error": "no_such_lesson", "message": m.group(1)})
                return self._send(200, asdict(lesson))
        except ValueError as e:
            return self._send(400, {"error": "bad_request", "message": str(e)})
        except ImportError as e:
            return self._send(503, {"error": "unavailable", "message": str(e)})
        return self._send(404, {"error": "not_found", "message": path})


def make_server(port: int = config.API_PORT, live: Path | None = None, lab: Path | None = None,
                host: str = "127.0.0.1", stop_file: Path | None = None, record: Path | None = None) -> ThreadingHTTPServer:
    live = Path(live or config.LIVE)
    record = Path(record) if record else (config.DATA / "record" if live == config.LIVE else live.parent / "record")
    handler = type("BoundHandler", (Handler,), {"live": live, "lab": Path(lab or config.LAB), "record": record,
                                                "stop_file": Path(stop_file or config.STOP_FILE)})
    ThreadingHTTPServer.request_queue_size = 128     # a page load asks for ~25 files at once
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    srv.daemon_threads = True
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m bazaar.api.server")
    ap.add_argument("--port", type=int, default=config.API_PORT)
    ap.add_argument("--live", default=None, help="data dir to serve (default config.LIVE)")
    ap.add_argument("--record", default=None, help="recorder dir (default config.DATA/record)")
    args = ap.parse_args(argv)
    srv = make_server(args.port, Path(args.live) if args.live else None, record=Path(args.record) if args.record else None)
    print(f"bazaar api on http://127.0.0.1:{args.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
