"""The recorder's scheduler and handlers. One thread, two request queues (public, keyed), never blocks on a bucket.

Each loop `step()`:
  1. `plan()` looks at the timers and the game clock and enqueues reads that are due (a read already queued is not
     queued twice, so a slow lane never piles up work).
  2. For each lane with a token, the highest-priority queued read runs and its handler records what changed.

Everything recorded goes through `Store` (see store.py / README.md). Nothing here can write to the game.
"""
from __future__ import annotations

import heapq
import itertools
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..gateway import GameError
from .client import CARDS_RPS, Bucket, Lane
from .store import Store, iter_records, sig

FEED_LIMIT = 500
FEED_EVERY_S = 4.0            # doors open: one feed read every 4 s ...
FEED_BUSY_EVERY_S = 1.0       # ... or every second while a read brings more than FEED_BUSY_NEW new events
FEED_BUSY_NEW = 120
CLOSED_EVERY_S = 30.0         # doors closed or paused: clock and feed
CLOSED_SLOW_S = 300.0         # doors closed: leaderboard, books and our private state
META_EVERY_S = 120.0          # dealers, levels, schedule
CATALOG_EVERY_S = 900.0        # doors closed
CATALOG_OPEN_S = 180.0         # doors open: `minted` moves with every pack and a set can be released mid-game
DEALER_DETAIL_EVERY_S = 1800.0
BOOK_SNAPSHOT_EVERY = 20      # ticks between full snapshots of each venue's book
BOOK_ALWAYS = ("v07",)  # our venue: read every tick even when rate-limited (El Rastro always is)
SHORT_TICK_S = 20.0           # Sunday's 15 s ticks: books are read on the squeezed rota (see plan_books)
BOOK_SQUEEZED_EVERY = 3       # while rate-limited, every other venue's book is read once in this many ticks
THREADS_ALL_EVERY = 20        # ticks between reads of every thread (not only the open ones)
DUELS_DONE_EVERY = 10         # ticks between reads of finished duels
KEYED_AT = 0.3                # share of the tick at which our private reads start (after the bot's own reads)
CARD_SWEEP_EVERY_S = 3600.0
CARD_PROBE_BEYOND = 15        # ids probed past the highest asset id we have seen
SEEN_KEEP = 4000              # feed dedupe window
REFRESH_TYPES = ("level.", "persona.", "venue.", "clock.", "announcement", "day.", "dealer.", "schedule.")
CATALOG_TYPES = ("set.", "round.", "catalog.", "day.")     # a release or a new round: read the catalog now
CLOCK_VOLATILE = ("next_tick_in",)


@dataclass(order=True)
class Job:
    prio: int
    n: int
    key: str = field(compare=False)
    lane: str = field(compare=False)
    path: str = field(compare=False)
    params: dict | None = field(compare=False, default=None)
    handler: Callable | None = field(compare=False, default=None)
    on_error: Callable | None = field(compare=False, default=None)


def _id(x: dict, *keys) -> Any:
    for k in keys:
        if isinstance(x, dict) and x.get(k) is not None:
            return x[k]
    return None


def asset_ids(obj: Any, out: set | None = None, depth: int = 0) -> set:
    """Every asset id (dicts with id + kind card/pack) anywhere in a response."""
    out = set() if out is None else out
    if depth > 8:
        return out
    if isinstance(obj, dict):
        if obj.get("kind") in ("card", "pack") and isinstance(obj.get("id"), int):
            out.add(obj["id"])
        for v in obj.values():
            if isinstance(v, (dict, list)):
                asset_ids(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                asset_ids(v, out, depth + 1)
    return out


def diff_offers(prev: dict, offers: list[dict]) -> tuple[dict, list, list, list]:
    """(new state {id: sig}, added offers, removed ids, changed offers)."""
    now = {}
    added, changed = [], []
    for o in offers:
        oid = str(_id(o, "id"))
        s = sig(o)
        now[oid] = s
        if oid not in prev:
            added.append(o)
        elif prev[oid] != s:
            changed.append(o)
    removed = [k for k in prev if k not in now]
    return now, added, removed, changed


def _msg_key(m: dict) -> str:
    if m.get("id") is not None:
        return f"id:{m['id']}"
    return "h:" + sig([m.get("tick"), m.get("from", m.get("sender")), m.get("text"), m.get("price"), m.get("days")])


class Recorder:
    def __init__(self, store: Store, public: Lane, keyed: Lane | None, *, now=time.time,
                 links: dict | None = None, cards: bool = True):
        self.store, self.now = store, now
        self.lanes: dict[str, Lane] = {"public": public}
        if keyed is not None:
            self.lanes["keyed"] = keyed
        self.queues: dict[str, list] = {k: [] for k in self.lanes}
        self.queued: set[str] = set()
        self._n = itertools.count()
        self.cards_bucket = Bucket(CARDS_RPS, 1.0)
        self.cards_enabled = cards and keyed is not None
        self.links = links or {}
        self.errors: deque = deque(maxlen=30)
        self.timers: dict[str, float] = {}
        self.marked_down: dict[str, bool] = {}
        # clock
        self.clock: dict = {}
        self.tick: int | None = None
        self.tick_seen_at = 0.0
        self.keyed_due: float | None = None
        self.feed_busy = False
        # docs cache
        self._docs: dict[str, dict] = {}
        self.counts: dict[str, int] = {}

        st = store.get("state.json", {}) or {}
        self.state: dict = {
            "last_event_id": int(st.get("last_event_id") or 0), "max_page": int(st.get("max_page") or 0),
            "hashes": dict(st.get("hashes") or {}), "books": dict(st.get("books") or {}),
            "book_snap_tick": dict(st.get("book_snap_tick") or {}), "my_offers": dict(st.get("my_offers") or {}),
            "open_threads": list(st.get("open_threads") or []), "live_duels": list(st.get("live_duels") or []),
            "cards": dict(st.get("cards") or {}), "max_asset": int(st.get("max_asset") or 0),
            "last_tick": st.get("last_tick"), "gaps": int(st.get("gaps") or 0),
        }
        self.state["cards"].setdefault("hashes", {})
        self.snapped_this_run: set[str] = set()
        self.seen: deque = deque(maxlen=SEEN_KEEP)
        self.seen_set: set[str] = set()
        self._rebuild_seen()
        self.store.append("gaps", {"kind": "recorder_start", "last_event_id": self.state["last_event_id"],
                                   "last_tick": self.state["last_tick"], "state_found": bool(st)})
        self._dirty = True
        self._saved_at = 0.0

    # ------------------------------------------------------------------ state
    def _rebuild_seen(self) -> None:
        """Feed dedupe window from the tail of the recorded stream: authoritative even after a crash that lost
        state.json (an event written but not yet in the state is never written twice)."""
        files = self.store.files("feed")[-2:]
        top = self.state["last_event_id"]
        for p in files:
            for rec in iter_records(p):
                k = rec.get("key")
                if k:
                    self._remember(k)
                try:
                    top = max(top, int(rec.get("id") or 0))
                except (TypeError, ValueError):
                    pass
        self.state["last_event_id"] = top

    def _remember(self, key: str) -> None:
        if len(self.seen) == self.seen.maxlen:
            self.seen_set.discard(self.seen[0])
        self.seen.append(key)
        self.seen_set.add(key)

    def save_state(self, force: bool = False) -> None:
        if not (force or (self._dirty and self.now() - self._saved_at >= 2.0)):
            return
        self.store.put("state.json", {**self.state, "saved": round(self.now(), 3)})
        self._dirty, self._saved_at = False, self.now()

    def _changed(self, name: str, obj: Any) -> bool:
        s = sig(obj)
        if self.state["hashes"].get(name) == s:
            return False
        self.state["hashes"][name] = s
        self._dirty = True
        return True

    def _rec(self, stream: str, rec: dict) -> None:
        self.store.append(stream, {"tick": self.tick, **rec})
        self.counts[stream] = self.counts.get(stream, 0) + 1

    def _doc(self, rel: str) -> dict:
        if rel not in self._docs:
            self._docs[rel] = self.store.get(rel, {}) or {}
        return self._docs[rel]

    # ------------------------------------------------------------------ queue
    def enqueue(self, lane: str, key: str, path: str, handler: Callable, params: dict | None = None,
                prio: int = 5, on_error: Callable | None = None) -> bool:
        if lane not in self.lanes or key in self.queued:
            return False
        self.queued.add(key)
        heapq.heappush(self.queues[lane], Job(prio, next(self._n), key, lane, path, params, handler, on_error))
        return True

    def _due(self, name: str, every: float) -> bool:
        t = self.now()
        if t >= self.timers.get(name, 0.0):
            self.timers[name] = t + every
            return True
        return False

    @property
    def open(self) -> bool:
        return self.clock.get("doors", "open") == "open" and not self.clock.get("paused")

    def tick_seconds(self) -> float:
        try:
            ts = float(self.clock.get("tick_seconds") or 30.0)
        except (TypeError, ValueError):
            ts = 30.0
        return ts if ts > 0 else 30.0

    # ------------------------------------------------------------------ plan
    def plan(self) -> None:
        now = self.now()
        ts = self.tick_seconds()
        if self._due("clock", ts if self.open else CLOSED_EVERY_S):    # open: re-timed by on_clock
            self.enqueue("public", "clock", "/api/clock", self.on_clock, prio=1)
        feed_every = (FEED_BUSY_EVERY_S if self.feed_busy else FEED_EVERY_S) if self.open else CLOSED_EVERY_S
        if self._due("feed", feed_every):
            self.enqueue("public", "feed", "/api/feed", self.on_feed, {"limit": FEED_LIMIT}, prio=0)
        if not self.clock:
            return                                   # nothing else until we know the clock
        if not self.open and self._due("closed_slow", CLOSED_SLOW_S):
            self._enqueue_public_tick()
            self._enqueue_keyed_tick()
        if self._due("meta", META_EVERY_S if self.open else CLOSED_SLOW_S * 2):
            self._enqueue_meta()
        if self._due("catalog", CATALOG_OPEN_S if self.open else CATALOG_EVERY_S):
            self.enqueue("public", "catalog", "/api/catalog", lambda d: self.on_meta("catalog", d), prio=6)
        if self.keyed_due is not None and now >= self.keyed_due:
            self.keyed_due = None
            self._enqueue_keyed_tick()
        self._plan_cards()

    def _enqueue_meta(self) -> None:
        self.enqueue("public", "dealers", "/api/dealers", self.on_dealers, prio=5)
        self.enqueue("public", "levels", "/api/levels", lambda d: self.on_meta("levels", d), prio=5)
        self.enqueue("public", "schedule", "/api/schedule", lambda d: self.on_meta("schedule", d), prio=5)

    def _enqueue_public_tick(self) -> None:
        self.enqueue("public", "leaderboard", "/api/leaderboard", self.on_leaderboard, prio=3)
        self.enqueue("public", "venues", "/api/venues", self.on_venues, prio=3)

    def _enqueue_keyed_tick(self) -> None:
        t = self.tick or 0
        self.enqueue("keyed", "duels", "/api/duels", self.on_duels, prio=0)
        self.enqueue("keyed", "me", "/api/me", self.on_me, prio=1)
        self.enqueue("keyed", "my_offers", "/api/me/offers", self.on_my_offers, prio=2)
        self.enqueue("keyed", "threads_open", "/api/me/threads", lambda d: self.on_threads(d, open_only=True),
                     {"status": "open"}, prio=2)
        if not self.open or self._due("threads_all", THREADS_ALL_EVERY * self.tick_seconds()):
            self.enqueue("keyed", "threads_all", "/api/me/threads", lambda d: self.on_threads(d, open_only=False),
                         prio=4)
        if not self.open or t % DUELS_DONE_EVERY == 0 or "duels_done" not in self.timers:
            self.timers["duels_done"] = self.now()
            self._enqueue_duels_done(prio=3)

    def _enqueue_duels_done(self, prio: int) -> None:
        self.enqueue("keyed", "duels_done", "/api/duels", lambda d: self.on_duels(d, done=True), {"done": "true"},
                     prio=prio)

    def on_new_tick(self, tick: int) -> None:
        self.tick = tick
        self.tick_seen_at = self.now()
        self.state["last_tick"] = tick
        self._dirty = True
        if self.open:
            self._enqueue_public_tick()
            nti = self.clock.get("next_tick_in")
            ts = self.tick_seconds()
            into = (ts - float(nti)) if isinstance(nti, (int, float)) and 0 <= nti <= ts else 0.0
            self.keyed_due = self.now() + max(0.0, KEYED_AT * ts - into)

    # ------------------------------------------------------------------ cards
    def _plan_cards(self) -> None:
        if not self.cards_enabled:
            return
        c = self.state["cards"]
        now = self.now()
        if not c.get("active") and now - float(c.get("started") or 0) >= CARD_SWEEP_EVERY_S:
            c.update(active=True, started=now, cursor=0, changed=0)
            self._rec("gaps", {"kind": "card_sweep_start", "max_asset": self.state["max_asset"]})
            self._dirty = True
        if not c.get("active") or self.queues.get("keyed") or not self.cards_bucket.ready():
            return
        end = max(self.state["max_asset"], 1) + CARD_PROBE_BEYOND
        cur = int(c.get("cursor") or 0)
        if cur >= end:
            c.update(active=False, finished=now)
            self._rec("gaps", {"kind": "card_sweep_end", "checked": cur, "changed": c.get("changed", 0),
                               "seconds": round(now - float(c.get("started") or now), 1)})
            self._dirty = True
            return
        nxt = cur + 1
        if self.enqueue("keyed", f"card:{nxt}", f"/api/cards/{nxt}", lambda d, i=nxt: self.on_card(i, d), prio=9,
                        on_error=lambda e, i=nxt: self.on_card_error(i, e)):
            self.cards_bucket.take()

    def on_card(self, cid: int, d: dict) -> None:
        c = self.state["cards"]
        c["cursor"] = max(int(c.get("cursor") or 0), cid)
        self._dirty = True
        if not isinstance(d, dict) or not d:
            return
        self.state["max_asset"] = max(self.state["max_asset"], cid)
        s = sig(d)
        prev = c["hashes"].get(str(cid))
        if prev == s:
            return
        c["hashes"][str(cid)] = s
        c["changed"] = int(c.get("changed") or 0) + 1
        hist = d.get("history") if isinstance(d.get("history"), list) else []
        self._rec("cards", {"id": cid, "ref": d.get("ref"), "owner": d.get("owner"), "new": prev is None,
                            "history_len": len(hist), "data": d})
        cards = self._doc("latest/cards.json")
        cards[str(cid)] = d
        self.store.put("latest/cards.json", cards)

    def on_card_error(self, cid: int, e: GameError) -> None:
        if e.status == 404 or "unknown" in e.code or e.code == "not_found":
            c = self.state["cards"]
            c["cursor"] = max(int(c.get("cursor") or 0), cid)
            self._dirty = True

    # ------------------------------------------------------------------ run
    def step(self) -> bool:
        """Plan, then run at most one read per lane. True when something ran."""
        try:
            self.plan()
        except Exception as e:  # noqa: BLE001
            self._err("plan", e)
        ran = False
        for name, lane in self.lanes.items():
            q = self.queues[name]
            if not q or not lane.available():
                continue
            job = heapq.heappop(q)
            self.queued.discard(job.key)
            ran = True
            self._run(lane, job)
        self.save_state()
        return ran

    def _run(self, lane: Lane, job: Job) -> None:
        try:
            data = lane.get(job.path, job.params)
        except GameError as e:
            self._outage_marks(lane)
            if job.on_error:
                try:
                    job.on_error(e)
                except Exception as e2:  # noqa: BLE001
                    self._err(job.key, e2)
            return                               # periodic reads are re-planned by their timers
        self._outage_marks(lane)
        try:
            if job.handler:
                job.handler(data)
        except Exception as e:  # noqa: BLE001 - a bad response must never stop the recorder
            self._err(job.key, e)

    def _outage_marks(self, lane: Lane) -> None:
        if lane.down_since is not None and not self.marked_down.get(lane.name):
            self.marked_down[lane.name] = True
            self._rec("gaps", {"kind": "outage_start", "lane": lane.name, "since": round(lane.down_since, 3),
                               "error": (list(lane.errors)[-1:] or [{}])[0]})
        started = lane.recovered()
        if started is not None:
            self.marked_down[lane.name] = False
            self._rec("gaps", {"kind": "outage_end", "lane": lane.name, "since": round(started, 3),
                               "seconds": round(self.now() - started, 1)})

    def _err(self, where: str, e: BaseException) -> None:
        self.errors.append({"t": round(self.now(), 1), "where": where, "error": f"{type(e).__name__}: {e}"[:300],
                            "trace": traceback.format_exc(limit=3)[-600:]})

    def next_wait(self) -> float:
        """Seconds the main loop may sleep before something can happen."""
        waits = [0.5, min(self.timers.values(), default=self.now() + 0.5) - self.now()]
        for name, lane in self.lanes.items():
            if self.queues[name]:
                waits.append(max(lane.bucket.wait_s(), lane.paused_until - lane.now()))
        return max(0.05, min(waits))

    # ------------------------------------------------------------------ public handlers
    def on_clock(self, d: dict) -> None:
        if not isinstance(d, dict) or "tick" not in d:
            return
        was_open = self.open if self.clock else None
        if self.clock and d.get("round") != self.clock.get("round"):
            self.timers["catalog"] = 0.0             # a new round releases its set (Chamberí on Sunday)
        self.clock = d
        stable = {k: v for k, v in d.items() if k not in CLOCK_VOLATILE}
        try:
            tick = int(d.get("tick") or 0)
        except (TypeError, ValueError):
            tick = 0
        if self._changed("clock", stable):
            self._rec("clock", {"data": stable, "tick": tick})
            self.store.put("latest/clock.json", d)
        if was_open is not None and was_open != self.open:
            self._rec("gaps", {"kind": "doors", "open": self.open, "doors": d.get("doors"), "paused": d.get("paused"),
                               "tick": tick})
            self.timers.pop("feed", None)
            self.timers.pop("closed_slow", None)
            self.timers.pop("catalog", None)         # doors opened or closed: the set of the day may be out
        if tick != self.tick:
            self.on_new_tick(tick)
        nti = d.get("next_tick_in")
        if self.open and isinstance(nti, (int, float)) and 0 <= nti <= self.tick_seconds():
            # one clock read per tick, just after the next one starts
            self.timers["clock"] = self.now() + float(nti) + 0.5

    def on_feed(self, d: dict) -> None:
        events = [e for e in (d.get("events") or []) if isinstance(e, dict)] if isinstance(d, dict) else []
        last = self.state["last_event_id"]
        self.state["max_page"] = max(self.state["max_page"], len(events))
        ids = [int(e.get("id") or 0) for e in events]
        fresh = []
        floor = min((int(k.split("|")[0]) for k in self.seen), default=0) if self.seen else 0
        for e in sorted(events, key=lambda e: int(e.get("id") or 0)):
            key = f"{e.get('id')}|{e.get('tick')}|{e.get('type')}"
            eid = int(e.get("id") or 0)
            if key in self.seen_set or (eid <= last and eid < floor):
                continue
            fresh.append((key, e))
        # A page that is full and starts after our last id may have skipped events.
        if last and fresh and ids and min(ids) > last + 1 and len(events) >= max(1, min(FEED_LIMIT, self.state["max_page"])):
            self.state["gaps"] += 1
            self._rec("gaps", {"kind": "feed_gap", "after_id": last, "before_id": min(ids), "page": len(events),
                               "missing_at_most": min(ids) - last - 1})
        stamp = round(self.now(), 3)
        refresh = False
        for key, e in fresh:
            self.store.append("feed", {"key": key, "seen_tick": self.tick, "seen_at": stamp, **e})
            self._remember(key)
            last = max(last, int(e.get("id") or 0))
            if str(e.get("type", "")).startswith(REFRESH_TYPES):
                refresh = True
            if str(e.get("type", "")).startswith(CATALOG_TYPES):
                self.timers["catalog"] = 0.0
        self.counts["feed"] = self.counts.get("feed", 0) + len(fresh)
        if fresh:
            self.state["last_event_id"] = last
            self.state["max_asset"] = max([self.state["max_asset"], *asset_ids([e for _, e in fresh])])
            self._dirty = True
            self.save_state(force=True)            # the feed offset is the one thing that must never go back
        self.feed_busy = len(fresh) > FEED_BUSY_NEW
        if refresh:
            self.timers["meta"] = 0.0

    def on_leaderboard(self, d: dict) -> None:
        if not isinstance(d, dict) or not self._changed("leaderboard", d):
            return
        self._rec("leaderboard", {"board_tick": d.get("tick"), "round": d.get("round"), "data": d})
        self.store.put("latest/leaderboard.json", d)

    def on_venues(self, d: dict) -> None:
        venues = [v for v in (d.get("venues") or []) if isinstance(v, dict)] if isinstance(d, dict) else []
        if self._changed("venues", venues):
            self._rec("venues", {"venues": venues})
            self.store.put("latest/venues.json", {"tick": self.tick, "venues": venues})
        ids = [str(_id(v, "venue", "id")) for v in venues if _id(v, "venue", "id") is not None]
        if "rastro" not in ids:
            ids.append("rastro")
        for gone in [v for v in self.state["books"] if v not in ids]:
            prev = self.state["books"].pop(gone)
            self._rec("books", {"venue": gone, "added": [], "removed": list(prev), "changed": [],
                                "venue_gone": True})
            self._dirty = True
        # While the game is rate-limiting our address, the essential reads (feed, clock, leaderboard, our own
        # state) go first: only El Rastro, our venue and a rotating third of the other books are read per tick.
        # A short tick squeezes the same way: every book every 15 s asks for more than the public lane's budget
        # and would starve the slower reads queued behind the books.
        squeezed = self.lanes["public"].limited_recently() > 0 or (self.open and self.tick_seconds() < SHORT_TICK_S)
        core = {"rastro", str(self.state.get("own_venue") or ""), *BOOK_ALWAYS}
        for i, vid in enumerate(ids):
            if squeezed and vid not in core and (i + int(self.tick or 0)) % BOOK_SQUEEZED_EVERY:
                continue
            self.enqueue("public", f"book:{vid}", f"/api/venues/{vid}/offers",
                         lambda data, v=vid: self.on_book(v, data), prio=3 if vid in core else 4,
                         on_error=lambda e, v=vid: self._book_error(v, e))

    def _book_error(self, vid: str, e: GameError) -> None:
        if e.status == 404:
            self._rec("gaps", {"kind": "book_missing", "venue": vid, "code": e.code})

    def on_book(self, vid: str, d: dict) -> None:
        offers = [o for o in (d.get("offers") or []) if isinstance(o, dict)] if isinstance(d, dict) else []
        prev = self.state["books"].get(vid, {})
        now, added, removed, changed = diff_offers(prev, offers)
        first = vid not in self.snapped_this_run
        if added or removed or changed:
            self._rec("books", {"venue": vid, "added": added, "removed": removed, "changed": changed,
                                "size": len(offers), **({"after_restart": True} if first and prev else {})})
            self.store.put(f"latest/books/{vid}.json", {"tick": self.tick, "venue": vid, "offers": offers})
            self.state["max_asset"] = max([self.state["max_asset"], *asset_ids(added)])
        last_snap = self.state["book_snap_tick"].get(vid)
        t = self.tick or 0
        if first or last_snap is None or t - int(last_snap) >= BOOK_SNAPSHOT_EVERY or t < int(last_snap):
            self._rec("book_snapshots", {"venue": vid, "offers": offers})
            self.state["book_snap_tick"][vid] = t
            self.snapped_this_run.add(vid)
            if not (added or removed or changed):
                self.store.put(f"latest/books/{vid}.json", {"tick": self.tick, "venue": vid, "offers": offers})
        self.state["books"][vid] = now
        self._dirty = True

    def on_meta(self, kind: str, d: dict) -> None:
        if isinstance(d, dict) and self._changed(kind, d):
            self._rec(kind, {"kind": kind, "data": d})
            self.store.put(f"latest/{kind}.json", d)

    def on_dealers(self, d: dict) -> None:
        self.on_meta("dealers", d)
        if not isinstance(d, dict):
            return
        people = d.get("personas", d.get("dealers")) or []
        if self._due("dealer_detail", DEALER_DETAIL_EVERY_S):
            for p in people:
                pid = _id(p, "id") if isinstance(p, dict) else None
                if pid:
                    self.enqueue("public", f"dealer:{pid}", f"/api/dealers/{pid}",
                                 lambda data, p=pid: self.on_dealer(p, data), prio=7)

    def on_dealer(self, pid: str, d: dict) -> None:
        if isinstance(d, dict) and self._changed(f"dealer:{pid}", d):
            self._rec("dealers", {"kind": "detail", "pid": pid, "data": d})
            self.store.put(f"latest/dealers/{pid}.json", d)

    # ------------------------------------------------------------------ keyed handlers
    def on_me(self, d: dict) -> None:
        if not isinstance(d, dict) or not d:
            return
        self.state["max_asset"] = max([self.state["max_asset"], *asset_ids(d.get("assets") or [])])
        if self._changed("me", d):
            self._rec("me", {"data": d})
            self.store.put("latest/me.json", d)

    def on_my_offers(self, d: dict) -> None:
        offers = [o for o in (d.get("offers") or []) if isinstance(o, dict)] if isinstance(d, dict) else []
        now, added, removed, changed = diff_offers(self.state["my_offers"], offers)
        if added or removed or changed:
            self._rec("my_offers", {"added": added, "removed": removed, "changed": changed, "size": len(offers)})
            self.store.put("latest/my_offers.json", {"tick": self.tick, "offers": offers})
            self.state["my_offers"] = now
            self._dirty = True

    def on_threads(self, d: dict, open_only: bool) -> None:
        threads = [t for t in (d.get("threads") or []) if isinstance(t, dict)] if isinstance(d, dict) else []
        for t in threads:
            self.merge_thread(t)
        if open_only:
            now_open = [str(t.get("id")) for t in threads]
            for tid in self.state["open_threads"]:
                if tid not in now_open:             # it ended since last tick: read how
                    self.enqueue("keyed", f"thread:{tid}", f"/api/threads/{tid}", self.on_thread, prio=3)
            self.state["open_threads"] = now_open
            self._dirty = True

    def on_thread(self, d: dict) -> None:
        if isinstance(d, dict):
            t = d.get("thread", d)
            if isinstance(t, dict) and t.get("id") is not None:
                if "messages" in d and "messages" not in t:
                    t = {**t, "messages": d["messages"]}
                self.merge_thread(t)

    def merge_thread(self, t: dict) -> None:
        tid = str(t.get("id"))
        rel = f"threads/{tid}.json"
        doc = self._doc(rel)
        new = not doc
        msgs = doc.get("messages") or []
        by_key = {_msg_key(m): i for i, m in enumerate(msgs)}
        added, updated = [], []
        for m in t.get("messages") or []:
            if not isinstance(m, dict):
                continue
            k = _msg_key(m)
            if k not in by_key:
                by_key[k] = len(msgs)
                msgs.append(m)
                added.append(m)
            elif sig(msgs[by_key[k]]) != sig(m):
                msgs[by_key[k]] = m
                updated.append(m)
        head = {k: v for k, v in t.items() if k != "messages"}
        old_status = doc.get("status")
        head_changed = sig({k: v for k, v in doc.items() if k in head}) != sig(head)
        if not (new or added or updated or head_changed):
            return
        hist = doc.get("status_history") or []
        if t.get("status") != old_status:
            hist.append({"tick": self.tick, "status": t.get("status")})
        doc.update(head)
        doc.update(messages=msgs, status_history=hist, first_seen_tick=doc.get("first_seen_tick", self.tick),
                   last_change_tick=self.tick, message_count=len(msgs))
        # a list whose message count says more than it shows: read the full thread once
        total = t.get("message_count") or t.get("messages_total")
        if isinstance(total, int) and total > len(t.get("messages") or []):
            self.enqueue("keyed", f"thread:{tid}", f"/api/threads/{tid}", self.on_thread, prio=3)
        self.store.put(rel, doc)
        self._rec("threads", {"thread": t.get("id"), "with": t.get("with"), "kind": t.get("kind"),
                              "status": t.get("status"), "new": new,
                              **({"status_from": old_status} if old_status != t.get("status") and not new else {}),
                              "messages_new": added, "messages_updated": updated,
                              "standing_offers": t.get("standing_offers")})

    def on_duels(self, d: dict, done: bool = False) -> None:
        duels = [x for x in (d.get("duels") or []) if isinstance(x, dict)] if isinstance(d, dict) else []
        live_now = []
        for x in duels:
            did = _id(x, "duel", "id")
            if did is None:
                continue
            if x.get("status", "live") == "live":
                live_now.append(str(did))
            self.merge_duel(str(did), x)
        if done:
            return
        # A duel that left the live list has finished: read the finished list now for its result.
        if any(i not in live_now for i in self.state["live_duels"]):
            self._enqueue_duels_done(prio=1)
        self.state["live_duels"] = live_now
        self._dirty = True

    def merge_duel(self, did: str, x: dict) -> None:
        rel = f"duels/{did}.json"
        doc = self._doc(rel)
        new = not doc
        msgs = doc.get("messages") or []
        keys = {_msg_key(m) for m in msgs}
        added = []
        for m in x.get("messages") or []:
            if isinstance(m, dict) and _msg_key(m) not in keys:
                keys.add(_msg_key(m))
                msgs.append(m)
                added.append(m)
        msgs.sort(key=lambda m: (m.get("tick") or 0))
        head = {k: v for k, v in x.items() if k != "messages"}
        old = {k: doc.get(k) for k in head}
        changed = {k: [old.get(k), v] for k, v in head.items() if old.get(k) != v} if not new else {}
        if not (new or added or changed):
            return
        hist = doc.get("status_history") or []
        if x.get("status") != doc.get("status"):
            hist.append({"tick": self.tick, "status": x.get("status")})
        doc.update(head)
        doc.update(messages=msgs, status_history=hist, first_seen_tick=doc.get("first_seen_tick", self.tick),
                   last_change_tick=self.tick, message_count=len(msgs))
        self.store.put(rel, doc)
        self._rec("duels", {"duel": x.get("duel", did), "status": x.get("status"), "rival": x.get("rival"),
                            "role": x.get("role"), "new": new, "messages_new": added,
                            "changed": changed,
                            **({"head": head} if new else {})})

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        lanes = {k: {**v.status(), "queued": len(self.queues[k])} for k, v in self.lanes.items()}
        keyed_down = "keyed" in self.lanes and self.lanes["keyed"].down_since is not None
        public_down = self.lanes["public"].down_since is not None
        state = ("public_down" if public_down else "gateway_down" if keyed_down
                 else "running" if self.open else "closed" if self.clock else "starting")
        limited = {k: v.limited_recently() for k, v in self.lanes.items() if v.limited_recently()}
        c = self.state["cards"]
        return {"updated": round(self.now(), 3), "state": state, "rate_limited": limited, "tick": self.tick,
                "doors": self.clock.get("doors"), "paused": self.clock.get("paused"),
                "tick_seconds": self.clock.get("tick_seconds"), "last_event_id": self.state["last_event_id"],
                "feed_gaps": self.state["gaps"], "feed_busy": self.feed_busy, "lanes": lanes,
                "cards": {"active": bool(c.get("active")), "cursor": c.get("cursor"), "max_asset": self.state["max_asset"],
                          "known": len(c.get("hashes") or {}), "finished": c.get("finished")},
                "written_this_run": dict(self.counts), "root": str(self.store.root),
                "last_errors": list(self.errors)[-5:], "links": self.links}
