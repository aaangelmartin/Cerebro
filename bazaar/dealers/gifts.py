"""The gift window: some dealers hand a card to a team every so often, and we want every one of them.

Measured on Saturday's recording (docs/easter-egg.md, "Regalos"): Abuela Carmen gives one card per team at
most every 240 ticks, in her answer to our FIRST PRICED message of a thread. It does not depend on kind
words, on buying or selling, on the price or on closing the deal; since tick 600 about every eligible thread
got one. Nothing has to be accepted: the card just arrives (public event `gift.given`).

So: remember the tick of our last gift per dealer and, once the window is open, make sure a thread with that
dealer gets a priced message from us. State lives in dealer_memory.json under "gifts":
  {"abuela": {"last_tick": 929, "cards": ["MAL-02"], "count": 2, "tries": [{"tick": 1170, "item": "SAL-05"}]}}

Pure functions on that dict, so the brain can read the same file.
"""
from __future__ import annotations

import json
from pathlib import Path

COOLDOWN_TICKS = {"abuela": 240}      # dealer -> ticks between two gifts to the same team (never seen shorter)
RETRY_TICKS = 6                       # after a thread that brought nothing, wait this long before the next one
MAX_TRIES = 4                         # threads opened only for the gift, per window: the hourly quota is for deals
DEALERS = tuple(COOLDOWN_TICKS)


def _mem(mem: dict, dealer: str) -> dict:
    return mem.setdefault("gifts", {}).setdefault(dealer, {})


def record(mem: dict, dealer: str, tick: int, cards: list | None = None) -> bool:
    """A gift arrived: restart the clock. False if this one was already recorded."""
    g = _mem(mem, dealer)
    seen = g.setdefault("ticks", [])
    if int(tick) in seen:
        return False
    seen.append(int(tick))
    del seen[:-20]
    if g.get("last_tick") is None or int(tick) >= int(g["last_tick"]):
        g["last_tick"] = int(tick)
        g["cards"] = [str(c) for c in cards or []]
        g["tries"] = []
    g["count"] = len(seen)
    return True


def note_feed(mem: dict, events, team) -> list[dict]:
    """Record every `gift.given` to our team among these public events; returns the new ones."""
    new = []
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") != "gift.given":
            continue
        p = e.get("payload") or {}
        dealer = str(e.get("actor") or "")
        if not team or p.get("team") != team or not dealer:
            continue
        if record(mem, dealer, int(e.get("tick") or 0), p.get("cards") or []):
            new.append({"dealer": dealer, "tick": int(e.get("tick") or 0), "cards": p.get("cards") or []})
    return new


def bootstrap(mem: dict, events_path: Path, team) -> None:
    """Once per memory file: read the gifts we already got from the recorded public feed."""
    if not team or (mem.setdefault("gifts", {}).get("_scanned") == team):
        return
    try:
        with open(events_path, encoding="utf-8") as f:
            for line in f:
                if '"gift.given"' not in line:
                    continue
                try:
                    note_feed(mem, [json.loads(line)], team)
                except ValueError:
                    continue
    except OSError:
        return
    mem["gifts"]["_scanned"] = team


def next_tick(mem: dict, dealer: str) -> int:
    """First tick the next gift is possible (0: we never got one, so now)."""
    last = (mem.get("gifts") or {}).get(dealer, {}).get("last_tick")
    return 0 if last is None else int(last) + COOLDOWN_TICKS.get(dealer, 240)


def window_open(mem: dict, dealer: str, tick: int) -> bool:
    if dealer not in COOLDOWN_TICKS:
        return False
    last = (mem.get("gifts") or {}).get(dealer, {}).get("last_tick")
    # a tick below the last gift's means the clock restarted (a new day): the window is open
    return last is None or tick < int(last) or tick >= next_tick(mem, dealer)


def tries(mem: dict, dealer: str) -> list[dict]:
    return list((mem.get("gifts") or {}).get(dealer, {}).get("tries") or [])


def note_try(mem: dict, dealer: str, tick: int, item: str = "") -> None:
    """We opened a thread for the gift (or one that serves as such)."""
    g = _mem(mem, dealer)
    g.setdefault("tries", []).append({"tick": int(tick), "item": str(item)})
    del g["tries"][:-12]


def due(mem: dict, dealer: str, tick: int) -> bool:
    """Open a gift thread now? The window is open, the last try is a while ago and we have tries left."""
    if not window_open(mem, dealer, tick):
        return False
    span = COOLDOWN_TICKS.get(dealer, 240)       # tries older than one cooldown no longer count (a missed gift event)
    done = [t for t in tries(mem, dealer) if tick - span < int(t.get("tick") or 0) <= tick]
    if len(done) >= MAX_TRIES:
        return False
    return not done or tick - int(done[-1].get("tick") or 0) >= RETRY_TICKS


def summary(mem: dict, tick: int | None = None) -> dict:
    """For the brain's picture: per dealer, the last gift and when the next one is possible."""
    out = {}
    for d in DEALERS:
        g = (mem.get("gifts") or {}).get(d, {})
        row = {"last_gift_tick": g.get("last_tick"), "last_gift_cards": g.get("cards") or [],
               "gifts_received": int(g.get("count") or 0), "next_possible_tick": next_tick(mem, d),
               "cooldown_ticks": COOLDOWN_TICKS[d], "tries_this_window": len(g.get("tries") or [])}
        if tick is not None:
            row["window_open"] = window_open(mem, d, int(tick))
        out[d] = row
    return out
