"""Big bargains: an offer whose cards are worth far more to us than it costs must be taken in the same tick.

Saturday's lesson: Team 8 listed LAV-11 (worth 288 P to us) on El Rastro at 172 -> 146 -> 125 P for ~45 ticks,
three ticks per listing, and sold it to a dealer. El Rastro's book is only re-read every 10 ticks and an offer
above our spend cap was dropped without a word, so the bot never saw it and the brain heard of it from a human.

This module gives the market domain:
- `FeedOffers`: every offer the feed lists, kept until it expires, is cancelled or settles (the feed is read
  every tick, so a three-tick listing is seen in its first tick);
- the thresholds of the fast path and the counter-offer we post when cash is short;
- `log()` / `recent()`: bargains.jsonl, read by el cerebro as `bargain` events (opportunities first);
- `funding()`: the bargain we are raising cash for, until its offer disappears.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .. import config

BIG_BARGAIN_P = 25.0            # gain at our values (after fees) that makes an offer a bargain: accept at once
EXACT_TRIGGER_P = 20.0          # estimated value - price above this: read the exact /api/me/value first
EXACT_READS_PER_TICK = 2
COUNTER_MAX_FRAC = 0.6          # a counter-offer never gives more than this share of the value we receive
COUNTER_EXPIRES = 20            # ticks
COUNTER_MAX_CARDS = 3
FUNDING_TTL_TICKS = 15          # the funding goal ends this long after the offer was last seen
FEASIBLE_MIN_TICKS = 5         # an offer that expires sooner cannot be funded in time: watch it, no alarm
FILE = "bargains.jsonl"
GOAL_FILE = "bargain_goal.json"


def _live(live: Path | None = None) -> Path:
    return Path(live) if live is not None else config.LIVE


class FeedOffers:
    """Open offers learned from the feed (`offer.listed`), dropped when cancelled, settled or expired."""

    def __init__(self):
        self.offers: dict[Any, dict] = {}

    def ingest(self, feed_new: list | None, tick: int) -> None:
        for e in feed_new or []:
            if not isinstance(e, dict):
                continue
            t, p = e.get("type"), e.get("payload") or {}
            if t == "offer.listed":
                o = p.get("offer") if isinstance(p.get("offer"), dict) else None
                if o and o.get("id") is not None:
                    self.offers[o["id"]] = {**o, "venue": o.get("venue") or p.get("venue")}
            elif t in ("offer.cancelled", "offer.expired", "offer.accepted", "offer.filled"):
                oid = p.get("offer", {}).get("id") if isinstance(p.get("offer"), dict) else p.get("offer")
                self.offers.pop(oid, None)
            elif t == "settlement":
                self.offers.pop(p.get("offer"), None)
                moved = {i.get("id") for i in p.get("items") or [] if isinstance(i, dict)}
                for oid, o in list(self.offers.items()):      # the card left its maker: the listing is dead
                    if any(isinstance(a, dict) and a.get("id") in moved
                           for a in ((o.get("give") or {}).get("assets") or [])):
                        self.offers.pop(oid, None)
        for oid, o in list(self.offers.items()):
            if o.get("expires_tick") is not None and int(o["expires_tick"]) <= tick:
                self.offers.pop(oid, None)

    def open(self) -> list[dict]:
        return [o for o in self.offers.values() if (o.get("status") or "open") == "open"]


def counter_give(cash_room: int, ask_price: int, value_in: float, pool: list[tuple[dict, float, float]]) -> dict | None:
    """What to offer the seller when cash is short: all the cash we may spend plus our cheapest cards from sets
    we do not collect, until the package (cash + book value of the cards) reaches the asking price. `pool` is
    [(asset, our_value, book)] already filtered to cards we may give. None when the package would give away
    more than COUNTER_MAX_FRAC of the value we receive, or nothing sensible can be built."""
    cash = max(0, min(int(cash_room), int(ask_price)))
    gap = ask_price - cash
    chosen, ours, book = [], 0.0, 0.0
    for a, v, b in sorted(pool, key=lambda x: (x[1] / max(1.0, x[2]), x[1])):   # most book per value given first
        if gap - book <= 0 or len(chosen) >= COUNTER_MAX_CARDS:
            break
        chosen.append(a)
        ours += v
        book += b
    if cash <= 0 and not chosen:
        return None
    if cash + ours > COUNTER_MAX_FRAC * value_in:
        return None
    return {"cash": cash, "assets": chosen, "value_given": round(cash + ours, 2), "package": round(cash + book, 2),
            "covers": cash + book >= ask_price}


def feasible(gap: float, liquid: float, ticks_left: int | None) -> bool:
    """Can a bargain we cannot pay yet still be funded? The cash missing must fit in what our sellable spares
    are worth on the market, and the offer must stay open long enough to sell them."""
    return float(gap) <= float(liquid) and (ticks_left is None or int(ticks_left) >= FEASIBLE_MIN_TICKS)


# --------------------------------------------------------------------------- the brain's side
def log(row: dict, live: Path | None = None) -> None:
    """Append a bargain row (the brain reads them as events). One row per offer and status."""
    p = _live(live) / FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), **row}, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def recent(live: Path | None = None, since: float = 0.0, limit: int = 50) -> list[dict]:
    p = _live(live) / FILE
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f.readlines()[-400:]:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if float(r.get("ts") or 0) > since:
                    out.append(r)
    except OSError:
        return []
    return out[-limit:]


def event_text(r: dict) -> str:
    refs = ", ".join(r.get("refs") or [])
    worth = f"worth {r.get('value')} P to us"
    if r.get("page_bonus"):
        worth += f" (page bonus of {r.get('page_bonus')} P included)"
    base = (f"BARGAIN {refs} from {r.get('seller') or '?'} on {r.get('venue')}: offer #{r.get('offer')} asks "
            f"{r.get('price')} P ({r.get('cost')} with the fee), {worth}, gain +{r.get('gain')} P")
    st = r.get("status")
    if st == "short" and r.get("feasible") is False:
        left = r.get("ticks_left")
        return ("Watch only, not fundable: " + base[len("BARGAIN "):]
                + f". Short by {r.get('gap')} P; our sellable spares raise about {r.get('liquid')} P"
                + (f" and the offer expires in {left} ticks" if left is not None else "")
                + ". Do not re-plan around it; compare its cost with what a dealer asks for the card.")
    if st == "accepting":
        return base + ". The bot is accepting it this tick (fast path)."
    if st == "short":
        c = r.get("counter")
        return (base + f". We hold {r.get('cash')} P and may spend {r.get('can_spend')} P in one deal now (reserve, "
                f"promised cash, per-deal and per-hour caps): short by {r.get('gap')} P. "
                + (f"The bot posted a counter-offer to the seller: {c}. " if c else "No counter-offer was possible. ")
                + "FUND IT NOW: sell cards above their value to us, cancel cash bids, lower the reserve; the bot "
                  "accepts the moment cash covers it.")
    if st == "gone":
        return f"Bargain gone: {refs} (offer #{r.get('offer')}) is no longer on offer."
    return base


def set_funding(goal: dict | None, live: Path | None = None) -> None:
    p = _live(live) / GOAL_FILE
    try:
        if goal is None:
            p.unlink(missing_ok=True)
        else:
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(goal, ensure_ascii=False, default=str), encoding="utf-8")
            tmp.replace(p)
    except OSError:
        pass


def funding(live: Path | None = None, tick: int | None = None) -> dict | None:
    """The bargain we are raising cash for ({refs, seller, price, cost, value, gap, last_seen_tick}), or None."""
    try:
        g = json.loads((_live(live) / GOAL_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(g, dict):
        return None
    if tick is not None and tick - int(g.get("last_seen_tick") or 0) > FUNDING_TTL_TICKS:
        return None
    return g
