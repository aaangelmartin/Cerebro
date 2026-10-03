"""Team gateway and dashboard for The Bazaar.

This machine is the only one that talks to the Bazaar. Teammates reach it
through ngrok:

- Browsers open the dashboard with basic auth (DASHBOARD_USER/DASHBOARD_PASSWORD).
  They may read an allowlist of routes and send the manual console's actions,
  which must carry the X-Dashboard header.
- Bots use the official SDK unchanged, pointed at this server:
  BAZAAR_URL=<ngrok url> BAZAAR_KEY=<their personal token>. Their X-Team-Key is
  swapped for the real team key here. They may call any non-admin route.

Every upstream call goes through one rate limiter per budget: keyed calls stay
under the team key's 5 req/s, and public reads go without the key, which has
its own per-address budget. One upstream event stream plus a poll of the
public feed are fanned out to everyone on /events (and /api/events/stream for
bots). Every write is appended to dashboard/actions.log.

    python3 dashboard/server.py   ->  http://127.0.0.1:8787
"""

import base64
import collections
import hmac
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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


ENV = {**load_env(Path(os.environ.get("DASHBOARD_ENV_FILE") or ROOT.parent / ".env")), **os.environ}
BASE = ENV.get("BAZAAR_BASE_URL", "https://bazaar.causaprima.ai").rstrip("/")
TEAM_KEY = ENV.get("BAZAAR_TEAM_KEY", "")
# Personal gateway tokens, "name:token,name:token"; GATEWAY_TOKEN is the owner's.
GATEWAY_TOKENS = dict(
    reversed(item.strip().split(":", 1)) for item in ENV.get("GATEWAY_TOKENS", "").split(",") if ":" in item
)
if ENV.get("GATEWAY_TOKEN"):
    GATEWAY_TOKENS[ENV["GATEWAY_TOKEN"]] = "owner"
DASHBOARD_AUTH = f"{ENV.get('DASHBOARD_USER', '')}:{ENV.get('DASHBOARD_PASSWORD', '')}"

# Public reads are fetched without the key; the rest of the dashboard's reads need it.
PUBLIC = {
    "/api/health", "/api/clock", "/api/catalog", "/api/leaderboard", "/api/feed",
    "/api/schedule", "/api/dealers", "/api/levels", "/api/venues",
}
PUBLIC_PATTERNS = [re.compile(r"/api/dealers/[\w-]+"), re.compile(r"/api/venues/[\w-]+/offers")]
PRIVATE = {"/api/me", "/api/me/offers", "/api/me/threads", "/api/me/value", "/api/duels"}
PRIVATE_PATTERNS = [re.compile(r"/api/cards/\d+"), re.compile(r"/api/threads/\d+")]

# Game actions the manual console may send, as (method, path pattern).
CONSOLE_WRITES = [(m, re.compile(p)) for m, p in [
    ("POST", r"/api/threads"),
    ("POST", r"/api/threads/\d+/messages"),
    ("POST", r"/api/threads/\d+/close"),
    ("POST", r"/api/offers"),
    ("DELETE", r"/api/offers/\d+"),
    ("POST", r"/api/offers/\d+/accept"),
    ("POST", r"/api/packs/\d+/open"),
    ("POST", r"/api/duels/\d+/messages"),
    ("POST", r"/api/duels/\d+/accept"),
    ("POST", r"/api/flags"),
]]
OPEN_WITHOUT_AUTH = {"/api/clock", "/api/health"}  # the SDK reads the clock without headers
MAX_BODY = 64 * 1024
ACTIONS_LOG = ROOT / "actions.log"
DOCS = ROOT.parent / "docs"
BOT_DATA = Path(ENV.get("BOT_DATA_DIR") or ROOT.parent / "bot" / "data")  # written by the team's bot
NOTES = {f"/notes/{name}": DOCS / name for name in ("LOG.md", "BAZAAR.md")}
# Front-end modules: dashboard/static/<name>.(js|css|svg), one level of subfolders.
STATIC = re.compile(r"/static/(?:[\w-]+/)?[\w.-]+\.(js|css|svg)")
STATIC_TYPES = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8", "svg": "image/svg+xml"}


def is_public(path):
    return path in PUBLIC or any(p.fullmatch(path) for p in PUBLIC_PATTERNS)


def is_private_read(path):
    return path in PRIVATE or any(p.fullmatch(path) for p in PRIVATE_PATTERNS)


class Bucket:
    """Token bucket that waits for a token instead of failing."""

    def __init__(self, rate, burst):
        self.rate, self.burst, self.tokens, self.at = rate, burst, burst, time.monotonic()
        self.lock = threading.Lock()

    def take(self):
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.burst, self.tokens + (now - self.at) * self.rate)
                self.at = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


# The team key allows 5/s (bursts of 20); a dev server runs slower so the live gateway keeps the budget.
KEYED = Bucket(rate=float(ENV.get("GATEWAY_KEYED_RATE", "4.5")), burst=15)
READ_ONLY = ENV.get("DASHBOARD_READ_ONLY") == "1"  # dev servers refuse every write
KEYLESS = Bucket(rate=20, burst=30)  # keyless reads allow 60/s per address


def fetch(path_qs, method="GET", body=None, keyed=True, extra_headers=None):
    (KEYED if keyed else KEYLESS).take()
    headers = {"Accept": "application/json", **(extra_headers or {})}
    if keyed:
        headers["X-Team-Key"] = TEAM_KEY
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path_qs, data=body, method=method, headers=headers)
    try:
        # Opening a venue returns the broker key only once: give it longer than the bot's 30 s wait.
        slow = method == "POST" and path_qs.split("?")[0] == "/api/venues"
        with urllib.request.urlopen(req, timeout=40 if slow else 20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        return 502, json.dumps({"error": "upstream", "message": str(e.reason)}).encode()


# Dashboard reads share a short cache; concurrent misses wait for one upstream fetch.
SLOW = {"/openapi.json": 600, "/api/catalog": 60, "/api/schedule": 30, "/api/dealers": 20}
CACHE_TTL = 4
_cache, _locks, _locks_guard = {}, {}, threading.Lock()


def cached_fetch(path_qs, keyed):
    ttl = SLOW.get(path_qs.split("?")[0], CACHE_TTL)
    with _locks_guard:
        lock = _locks.setdefault(path_qs, threading.Lock())
    with lock:
        hit = _cache.get(path_qs)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1], hit[2]
        status, body = fetch(path_qs, keyed=keyed)
        if status == 200:
            _cache[path_qs] = (time.monotonic(), status, body)
        return status, body


# The bot's own control API (bot/control_api.py), reachable only from this machine.
BOT_CONTROL = ENV.get("BOT_CONTROL_URL", "http://127.0.0.1:8790").rstrip("/")
BOT_CONTROL_PREFIXES = ("/bot/live/", "/bot/practice/")


def bot_control(path_qs, body=None):
    headers = {"Accept": "application/json", "X-Dashboard": "1"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BOT_CONTROL + path_qs, data=body, method="POST" if body is not None else "GET",
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        return 502, json.dumps({"error": "bot_offline", "message": str(e.reason)}).encode()


# The new bot's supervisor dashboard and API (bazaar/api/server.py), served under /v2/ for logged-in users.
V2_URL = ENV.get("BAZAAR_API_URL", "http://127.0.0.1:8791").rstrip("/")
V2_PREFIX = "/v2"


def v2_proxy(path_qs, method="GET", body=None, accept=None, dashboard_header=False):
    """Forwards /v2/<rest> to the bazaar API; returns (status, content type, body)."""
    rest = path_qs[len(V2_PREFIX):] or "/"
    headers = {"Accept": accept or "*/*"}
    if dashboard_header:
        headers["X-Dashboard"] = "1"
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(V2_URL + rest, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers.get("Content-Type", "application/json"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "application/json"), e.read()
    except urllib.error.URLError as e:
        return 502, "application/json", json.dumps({"error": "bazaar_api_offline", "message": str(e.reason)}).encode()


SECRET_FIELDS = {"broker_key", "key", "x-broker-key"}
_SECRET_RE = re.compile(r'("(?:broker_key|key|X-Broker-Key)"\s*:\s*)"[^"]*"', re.IGNORECASE)


def redact(obj):
    """A copy with every broker_key/key field replaced, at any depth (the venue response carries the key once)."""
    if isinstance(obj, dict):
        return {k: ("<redacted>" if str(k).lower() in SECRET_FIELDS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def _redact_text(raw):
    """Logged text with secrets removed: parsed as JSON when possible, else a regex over the raw text."""
    text = (raw or b"").decode(errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
    try:
        return json.dumps(redact(json.loads(text)), ensure_ascii=False)
    except ValueError:
        return _SECRET_RE.sub(r'\1"<redacted>"', text)


def log_action(client, method, path, body, status, resp):
    with ACTIONS_LOG.open("a") as f:
        f.write(json.dumps({
            "at": time.strftime("%Y-%m-%d %H:%M:%S"), "client": client, "method": method, "path": path,
            "body": _redact_text(body), "status": status,
            "response": _redact_text(resp)[:2000],
        }) + "\n")


class Hub:
    """Recent events from the team stream and the public feed, fanned out to every listener."""

    def __init__(self, size=1000):
        self.events = collections.deque(maxlen=size)
        self.seq = 0
        self.cond = threading.Condition()

    def publish(self, source, kind, data):
        with self.cond:
            self.seq += 1
            self.events.append({"seq": self.seq, "source": source, "type": kind, "data": data})
            self.cond.notify_all()

    def since(self, seq, timeout):
        with self.cond:
            if not self.events or self.events[-1]["seq"] <= seq:
                self.cond.wait(timeout)
            return [e for e in self.events if e["seq"] > seq]


HUB = Hub()


def team_stream():
    """Holds the single upstream stream for our key and republishes its events."""
    backoff = 1
    while True:
        try:
            KEYED.take()
            req = urllib.request.Request(
                BASE + "/api/events/stream?scope=team",
                headers={"X-Team-Key": TEAM_KEY, "Accept": "text/event-stream"})
            with urllib.request.urlopen(req, timeout=90) as r:
                backoff, kind, data = 1, "message", []
                for raw in r:
                    line = raw.decode(errors="replace").rstrip("\r\n")
                    if line.startswith("event:"):
                        kind = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].strip())
                    elif not line and data:
                        try:
                            payload = json.loads("\n".join(data))
                        except ValueError:
                            payload = "\n".join(data)
                        HUB.publish("team", kind, payload)
                        kind, data = "message", []
        except Exception as e:  # noqa: BLE001 - reconnect on anything
            HUB.publish("gateway", "gateway.stream_error", {"message": str(e)})
        time.sleep(backoff)
        backoff = min(backoff * 2, 30)


class History:
    """Leaderboard snapshots over time, kept in memory and appended to dashboard/data/leaderboard.jsonl."""

    def __init__(self, path, size=2000):
        self.path, self.snaps, self.lock = path, collections.deque(maxlen=size), threading.Lock()
        if path.exists():
            for line in path.read_text().splitlines()[-size:]:
                try:
                    self.snaps.append(json.loads(line))
                except ValueError:
                    pass

    def add(self, snap):
        with self.lock:
            last = self.snaps[-1] if self.snaps else None
            if last and last["teams"] == snap["teams"] and last["tick"] == snap["tick"]:
                return
            self.snaps.append(snap)
            self.path.parent.mkdir(exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(snap) + "\n")

    def dump(self):
        with self.lock:
            return list(self.snaps)


HISTORY = History(ROOT / "data" / "leaderboard.jsonl")


def leaderboard_recorder():
    """Snapshots the public leaderboard every minute (keyless) for the rivals analytics."""
    keep = ("score", "negotiating", "market", "level", "album_filled", "pages_complete", "deals", "rank", "venue")
    while True:
        status, body = fetch("/api/leaderboard", keyed=False)
        if status == 200:
            try:
                lb = json.loads(body)
                HISTORY.add({
                    "at": int(time.time()), "tick": lb.get("tick"), "round": lb.get("round"),
                    "teams": {t["team"]: {k: t.get(k) for k in keep} for t in lb.get("teams", [])},
                })
            except (ValueError, KeyError, TypeError):
                pass
        time.sleep(60)


def feed_poller():
    """Republishes new public feed events, oldest first."""
    seen = 0
    while True:
        status, body = fetch("/api/feed?limit=100", keyed=False)
        if status == 200:
            try:
                events = json.loads(body).get("events", [])
            except ValueError:
                events = []
            for e in sorted(events, key=lambda e: e.get("id", 0)):
                if e.get("id", 0) > seen:
                    seen = e["id"]
                    HUB.publish("public", e.get("type", "event"), e)
        time.sleep(3)


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def client(self):
        """'bot:<name>' for a gateway token, 'dashboard' for basic auth, else None."""
        token = self.headers.get("X-Team-Key", "")
        for known, name in GATEWAY_TOKENS.items():
            if token and hmac.compare_digest(token, known):
                return f"bot:{name}"
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic ") and DASHBOARD_AUTH != ":":
            try:
                given = base64.b64decode(auth[6:]).decode()
            except ValueError:
                return None
            if hmac.compare_digest(given, DASHBOARD_AUTH):
                return "dashboard"
        return None

    def deny(self):
        body = b'{"error":"unauthorized","message":"dashboard login or gateway token required"}'
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Bazaar Team 10"')
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        client = self.client()
        if client is None and path not in OPEN_WITHOUT_AUTH:
            return self.deny()
        if path == V2_PREFIX or path.startswith(V2_PREFIX + "/"):
            return self.v2(client, "GET")
        if path == "/bot/status":
            return self.send_file(BOT_DATA / "status.json", "application/json")
        if path.startswith(BOT_CONTROL_PREFIXES):
            if client != "dashboard":
                return self.send_error(403)
            return self.send_json(*bot_control(self.path))
        if path == "/bot/intel":
            return self.send_file(BOT_DATA / "intel.json", "application/json")
        if path == "/bot/decisions":
            return self.send_json(200, json.dumps({"decisions": tail_jsonl(
                BOT_DATA / "decisions.jsonl", _int(_query(self.path).get("limit"), 50))}).encode())
        if path == "/intel/history":
            return self.send_json(200, json.dumps({"snapshots": HISTORY.dump()}).encode())
        if path == "/gateway/whoami":
            return self.send_json(200, json.dumps({"client": client, "team": "t10"}).encode())
        if path == "/openapi.json":
            return self.send_json(*cached_fetch("/openapi.json", keyed=False))
        if path == "/gateway/guide":
            return self.send_file(DOCS / "GATEWAY_API.md", "text/markdown; charset=utf-8")
        if path in ("/events", "/api/events/stream"):
            return self.stream()
        if path in NOTES:
            return self.send_file(NOTES[path], "text/markdown; charset=utf-8")
        if STATIC.fullmatch(path) and ".." not in path:
            return self.send_file(ROOT / path.lstrip("/"), STATIC_TYPES[path.rsplit(".", 1)[1]])
        if not path.startswith("/api/"):
            if path not in ("/", "/index.html"):
                return self.send_error(404)
            return self.send_file(ROOT / "index.html", "text/html; charset=utf-8")
        if path.startswith("/api/admin"):
            return self.send_error(403)
        if is_public(path):
            if (client or "").startswith("bot"):
                return self.send_json(*fetch(self.path, keyed=False))
            return self.send_json(*cached_fetch(self.path, keyed=False))
        if (client or "").startswith("bot"):
            return self.send_json(*fetch(self.path, extra_headers=self.broker_header()))
        if is_private_read(path):
            return self.send_json(*cached_fetch(self.path, keyed=True))
        return self.send_error(403)

    def do_POST(self):
        self.write("POST")

    def do_PUT(self):
        self.write("PUT")

    def do_PATCH(self):
        self.write("PATCH")

    def do_DELETE(self):
        self.write("DELETE")

    def write(self, method):
        path = self.path.split("?")[0]
        client = self.client()
        if client is None:
            return self.deny()
        if path.startswith(V2_PREFIX + "/"):
            return self.v2(client, method)
        if path.startswith(BOT_CONTROL_PREFIXES):
            return self.bot_write(client, path)
        if READ_ONLY:
            return self.send_json(403, b'{"error":"read_only","message":"this dev server never writes"}')
        if not path.startswith("/api/") or path.startswith("/api/admin"):
            return self.send_error(403)
        if client == "dashboard":
            if not any(m == method and p.fullmatch(path) for m, p in CONSOLE_WRITES):
                return self.send_error(403)
            # A custom header cannot be sent cross-site without a CORS preflight, which this server never grants.
            if self.headers.get("X-Dashboard") != "1":
                return self.send_error(403)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self.send_error(413)
        body = self.rfile.read(length) if length else (b"{}" if method in ("POST", "PUT", "PATCH") else None)
        status, resp = fetch(self.path, method, body, extra_headers=self.broker_header())
        _cache.clear()
        log_action(client, method, path, body, status, resp)
        self.send_json(status, resp)

    def bot_write(self, client, path):
        """Arming, mode and approvals for the bot: dashboard users only, never bot tokens."""
        if client != "dashboard" or self.headers.get("X-Dashboard") != "1":
            return self.send_error(403)
        if READ_ONLY:
            return self.send_json(403, b'{"error":"read_only","message":"this dev server never writes"}')
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self.send_error(413)
        body = self.rfile.read(length) if length else b"{}"
        status, resp = bot_control(self.path, body)
        log_action(client, "POST", path, body, status, resp)
        self.send_json(status, resp)

    def v2(self, client, method):
        """The new dashboard: browsers with the dashboard login only, never bot tokens."""
        path = self.path.split("?")[0]
        if client != "dashboard":
            return self.send_error(403)
        if path == V2_PREFIX:  # relative URLs in the page need the trailing slash
            self.send_response(301)
            self.send_header("Location", V2_PREFIX + "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "GET":
            status, ctype, body = v2_proxy(self.path, accept=self.headers.get("Accept"))
            return self.send_raw(status, ctype, body)
        if method not in ("POST", "DELETE") or self.headers.get("X-Dashboard") != "1":
            return self.send_error(403)
        if READ_ONLY:
            return self.send_json(403, b'{"error":"read_only","message":"this dev server never writes"}')
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self.send_error(413)
        body = self.rfile.read(length) if length else (b"{}" if method == "POST" else None)
        status, ctype, resp = v2_proxy(self.path, method, body, dashboard_header=True)
        log_action(client, method, path, body, status, resp)
        self.send_raw(status, ctype, resp)

    def send_raw(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def broker_header(self):
        key = self.headers.get("X-Broker-Key")
        return {"X-Broker-Key": key} if key else {}

    def stream(self):
        """Server-sent events from the hub; Last-Event-ID or ?since=<seq> replays what was missed."""
        try:
            since = int(self.headers.get("Last-Event-ID") or _query(self.path).get("since", -1))
        except ValueError:
            since = -1
        if since < 0:  # a new listener gets recent history
            since = max(0, HUB.seq - 200)
        named = self.path.startswith("/api/events/stream")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        try:
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            while True:
                events = HUB.since(since, timeout=15)
                if not events:
                    self.wfile.write(b": keepalive\n\n")
                for e in events:
                    since = e["seq"]
                    # Browsers listen with onmessage, which only sees unnamed events; bots get the type as the name.
                    name = f"event: {e['type']}\n" if named else ""
                    self.wfile.write(f"id: {e['seq']}\n{name}data: {json.dumps(e)}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def send_json(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type):
        if not path.exists():
            return self.send_error(404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if ENV.get("DASHBOARD_LOG") == "1":  # request log for debugging a browser
            print(f"{time.strftime('%H:%M:%S')} {self.headers.get('User-Agent', '')[:40]!r} "
                  f"auth={'y' if self.headers.get('Authorization') else 'n'} {fmt % args}", flush=True)


def _int(value, default):
    try:
        return max(1, min(int(value), 1000))
    except (TypeError, ValueError):
        return default


def tail_jsonl(path, limit):
    """The last `limit` JSON lines of a file, newest first."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out[::-1]


def _query(path):
    return {k: v[-1] for k, v in parse_qs(urlsplit(path).query).items()}


class Server(ThreadingHTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    if not TEAM_KEY:
        print("warning: BAZAAR_TEAM_KEY is empty in .env")
    if not GATEWAY_TOKENS:
        print("warning: no gateway tokens in .env; bots cannot use the gateway")
    threading.Thread(target=team_stream, daemon=True).start()
    threading.Thread(target=feed_poller, daemon=True).start()
    threading.Thread(target=leaderboard_recorder, daemon=True).start()
    print(f"The Bazaar gateway -> http://127.0.0.1:{PORT}")
    Server(("127.0.0.1", PORT), Handler).serve_forever()
