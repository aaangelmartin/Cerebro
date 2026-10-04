"""TickContext (what every domain gets each tick) and the budget that carries across ticks.

run.py builds one TickContext per tick. `budget` is a plain dict so domains can read it without
importing anything; Budget keeps the rolling numbers (spend per hour, deals per team per hour)
across ticks and restarts (data/live/budget.json).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import config
from .types import ACCEPT_KINDS, MESSAGE_KINDS, Action

HOUR = 3600.0


@dataclass
class TickContext:
    tick: int
    day: str
    deadline: float                       # epoch: decide before this (55 % of the tick)
    lessons: Any = None                   # lab.store.LessonStore (or None while the Lab is missing)
    llm: Any = None                       # the bazaar.llm.client module
    ledger: Any = None                    # core.ledger.Ledger
    budget: dict = field(default_factory=dict)    # see Budget.for_tick
    control: dict = field(default_factory=dict)   # operator control (armed, mode, caps, protected)
    tick_seconds: float = 30.0
    tick_start: float = 0.0
    cautious: bool = False                # breaker: no buys this tick
    llm_ok: bool = True                   # breaker: False -> domains should rely on code only
    value: Any = None                     # value(ref) -> float | None: our private value of one more copy

    def time_left(self, now: float | None = None) -> float:
        return self.deadline - (time.time() if now is None else now)

    def expired(self, now: float | None = None) -> bool:
        return self.time_left(now) <= 0

    def with_deadline(self, deadline: float) -> "TickContext":
        from dataclasses import replace
        return replace(self, deadline=deadline)


def conv_key(action: Action) -> str:
    """Budget key of the conversation an action speaks in: 'thread:5' or 'duel:5' (ids can collide)."""
    p = action.params or {}
    if p.get("duel") is not None and action.kind.startswith("duel"):
        return f"duel:{p['duel']}"
    if p.get("thread") is not None:
        return f"thread:{p['thread']}"
    if p.get("duel") is not None:
        return f"duel:{p['duel']}"
    return "none"


def _cash_out(action: Action) -> int:
    """Primas this action can take out of our cash if it goes through (0 when unknown/none)."""
    p = action.params or {}
    if "spend" in (action.expected or {}):
        try:
            return int(action.expected["spend"] or 0)
        except (TypeError, ValueError):
            return 0
    if action.kind == "accept_offer":
        exp = p.get("expect") or {}
        return int(((exp.get("want") or {}).get("cash")) or 0)   # we give what the maker wants
    return 0                     # a posted bid is a promise, not spend: it counts when it fills


# --- cash promised in open bids (market + dealers) --------------------------------------------------------
# A posted bid is not spend (see _cash_out), but every open bid can fill at once. Both buying domains size
# new bids against cash - reserve - venue bond - committed_cash(sit), so all our open promises together
# never exceed what we may spend.

def _get(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _int(x) -> int:
    try:
        return max(0, int(x or 0))
    except (TypeError, ValueError):
        return 0


def market_committed(sit) -> int:
    """Cash in our own open market offers (we are the maker, not inside a dealer thread)."""
    my_id = (_get(sit, "me") or {}).get("id")
    total = 0
    for o in _get(sit, "my_offers") or []:
        if not isinstance(o, dict) or o.get("thread") is not None or o.get("status", "open") != "open":
            continue
        if my_id is not None and o.get("maker") != my_id:
            continue                                     # addressed to us by another team: not our promise
        total += _int((o.get("give") or {}).get("cash"))
    return total


def dealer_committed(sit, exclude_thread=None) -> int:
    """Our latest price in each open dealer BUY thread: the dealer can take any of them."""
    from bazaar.dealers.threads import parse_thread     # pure parser; imported lazily (core stays light)
    total = 0
    for t in _get(sit, "threads") or []:
        if exclude_thread is not None and str(t.get("id")) == str(exclude_thread):
            continue
        try:
            v = parse_thread(t)
        except Exception:  # noqa: BLE001 - a malformed thread never blocks sizing
            continue
        if v is not None and v.status == "open" and v.buying and v.last_ours:
            total += _int(v.last_ours)
    return total


def committed_cash(sit) -> int:
    """All cash our open bids promise: market bids + dealer buy bids."""
    return market_committed(sit) + dealer_committed(sit)


def record_spend(ctx, amount: int, now: float | None = None) -> None:
    """Count cash that left through a fill the domain inferred (a posted bid taken by someone): appends to
    the persisted hourly spend window when run.py exposes it, and updates this tick's view at once."""
    amount = _int(amount)
    b = _get(ctx, "budget")
    if not amount or not isinstance(b, dict):
        return
    log = b.get("_spend_log")
    if isinstance(log, list):
        log.append([time.time() if now is None else now, amount])
    b["spend_hour"] = float(b.get("spend_hour") or 0) + amount
    if "spend_hour_left" in b:
        b["spend_hour_left"] = max(0, int(b["spend_hour_left"] or 0) - amount)


class ValueCache:
    """Cached GET /api/me/value?card=<ref> (value of one more copy). Cleared when our holdings change.

    `values` is the same dict run.py exposes as sit.values, so rails can read either.
    """

    def __init__(self, gw=None, ttl_s: float = 600.0):
        self.gw, self.ttl_s = gw, ttl_s
        self.values: dict[str, float] = {}
        self._at: dict[str, float] = {}
        self._holdings: Any = None

    def refresh(self, me: dict, now: float | None = None) -> None:
        held = sorted(str(a.get("id")) for a in (me or {}).get("assets") or [])
        if held != self._holdings:
            self._holdings = held
            self.values.clear()
            self._at.clear()

    def __call__(self, ref: str) -> float | None:
        now = time.time()
        if ref in self.values and now - self._at.get(ref, 0) < self.ttl_s:
            return self.values[ref]
        if self.gw is None:
            return self.values.get(ref)
        try:
            if hasattr(self.gw, "value"):
                v = self.gw.value(ref)
            else:
                r = self.gw.get("/api/me/value", card=ref) or {}
                v = next((float(r[k]) for k in ("your_value", "value", "next_copy")
                          if isinstance(r.get(k), (int, float))), None)
        except Exception:  # noqa: BLE001 - unknown value: rails will refuse the buy
            return self.values.get(ref)
        if v is not None:
            self.values[ref] = float(v)
            self._at[ref] = now
        return v



# Duel accepts have their own limit (organiser's Duels brief): one per live duel. Sunday's sessions run four
# duels at once (schedule: max_concurrent 4) and the four of a wave share one deadline, so a cap of three would
# drop the fourth accept of a last tick. Two accepts in one tick both went through on Saturday (ticks 1250,
# 1259, 1265, 1337).
DUEL_ACCEPTS_PER_TICK = 4


def duel_accept_cap(limits: dict | None) -> int:
    """Duel accepts per tick. The game's `accepts_per_team_per_tick` counts offer accepts only."""
    lim = limits or {}
    for key in ("duel_accepts_per_team_per_tick", "duel_accepts_per_tick"):
        if lim.get(key) is not None:
            return int(lim[key])
    return DUEL_ACCEPTS_PER_TICK


class Budget:
    """Per-tick counters plus rolling per-hour windows, persisted between ticks."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or config.LIVE / "budget.json")
        self.state: dict = {"tick": None, "accepts": 0, "duel_accepts": 0, "messages": {}, "offers": 0,
                            "spend": [], "deals": [], "llm_usd": 0.0}
        try:
            self.state.update(json.loads(self.path.read_text()))
        except (OSError, ValueError):
            pass

    def _prune(self, now: float):
        for k in ("spend", "deals"):
            self.state[k] = [r for r in self.state.get(k, []) if now - r[0] < HOUR]

    def for_tick(self, tick: int, limits: dict | None = None, now: float | None = None,
                 hour_cap: int | None = None) -> dict:
        """Reset per-tick counters on a new tick and return the dict that goes into ctx.budget. `hour_cap` is
        the operator's max_spend_per_hour (control); without it the config default sizes the hour, and a cap
        raised in control would still leave the domains planning against the old one."""
        now = time.time() if now is None else now
        if self.state.get("tick") != tick:
            self.state.update(tick=tick, accepts=0, duel_accepts=0, messages={}, offers=0)
        self._prune(now)
        limits = limits or {}
        spent_hour = sum(r[1] for r in self.state["spend"])
        hour_cap = int(hour_cap) if hour_cap is not None else config.MAX_SPEND_PER_HOUR
        deals_by_team: dict[str, int] = {}
        for _, team in self.state["deals"]:
            deals_by_team[team] = deals_by_team.get(team, 0) + 1
        acc_cap = int(limits.get("accepts_per_team_per_tick", 1))
        duel_cap = duel_accept_cap(limits)
        duel_used = int(self.state.get("duel_accepts") or 0)
        return {
            "tick": tick,
            "accepts_used": self.state["accepts"],
            "accepts_left": max(0, acc_cap - self.state["accepts"]),
            "duel_accepts_used": duel_used,                    # duels have their own limit: never block a trade
            "duel_accepts_left": max(0, duel_cap - duel_used),
            "messages": dict(self.state["messages"]),          # "thread:5"/"duel:5" -> messages sent this tick
            "offers_posted": self.state["offers"],
            "offers_left": max(0, int(limits.get("offers_per_team_per_tick", 12)) - self.state["offers"]),
            "spend_hour": spent_hour,
            "spend_hour_cap": hour_cap,
            "spend_hour_left": max(0, hour_cap - spent_hour),
            "_spend_log": self.state["spend"],                 # live list: context.record_spend appends fills
            "deals_by_team_hour": deals_by_team,
            "llm_usd": self.state.get("llm_usd", 0.0),
            "limits": dict(limits),
        }

    def record(self, action: Action, status: str, now: float | None = None) -> None:
        """Count an action that the game took (status 'sent' or 'deal')."""
        if status not in ("sent", "deal"):
            return
        now = time.time() if now is None else now
        p = action.params or {}
        if action.kind == "duel_accept":
            self.state["duel_accepts"] = int(self.state.get("duel_accepts") or 0) + 1
        elif action.kind in ACCEPT_KINDS:
            self.state["accepts"] += 1
        if action.kind in MESSAGE_KINDS:
            key = conv_key(action)
            self.state["messages"][key] = self.state["messages"].get(key, 0) + 1
        if action.kind == "post_offer":
            self.state["offers"] += 1
        out = _cash_out(action)
        if out > 0:
            self.state["spend"].append([now, out])
        if action.kind in ("accept_offer", "duel_accept"):
            team = str(((p.get("expect") or {}).get("maker")) or p.get("with") or "?")
            self.state["deals"].append([now, team])

    def add_llm(self, usd: float):
        self.state["llm_usd"] = round(self.state.get("llm_usd", 0.0) + float(usd or 0), 6)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        tmp.replace(self.path)
