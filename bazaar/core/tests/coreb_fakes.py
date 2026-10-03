"""Test doubles shared by CORE-B tests (state, council, run, api). Not a test module itself."""
from __future__ import annotations

import copy


class FakeError(Exception):
    def __init__(self, code="boom", message="", status=500):
        super().__init__(message or code)
        self.code, self.message, self.status, self.body = code, message, status, {"error": code}


def clock(tick=10, next_tick_in=20.0, tick_seconds=30.0, paused=False, doors="open", limits=None, today="sat"):
    return {"tick": tick, "t_hours": tick * tick_seconds / 3600, "tick_seconds": tick_seconds, "paused": paused,
            "next_tick_in": next_tick_in, "doors": doors, "today": today,
            "limits": limits or {"accepts_per_team_per_tick": 1, "messages_per_side_per_tick": 1,
                                 "max_open_threads_per_team": 6, "max_open_offers_per_team": 30,
                                 "offers_per_team_per_tick": 12}}


class FakeGateway:
    """Answers GETs from a dict of path -> response (callable or value); records every call."""

    def __init__(self, routes: dict | None = None, real: bool = False):
        self.calls: list[tuple] = []
        self.posts: list[tuple] = []
        self.real = real
        self.routes = {
            "/api/clock": clock(),
            "/api/me": {"id": "t10", "cash": 300, "collection_value": 700.0, "score": {"score": 20.0},
                        "assets": [], "level": 2},
            "/api/me/threads": {"threads": []},
            "/api/me/offers": {"offers": []},
            "/api/duels": {"duels": []},
            "/api/feed": {"events": []},
            "/api/dealers": {"personas": [{"id": "abuela", "status": "active", "menu": {"sells": []}}]},
            "/api/levels": {"levels": [{"id": "chato", "state": "active"}]},
            "/api/schedule": {"upcoming": [{"at_hours": 5.0, "action": "bench", "params": {}}]},
            "/api/venues": {"venues": []},
            "/api/leaderboard": {"tick": 9, "round": 2, "teams": [{"team": "t10", "score": 20.0}]},
            "/api/venues/rastro/offers": {"offers": []},
        }
        self.routes.update(routes or {})

    def get(self, path, **params):
        self.calls.append((path, params))
        r = self.routes.get(path)
        if r is None:
            for k, v in self.routes.items():
                if k.endswith("*") and path.startswith(k[:-1]):
                    r = v
                    break
        if r is None:
            raise FakeError("not_found", path, 404)
        if callable(r):
            r = r(path, params)
        if isinstance(r, Exception):
            raise r
        return copy.deepcopy(r)

    def post(self, path, body=None, broker_key=None):
        if not self.real:
            raise FakeError("not_real", "dry", 0)
        self.posts.append((path, body))
        return {"ok": True}

    def delete(self, path):
        return self.post(path)

    def paths(self):
        return [c[0] for c in self.calls]


class FakeLLMResult:
    def __init__(self, data=None, text="", model="claude-opus-5-5", cost=0.001):
        self.text = text
        self.tool_calls = [{"name": "vote", "input": data}] if data is not None else []
        self.model, self.key, self.usage, self.cost_usd, self.latency_s = model, "A", {}, cost, 0.1
