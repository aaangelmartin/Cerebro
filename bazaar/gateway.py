"""HTTP client for the team gateway (the only door to the Bazaar). Standard library only.

Reads may retry once; writes never retry. A refused request raises GameError with the game's code
(`wait_for_tick`, `insufficient_cash`, ...). Writes need `real=True` (only run.py sets it).
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config

TIMEOUT_S = 10.0
MAX_RPS = 4.0                    # per process; the team key allows 5/s shared with the dashboard
RETRY_READ_CODES = {"rate_limited", "upstream", "network", "timeout", "server_error"}


class GameError(Exception):
    def __init__(self, code: str, message: str = "", status: int = 0, body: dict | None = None):
        super().__init__(f"{code}: {message}" if message else code)
        self.code, self.message, self.status, self.body = code, message, status, body or {}

    @property
    def next_tick_in(self) -> float | None:
        v = self.body.get("next_tick_in")
        return float(v) if isinstance(v, (int, float)) else None


class _RateLimiter:
    """Spaces requests at least 1/MAX_RPS apart across every Gateway in this process."""

    def __init__(self, rps: float):
        self.gap, self.next_at, self.lock = 1.0 / rps, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            at = max(now, self.next_at)
            self.next_at = at + self.gap
        if at > now:
            time.sleep(at - now)


_LIMITER = _RateLimiter(MAX_RPS)


class Gateway:
    def __init__(self, url: str = config.GATEWAY_URL, token: str = config.GATEWAY_TOKEN, real: bool = False,
                 timeout: float = TIMEOUT_S):
        self.url, self.token, self.real, self.timeout = url.rstrip("/"), token, real, timeout

    # --- verbs ------------------------------------------------------------------
    def get(self, path: str, **params) -> dict:
        q = {k: v for k, v in params.items() if v is not None}
        full = path + ("?" + urllib.parse.urlencode(q) if q else "")
        try:
            return self._request("GET", full)
        except GameError as e:
            if e.code not in RETRY_READ_CODES:
                raise
            time.sleep(0.5)
            return self._request("GET", full)

    def post(self, path: str, body: dict | None = None, broker_key: str | None = None) -> dict:
        self._guard(path)
        return self._request("POST", path, {} if body is None else body, broker_key)

    def patch(self, path: str, body: dict | None = None, broker_key: str | None = None) -> dict:
        self._guard(path)
        return self._request("PATCH", path, body or {}, broker_key)

    def delete(self, path: str) -> dict:
        self._guard(path)
        return self._request("DELETE", path)

    # --- helpers ----------------------------------------------------------------
    def me(self) -> dict:
        return self.get("/api/me")

    def clock(self) -> dict:
        return self.get("/api/clock")

    def value(self, card: str) -> float | None:
        """Our private value of one more copy of `card` (e.g. "LAV-03")."""
        r = self.get("/api/me/value", card=card)
        for k in ("value", "your_value", "next_copy"):
            if isinstance(r.get(k), (int, float)):
                return float(r[k])
        return None

    # --- plumbing ---------------------------------------------------------------
    def _guard(self, path: str):
        if not self.real:
            raise GameError("not_real", f"write to {path} blocked: gateway is not real")

    def _request(self, method: str, path: str, body: dict | None = None, broker_key: str | None = None) -> dict:
        headers = {"Accept": "application/json", "X-Team-Key": self.token}
        if broker_key:
            headers["X-Broker-Key"] = broker_key
        data = None
        if body is not None:
            data = json.dumps(body, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        _LIMITER.wait()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise _from_http(e) from None
        except TimeoutError:
            raise GameError("timeout", f"{method} {path} took over {self.timeout}s") from None
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            reason = getattr(e, "reason", e)
            code = "timeout" if "timed out" in str(reason) else "network"
            raise GameError(code, str(reason)) from None
        if not raw:
            return {}
        try:
            out = json.loads(raw)
        except ValueError:
            raise GameError("bad_json", raw[:200].decode(errors="replace")) from None
        return out if isinstance(out, dict) else {"items": out}


def _from_http(e: urllib.error.HTTPError) -> GameError:
    try:
        body = json.loads(e.read() or b"{}")
    except ValueError:
        body = {}
    finally:
        e.close()
    if not isinstance(body, dict):
        body = {"detail": body}
    code = body.get("error")
    if not code:
        if e.code == 422:
            code = "validation"
        elif e.code == 429:
            code = "rate_limited"
        elif e.code >= 500:
            code = "upstream" if e.code == 502 else "server_error"
        else:
            code = f"http_{e.code}"
    msg = body.get("message") or (json.dumps(body["detail"])[:300] if "detail" in body else e.reason or "")
    return GameError(str(code), str(msg), e.code, body)
