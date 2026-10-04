"""Matchmaker for our venue: find two OTHER teams that want to trade and bring both sides to v07.

Our market scores when two other teams gain on it ("zero fee alone is no reason to come"). So this module
reads what is public (bids, asks, dealer hunts: `intel.needs.needs_report`), pairs a seller with a buyer for
the same card, prices the pair where both gain, and tells them: one venue announcement with the best pairs
and, when control allows, one short thread message to each side. The broker then crosses the pair as soon
as both offers sit in our book (it already pairs every crossing bid and ask).

It never proposes us as a party (a team cannot trade on its own venue) and never pushes give-away prices:
a trade below the floor of its rarity destroys value and costs the venue points.

Runs inside the broker process between Market Test sessions, never in the bot's decision loop.
State and proposals live in data/live/matchmaker.json (the brain reads it in its picture).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

VENUE = "v07"
US = "t10"
RASTRO_FEE_BPS, RASTRO_FEE_FLAT = 500, 1          # El Rastro: the taker pays 5 % + 1 P per card
FLOOR = {"common": 4, "uncommon": 12, "rare": 40, "epic": 110, "legendary": 300}   # below this a sale is a giveaway
DEALER_LIST = {"common": 10, "uncommon": 25, "rare": 63, "epic": 162, "legendary": 585}   # a team ask above this loses to a dealer
NEAR_GAP = 0.15                                   # ask above bid by at most 15 % (or 2 P): worth a nudge
EVERY_TICKS = 5
ANNOUNCE_EVERY = 20                               # game limit: one announcement per venue per 20 ticks
REPEAT_AFTER = 60                                 # the same pair is not messaged again before this many ticks
THREADS_PER_WINDOW, WINDOW = 4, 10
MAX_TEXT = 240                                    # the game cuts a venue announcement at 240 characters
HELPER_TIMEOUT_S = 2.0                            # the plaza's helpers get this long, then the pass goes on without them
HELPER_PAUSE_S = 120.0                            # and are left alone this long after a miss


def rastro_fee(price: float) -> float:
    return round(price * RASTRO_FEE_BPS / 10000 + RASTRO_FEE_FLAT, 1)


def _rarities(record: Path | None = None) -> dict[str, str]:
    try:
        if record is None:
            from bazaar import config
            record = config.DATA / "record"
        doc = json.loads((Path(record) / "latest" / "catalog.json").read_text())
        doc = doc.get("data", doc) if isinstance(doc, dict) else {}
        return {c["id"]: c.get("rarity") for s in doc.get("sets") or [] for c in s.get("cards") or [] if c.get("id")}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _is_card(ref: str) -> bool:
    return len(ref) >= 6 and ref[3] == "-" and ref[:3].isalpha() and ref[4:].isdigit()


def find_pairs(report: dict, rarity_of: dict[str, str] | None = None, us: str = US, venue: str = VENUE,
               exclude: tuple[str, ...] = ()) -> list[dict]:
    """Seller/buyer pairs among rival teams, best first. Each pair: kind (cross | near | wanted | swap),
    seller, buyer, ref, price, ask, bid, offers, saves, score, why."""
    rarity_of = rarity_of or {}
    rivals = {t: r for t, r in (report.get("rivals") or {}).items() if t != us and t not in exclude}
    pairs: list[dict] = []
    for b, rb in rivals.items():
        hunting = rb.get("hunting") or {}
        by_set: dict[str, int] = {}
        for ref in hunting:
            if _is_card(ref):
                by_set[ref[:3]] = by_set.get(ref[:3], 0) + 1
        for ref, h in hunting.items():
            if not _is_card(ref):
                continue
            bid = float(h.get("bid") or 0)
            rarity = rarity_of.get(ref)
            floor = FLOOR.get(rarity or "", 0)
            maybe_last = by_set.get(ref[:3]) == 1 and ref[:3] in (rb.get("set_focus") or []) and int(ref[4:]) <= 10
            for a, ra in rivals.items():
                if a == b:
                    continue
                s = (ra.get("selling") or {}).get(ref)
                if not s or not s.get("ask"):
                    continue
                ask = float(s["ask"])
                if s.get("venue") == venue and h.get("venue") == venue:
                    continue                                   # both already in our book: the broker pairs them
                if bid >= ask:
                    kind, price = "cross", round((bid + ask) / 2)
                elif bid > 0 and ask - bid <= max(2.0, NEAR_GAP * ask):
                    kind, price = "near", round((bid + ask) / 2)
                elif bid == 0 and h.get("dealer_threads") and ask <= DEALER_LIST.get(rarity or "", 0):
                    kind, price = "wanted", round(ask)         # hunting it at a dealer: the team ask beats the list
                else:
                    continue
                if price < floor:
                    continue                                   # a giveaway destroys value: never push it
                saves = rastro_fee(price)
                score = {"cross": 3.0, "near": 1.5, "wanted": 1.0}[kind]
                score += 3.0 if maybe_last else 0.0
                score += {"rare": 1.5, "epic": 2.5, "legendary": 3.0}.get(rarity or "", 0.0)
                score += min(2.0, saves / 5)
                why = (f"{b} bids {bid:.0f}" if bid else f"{b} asks dealers for it") + f", {a} asks {ask:.0f}"
                pairs.append({"kind": kind, "seller": a, "buyer": b, "ref": ref, "rarity": rarity,
                              "price": int(price), "ask": ask, "bid": bid, "ask_offer": s.get("offer"),
                              "ask_venue": s.get("venue"), "bid_offer": h.get("offer"), "bid_venue": h.get("venue"),
                              "saves": saves, "maybe_last": bool(maybe_last), "score": round(score, 2), "why": why})
    # mutual swaps: A sells X and hunts Y; B sells Y and hunts X -> card for card, no cash, no fee
    seen = set()
    for a, ra in rivals.items():
        for b, rb in rivals.items():
            if a >= b:
                continue
            for x in (ra.get("selling") or {}):
                if not _is_card(x) or x not in (rb.get("hunting") or {}):
                    continue
                for y in (rb.get("selling") or {}):
                    if not _is_card(y) or y == x or y not in (ra.get("hunting") or {}):
                        continue
                    if rarity_of.get(x) != rarity_of.get(y) or (a, b, x, y) in seen:
                        continue                               # same rarity only: an even swap, both gain
                    seen.add((a, b, x, y))
                    r = rarity_of.get(x)
                    pairs.append({"kind": "swap", "seller": a, "buyer": b, "ref": x, "ref_back": y, "rarity": r,
                                  "price": 0, "saves": rastro_fee(float((ra["selling"][x] or {}).get("ask") or 0)),
                                  "maybe_last": False,
                                  "score": 4.0 + {"rare": 1.5, "epic": 2.5}.get(r or "", 0.0),
                                  "why": f"{a} has {x} and wants {y}; {b} has {y} and wants {x}"})
    pairs.sort(key=lambda p: (-p["score"], p["ref"], p["seller"], p["buyer"]))
    best: dict[tuple, dict] = {}
    for p in pairs:                                            # one proposal per (buyer, card): the best seller
        best.setdefault((p["buyer"], p["ref"], p["kind"] == "swap"), p)
    return list(best.values())


def pair_key(p: dict) -> str:
    if p["kind"] == "relist":
        return f"relist:{p['side']}:{p['seller'] or p['buyer']}:{p['ref']}"
    return f"{p['kind'] == 'swap' and 'swap' or 'sale'}:{p['seller']}>{p['buyer']}:{p['ref']}"


BIG_RARITIES = ("rare", "epic", "legendary")


def big_tickets(report: dict, rarity_of: dict[str, str] | None = None, us: str = US, venue: str = VENUE,
                exclude: tuple[str, ...] = ()) -> list[dict]:
    """Rare-or-better public asks and bids of rival teams that sit on a fee venue (El Rastro: 5 % + 1 P to the
    taker). These are the trades that create the most value, and the ones that settled on a fee venue all
    Saturday night (RET-11 at 216, SAL-11 at 207, MAL-11 at 195). One line each: move it to our venue."""
    rarity_of = rarity_of or {}
    out: list[dict] = []
    for t, r in (report.get("rivals") or {}).items():
        if t == us or t in exclude:
            continue
        for side, book, field in (("ask", r.get("selling") or {}, "ask"), ("bid", r.get("hunting") or {}, "bid")):
            for ref, o in book.items():
                if not _is_card(ref) or rarity_of.get(ref) not in BIG_RARITIES:
                    continue
                price = float((o or {}).get(field) or 0)
                if price <= 0 or (o or {}).get("venue") != "rastro" or (o or {}).get("to"):
                    continue                                   # only public offers on the house market
                rarity = rarity_of[ref]
                if side == "ask" and price < FLOOR.get(rarity, 0):
                    continue                                   # a giveaway destroys value: never push it
                if side == "bid" and price < FLOOR.get(rarity, 0):
                    continue                                   # a bid nobody should take: not worth a line
                saves = rastro_fee(price)
                score = 1.0 + {"rare": 1.5, "epic": 2.5, "legendary": 3.0}[rarity] + min(2.0, saves / 5)
                out.append({"kind": "relist", "side": side, "seller": t if side == "ask" else None,
                            "buyer": t if side == "bid" else None, "ref": ref, "rarity": rarity,
                            "price": int(round(price)), "ask": price if side == "ask" else 0.0,
                            "bid": price if side == "bid" else 0.0, "offer": (o or {}).get("offer"),
                            "saves": saves, "maybe_last": False, "score": round(score, 2),
                            "why": f"{t} {'asks' if side == 'ask' else 'bids'} {price:.0f} on El Rastro"})
    out.sort(key=lambda p: (-p["score"], p["ref"], p["seller"] or p["buyer"]))
    return out


def top_rivals(report: dict, n: int = 2, us: str = US) -> tuple[str, ...]:
    """The n best-placed rivals: we do not hand them page cards through our own venue."""
    rows = [(float(r.get("score") or 0), t) for t, r in (report.get("rivals") or {}).items() if t != us]
    return tuple(t for _, t in sorted(rows, reverse=True)[:n])


def mix(pairs: list[dict], tickets: list[dict]) -> list[dict]:
    """The best big ticket, then the best two-team pair, then the next ticket, then the rest by score: an
    announcement always carries a named pair when there is one, and the high-value line leads."""
    head = tickets[:1] + pairs[:1] + tickets[1:2]
    rest = sorted(pairs[1:] + tickets[2:], key=lambda p: -p["score"])
    return head + rest


def one_per_card(pairs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for p in pairs:
        if p["ref"] not in seen:
            seen.add(p["ref"])
            out.append(p)
    return out


def _bid_call(ref: str, price: int, venue: str, to: str | None = None) -> str:
    """The game's own call for a bid on our venue, ready for an agent to send with its team key."""
    body = {"venue": venue, "give": {"cash": int(price)}, "want": {"cards": [ref]}}
    if to:
        body["to"] = to
    return "POST /api/offers " + json.dumps(body, separators=(",", ":"))


def _ask_call(ref: str, price: int, venue: str, to: str | None = None) -> str:
    body = {"venue": venue, "give": {"assets": ["<your " + ref + " asset id>"]}, "want": {"cash": int(price)}}
    if to:
        body["to"] = to
    return "POST /api/offers " + json.dumps(body, separators=(",", ":"))


ACCEPT = "POST /api/offers/<id>/accept"


def announcement(pairs: list[dict], venue: str = VENUE, limit: int = 3, max_len: int = MAX_TEXT,
                 page: str | None = None) -> str | None:
    """One public line per card, with who, what, at which price and the exact call. The recipe is the one that
    settled every team-venue deal on Saturday: one side posts the offer on a 0-fee venue and the other accepts
    it. An agent that reads the line can run it as it is, with its own key; nothing to connect."""
    lines = []
    for p in one_per_card(pairs)[:limit]:
        if p["kind"] == "swap":
            lines.append(f"{p['ref']} <> {p['ref_back']}: {p['seller']} and {p['buyer']} each hold what the other "
                         f"wants. {p['seller']}: post give {p['ref']} want {p['ref_back']} on {venue} to "
                         f"{p['buyer']}; {p['buyer']}: accept it. Card for card, no cash, no fee.")
        elif p["kind"] == "relist" and p["side"] == "ask":
            lines.append(f"{p['ref']} ({p['rarity']}): {p['seller']} asks {p['price']} on El Rastro (buyer pays "
                         f"{p['saves']:.0f} P fee). {p['seller']}: {_ask_call(p['ref'], p['price'], venue)} ; "
                         f"buyers: {ACCEPT}, pay 0 fee.")
        elif p["kind"] == "relist":
            lines.append(f"{p['ref']} ({p['rarity']}): {p['buyer']} bids {p['price']} on El Rastro (seller loses "
                         f"{p['saves']:.0f} P fee). {p['buyer']}: {_bid_call(p['ref'], p['price'], venue)} ; "
                         f"holders: {ACCEPT}, keep the full {p['price']}.")
        elif p["kind"] == "wanted":
            lines.append(f"{p['ref']}: {p['buyer']} wants it, {p['seller']} sells it at "
                         f"{p['ask']:.0f}. {p['seller']}: {_ask_call(p['ref'], p['price'], venue, p['buyer'])} ; "
                         f"{p['buyer']}: {ACCEPT}. 0 fee.")
        else:
            lines.append(f"{p['ref']}: {p['buyer']} bids {p['bid']:.0f}, {p['seller']} asks {p['ask']:.0f}. "
                         f"{p['seller']}: {_ask_call(p['ref'], p['price'], venue, p['buyer'])} ; {p['buyer']}: "
                         f"{ACCEPT}. Saves {p['saves']:.0f} P of Rastro fee.")
    if not lines:
        return None
    # The game keeps 240 characters: a short head, then whole lines while they fit (the first one always goes,
    # with its call complete), then the plaza link only when there is room left for it.
    head = f"{venue} 0% fee, no setup. "
    tail = f" More: {page}/board" if page else ""   # the plaza (bazaar.plaza)
    text = head + lines[0]
    for line in lines[1:]:
        if len(text) + 3 + len(line) > max_len:
            break
        text += " | " + line
    text = text[:max_len]
    return text + tail if len(text) + len(tail) <= max_len else text


def thread_texts(p: dict, venue: str = VENUE) -> dict[str, str]:
    """A short message for each side of a pair. Not a trade request from us: we are not a party."""
    if p["kind"] == "swap":
        t = (f"Matchmaker note from {venue}, not a trade request: {{other}} holds {{get}} and wants your {{give}}. "
             f"Post give {{give}} want {{get}} on {venue} addressed to {{other}}: card for card, no cash, 0 fee.")
        return {p["seller"]: t.format(other=p["buyer"], get=p["ref_back"], give=p["ref"]),
                p["buyer"]: t.format(other=p["seller"], get=p["ref"], give=p["ref_back"])}
    if p["kind"] == "relist":
        team = p["seller"] or p["buyer"]
        what = "ask" if p["side"] == "ask" else "bid"
        return {team: (f"Matchmaker note from {venue}, not a trade request: your {what} of {p['price']} for "
                       f"{p['ref']} sits on El Rastro, where the taker pays {p['saves']:.0f} P of fee. Post it on "
                       f"{venue} too: 0 fee, so the other side keeps or saves that and takes it sooner.")}
    return {
        p["seller"]: (f"Matchmaker note from {venue}, not a trade request: {p['buyer']} wants {p['ref']}"
                      + (f" (bids {p['bid']:.0f})" if p["bid"] else "")
                      + f". Post it on {venue} addressed to {p['buyer']} at {p['price']}: 0 fee, they accept "
                        f"it and it settles the next tick."),
        p["buyer"]: (f"Matchmaker note from {venue}, not a trade request: {p['seller']} sells {p['ref']} "
                     f"(asks {p['ask']:.0f}). Ask them to post it on {venue} addressed to you at {p['price']}, "
                     f"or bid {p['price']} there: 0 fee, you save {p['saves']:.0f} P of Rastro fee."),
    }


class MatchMaker:
    """Stateful runner. `announce(text)` and `message(team, text)` are injected (None = cannot)."""

    def __init__(self, state_file: Path, report_fn: Callable[[], dict], control_fn: Callable[[], dict],
                 announce: Callable[[str], Any] | None = None, message: Callable[[str, str], Any] | None = None,
                 rarity_fn: Callable[[], dict] = _rarities, venue: str = VENUE, us: str = US,
                 page_fn: Callable[[], str | None] | None = None,
                 declared_fn: Callable[[], list[dict]] | None = None):
        self.state_file, self.report_fn, self.control_fn = Path(state_file), report_fn, control_fn
        self.page_fn, self.declared_fn = page_fn, declared_fn      # the plaza: its address, and what agents declared
        self._announce, self._message, self.rarity_fn = announce, message, rarity_fn
        self.venue, self.us = venue, us
        self.state: dict = {"announced_tick": None, "sent": {}, "threads": [], "pairs": [], "log": []}
        self._busy: dict[str, threading.Thread] = {}     # helper name -> a call that never came back
        self._pause: dict[str, float] = {}               # helper name -> not before this time
        try:
            d = json.loads(self.state_file.read_text())
            if isinstance(d, dict):
                self.state.update(d)
        except (OSError, ValueError):
            pass

    # ---- switches
    def enabled(self) -> bool:
        return str((self.control_fn() or {}).get("matchmaker", "on")).lower() not in ("off", "false", "0")

    def threads_on(self) -> bool:
        return bool((self.control_fn() or {}).get("matchmaker_threads", False))

    def _save(self) -> None:
        self.state["log"] = self.state.get("log", [])[-60:]
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False))
        tmp.replace(self.state_file)

    def _log(self, tick: int, what: str, **kw) -> None:
        self.state.setdefault("log", []).append({"tick": tick, "t": round(time.time(), 1), "what": what, **kw})

    def _helper(self, tick: int, name: str, fn: Callable[[], Any] | None, default: Any) -> Any:
        """Call a helper that lives in another package (the plaza) without trusting it: in its own thread,
        with a deadline, and left alone for a while after it fails or is late. The broker's tick loop also
        plays the Market Test and the supervisor restarts a broker that stops writing its heartbeat, so a
        slow or broken plaza must cost this pass its extras and nothing more."""
        if fn is None:
            return default
        timeout = HELPER_TIMEOUT_S
        old = self._busy.get(name)
        if (old is not None and old.is_alive()) or time.time() < self._pause.get(name, 0.0):
            return default
        box: dict = {}

        def run() -> None:
            try:
                box["value"] = fn()
            except Exception as e:  # noqa: BLE001
                box["error"] = f"{type(e).__name__}: {e}"

        t = threading.Thread(target=run, daemon=True, name=f"matchmaker-{name}")
        t.start()
        t.join(timeout)
        if t.is_alive() or "error" in box:
            if t.is_alive():
                self._busy[name] = t
            self._pause[name] = time.time() + HELPER_PAUSE_S
            self._log(tick, "helper_failed", helper=name,
                      error=box.get("error") or f"no answer in {timeout:.1f} s")
            return default
        self._busy.pop(name, None)
        return box.get("value", default)

    def _fresh(self, tick: int, key: str) -> bool:
        last = (self.state.get("sent") or {}).get(key)
        return last is None or tick - int(last) >= REPEAT_AFTER

    @staticmethod
    def _deals(report: dict, p: dict) -> int:
        """How many times the buyer has bought this card from this seller so far (the public feed)."""
        got = ((report.get("rivals") or {}).get(p["buyer"]) or {}).get("bought") or []
        return sum(1 for d in got if d.get("ref") == p["ref"] and d.get("from") == p["seller"])

    def _results(self, tick: int, report: dict) -> None:
        """Mark proposals whose buyer bought that card from that seller after we proposed it."""
        for p in self.state.get("pairs", []):
            if not p.get("result") and self._deals(report, p) > int(p.get("base") or 0):
                p["result"] = {"traded": True, "seen_tick": tick}

    def step(self, tick: int, last_venue_announce: int | None = None) -> dict:
        """One pass. Returns what it did: {"pairs": n, "announced": bool, "messages": n, "skipped": why}."""
        if not self.enabled():
            return {"skipped": "control matchmaker=off"}
        report = self.report_fn() or {}
        self._results(tick, report)                            # before the list is rebuilt
        closed = [p for p in self.state.get("pairs", []) if p.get("result")]
        ctl = self.control_fn() or {}
        # Every team is announced: the market vetoes nobody. `blocked_teams` is our own bot's rule for its own
        # trades, not the venue's; only an explicit `matchmaker_exclude` list leaves a team out.
        exclude = ctl.get("matchmaker_exclude")
        exclude = tuple(exclude) if isinstance(exclude, list) else ()
        rar = self.rarity_fn()
        pairs = find_pairs(report, rar, us=self.us, venue=self.venue, exclude=exclude)
        pairs = mix(pairs, big_tickets(report, rar, us=self.us, venue=self.venue, exclude=exclude))
        try:                                                   # pairs both agents declared on the plaza go first
            declared = [p for p in (self._helper(tick, "declared", self.declared_fn, []) or [])
                        if p.get("seller") not in exclude and p.get("buyer") not in exclude]
        except Exception:  # noqa: BLE001 - the plaza is optional
            declared = []
        seen_keys = {pair_key(p) for p in declared}
        pairs = declared + [p for p in pairs if pair_key(p) not in seen_keys]
        done = {"pairs": len(pairs), "announced": False, "messages": 0}
        old = {pair_key(p): p for p in self.state.get("pairs", [])}
        kept = []
        for p in pairs[:12]:
            k = pair_key(p)
            o = old.get(k) or {}
            kept.append({**p, "key": k, "tick": o.get("tick", tick), "result": o.get("result"),
                         "base": o["base"] if "base" in o else self._deals(report, p)})
        have = {p["key"] for p in kept}
        self.state["pairs"] = kept + [p for p in closed if p["key"] not in have][-8:]
        self.state["tick"] = tick
        self.state["excluded"] = list(exclude)

        ann_at = max([x for x in (self.state.get("announced_tick"), last_venue_announce) if x is not None], default=None)
        new = [p for p in pairs if self._fresh(tick, "ann:" + pair_key(p))] or pairs
        page = self._helper(tick, "page", self.page_fn, None)
        page = page if isinstance(page, str) and page.startswith("http") else None
        text = announcement(new, self.venue, page=page)
        if text and self._announce and (ann_at is None or tick - ann_at >= ANNOUNCE_EVERY):
            try:
                self._announce(text)
                self.state["announced_tick"] = tick
                self.state["last_text"] = text
                for p in one_per_card(new)[:3]:
                    self.state.setdefault("sent", {})["ann:" + pair_key(p)] = tick
                done["announced"] = True
                self._log(tick, "announce", text=text[:300])
            except Exception as e:  # noqa: BLE001 - the venue limit or the network: try on a later pass
                self.state["announced_tick"] = tick if "rate" in str(e).lower() or "limit" in str(e).lower() else ann_at
                self._log(tick, "announce_failed", error=str(e)[:160])

        if self._message and self.threads_on():
            recent = [t for t in self.state.get("threads", []) if tick - t < WINDOW]
            budget = THREADS_PER_WINDOW - len(recent)
            for p in pairs:
                if budget < 2:
                    break
                k = "msg:" + pair_key(p)
                if not self._fresh(tick, k):
                    continue
                sent = 0
                for team, txt in thread_texts(p, self.venue).items():
                    try:
                        self._message(team, txt)
                        sent += 1
                    except Exception as e:  # noqa: BLE001
                        self._log(tick, "message_failed", team=team, error=str(e)[:160])
                self.state.setdefault("sent", {})[k] = tick
                recent += [tick] * sent
                budget -= sent
                done["messages"] += sent
                if sent:
                    self._log(tick, "messages", pair=pair_key(p), n=sent)
            self.state["threads"] = recent
        self._save()
        return done


def summary(live_dir: Path | str | None = None) -> dict:
    """What the brain sees: the open proposals, the last announcement and what closed on our venue."""
    if live_dir is None:
        from bazaar import config
        live_dir = config.LIVE
    try:
        d = json.loads((Path(live_dir) / "matchmaker.json").read_text())
    except (OSError, ValueError):
        return {"active": False, "note": "no matchmaker state yet"}
    pairs = d.get("pairs") or []
    return {"active": True, "tick": d.get("tick"), "announced_tick": d.get("announced_tick"),
            "last_text": (d.get("last_text") or "")[:400],
            "proposals": [{k: p.get(k) for k in ("kind", "seller", "buyer", "ref", "ref_back", "price", "ask", "bid",
                                                 "maybe_last", "result") if p.get(k) is not None} for p in pairs[:8]],
            "traded_after_proposal": [p["key"] for p in pairs if (p.get("result") or {}).get("traded")],
            "note": "pairs of OTHER teams we invite to v07; control.matchmaker = off stops it"}
