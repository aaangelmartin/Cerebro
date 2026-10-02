"""Local read-only dashboard for The Bazaar.

Serves index.html and proxies GET /api/* to the Bazaar, adding the team key
from ../.env so it never reaches the browser.

    python3 dashboard/server.py   ->  http://127.0.0.1:8787
"""

import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("DASHBOARD_PORT", "8787"))


def load_env(path):
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = {**load_env(ROOT.parent / ".env"), **os.environ}
BASE = ENV.get("BAZAAR_BASE_URL", "https://bazaar.causaprima.ai").rstrip("/")
TEAM_KEY = ENV.get("BAZAAR_TEAM_KEY", "")

# Only these read endpoints are proxied, so a shared link cannot reach anything else.
ALLOWED = {
    "/api/me", "/api/me/offers", "/api/me/threads", "/api/duels",
    "/api/clock", "/api/catalog", "/api/leaderboard", "/api/schedule",
    "/api/dealers", "/api/feed", "/api/levels", "/api/venues",
    "/api/health", "/api/me/value",
}
ALLOWED_PATTERNS = [
    re.compile(r"/api/dealers/[\w-]+"),
    re.compile(r"/api/venues/[\w-]+/offers"),
    re.compile(r"/api/cards/\d+"),
    re.compile(r"/api/threads/\d+"),
]


def allowed(path):
    return path in ALLOWED or any(p.fullmatch(path) for p in ALLOWED_PATTERNS)


# Every viewer shares one team key (5 req/s), so identical requests are served
# from a short cache and concurrent misses wait for a single upstream fetch.
SLOW = {"/api/catalog": 60, "/api/schedule": 30, "/api/dealers": 30}
CACHE_TTL = 4
_cache, _locks, _locks_guard = {}, {}, threading.Lock()


def fetch(path):
    req = urllib.request.Request(BASE + path, headers={"X-Team-Key": TEAM_KEY})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        return 502, f'{{"error":"upstream","message":"{e.reason}"}}'.encode()


def cached_fetch(path):
    ttl = SLOW.get(path.split("?")[0], CACHE_TTL)
    with _locks_guard:
        lock = _locks.setdefault(path, threading.Lock())
    with lock:
        hit = _cache.get(path)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1], hit[2]
        status, body = fetch(path)
        if status == 200:
            _cache[path] = (time.monotonic(), status, body)
        return status, body


# The team's shared docs, shown in the dashboard.
DOCS = ROOT.parent / "docs"
NOTES = {f"/notes/{name}": DOCS / name for name in ("LOG.md", "BAZAAR.md")}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path.split("?")[0] in NOTES:
            return self.send_note(NOTES[self.path.split("?")[0]])
        if not self.path.startswith("/api/"):
            if self.path.split("?")[0] not in ("/", "/index.html"):
                return self.send_error(404)
            return super().do_GET()
        if not allowed(self.path.split("?")[0]):
            return self.send_error(403)
        status, body = cached_fetch(self.path)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_note(self, path):
        if not path.exists():
            return self.send_error(404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    if not TEAM_KEY:
        print("warning: BAZAAR_TEAM_KEY is empty in .env")
    print(f"The Bazaar dashboard -> http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
