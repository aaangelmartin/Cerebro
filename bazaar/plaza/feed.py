"""The public game feed, as the plaza needs it: open offers on every venue, sales per card and floor items.

Read from the recorder's files only (data/live/events.jsonl grows by appends; record/latest/books and venues are
small snapshots). No game request is made here. The feed names the maker of every offer; the books say which
unaddressed offers are still open."""
from __future__ import annotations

import collections
import json
from pathlib import Path

VENUE = "v07"
RASTRO = "rastro"
RASTRO_FEE = (500, 1)                      # bps, P per card, when venues.json does not say
KEEP_ITEMS = 600
KEEP_SALES = 4000
KEEP_LOG = 4000
WANTED = ('"offer.listed"', '"offer.cancelled"', '"settlement"', '"pack.opened"', '"taller.crafted"',
          '"venue.announcement"')


def _refs(side: dict | None) -> list[str]:
    side = side or {}
    out = [a.get("ref") for a in side.get("assets") or [] if isinstance(a, dict) and a.get("ref")]
    for t in list(side.get("types") or []) + list(side.get("cards") or []):
        if isinstance(t, str):
            out.append(t.split(":", 1)[1] if t.startswith("card:") else t)
    return [r for r in out if isinstance(r, str)]


def norm_offer(o: dict) -> dict | None:
    """A game offer as the plaza shows it: side ask | bid | swap, the card, the price."""
    if not isinstance(o, dict) or o.get("thread"):
        return None                                           # dealer and team threads are not the open market
    give, want = o.get("give") or {}, o.get("want") or {}
    gives, wants = _refs(give), _refs(want)
    gcash, wcash = int(give.get("cash") or 0), int(want.get("cash") or 0)
    if gives and wants:
        side, ref, price = "swap", gives[0], 0
    elif gives and wcash > 0:
        side, ref, price = "ask", gives[0], wcash
    elif wants and gcash > 0:
        side, ref, price = "bid", wants[0], gcash
    else:
        return None
    return {"id": o.get("id"), "maker": o.get("maker"), "to": o.get("to"), "venue": o.get("venue"), "side": side,
            "ref": ref, "ref_back": wants[0] if side == "swap" else None, "price": price,
            "created_tick": o.get("created_tick"), "expires_tick": o.get("expires_tick")}


def venue_fees(record: Path) -> dict[str, dict]:
    """venue -> {bps, per_card, name, owner}; El Rastro's default when the snapshot lacks it."""
    out = {RASTRO: {"bps": RASTRO_FEE[0], "per_card": RASTRO_FEE[1], "name": "El Rastro", "owner": None},
           VENUE: {"bps": 0, "per_card": 0, "name": VENUE, "owner": None}}       # ours charges nothing
    try:
        data = json.loads((Path(record) / "latest" / "venues.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    for v in (data.get("venues") if isinstance(data, dict) else data) or []:
        if isinstance(v, dict) and v.get("venue"):
            out[v["venue"]] = {"bps": int(v.get("fee_bps") or 0), "per_card": int(v.get("fee_per_card") or 0),
                               "name": v.get("name") or v["venue"], "owner": v.get("owner"),
                               "status": v.get("status")}
    return out


def fee(fees: dict[str, dict], venue: str | None, price: float, cards: int = 1) -> int:
    f = fees.get(venue or RASTRO) or fees[RASTRO]
    return int(round(price * f["bps"] / 10000 + f["per_card"] * cards)) if price > 0 or f["per_card"] else 0


class Feed:
    """Follows events.jsonl by offset. `refresh()` returns the floor items that appeared since the last call."""

    def __init__(self, live: Path, record: Path, venue: str = VENUE):
        self.path, self.record, self.venue = Path(live) / "events.jsonl", Path(record), venue
        self.offset = 0
        self.tick: int | None = None
        self.offers: dict[int, dict] = {}                      # id -> normalised offer, as listed
        self.cancelled: set[int] = set()
        self.sales: collections.deque = collections.deque(maxlen=KEEP_SALES)
        self.items: collections.deque = collections.deque(maxlen=KEEP_ITEMS)
        self.venue_log: list[dict] = []                        # offers and sales between teams, for the match threads
        self.team_deals: collections.deque = collections.deque(maxlen=KEEP_SALES)   # team-to-team sales, any venue
        self.counts = {"venue_offers": 0, "venue_deals": 0, "venue_volume": 0, "team_deals": 0}

    # ---- reading
    def refresh(self) -> list[dict]:
        new: list[dict] = []
        try:
            size = self.path.stat().st_size
            if size < self.offset:                             # the file was rotated: start again
                self.__init__(self.path.parent, self.record, self.venue)
            if size == self.offset:
                return new
            with self.path.open("rb") as f:
                f.seek(self.offset)
                chunk = f.read()
        except OSError:
            return new
        end = chunk.rfind(b"\n")
        if end < 0:
            return new                                         # a line still being written
        self.offset += end + 1
        for raw in chunk[:end].split(b"\n"):
            line = raw.decode("utf-8", errors="replace")
            if not any(w in line for w in WANTED):
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            item = self._take(e)
            if item:
                self.items.append(item)
                new.append(item)
        return new

    def _take(self, e: dict) -> dict | None:
        p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        kind, tick = e.get("type"), e.get("tick")
        if isinstance(tick, int):
            self.tick = tick
        base = {"src": "game", "gid": e.get("id"), "ts": e.get("ts"), "tick": tick}
        if kind == "offer.listed":
            if p.get("kind") == "persona":
                return None
            o = norm_offer(p.get("offer") if isinstance(p.get("offer"), dict) else p)
            if not o or not isinstance(o.get("id"), int) or not str(o.get("maker") or "").startswith("t"):
                return None
            self.offers[o["id"]] = o
            if o["venue"] == self.venue:
                self.counts["venue_offers"] += 1
            if o["venue"] == self.venue or o.get("to"):       # ours, and addressed offers anywhere (wrong venue)
                self._log({"t": "listed", "tick": tick, "venue": o["venue"],
                           **{k: o[k] for k in ("id", "maker", "to", "side", "ref", "ref_back", "price")}})
            return {**base, "kind": "offer", "side": o["side"], "team": o["maker"], "to": o["to"],
                    "venue": o["venue"], "ref": o["ref"], "ref_back": o["ref_back"], "price": o["price"],
                    "offer": o["id"], "highlight": o["venue"] == self.venue}
        if kind == "offer.cancelled":
            oid = p.get("offer")
            oid = oid.get("id") if isinstance(oid, dict) else oid
            if isinstance(oid, int):
                self._log({"t": "cancelled", "tick": tick, "id": oid,
                           "venue": (self.offers.get(oid) or {}).get("venue") or p.get("venue")})
                self.cancelled.add(oid)
                self.offers.pop(oid, None)
            return None
        if kind == "settlement":
            parties = [x for x in p.get("parties") or [] if isinstance(x, str)]
            refs = [i.get("ref") for i in p.get("items") or [] if isinstance(i, dict) and i.get("ref")]
            if not refs:
                return None
            venue, price = p.get("venue"), p.get("price") or 0
            teams = [x for x in parties if x.startswith("t") and x[1:].isdigit()]
            for i in p.get("items") or []:
                if isinstance(i, dict) and i.get("ref"):
                    self.sales.append({"ref": i["ref"], "tick": tick, "price": price, "venue": venue,
                                       "from": i.get("frm"), "to": i.get("to"), "dealer": p.get("persona")})
            for oid, o in list(self.offers.items()):           # an addressed offer between these two is done
                if o.get("to") and {o["maker"], o["to"]} == set(parties) and o["ref"] in refs:
                    self.offers.pop(oid, None)
            if len(teams) == 2:
                self.counts["team_deals"] += 1
                self.team_deals.append({"tick": tick, "venue": venue, "parties": teams, "refs": refs, "price": price})
            if venue == self.venue or (len(teams) == 2 and not p.get("persona")):
                # every sale between two teams, wherever it closed: a match that settles off our venue is lost
                self._log({"t": "settled", "tick": tick, "venue": venue, "id": p.get("settlement"),
                           "parties": parties, "refs": refs, "price": price})
            if venue == self.venue:
                self.counts["venue_deals"] += 1
                self.counts["venue_volume"] += price
            if p.get("persona") and len(teams) < 2:
                return {**base, "kind": "deal", "team": teams[0] if teams else None, "dealer": p.get("persona"),
                        "venue": None, "ref": refs[0], "refs": refs, "price": price, "highlight": False}
            frm = (p.get("items") or [{}])[0].get("frm")
            return {**base, "kind": "deal", "team": frm if frm in teams else (teams[0] if teams else None),
                    "to": next((t for t in teams if t != frm), None), "venue": venue, "ref": refs[0], "refs": refs,
                    "price": price, "highlight": venue == self.venue}
        if kind == "pack.opened":
            return {**base, "kind": "pack", "team": p.get("team"), "text": str(p.get("pack") or "pack")[:40],
                    "highlight": False}
        if kind == "taller.crafted":
            return {**base, "kind": "craft", "team": p.get("team"), "text": str(p.get("card") or "")[:60],
                    "highlight": False}
        if kind == "venue.announcement":
            text = p.get("text") or p.get("message") or ""
            if not isinstance(text, str) or not text.strip():
                return None
            return {**base, "kind": "announce", "team": p.get("owner") or e.get("actor") or None,
                    "venue": p.get("venue"), "text": text[:400], "highlight": p.get("venue") == self.venue}
        return None

    def _log(self, entry: dict) -> None:
        self.venue_log.append(entry)
        if len(self.venue_log) > 2 * KEEP_LOG:                 # shrinking makes the reader start over, harmlessly
            del self.venue_log[:KEEP_LOG]

    # ---- views
    def open_offers(self, fees: dict[str, dict] | None = None) -> list[dict]:
        """Offers still open: listed, not cancelled or expired, and (unaddressed) still in their venue's book."""
        tick = self.tick or 0
        book_ids: dict[str, tuple[int, set[int]]] = {}
        folder = self.record / "latest" / "books"
        try:
            for path in folder.glob("*.json"):
                try:
                    b = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                book_ids[b.get("venue") or path.stem] = (int(b.get("tick") or 0),
                                                         {o.get("id") for o in b.get("offers") or []})
        except OSError:
            pass
        fees = fees or venue_fees(self.record)
        out = []
        for oid, o in self.offers.items():
            if (o.get("expires_tick") or 0) < tick:
                continue
            seen = book_ids.get(o["venue"])
            if not o.get("to") and seen and seen[0] >= (o.get("created_tick") or 0) + 1 and oid not in seen[1]:
                continue                                       # gone from a book taken after it was listed
            v = fees.get(o["venue"]) or {}
            f = fee(fees, o["venue"], o["price"])
            out.append({**o, "venue_name": v.get("name") or o["venue"], "fee": f,
                        "cost": o["price"] + f if o["side"] == "ask" else None,
                        "nets": o["price"] - f if o["side"] == "bid" else None})
        out.sort(key=lambda x: (-(x.get("created_tick") or 0), x["id"]))
        return out

    def sales_of(self, ref: str, limit: int = 12) -> list[dict]:
        rows = [s for s in self.sales if s["ref"] == ref]
        return rows[-limit:][::-1]

    def offer(self, oid) -> dict | None:
        """An offer the feed listed and has not seen cancelled or settled, on any venue."""
        return self.offers.get(oid) if isinstance(oid, int) and not isinstance(oid, bool) else None

    def team_prices(self, last: int = 5) -> dict[str, int]:
        """ref -> the public reference price: the median of its last sales between two teams (dealers excluded).
        A card nobody has traded has no entry."""
        by: dict[str, list[int]] = {}
        for s in self.sales:
            if s.get("dealer") or not s.get("price"):
                continue
            if all(str(s.get(k) or "").startswith("t") and str(s.get(k))[1:].isdigit() for k in ("from", "to")):
                by.setdefault(s["ref"], []).append(int(s["price"]))
        out = {}
        for ref, prices in by.items():
            tail = sorted(prices[-last:])
            out[ref] = tail[len(tail) // 2] if len(tail) % 2 else round((tail[len(tail) // 2 - 1] + tail[len(tail) // 2]) / 2)
        return out

    def traded_pairs(self, venue: str | None = None) -> set[frozenset]:
        """Pairs of teams that have closed a sale on `venue` (ours by default)."""
        venue = venue or self.venue
        return {frozenset(d["parties"]) for d in self.team_deals if d["venue"] == venue}

    def by_venue(self, since_tick: int = 0) -> dict[str, int]:
        """Team-to-team sales per venue since a tick: our share of the trades teams make."""
        out: dict[str, int] = {}
        for d in self.team_deals:
            if (d.get("tick") or 0) >= since_tick:
                out[d.get("venue") or "?"] = out.get(d.get("venue") or "?", 0) + 1
        return out
