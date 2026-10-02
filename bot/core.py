"""Shared pieces every strategy uses: the client, private values, the per-tick budget and the journal.

The bot talks to the team gateway (dashboard/server.py), never to the Bazaar directly, so the
team key stays on the gateway and every write lands in the gateway's action log too.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DATA = Path(os.environ.get("BOT_DATA_DIR") or ROOT / "data")
STOP_FILE = ROOT / "STOP"
sys.path.insert(0, str(REPO / "sdk" / "bazaar-kit"))

from bazaar_sdk import Bazaar, BazaarError  # noqa: E402

__all__ = ["Bazaar", "BazaarError", "Ctx", "Journal", "TickBudget", "Values", "gateway_url", "load_env", "make_client", "REAL_GATEWAY"]


def load_env() -> dict:
    env = {}
    path = REPO / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return {**env, **os.environ}


REAL_GATEWAY = "http://127.0.0.1:8787"


def gateway_url(env: dict) -> str:
    return env.get("BOT_GATEWAY_URL", REAL_GATEWAY).rstrip("/")


def make_client(env: dict) -> Bazaar:
    url = gateway_url(env)
    token = env.get("BOT_GATEWAY_TOKEN") or env.get("GATEWAY_TOKEN", "")
    if not token:
        raise SystemExit("GATEWAY_TOKEN is missing in .env")
    # wait_on_tick=False: the scheduler owns the clock, a strategy never sleeps inside a call.
    return Bazaar(url, token, wait_on_tick=False, retries=3, timeout=20)


class Values:
    """Our private values, from /api/me plus the catalog's value rules.

    A card's value to us is its book value times our set multiplier times the marginal for the
    copy number (1st copy 1.0, 2nd 0.25, 3rd 0.1, ...). /api/me gives the exact figure for cards we
    hold and /api/me/value for one more copy of any card; this class estimates the same thing
    offline so strategies can price whole packs and books without spending requests.
    """

    def __init__(self, me: dict, catalog: dict):
        self.me, self.catalog = me, catalog
        self.affinity = me.get("affinity", {})
        self.cards = {c["id"]: {**c, "set": s["id"], "released": s.get("released", False)}
                      for s in catalog["sets"] for c in s["cards"]}
        self.marginals = catalog.get("values", {}).get("copy_marginals", [1.0, 0.25, 0.1])
        self.held: dict[str, list[dict]] = {}
        for a in me.get("assets", []):
            if a.get("kind") == "card":
                self.held.setdefault(a["ref"], []).append(a)

    def count(self, ref: str) -> int:
        return len(self.held.get(ref, []))

    def marginal(self, copy_index: int) -> float:
        m = self.marginals
        return m[copy_index] if copy_index < len(m) else m[-1]

    def next_copy(self, ref: str) -> float:
        """Value to us of ONE MORE copy of `ref`."""
        c = self.cards.get(ref)
        if not c:
            return 0.0
        return c["book"] * self.affinity.get(c["set"], 1.0) * self.marginal(self.count(ref))

    def held_copy(self, asset: dict) -> float:
        """Value to us of a card we hold, as /api/me reports it (falls back to the estimate)."""
        if asset.get("your_value") is not None:
            return float(asset["your_value"])
        return self.next_copy(asset["ref"])

    def spare_value(self, ref: str) -> float:
        """What we lose by giving away our least valuable copy of `ref`."""
        copies = self.held.get(ref, [])
        if not copies:
            return 0.0
        c = self.cards.get(ref, {})
        return c.get("book", 0) * self.affinity.get(c.get("set"), 1.0) * self.marginal(len(copies) - 1)

    def spares(self) -> list[dict]:
        """Copies beyond the first, cheapest to us first: the natural things to sell or swap."""
        out = []
        for ref, copies in self.held.items():
            for a in sorted(copies, key=lambda a: a.get("serial", 0))[1:]:
                out.append({**a, "loss": self.spare_value(ref)})
        return sorted(out, key=lambda a: a["loss"])

    def pack_value(self, pack_id: str) -> float:
        """Expected value to us of a sealed pack: each slot draws a rarity, then a card of that rarity
        from the released sets (uniformly; a sold-out rarity falls back, which we ignore)."""
        pack = next((p for p in self.catalog.get("packs", []) if p["id"] == pack_id), None)
        if not pack:
            return 0.0
        by_rarity: dict[str, list[str]] = {}
        for ref, c in self.cards.items():
            if c["released"] and not c.get("hidden"):
                by_rarity.setdefault(c["rarity"], []).append(ref)
        total = 0.0
        for slot in pack["slots"]:
            for rarity, p in slot.items():
                refs = by_rarity.get(rarity) or []
                if refs:
                    total += p * sum(self.next_copy(r) for r in refs) / len(refs)
        return total


class TickBudget:
    """What the team may still do this tick (limits from /api/clock).

    Accepts are team-wide (one per tick for the whole team, teammates included), so a refused
    accept with wait_for_tick just means someone else used it.
    """

    def __init__(self, clock: dict):
        self.tick = clock.get("tick")
        lim = clock.get("limits", {})
        self.accepts = lim.get("accepts_per_team_per_tick", 1)
        self.listings = lim.get("offers_per_team_per_tick", 12)
        self.max_threads = lim.get("max_open_threads_per_team", 6)
        self.max_offers = lim.get("max_open_offers_per_team", 30)
        self.messaged: set = set()  # thread/duel ids we already spoke in this tick

    def can_accept(self) -> bool:
        return self.accepts > 0

    def use_accept(self):
        self.accepts -= 1

    def can_say(self, key) -> bool:
        return key not in self.messaged

    def use_say(self, key):
        self.messaged.add(key)


class Journal:
    """Live status (bot/data/status.json) and an append-only decision log (bot/data/decisions.jsonl)."""

    def __init__(self):
        DATA.mkdir(exist_ok=True)
        self.status_path = DATA / "status.json"
        self.decisions_path = DATA / "decisions.jsonl"
        self.status: dict = {"strategies": {}, "errors": []}
        self.last: dict = {}  # the latest decision per strategy: the reasoning shown next to a proposal

    def decide(self, strategy: str, action: str, **info):
        rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "strategy": strategy, "action": action, **info}
        if action not in ("received", "operator rejected") and strategy not in ("llm", "safety"):
            # The reasoning shown next to a proposal: the strategy's latest decisions before acting.
            self.last[strategy] = (self.last.get(strategy, []) + [rec])[-3:]
        with self.decisions_path.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{rec['at']}] {strategy}: {action} {json.dumps(info, ensure_ascii=False)[:300]}", flush=True)

    def error(self, strategy: str, err: Exception):
        msg = {"at": time.strftime("%H:%M:%S"), "strategy": strategy, "error": str(err)}
        self.status["errors"] = (self.status["errors"] + [msg])[-20:]
        print(f"[{msg['at']}] {strategy} ERROR {err}", flush=True)

    def set(self, strategy: str, state: dict):
        self.status["strategies"][strategy] = state

    def flush(self, **top):
        self.status.update(top, updated=time.strftime("%Y-%m-%d %H:%M:%S"))
        tmp = self.status_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.status, ensure_ascii=False, indent=1))
        tmp.replace(self.status_path)


@dataclass
class Ctx:
    """Everything a strategy sees in one tick."""

    b: Bazaar
    me: dict
    clock: dict
    catalog: dict
    values: Values
    budget: TickBudget
    journal: Journal
    dry_run: bool
    env: dict
    memory: dict = field(default_factory=dict)  # per-strategy state that survives ticks (and restarts)
    shared: dict = field(default_factory=dict)  # state shared by all strategies, e.g. "reserved" asset ids
    control: object = None  # bot.control.Control when the operator can review actions

    def write(self, strategy: str, action: str, fn, *args, **kwargs):
        """Run a game action, or only log it in dry-run. Returns the API result (None in dry-run).

        Live, the action first goes through the operator's gate (bot/control.py): in review or
        manual mode it waits as a proposal that can be approved, edited or rejected. A rejection
        raises BazaarError("operator_rejected"), which strategies treat like any refused request."""
        context = {"reasoning": list(getattr(self.journal, "last", {}).get(strategy, []))}
        self.journal.decide(strategy, action, dry_run=self.dry_run, args=list(args), kwargs=kwargs)
        if self.dry_run:
            return None
        if self.control is not None:
            from .control import OperatorRejected
            deadline = time.time() + max(1.0, float(self.clock.get("next_tick_in") or 10) - 1.5)
            try:
                args, kwargs = self.control.gate(strategy, action, list(args), kwargs, context, deadline)
            except OperatorRejected as e:
                self.journal.decide(strategy, "operator rejected", proposed=action, why=str(e))
                raise BazaarError("operator_rejected", str(e)) from None
            args = tuple(args)
        return fn(*args, **kwargs)
