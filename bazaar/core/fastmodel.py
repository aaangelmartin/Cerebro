"""Which model a per-tick call may use when the tick is short.

Measured on Sunday's 15 s ticks (bazaar/data/live/llm.jsonl, 09:20-10:05): the keys are healthy (no 429, 529 or
network error); every "timeout" is our own tick deadline. A market or dealer call starts 2-4 s into the tick, so it
has 6-8 s, and Opus needs 5.5-7.5 s for ~2.3k tokens in and ~300 out: about half the calls were cut off and fell
back to code. Sonnet answers the same prompt in 2-3 s. Duels already race Opus against Sonnet (duels/domain.py).
"""
from __future__ import annotations

import time

from .. import config

SHORT_TICK_S = 20.0          # Sunday's 15 s ticks
OPUS_NEEDS_S = 7.5           # the slowest Opus answer seen for a dealer or market prompt


def pick(default: str | None, tick_seconds: float | None, deadline: float | None, *, always_fast: bool = False,
         now: float | None = None) -> str | None:
    """`default` on long ticks. On short ticks: Sonnet when `always_fast`, or when less than OPUS_NEEDS_S is left
    before `deadline`; otherwise `default`. A caller that already asked for a cheaper model keeps it."""
    if not isinstance(tick_seconds, (int, float)) or not 0 < tick_seconds <= SHORT_TICK_S:
        return default
    if default not in (None, config.OPUS):
        return default
    if always_fast:
        return config.SONNET
    if deadline is None:
        return default
    left = deadline - (time.time() if now is None else now)
    return config.SONNET if left < OPUS_NEEDS_S else default
