"""Read-only HTTP lanes for the recorder, each with its own token bucket.

- public: keyless reads straight to the public API (or the simulator). The server allows 60 req/s per address;
  the recorder keeps itself under PUBLIC_RPS.
- keyed: reads through the team gateway with X-Team-Key. The gateway's keyed budget (4.5 req/s) is shared with the
  bot, so the recorder takes at most KEYED_RPS of it, and card histories at most CARDS_RPS of that.

Only GET exists here: the recorder cannot write to the game even by mistake.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

from ..gateway import GameError, _from_http

PUBLIC_RPS = 1.8
KEYED_RPS = 0.5
CARDS_RPS = 0.2
TIMEOUT_S = 8.0
MAX_BACKOFF_S = 60.0


class Bucket:
    """Token bucket; `take()` never sleeps, the caller just tries again later."""

    def __init__(self, rate: float, burst: float = 1.0, now=time.monotonic):
        self.rate, self.burst, self.now = float(rate), float(burst), now
        self.tokens, self.at = float(burst), now()

    def _refill(self) -> None:
        t = self.now()
        self.tokens = min(self.burst, self.tokens + (t - self.at) * self.rate)
        self.at = t

    def ready(self) -> bool:
        self._refill()
        return self.tokens >= 1.0

    def take(self) -> bool:
        self._refill()
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def wait_s(self) -> float:
        self._refill()
        return 0.0 if self.tokens >= 1.0 else (1.0 - self.tokens) / self.rate


def http_get(base: str, path: str, params: dict | None, headers: dict, timeout: float) -> dict:
    q = {k: v for k, v in (params or {}).items() if v is not None}
    url = base.rstrip("/") + path + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise _from_http(e) from None
    except TimeoutError:
        raise GameError("timeout", f"GET {path} took over {timeout}s") from None
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise GameError("timeout" if "timed out" in str(reason) else "network", str(reason)[:200]) from None
    if not raw:
        return {}
    try:
        out = json.loads(raw)
    except ValueError:
        raise GameError("bad_json", raw[:200].decode(errors="replace")) from None
    return out if isinstance(out, dict) else {"items": out}


# Errors that mean "the lane is down" (back off and mark an outage) rather than "this one read failed".
DOWN_CODES = {"network", "timeout", "upstream", "server_error", "rate_limited", "bad_json"}


class Lane:
    def __init__(self, name: str, base: str, rps: float, headers: dict | None = None, burst: float = 1.0,
                 timeout: float = TIMEOUT_S, fetch=http_get, now=time.monotonic, wall=time.time):
        self.name, self.base, self.headers, self.timeout = name, base, dict(headers or {}), timeout
        self.bucket = Bucket(rps, burst, now)
        self.fetch, self.now, self.wall = fetch, now, wall
        self.sent: deque = deque()            # monotonic times of the last minute's requests
        self.total = 0
        self.errors: deque = deque(maxlen=20)
        self.fails = 0                        # consecutive lane-down failures
        self.paused_until = 0.0               # monotonic
        self.down_since: float | None = None  # wall time of the first failure of the current outage

    def available(self) -> bool:
        return self.now() >= self.paused_until and self.bucket.ready()

    def get(self, path: str, params: dict | None = None) -> dict:
        """One read. The caller checked available(); this spends the token. Raises GameError."""
        self.bucket.take()
        t = self.now()
        self.sent.append(t)
        self.total += 1
        try:
            out = self.fetch(self.base, path, params, self.headers, self.timeout)
        except GameError as e:
            self.errors.append({"t": round(self.wall(), 1), "path": path, "code": e.code, "msg": str(e)[:160]})
            if e.code in DOWN_CODES:
                self.fails += 1
                if self.down_since is None:
                    self.down_since = self.wall()
                wait = 5.0 if e.code == "rate_limited" else min(MAX_BACKOFF_S, 1.0 * 2 ** min(self.fails, 6))
                self.paused_until = self.now() + wait
            raise
        self.fails = 0
        return out

    def recovered(self) -> float | None:
        """If an outage just ended, return when it started (and forget it)."""
        if self.down_since is not None and self.fails == 0:
            s, self.down_since = self.down_since, None
            return s
        return None

    def rps(self) -> float:
        cut = self.now() - 60.0
        while self.sent and self.sent[0] < cut:
            self.sent.popleft()
        return round(len(self.sent) / 60.0, 3)

    def status(self) -> dict:
        return {"base": self.base, "rps_60s": self.rps(), "limit_rps": self.bucket.rate, "total": self.total,
                "down_since": self.down_since, "fails": self.fails,
                "paused_for_s": round(max(0.0, self.paused_until - self.now()), 1),
                "last_errors": list(self.errors)[-5:]}
