"""Shared types every bazaar module speaks. Change only with the owner of core (see CONTRACTS.md)."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ActionKind = Literal[
    "open_thread",      # params: with, topic                       -> POST /api/threads
    "thread_message",   # params: thread, price, text               -> POST /api/threads/{id}/messages
    "close_thread",     # params: thread                            -> POST /api/threads/{id}/close
    "accept_offer",     # params: offer (id), expect (dict: give/want as evaluated)
    "post_offer",       # params: venue, give, want                 -> POST /api/offers
    "cancel_offer",     # params: offer
    "duel_message",     # params: duel, price, days?, text          -> POST /api/duels/{id}/messages
    "duel_accept",      # params: duel, expect (rival offer as evaluated)
    "venue_open",       # params: name, fee_bps, fee_per_card, mechanism, description
    "venue_patch",      # params: venue, fee_bps?, fee_per_card?, description?
    "broker_match",     # params: sell, buy, price                  (broker key)
    "broker_announce",  # params: text
    "open_pack",        # params: asset (id of a sealed pack we hold)  -> POST /api/packs/{id}/open
    "taller",           # params: assets [3 spare card ids of one rarity]  -> POST /api/taller (the Workshop)
    "noop",
]

# Actions that consume the team's single accept per tick.
ACCEPT_KINDS = {"accept_offer", "duel_accept"}
# Actions that consume the one message per conversation per tick.
MESSAGE_KINDS = {"thread_message", "duel_message"}


@dataclass
class Action:
    kind: ActionKind
    params: dict[str, Any]
    domain: str                      # "duels" | "dealers" | "market" | "broker" | "lab"
    reason: str = ""                 # why, in one or two sentences (shown in the dashboard)
    expected: dict[str, Any] = field(default_factory=dict)  # e.g. {"points": 12.3, "close_prob": 0.7, "value_gain": 8}
    lesson_ids: list[str] = field(default_factory=list)
    big: bool = False                # True -> council reviews it when time allows
    priority: float = 0.0            # expected points; the arbiter sorts by (domain rank, priority)
    source: str = "opus"             # "opus" | "council" | "sonnet" | "fallback" | "code"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Verdict:
    """What the rails said about an action."""
    ok: bool
    rail: str = ""                   # which invariant vetoed it
    detail: str = ""


@dataclass
class Outcome:
    """What really happened after an action, written by the ledger for the Lab."""
    action_id: str
    tick: int
    status: Literal["sent", "refused", "vetoed", "deal", "no_deal", "expired", "error"]
    response: dict[str, Any] = field(default_factory=dict)
    realised: dict[str, Any] = field(default_factory=dict)   # e.g. {"price": 21, "points_delta": 3.1}


@dataclass
class Lesson:
    """One learned rule. Data only: lessons can never change the rails."""
    id: str
    scope: str                       # "duel" | "dealer:abuela" | "dealer:chato" | "market" | "broker" | "global"
    rule: str                        # plain-language rule Claude reads
    params: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)       # event ids / decision ids
    n: int = 0                       # independent cases
    sources: int = 0                 # distinct teams/dealers behind the evidence
    backtest: dict[str, Any] = field(default_factory=dict)  # {"hit": 0.8, "lift": 0.07}
    status: Literal["proposed", "shadow", "canary", "active", "retired"] = "proposed"
    weight: float = 0.0              # 0..1, how strongly the operator should lean on it
    version: int = 1
    created_by: str = "seed"         # "seed" | "lab" | "human"
    updated: float = field(default_factory=time.time)
