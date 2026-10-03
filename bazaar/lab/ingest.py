"""Ingest: turn Friday's material and the live ledger into one corpus, then into features.

The corpus is plain JSON (persisted at ``config.LAB / "corpus.json"`` with the read offsets of every
live file in ``ingest_state.json``), so the Lab process can restart and continue where it was.

    corpus = Corpus(); load_friday(corpus)           # once
    ing = Ingestor(corpus); ing.poll()               # every tick: reads only the new bytes
    feats = build_features(corpus)                   # dealer curves, prices, attribution, duels, errors

Evidence ids (``thr:``, ``duel:``, ``set:``, ``lb:``, ``dec:``) point back into the corpus and carry
their source (team, dealer or rival) and tick, which the gate needs for its diversity rules.
"""
from __future__ import annotations

import statistics as st
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from bazaar import config
import re

from bazaar.lab.common import (WINDOW_TICKS, book_of, iter_jsonl, rarity_of, read_json, read_jsonl, safe_id,
                               safe_team, window_of, write_json)

KNOWN_EVENT_TYPES = {
    "thread.message", "duel.closed", "offer.listed", "offer.cancelled", "thread.opened", "settlement",
    "pack.opened", "venue.fee_announced", "announcement", "gift.given", "venue.fee_changed",
    "venue.announcement", "level.unlocked", "persona.open_to_all", "day.closed", "clock.changed",
    "venue.opened", "venue.closed", "thread.closed", "offer.accepted", "offer.expired", "duel.opened",
    "day.opened", "round.started", "round.ended", "bench.started", "bench.ended", "flag.resolved",
    "level.announced", "level.activated", "clock.limits_changed",
}
KNOWN_DEALERS = {"abuela", "chato"}
MAX_TEAM_EVENTS = 400
MAX_LISTINGS = 3000
MAX_NOVELTY = 300
MAX_CLOSINGS = 5000
SCHEMA = 2                 # 2: (id, tick, type) dedupe, settlement source = team pair, closings, offsets inside
_KEY_RE = re.compile(r"^[a-z0-9_.:-]{1,40}$")


def _safe_key(x: Any) -> str:
    """Event types / error codes come from outside: keep them only when they look like identifiers."""
    return x if isinstance(x, str) and _KEY_RE.match(x) else "unknown"


def _q(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    i = (len(xs) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (i - lo), 2)


def _med(xs):
    return round(st.median(xs), 2) if xs else None


def _mean(xs):
    return round(sum(xs) / len(xs), 3) if xs else None


def classify_rival(prices: list[float], role: str) -> str:
    """Duel rival archetype from its offer sequence: mute, fixed, stepped or tough."""
    prices = [p for p in prices if p is not None]
    if not prices:
        return "mute"
    if len(prices) >= 2 and len(set(prices)) == 1:
        return "fixed"
    if len(prices) < 2:
        return "stepped"           # one offer: treat as a mover (it made a reasonable first offer)
    steps = [abs(b - a) for a, b in zip(prices, prices[1:])]
    rel = sum(steps) / len(steps) / max(1.0, abs(prices[0]))
    return "stepped" if rel >= 0.02 else "tough"


class Corpus:
    def __init__(self, data: dict | None = None):
        d = data or {}
        self.threads: dict[str, dict] = d.get("threads", {})
        self.settlements: list[dict] = d.get("settlements", [])
        self.duels: dict[str, dict] = d.get("duels", {})
        self.public_duels: dict[str, dict] = d.get("public_duels", {})
        self.leaderboard: list[dict] = d.get("leaderboard", [])
        self.team_events: dict[str, list] = d.get("team_events", {})
        self.listings: list[dict] = d.get("listings", [])
        self.decisions: dict[str, dict] = d.get("decisions", {})
        self.novelty: list[dict] = d.get("novelty", [])
        self.evidence: dict[str, dict] = d.get("evidence", {})
        self.llm_cost: dict[str, float] = d.get("llm_cost", {})
        self.council_votes: int = d.get("council_votes", 0)
        self.max_tick: dict[str, int] = d.get("max_tick", {})
        seen = d.get("seen", {})
        self.seen = {
            "dealers": set(seen.get("dealers", KNOWN_DEALERS)),
            "event_types": set(seen.get("event_types", KNOWN_EVENT_TYPES)),
            "limits": seen.get("limits", {}),
            "venues": set(seen.get("venues", [])),
            "decays": set(seen.get("decays", [0.06])),
            "errors": set(seen.get("errors", [])),
            "tick_seconds": seen.get("tick_seconds"),
        }
        self.version = d.get("version", 0)
        self.schema = d.get("schema", 1 if d else SCHEMA)
        # The live recorder may replay events already loaded (e.g. Friday's tail). A replay repeats id, tick
        # AND type; a new game may reuse an id with another tick/type, which must not be dropped.
        self.event_keys: set[str] = set(d.get("event_keys", []))
        # Closed negotiations (duel / dealer thread / market offer) with their lesson ids: the feedback loop.
        self.closings: dict[str, dict] = d.get("closings", {})
        self.offsets: dict[str, int] = dict(d.get("ingest_offsets", {}))
        # Seconds of LIVE play seen (from tick advances in the live feed): the clock of the lesson TTLs.
        self.live_clock: float = float(d.get("live_clock", 0.0))
        self.last_live_tick: int | None = d.get("last_live_tick")

    def to_dict(self) -> dict:
        return {
            "threads": self.threads, "settlements": self.settlements, "duels": self.duels,
            "public_duels": self.public_duels, "leaderboard": self.leaderboard,
            "team_events": self.team_events, "listings": self.listings[-MAX_LISTINGS:],
            "decisions": self.decisions, "novelty": self.novelty[-MAX_NOVELTY:], "evidence": self.evidence,
            "llm_cost": self.llm_cost, "council_votes": self.council_votes, "max_tick": self.max_tick,
            "seen": {k: (sorted(v) if isinstance(v, set) else v) for k, v in self.seen.items()},
            "version": self.version, "schema": SCHEMA, "event_keys": sorted(self.event_keys),
            "closings": dict(list(self.closings.items())[-MAX_CLOSINGS:]), "ingest_offsets": self.offsets,
            "live_clock": round(self.live_clock, 1), "last_live_tick": self.last_live_tick,
        }

    # --- helpers -------------------------------------------------------------
    def _ev(self, eid: str, src: str, tick: int | None, origin: str) -> str:
        self.evidence[eid] = {"src": src, "tick": tick, "w": window_of(tick, origin), "origin": origin}
        return eid

    def _team_event(self, team: str, tick: int, origin: str, kind: str, detail: Any) -> None:
        if not safe_team(team):
            return
        lst = self.team_events.setdefault(team, [])
        lst.append([tick, origin, kind, detail])
        if len(lst) > MAX_TEAM_EVENTS:
            del lst[: len(lst) - MAX_TEAM_EVENTS]

    def novel(self, kind: str, key: str, tick: int | None, detail: Any, origin: str = "live") -> None:
        if any(n["kind"] == kind and n["key"] == key for n in self.novelty):
            return
        self.novelty.append({"kind": kind, "key": key, "tick": tick, "detail": detail, "origin": origin,
                             "handled": False})

    def _thread(self, origin: str, tid: Any, **init) -> dict:
        key = f"{origin}:thr:{tid}"
        t = self.threads.get(key)
        if t is None:
            t = {"key": key, "id": tid, "origin": origin, "dealer": None, "team": None, "side": None,
                 "item": None, "rarity": None, "dealer_prices": [], "team_prices": [], "final": False,
                 "status": "open", "deal_price": None, "first_tick": None, "last_tick": None}
            if origin == "live":
                t["lc"] = self.live_clock
            self.threads[key] = t
        for k, v in init.items():
            if v is not None and t.get(k) in (None, [], False):
                t[k] = v
        return t

    # --- events --------------------------------------------------------------
    def add_event(self, e: dict, origin: str = "live") -> None:
        if "payload" not in e and isinstance(e.get("data"), dict):     # gateway SSE envelope
            data = e["data"]
            e = data if "payload" in data else {"id": e.get("seq"), "type": e.get("type"),
                                                 "tick": data.get("tick"), "payload": data}
        typ, p = _safe_key(e.get("type") or ""), e.get("payload") or {}
        eid = e.get("id")
        tick = int(e.get("tick") or p.get("tick") or 0)
        if isinstance(eid, int) and e.get("scope", "public") == "public":
            key = f"{eid}|{tick}|{typ}"
            if key in self.event_keys:
                return                      # already seen (replayed feed)
            self.event_keys.add(key)
        self.max_tick[origin] = max(self.max_tick.get(origin, 0), tick)
        if origin == "live" and tick:
            self._advance_live_clock(tick)
        self.version += 1
        if typ not in self.seen["event_types"]:
            self.seen["event_types"].add(typ)
            self.novel("event_type", typ, tick, {"example": _short(p)}, origin)
        actor = e.get("actor") or ""
        if typ == "thread.opened" and p.get("kind") == "persona":
            topic = p.get("topic") or {}
            side = "sell" if "buy" in topic else "buy" if "sell" in topic else None
            buy = topic.get("buy") or {}
            item = buy.get("card") or buy.get("pack") or buy.get("rarity")
            t = self._thread(origin, p.get("thread"), dealer=safe_id(p.get("with"), "unknown"),
                             team=safe_team(p.get("team")), side=side, item=item, first_tick=tick)
            t["rarity"] = t["rarity"] or (rarity_of(item) if item else None)
            self._new_dealer(p.get("with"), tick, origin)
            self._team_event(p.get("team", ""), tick, origin, "thread.opened", p.get("with"))
        elif typ == "thread.message" and p.get("kind") == "persona":
            self._thread_message(p, tick, origin)
        elif typ == "settlement":
            self._settlement(p, tick, origin)
        elif typ == "duel.closed":
            self.public_duels[f"{origin}:{p.get('duel')}"] = {"status": p.get("status"), "tick": tick,
                                                              "session": p.get("session")}
        elif typ == "offer.listed":
            self._listing(p, tick, origin)
        elif typ in ("level.unlocked", "persona.open_to_all", "level.announced", "level.activated"):
            self._new_dealer(p.get("persona") or p.get("id"), tick, origin, detail=p)
            self._team_event(p.get("team", ""), tick, origin, "level", p.get("persona"))
        elif typ in ("clock.changed", "clock.limits_changed"):
            lim = p.get("limits")
            if isinstance(lim, dict) and lim != self.seen["limits"]:
                if self.seen["limits"]:
                    self.novel("limits", f"limits@{tick}", tick, {"old": self.seen["limits"], "new": lim}, origin)
                self.seen["limits"] = lim
            ts = p.get("tick_seconds")
            if ts and ts != self.seen.get("tick_seconds"):
                if self.seen.get("tick_seconds"):
                    self.novel("tick_seconds", f"tick_seconds@{tick}", tick, {"tick_seconds": ts}, origin)
                self.seen["tick_seconds"] = ts
        elif typ == "announcement":
            text = str(p.get("text", ""))
            if any(w in text.lower() for w in ("limit", "rule", "per tick", "quota", "new dealer", "now ")):
                self.novel("announcement", f"ann@{tick}", tick, {"text": text[:300]}, origin)
        elif typ.startswith("venue."):
            v = safe_id(p.get("venue"))
            if v and v not in self.seen["venues"]:
                self.seen["venues"].add(v)
                if origin == "live":
                    self.novel("venue", v, tick, _short(p), origin)
        if actor.startswith("t") and typ not in ("thread.message", "settlement", "offer.listed"):
            self._team_event(actor, tick, origin, typ, None)

    def _advance_live_clock(self, tick: int) -> None:
        last = self.last_live_tick
        if last is None or tick < last - 30:          # first live event, or the game renumbered its ticks
            self.last_live_tick = tick
        elif tick > last:
            self.live_clock += min(tick - last, 5) * float(self.seen.get("tick_seconds") or 60.0)
            self.last_live_tick = tick

    def _new_dealer(self, dealer: str | None, tick: int, origin: str, detail: Any = None) -> None:
        if not safe_id(dealer) or safe_team(dealer) or dealer == "unknown":
            return
        if dealer not in self.seen["dealers"]:
            self.seen["dealers"].add(dealer)
            self.novel("dealer", dealer, tick, detail or {"first_seen": tick}, origin)

    def _thread_message(self, p: dict, tick: int, origin: str) -> None:
        dealer, team, sender = safe_id(p.get("with"), "unknown"), safe_team(p.get("team")), p.get("sender")
        offer = p.get("offer") or {}
        give, want = offer.get("give") or {}, offer.get("want") or {}
        t = self._thread(origin, p.get("thread"), dealer=dealer, team=team, first_tick=tick)
        if t.get("from_memory"):
            return
        self._new_dealer(dealer, tick, origin)
        t["last_tick"] = tick
        types = (give.get("types") or []) + (want.get("types") or [])
        item = types[0].split(":", 1)[1] if types else None
        if not item:
            refs = [a.get("ref") for a in (give.get("assets") or []) + (want.get("assets") or [])
                    if isinstance(a, dict) and a.get("ref")]
            item = refs[0] if refs else None
        if item and not t["item"]:
            t["item"] = item
        if item and (not t["rarity"] or t["rarity"] in ("unknown", "common", "uncommon", "rare")):
            t["rarity"] = rarity_of(item)
        if sender == p.get("with") and not offer:
            if p.get("text"):
                t["last_text"] = str(p["text"])[:300]
        elif sender == p.get("with"):
            if give.get("types") or give.get("assets"):
                t["side"], price = "sell", want.get("cash")
            else:
                t["side"], price = "buy", give.get("cash")
            if price is not None:
                t["dealer_prices"].append([tick, price, bool(offer.get("final"))])
                t["final"] = t["final"] or bool(offer.get("final"))
            if p.get("text"):
                t["last_text"] = str(p["text"])[:300]
        elif offer:
            price = give.get("cash") if give.get("cash") else want.get("cash")
            if price:
                t["team_prices"].append([tick, price])

    def _settlement(self, p: dict, tick: int, origin: str) -> None:
        items = p.get("items") or []
        refs = [i.get("ref") for i in items]
        persona = p.get("persona")
        parties = p.get("parties") or []
        row = {"id": p.get("settlement"), "tick": tick, "origin": origin, "venue": p.get("venue"),
               "persona": persona, "refs": refs, "price": p.get("price"), "fee": p.get("fee", 0),
               "parties": parties, "kind": p.get("kind")}
        if origin == "live":
            row["lc"] = self.live_clock
        if items:
            row["seller"] = items[0].get("frm")
            row["buyer"] = items[0].get("to")
        self.settlements.append(row)
        # The source of a settlement is the PAIR of parties: two colluding teams count as one source.
        src = "|".join(sorted({str(x) for x in parties if x})) or persona or "?"
        row["eid"] = self._ev(f"set:{origin}:{row['id']}", src, tick, origin)
        if persona:
            team = next((x for x in parties if x != persona), None)
            cands = [t for t in self.threads.values() if t["origin"] == origin and t["dealer"] == persona
                     and t["team"] == team and t["status"] == "open"]
            if cands:
                t = max(cands, key=lambda t: t.get("last_tick") or 0)
                t["status"], t["deal_price"] = "deal", p.get("price")
            for x in parties:
                self._team_event(x, tick, origin, "deal_dealer",
                                 {"persona": persona, "refs": refs, "price": p.get("price"),
                                  "dir": "buy" if row.get("buyer") == x else "sell"})
        else:
            for x in parties:
                self._team_event(x, tick, origin, "deal_team",
                                 {"venue": p.get("venue"), "refs": refs, "price": p.get("price"),
                                  "dir": "buy" if row.get("buyer") == x else "sell"})

    def _listing(self, p: dict, tick: int, origin: str) -> None:
        o = p.get("offer") or {}
        give, want = o.get("give") or {}, o.get("want") or {}
        g_refs = [a.get("ref") for a in give.get("assets") or []]
        w_refs = [x.split(":", 1)[1] for x in want.get("types") or [] if ":" in x] + list(want.get("cards") or [])
        row = {"tick": tick, "origin": origin, "maker": safe_team(o.get("maker")) or "?",
               "venue": safe_id(p.get("venue") or o.get("venue"), "venue"),
               "ask_refs": g_refs, "ask": want.get("cash") if g_refs else None,
               "bid_refs": w_refs, "bid": give.get("cash") if w_refs else None}
        if origin == "live":
            row["lc"] = self.live_clock
        self.listings.append(row)
        if len(self.listings) > MAX_LISTINGS:
            del self.listings[: len(self.listings) - MAX_LISTINGS]
        self._team_event(o.get("maker", ""), tick, origin, "listed",
                         {"ask": row["ask"], "ask_refs": g_refs, "bid": row["bid"], "bid_refs": w_refs})

    # --- our own records -----------------------------------------------------
    def add_duel(self, raw: dict, origin: str) -> None:
        did = raw.get("duel") or raw.get("id")
        rival_prices = [m.get("price") for m in raw.get("messages", []) if m.get("from") not in ("you", None)
                        and m.get("price") is not None]
        our_prices = [m.get("price") for m in raw.get("messages", []) if m.get("from") == "you"]
        status = raw.get("status")
        key = f"{origin}:duel:{did}"
        rec = {"key": key, "id": did, "origin": origin, "status": status, "role": raw.get("role"),
               "limit": raw.get("your_limit"), "price": raw.get("price"), "rounds": raw.get("rounds", 0),
               "points": raw.get("result") or 0.0, "rival": raw.get("rival"), "rival_prices": rival_prices,
               "our_first": our_prices[0] if our_prices else None, "issues": raw.get("issues") or ["price"],
               "decay": raw.get("decay_per_round", 0.06), "session": raw.get("session"),
               "tick": raw.get("deadline_tick"), "kind": classify_rival(rival_prices, raw.get("role", ""))}
        if origin == "live":
            rec["lc"] = (self.duels.get(key) or {}).get("lc", self.live_clock)
        dec = rec["decay"]
        if dec is not None and dec not in self.seen["decays"]:
            self.seen["decays"].add(dec)
            self.novel("duel_decay", str(dec), rec["tick"], {"decay": dec, "issues": rec["issues"]}, origin)
        self.duels[key] = rec
        self._ev(f"duel:{origin}:{did}", f"rival:{raw.get('rival')}", rec["tick"], origin)
        self.version += 1

    def add_our_thread(self, tid: Any, th: dict, origin: str = "friday") -> None:
        hist = th.get("history") or []
        t = self._thread(origin, tid, dealer=th.get("dealer"), team="t10",
                         side="sell" if th.get("goal") == "buy" else "buy", item=th.get("item"))
        t["from_memory"] = True
        t["rarity"] = rarity_of(th.get("item") or "")
        t["dealer_prices"] = [[h[0], h[2], False] for h in hist if h[2] is not None]
        if t["dealer_prices"] and th.get("final"):
            t["dealer_prices"][-1][2] = True
        t["team_prices"] = [[h[0], h[1]] for h in hist if h[1] is not None]
        t["final"] = bool(th.get("final"))
        t["status"] = {"deal": "deal", "walked": "walked", "closed": "closed"}.get(th.get("status"), "open")
        t["deal_price"] = th.get("theirs") if t["status"] == "deal" else None
        t["first_tick"] = hist[0][0] if hist else None
        t["last_tick"] = hist[-1][0] if hist else None
        t["our_limit"] = th.get("limit")

    def add_leaderboard(self, row: dict, origin: str) -> None:
        teams = row.get("teams") or (row.get("data") or {}).get("teams") or (row.get("leaderboard") or {}).get("teams")
        tick = row.get("tick") or (row.get("data") or {}).get("tick")
        if isinstance(teams, list):
            teams = {t.get("team") or t.get("id"): t for t in teams}
        if not teams or tick is None:
            return
        if any(s["tick"] == tick and s["origin"] == origin for s in self.leaderboard):
            return
        slim = {tid: {k: v.get(k) for k in ("score", "negotiating", "market", "deals", "level", "venue",
                                            "album_filled", "luck")} for tid, v in teams.items() if tid}
        snap = {"tick": int(tick), "origin": origin, "teams": slim}
        if origin == "live":
            snap["lc"] = self.live_clock
        self.leaderboard.append(snap)
        self.leaderboard.sort(key=lambda s: (s["origin"] != "friday", s["tick"]))
        self.version += 1

    def add_decision(self, row: dict) -> None:
        a = row.get("action") if isinstance(row.get("action"), dict) else row
        aid = a.get("id") or row.get("action_id")
        if not aid:
            return
        v = row.get("verdict") or {}
        d = self.decisions.setdefault(aid, {})
        d.update({"id": aid, "tick": row.get("tick") or a.get("tick"), "domain": a.get("domain"),
                  "kind": a.get("kind"), "params": a.get("params") or {}, "expected": a.get("expected") or {},
                  "lesson_ids": a.get("lesson_ids") or [], "source": row.get("source") or a.get("source"),
                  "ok": v.get("ok", True) if isinstance(v, dict) else True,
                  "rail": v.get("rail") if isinstance(v, dict) else None})
        self.version += 1

    def add_closing(self, row: dict) -> dict | None:
        """A closed negotiation (status deal|no_deal) written by a domain; idempotent by its key."""
        key = str(row.get("closing") or "")
        if not key or key in self.closings:
            return None
        aids = [str(a) for a in (row.get("action_ids") or []) if a]
        lids = [str(x) for x in (row.get("lesson_ids") or [])]
        for a in aids:
            lids += [str(x) for x in (self.decisions.get(a) or {}).get("lesson_ids") or []]
            if a in self.decisions:
                self.decisions[a]["closing"] = key
        c = {"key": key, "domain": row.get("domain"), "status": row.get("status"), "tick": row.get("tick"),
             "realised": row.get("realised") or {}, "action_ids": aids,
             "lesson_ids": list(dict.fromkeys(lids))[:16], "applied": False, "ts": row.get("ts")}
        self.closings[key] = c
        self.version += 1
        return c

    def add_outcome(self, row: dict) -> None:
        aid = row.get("action_id")
        resp = row.get("response") or {}
        if row.get("closing"):
            self.add_closing(row)
            if isinstance(resp, dict) and resp.get("duel") is not None and row.get("status") in ("deal", "no_deal"):
                self.add_duel({**resp, "status": resp.get("status") or row.get("status")}, "live")
            return
        if not aid:
            return
        d = self.decisions.setdefault(aid, {"id": aid})
        d["outcome"] = {"status": row.get("status"), "tick": row.get("tick"),
                        "realised": row.get("realised") or {}}
        self._ev(f"dec:{aid}", "t10", row.get("tick"), "live")
        err = _safe_key(resp.get("error")) if isinstance(resp, dict) and resp.get("error") else None
        if err and err not in self.seen["errors"]:
            self.seen["errors"].add(err)
            self.novel("error_code", err, row.get("tick"), {"message": str(resp.get("message", ""))[:200]})
        if isinstance(resp, dict) and resp.get("duel") and resp.get("status") in ("deal", "no_deal"):
            self.add_duel(resp, "live")
        self.version += 1


def _short(p: Any) -> Any:
    s = str(p)
    return s[:300]


# --- loaders ---------------------------------------------------------------------------------
def load_friday(corpus: Corpus, root: Path | None = None) -> Corpus:
    root = root or config.FRIDAY
    mem = read_json(root / "bot" / "memory.json", {}) or {}
    for tid, th in ((mem.get("dealer") or {}).get("threads") or {}).items():
        corpus.add_our_thread(tid, th, "friday")
    for e in iter_jsonl(root / "bot" / "history" / "events.jsonl"):
        corpus.add_event(e, "friday")
    for d in iter_jsonl(root / "bot" / "decisions.jsonl"):
        if d.get("strategy") == "duels" and d.get("action") == "result" and isinstance(d.get("raw"), dict):
            corpus.add_duel(d["raw"], "friday")
    for name in ("bot/history/leaderboard.jsonl", "gateway/leaderboard.jsonl"):
        for row in iter_jsonl(root / name):
            corpus.add_leaderboard(row, "friday")
    for t in corpus.threads.values():
        if t["origin"] == "friday":
            corpus._ev(f"thr:friday:{t['id']}", t.get("team") or "?", t.get("first_tick"), "friday")
    # Friday's novelty is the baseline, not news.
    for n in corpus.novelty:
        n["handled"] = True
    return corpus


LIVE_FILES = ("events.jsonl", "decisions.jsonl", "outcomes.jsonl", "leaderboard.jsonl", "council.jsonl",
              "llm.jsonl")


class Ingestor:
    """Reads the live ledger incrementally (byte offsets) into a Corpus.

    The offsets live inside the corpus (``corpus.offsets``) and both are saved together in one atomic
    write-then-rename, so a crash can never leave offsets ahead of (or behind) the corpus. An offset
    only moves after its rows were processed.
    """

    def __init__(self, corpus: Corpus, live: Path | None = None, state_path: Path | None = None):
        self.corpus = corpus
        self.live = Path(live or config.LIVE)
        self.state_path = Path(state_path or config.LAB / "ingest_state.json")
        if not corpus.offsets and corpus.schema < SCHEMA:          # legacy corpus: offsets were separate
            corpus.offsets.update((read_json(self.state_path, {}) or {}).get("offsets", {}))
        self.errors: list[str] = []

    @property
    def offsets(self) -> dict[str, int]:
        return self.corpus.offsets

    def _one(self, name: str, r: dict) -> None:
        c = self.corpus
        if name == "events.jsonl":
            c.add_event(r, "live")
        elif name == "decisions.jsonl":
            c.add_decision(r)
        elif name == "outcomes.jsonl":
            c.add_outcome(r)
        elif name == "leaderboard.jsonl":
            c.add_leaderboard(r, "live")
        elif name == "council.jsonl":
            c.council_votes += 1
        elif name == "llm.jsonl":
            purpose = r.get("purpose", "?")
            c.llm_cost[purpose] = round(c.llm_cost.get(purpose, 0.0) + float(r.get("cost_usd") or 0), 4)

    def poll(self) -> dict[str, int]:
        c, counts = self.corpus, {}
        for name in LIVE_FILES:
            path = self.live / name
            off = self.offsets.get(name, 0)
            try:
                if path.stat().st_size < off:     # rotated or truncated: start again
                    off = 0
            except FileNotFoundError:
                continue
            rows, new = read_jsonl(path, off)
            for r in rows:
                try:
                    self._one(name, r)
                except Exception as e:  # noqa: BLE001 - one bad row never blocks the file
                    self.errors.append(f"{name}: {type(e).__name__}: {e}"[:200])
                    del self.errors[:-20]
            self.offsets[name] = new              # only after the rows are in the corpus
            counts[name] = len(rows)
        for t in c.threads.values():
            if t["origin"] == "live":
                c._ev(f"thr:live:{t['id']}", t.get("team") or "?", t.get("first_tick"), "live")
        return counts

    def save(self, corpus_path: Path | None = None) -> None:
        """Corpus and offsets in ONE file, written atomically; ingest_state.json is only informational."""
        write_json(Path(corpus_path or config.LAB / "corpus.json"), self.corpus.to_dict())
        try:
            write_json(self.state_path, {"offsets": dict(self.offsets), "note": "informational; the corpus holds them"})
        except OSError:
            pass


def seed_known(corpus: Corpus, live: Path | None = None) -> bool:
    """Seed seen limits / tick speed from the operator's known.json, so the first live change is news."""
    known = read_json(Path(live or config.LIVE) / "known.json", {}) or {}
    changed = False
    if not corpus.seen.get("limits") and isinstance(known.get("limits"), dict) and known["limits"]:
        corpus.seen["limits"] = dict(known["limits"])
        changed = True
    if not corpus.seen.get("tick_seconds") and known.get("tick_seconds"):
        corpus.seen["tick_seconds"] = known["tick_seconds"]
        changed = True
    return changed


def load_or_build(corpus_path: Path | None = None, friday_root: Path | None = None) -> Corpus:
    """The saved corpus, or a fresh one from Friday when absent or of an older schema (the live files are
    then re-read from offset 0 by the Ingestor, which recovers live events an older dedupe dropped)."""
    path = Path(corpus_path or config.LAB / "corpus.json")
    data = read_json(path)
    if data and int(data.get("schema", 1)) >= SCHEMA:
        return Corpus(data)
    c = load_friday(Corpus(), friday_root)
    if data:
        c.novelty = [n for n in data.get("novelty", []) if n.get("origin") == "live"] + c.novelty
    return c


# --- features --------------------------------------------------------------------------------
def dealer_curves(c: Corpus) -> dict[str, dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in c.threads.values():
        if t.get("dealer") and t.get("side") and t["dealer_prices"]:
            groups[f"{t['dealer']}|{t['side']}|{t.get('rarity') or 'unknown'}"].append(t)
    out = {}
    for key, ts in groups.items():
        opens = [t["dealer_prices"][0][1] for t in ts]
        finals = [t["dealer_prices"][-1][1] for t in ts if t["final"]]
        deals = [t["deal_price"] for t in ts if t["deal_price"] is not None]
        lasts = [t["dealer_prices"][-1][1] for t in ts]
        steps_to_final = [len(t["dealer_prices"]) for t in ts if t["final"]]
        ratios = []
        for t in ts:
            ratios.extend(_mirror_ratios(t))
        out[key] = {
            "n": len(ts), "teams": len({t.get("team") for t in ts}),
            "open_med": _med(opens), "open_range": [min(opens), max(opens)],
            "final_med": _med(finals), "final_range": [min(finals), max(finals)] if finals else None,
            "deal_med": _med(deals), "deal_range": [min(deals), max(deals)] if deals else None,
            "last_med": _med(lasts), "steps_to_final": _med(steps_to_final),
            "mirror_ratio_med": _med(ratios), "n_ratio": len(ratios),
            "first_price_deals": sum(1 for t in ts if t["deal_price"] is not None and t["deal_price"] == t["dealer_prices"][0][1]),
            "evidence": [f"thr:{t['origin']}:{t['id']}" for t in ts][:12],
        }
    return out


def _mirror_ratios(t: dict) -> list[float]:
    """Dealer concession / team concession, per exchange where the team moved."""
    dp = [p for _, p, _ in t["dealer_prices"]]
    tp = [p for _, p in t["team_prices"]]
    out = []
    for i in range(1, min(len(dp), len(tp))):
        team_step = abs(tp[i] - tp[i - 1]) if i < len(tp) else 0
        dealer_step = abs(dp[i] - dp[i - 1])
        if team_step > 0:
            out.append(round(dealer_step / team_step, 3))
    return out


def price_table(c: Corpus) -> dict[str, Any]:
    by_ref: dict[str, list] = defaultdict(list)
    by_class: dict[str, list] = defaultdict(list)
    for s in c.settlements:
        if s.get("price") is None or not s["refs"]:
            continue
        ref = s["refs"][0]
        if len(s["refs"]) > 1:
            continue
        r = rarity_of(ref)
        if s.get("persona"):
            team_buys = s.get("buyer", "").startswith("t")
            klass = f"{s['persona']}:{'sells' if team_buys else 'buys'}:{r}"
        else:
            klass = f"{s.get('venue') or 'venue'}:{r}"
        by_ref[ref].append([s["price"], klass, s["tick"]])
        by_class[klass].append(s["price"])
    asks: dict[str, list] = defaultdict(list)
    bids: dict[str, list] = defaultdict(list)
    for l in c.listings:
        for ref in l["ask_refs"][:1]:
            if l["ask"]:
                asks[rarity_of(ref)].append(l["ask"])
        for ref in l["bid_refs"][:1]:
            if l["bid"]:
                bids[rarity_of(ref)].append(l["bid"])
    return {
        "by_class": {k: {"n": len(v), "med": _med(v), "p25": _q(v, .25), "p75": _q(v, .75), "min": min(v), "max": max(v)}
                     for k, v in by_class.items()},
        "by_ref": {k: v[-6:] for k, v in by_ref.items()},
        "listing_asks": {k: {"n": len(v), "med": _med(v), "p25": _q(v, .25), "p75": _q(v, .75)} for k, v in asks.items()},
        "listing_bids": {k: {"n": len(v), "med": _med(v), "p25": _q(v, .25), "p75": _q(v, .75)} for k, v in bids.items()},
    }


def attribution(c: Corpus, origin: str | None = None) -> dict[str, Any]:
    """Leaderboard score jumps attributed to each team's public actions in the window.

    For each pair of consecutive snapshots, a team's delta is corrected by the median delta of teams
    with no new deals (the whole board moves when the leader moves). A case is *clean* when the team
    did exactly one public deal in the window. Classes aggregate clean cases with sample sizes.
    """
    snaps = [s for s in c.leaderboard if origin is None or s["origin"] == origin]
    cases, classes = [], defaultdict(list)
    for a, b in zip(snaps, snaps[1:]):
        if a["origin"] != b["origin"] or b["tick"] <= a["tick"]:
            continue
        deltas, idle = {}, []
        for tid, tb in b["teams"].items():
            ta = a["teams"].get(tid)
            if not ta or tb.get("score") is None or ta.get("score") is None:
                continue
            dd = (tb.get("deals") or 0) - (ta.get("deals") or 0)
            deltas[tid] = (tb["score"] - ta["score"], dd)
            if dd == 0:
                idle.append(tb["score"] - ta["score"])
        drift = _med(idle) or 0.0
        for tid, (delta, dd) in deltas.items():
            acts = [e for e in c.team_events.get(tid, []) if e[1] == a["origin"] and a["tick"] < e[0] <= b["tick"]
                    and e[2] in ("deal_dealer", "deal_team")]
            adj = round(delta - drift, 3)
            case = {"team": tid, "from": a["tick"], "to": b["tick"], "origin": a["origin"], "delta": adj,
                    "deals_delta": dd, "public_deals": len(acts)}
            if dd == 1 and len(acts) == 1:
                klass = deal_class(acts[0])
                case["class"] = klass
                case["clean"] = True
                eid = f"lb:{a['origin']}:{a['tick']}-{b['tick']}:{tid}"
                c._ev(eid, tid, b["tick"], a["origin"])
                case["eid"] = eid
                classes[klass].append(case)
            cases.append(case)
    summary = {}
    for k, v in classes.items():
        ds = [x["delta"] for x in v]
        summary[k] = {"n": len(v), "teams": len({x["team"] for x in v}), "mean": _mean(ds), "med": _med(ds),
                      "pos": sum(1 for d in ds if d > 0), "neg": sum(1 for d in ds if d < 0),
                      "robust": len(v) >= 3 and len({x["team"] for x in v}) >= 2,
                      "evidence": [x["eid"] for x in v][:10]}
    big = sorted((x for x in cases if abs(x["delta"]) >= 2.0), key=lambda x: -abs(x["delta"]))[:12]
    return {"classes": summary, "big_moves": big, "n_cases": len(cases)}


def deal_class(ev: list) -> str:
    """'dealer_buy:rare:over_list' style class for one team deal event [tick, origin, kind, detail]."""
    d = ev[3] or {}
    refs = d.get("refs") or []
    ref = refs[0] if refs else ""
    r = rarity_of(ref)
    price = d.get("price") or 0
    book = book_of(ref) or 0
    rel = "over_book" if book and price > book else "under_book"
    if ev[2] == "deal_dealer":
        return f"dealer_{d.get('dir')}:{r}:{rel}"
    return f"team_{d.get('dir')}:{r}:{rel}"


def duel_stats(c: Corpus) -> dict[str, Any]:
    ds = list(c.duels.values())
    by_kind: dict[str, list] = defaultdict(list)
    for d in ds:
        by_kind[d["kind"]].append(d)

    def summ(xs):
        deals = [x for x in xs if x["status"] == "deal"]
        return {"n": len(xs), "deals": len(deals), "deal_rate": round(len(deals) / len(xs), 3) if xs else None,
                "points_mean": _mean([x["points"] for x in deals]), "rounds_mean": _mean([x["rounds"] for x in deals]),
                "evidence": [f"duel:{x['origin']}:{x['id']}" for x in xs][:12]}
    fast = [d for d in ds if d["status"] == "deal" and d["rounds"] <= 3]
    slow = [d for d in ds if d["status"] == "deal" and d["rounds"] > 3]
    pub = list(c.public_duels.values())
    return {
        "ours": summ(ds), "by_kind": {k: summ(v) for k, v in by_kind.items()},
        "fast_points": _mean([d["points"] for d in fast]), "slow_points": _mean([d["points"] for d in slow]),
        "n_fast": len(fast), "n_slow": len(slow),
        "public": {"n": len(pub), "deal_rate": round(sum(1 for p in pub if p["status"] == "deal") / len(pub), 3) if pub else None},
        "decays": sorted(c.seen["decays"]),
    }


def error_stats(c: Corpus) -> dict[str, Any]:
    per: dict[str, list] = defaultdict(list)
    statuses: dict[str, Counter] = defaultdict(Counter)
    for d in c.decisions.values():
        out = d.get("outcome")
        if not out:
            continue
        statuses[d.get("domain") or "?"][out.get("status")] += 1
        exp = (d.get("expected") or {}).get("points")
        real = (out.get("realised") or {}).get("points_delta")
        if isinstance(exp, (int, float)) and isinstance(real, (int, float)):
            per[d.get("domain") or "?"].append((exp, real))
    return {dom: {"n": len(v), "expected_mean": _mean([e for e, _ in v]), "realised_mean": _mean([r for _, r in v]),
                  "bias": _mean([e - r for e, r in v]), "mae": _mean([abs(e - r) for e, r in v]),
                  "statuses": dict(statuses[dom])} for dom, v in per.items()} | \
           {dom: {"n": 0, "statuses": dict(s)} for dom, s in statuses.items() if dom not in per}


def activity(c: Corpus, last_ticks: int = 60) -> dict[str, Any]:
    out = {}
    for team, evs in c.team_events.items():
        if not evs:
            continue
        top = max(e[0] for e in evs if e[1] == evs[-1][1])
        recent = [e for e in evs if e[1] == evs[-1][1] and e[0] > top - last_ticks]
        k = Counter(e[2] for e in recent)
        out[team] = dict(k)
    return out


def build_features(c: Corpus) -> dict[str, Any]:
    return {
        "dealer_curves": dealer_curves(c),
        "prices": price_table(c),
        "attribution": attribution(c),
        "duels": duel_stats(c),
        "errors": error_stats(c),
        "activity": activity(c),
        "novelty": [n for n in c.novelty if not n.get("handled")],
        "counts": {"threads": len(c.threads), "settlements": len(c.settlements), "duels": len(c.duels),
                   "leaderboard": len(c.leaderboard), "listings": len(c.listings), "decisions": len(c.decisions),
                   "evidence": len(c.evidence)},
        "max_tick": c.max_tick,
        "window_ticks": WINDOW_TICKS,
    }
