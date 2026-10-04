"""Card needs: which cards WE need, which cards OTHER teams need, and the opportunities in between.

Pure read-only analysis of the recorder's files (bazaar/recorder/README.md):
  record/latest/{me,catalog,leaderboard,venues,dealers}.json, record/latest/books/<venue>.json,
  record/feed/*.jsonl (offer.listed / offer.cancelled / settlement / thread.opened).

Books hide the maker behind an anonymised id; the feed's `offer.listed` names the real team, so offers are
joined by offer id. Every number in the report is cited so the brain can reason on it.

    from bazaar.intel.needs import needs_report, summary_text
    rep = needs_report()                       # defaults: config.DATA / "record", config.LIVE
    text = summary_text(rep, max_chars=4000)   # for the brain prompt
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

FEED_TYPES = ('"offer.listed"', '"offer.cancelled"', '"settlement"', '"thread.opened"', '"pack.opened"')
HIGH_RARITIES = ("epic", "legendary")   # not page cards, but worth a lot to us: never ignore them
EXTRA_MIN_VALUE = 40.0              # a non-page card worth at least this to us is an opportunity when sold below it
RASTRO_FEE = (500, 1)               # bps, P per card, if venues.json lacks it
MIN_GAIN_P = 1.0                    # opportunities below this are noise
AVOID_HELD_FRAC = 0.5               # a set with less than half its page held...
AVOID_MAX_AFFINITY = 1.15           # ...and low affinity: buying its cards barely moves our score
FEED_MAX_LINES = 400_000


# ----------------------------------------------------------------------------- loading
def _load(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _feed_rows(record: Path):
    files = sorted((record / "feed").glob("*.jsonl"))
    n = 0
    for f in files:
        try:
            with f.open() as fh:
                for line in fh:
                    n += 1
                    if n > FEED_MAX_LINES:
                        return
                    if not any(t in line for t in FEED_TYPES):
                        continue
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
        except OSError:
            continue


def _refs(side: dict | None) -> list[str]:
    side = side or {}
    out = [a.get("ref") for a in side.get("assets") or [] if isinstance(a, dict) and a.get("ref")]
    out += [t.split(":", 1)[1] for t in side.get("types") or [] if isinstance(t, str) and t.startswith("card:")]
    return out


def _cash(side: dict | None) -> int:
    try:
        return int((side or {}).get("cash") or 0)
    except (TypeError, ValueError):
        return 0


def _kind(o: dict) -> str:
    """ask (card for cash), bid (cash for card), swap (card for card), other."""
    g, w = o.get("give") or {}, o.get("want") or {}
    gr, wr = _refs(g), _refs(w)
    if gr and not wr and _cash(w) > 0:
        return "ask"
    if wr and not gr and _cash(g) > 0:
        return "bid"
    if gr and wr:
        return "swap"
    return "other"


def _fee(venue: dict | None, price: float) -> float:
    bps, per = RASTRO_FEE if venue is None else (int(venue.get("fee_bps") or 0), int(venue.get("fee_per_card") or 0))
    return price * bps / 10_000 + per


# ----------------------------------------------------------------------------- values
class _CatalogValues:
    """Minimal fallback when dealers.values.Values can't be built: book x affinity x copy marginal."""
    MARG = [1.0, 0.35, 0.15, 0.05]

    def __init__(self, me: dict, catalog: dict):
        self.affinity = me.get("affinity") or {}
        self.cards = {}
        for s in catalog.get("sets") or []:
            for c in s.get("cards") or []:
                self.cards[c["id"]] = {**c, "set": s.get("id"), "released": s.get("released")}
        self.held: dict[str, list] = defaultdict(list)
        for a in me.get("assets") or []:
            if a.get("kind", "card") == "card" and a.get("ref"):
                self.held[a["ref"]].append(a)

    @staticmethod
    def set_of(ref):
        return str(ref).split("-")[0]

    def count(self, ref):
        return len(self.held.get(ref, []))

    def _m(self, i):
        return self.MARG[i] if i < len(self.MARG) else self.MARG[-1]

    def next_copy(self, ref):
        c = self.cards.get(ref) or {}
        return float(c.get("book") or 10) * self.affinity.get(self.set_of(ref), 1.0) * self._m(self.count(ref))

    def asset_value(self, aid):
        for ref, lst in self.held.items():
            if any(a.get("id") == aid for a in lst):
                c = self.cards.get(ref) or {}
                return float(c.get("book") or 10) * self.affinity.get(self.set_of(ref), 1.0) * self._m(self.count(ref) - 1)
        return 0.0


def _values(me: dict, catalog: dict, values=None):
    if values is not None:
        return values
    try:
        from bazaar.dealers.values import Values
        return Values(me, catalog)
    except Exception:  # noqa: BLE001 - fall back to the catalog formula
        return _CatalogValues(me, catalog)


def _avoid(s: dict | None) -> bool:
    """A set not worth building: less than half the page held and low affinity."""
    return bool(s) and s["held"] / max(1, s["page"]) < AVOID_HELD_FRAC and s["affinity"] <= AVOID_MAX_AFFINITY


def _spare_value(values, ref: str, assets: list[dict]) -> float:
    try:
        return float(values.asset_value(assets[-1]["id"]))
    except Exception:  # noqa: BLE001
        return 0.0


# ----------------------------------------------------------------------------- report
def needs_report(record_dir: Path | str | None = None, live_dir: Path | str | None = None, values=None) -> dict:
    if record_dir is None or live_dir is None:
        from bazaar import config
        record_dir = record_dir or config.DATA / "record"
        live_dir = live_dir or config.LIVE
    record = Path(record_dir)
    latest = record / "latest"
    me = _load(latest / "me.json", {}) or {}
    me = me.get("data", me) if isinstance(me, dict) else {}
    catalog = _load(latest / "catalog.json", {}) or {}
    catalog = catalog.get("data", catalog) if isinstance(catalog, dict) else {}
    lb = _load(latest / "leaderboard.json", {}) or {}
    lb = lb.get("data", lb) if isinstance(lb, dict) else {}
    venues_doc = _load(latest / "venues.json", {}) or {}
    venues = {v.get("venue"): v for v in (venues_doc.get("venues") or []) if isinstance(v, dict)}
    dealers_doc = _load(latest / "dealers.json", {}) or {}
    personas = [p for p in dealers_doc.get("personas") or [] if isinstance(p, dict)]
    us = me.get("id") or "t10"
    affinity = me.get("affinity") or {}
    vals = _values(me, catalog, values)

    # --- catalog: page cards per set ---
    sets: dict[str, dict] = {}
    for s in catalog.get("sets") or []:
        page = [c for c in s.get("cards") or [] if c.get("page", True) and not c.get("hidden")]
        sets[s.get("id")] = {"name": s.get("name"), "released": bool(s.get("released")),
                             "page": [c["id"] for c in page],
                             "rarity": {c["id"]: c.get("rarity") for c in s.get("cards") or []},
                             "names": {c["id"]: c.get("name") for c in s.get("cards") or []}}
    rarity_of = {r: k for s in sets.values() for r, k in s["rarity"].items()}
    name_of = {r: n for s in sets.values() for r, n in s["names"].items()}

    held: dict[str, list] = defaultdict(list)
    for a in me.get("assets") or []:
        if a.get("kind", "card") == "card" and a.get("ref"):
            held[a["ref"]].append(a)

    # --- feed: who made which offer, deals, dealer hunts ---
    offer_team: dict[int, str] = {}
    feed_offers: dict[int, dict] = {}
    bought: dict[str, list] = defaultdict(list)       # team -> [{ref, price, frm, venue, tick}]
    sold: dict[str, list] = defaultdict(list)
    dealer_hunts: dict[str, Counter] = defaultdict(Counter)
    watch: dict[str, dict] = {}                       # epics / legendaries seen in the feed
    moved_assets: set = set()                         # asset ids that changed hands (their old listings are dead)

    def _watch(ref, rarity=None):
        return watch.setdefault(ref, {"ref": ref, "rarity": rarity, "holder": None, "asks": [], "bids": [],
                                      "last_sale": None})

    for r in _feed_rows(record):
        t, p = r.get("type"), r.get("payload") or {}
        if t == "pack.opened":
            b = p.get("best") or {}
            if b.get("rarity") in HIGH_RARITIES and b.get("ref"):
                w = _watch(b["ref"], b.get("rarity"))
                w["holder"], w["source"] = p.get("team"), f"pack {p.get('pack')}"
        elif t == "offer.listed":
            o = p.get("offer") or {}
            if o.get("id") is not None:
                team = o.get("maker") or r.get("actor")
                offer_team[o["id"]] = team
                feed_offers[o["id"]] = {**o, "team": team, "venue": o.get("venue") or p.get("venue")}
                for a in (o.get("give") or {}).get("assets") or []:
                    if isinstance(a, dict) and a.get("rarity") in HIGH_RARITIES and a.get("ref"):
                        w = _watch(a["ref"], a.get("rarity"))
                        w["holder"] = team
                        w["asks"] = (w["asks"] + [{"price": _cash(o.get("want")), "tick": r.get("tick"), "to": o.get("to"),
                                                   "venue": o.get("venue") or p.get("venue"), "offer": o["id"]}])[-5:]
                for ty in (o.get("want") or {}).get("types") or []:
                    ref = str(ty)[5:] if str(ty).startswith("card:") else None
                    if ref and ref[-3:] in ("-11", "-12"):
                        w = _watch(ref)
                        w["bids"] = (w["bids"] + [{"team": team, "cash": _cash(o.get("give")), "tick": r.get("tick"),
                                                   "gives": _refs(o.get("give"))}])[-6:]
        elif t == "offer.cancelled":
            oid = (p.get("offer") or {}).get("id") if isinstance(p.get("offer"), dict) else p.get("offer")
            if oid in feed_offers:
                feed_offers[oid]["status"] = "cancelled"
        elif t == "settlement":
            price = p.get("price") or 0
            cards = [i for i in p.get("items") or [] if i.get("kind") == "card"]
            for i in cards:
                moved_assets.add(i.get("id"))
                if i.get("rarity") in HIGH_RARITIES and i.get("ref"):
                    w = _watch(i["ref"], i.get("rarity"))
                    w["holder"] = i.get("to")
                    w["last_sale"] = {"price": price, "frm": i.get("frm"), "to": i.get("to"), "tick": p.get("tick")}
                row = {"ref": i.get("ref"), "price": round(price / max(1, len(cards)), 1), "frm": i.get("frm"),
                       "to": i.get("to"), "venue": p.get("venue"), "dealer": p.get("persona"), "tick": p.get("tick")}
                if i.get("to"):
                    bought[i["to"]].append(row)
                if i.get("frm"):
                    sold[i["frm"]].append(row)
        elif t == "thread.opened":
            buy = ((p.get("topic") or {}).get("buy") or {})
            ref = buy.get("card")
            if ref and p.get("team"):
                dealer_hunts[p["team"]][ref] += 1

    # --- current books, makers resolved through the feed ---
    book_offers: list[dict] = []
    for f in sorted((latest / "books").glob("*.json")):
        b = _load(f, {}) or {}
        for o in b.get("offers") or []:
            if not isinstance(o, dict) or (o.get("status") or "open") != "open":
                continue
            team = offer_team.get(o.get("id")) or o.get("maker")
            book_offers.append({**o, "team": team, "venue": o.get("venue") or b.get("venue"), "kind": _kind(o)})
    # listings only the feed shows yet (books are snapshots): still open, not expired, the card has not moved since
    clock = _load(latest / "clock.json", {}) or {}
    clock = clock.get("data", clock) if isinstance(clock, dict) else {}
    now_tick = clock.get("tick") or lb.get("tick") or 0
    in_books = {o.get("id") for o in book_offers}
    for oid, o in feed_offers.items():
        if oid in in_books or (o.get("status") or "open") != "open" or o.get("thread") is not None:
            continue
        if o.get("expires_tick") is None or int(o["expires_tick"]) <= int(now_tick or 0):
            continue
        if any(isinstance(a, dict) and a.get("id") in moved_assets for a in (o.get("give") or {}).get("assets") or []):
            continue
        if o.get("to") not in (None, us):
            continue
        book_offers.append({**o, "kind": _kind(o)})
    # addressed offers to us (not always in books)
    mo = _load(latest / "my_offers.json", {}) or {}
    mo = mo.get("data", mo) if isinstance(mo, dict) else {}
    seen_ids = {o.get("id") for o in book_offers}
    for o in (mo.get("offers") if isinstance(mo, dict) else mo) or []:
        if isinstance(o, dict) and o.get("id") not in seen_ids and (o.get("status") or "open") == "open":
            book_offers.append({**o, "team": o.get("maker"), "kind": _kind(o)})

    def is_us(team):
        return team == us

    # --- ours ---
    ours_sets, missing_all, spares = {}, {}, []
    for sid, s in sets.items():
        if not s["released"] or not s["page"]:
            continue
        have = [r for r in s["page"] if held.get(r)]
        miss = [r for r in s["page"] if not held.get(r)]
        miss_rows = []
        for r in miss:
            v = round(float(vals.next_copy(r)), 1)
            row = {"ref": r, "name": name_of.get(r), "rarity": rarity_of.get(r), "value": v}
            miss_rows.append(row)
            missing_all[r] = row
        ours_sets[sid] = {"name": s["name"], "affinity": affinity.get(sid, 1.0), "held": len(have),
                          "page": len(s["page"]), "missing": miss_rows, "completes_page": len(miss) <= 2 and bool(miss)}
    # control.protected: a ref keeps every copy, an asset id keeps that copy. The spare we show is always a copy
    # the rails let go (never the protected one), so sell orders built on it are not vetoed.
    from bazaar.core.spares import free_copies, protected_set
    control = _load(Path(live_dir) / "control.json", {}) or {}
    protected = protected_set(control if isinstance(control, dict) else {})
    for ref, lst in held.items():
        if len(lst) > 1:
            free = free_copies(lst, protected, ref)
            if not free:
                continue                                  # every spare copy is protected: nothing to sell
            spares.append({"ref": ref, "copies": len(lst), "spare_value": round(_spare_value(vals, ref, lst), 1),
                           "asset": free[-1].get("id")})
        elif _avoid(ours_sets.get(vals.set_of(ref))):
            # a set we don't build (low affinity, far from a page): our single copy is tradeable too
            if not free_copies(lst, protected, ref, keep=0):
                continue
            spares.append({"ref": ref, "copies": 1, "spare_value": round(_spare_value(vals, ref, lst), 1),
                           "asset": lst[-1].get("id"), "low_affinity": True})

    # availability of missing cards
    availability: dict[str, list] = defaultdict(list)
    for o in book_offers:
        if is_us(o.get("team")) or o["kind"] != "ask":
            continue
        for r in _refs(o.get("give")):
            price = _cash(o.get("want"))
            availability[r].append({"venue": o.get("venue"), "price": price, "team": o.get("team"), "offer": o.get("id"),
                                    "cost": round(price + _fee(venues.get(o.get("venue")), price), 1)})
    for p in personas:
        if not p.get("enabled", True) or p.get("status") not in (None, "active"):
            continue
        open_ = p.get("open_to_all") or p.get("id") in (me.get("unlocked") or [])
        for e in (p.get("menu") or {}).get("sells") or []:
            rar = e.get("rarity")
            if not rar:
                continue
            for ref, row in missing_all.items():
                if row["rarity"] == rar:
                    availability[ref].append({"dealer": p.get("id"), "list_price": e.get("list_price"),
                                              "open_to_us": bool(open_)})
    for ref, row in missing_all.items():
        av = availability.get(ref, [])
        costs = [a["cost"] for a in av if "cost" in a] + [a["list_price"] for a in av if a.get("list_price") and a.get("open_to_us")]
        row["available"] = sorted(av, key=lambda a: a.get("cost", a.get("list_price") or 9e9))[:4]
        row["best_price"] = min(costs) if costs else None

    # --- rivals ---
    rivals: dict[str, dict] = {}
    teams = {t.get("team"): t for t in lb.get("teams") or [] if isinstance(t, dict)}

    def rv(team):
        if team not in rivals:
            t = teams.get(team) or {}
            rivals[team] = {"team": team, "name": t.get("name"), "score": t.get("score"),
                            "negotiating": t.get("negotiating"), "market": t.get("market"),
                            "album": f"{t.get('album_filled')}/{t.get('album_slots')}" if t else None,
                            "pages": t.get("pages_complete"), "hunting": {}, "selling": {}, "bought": [],
                            "set_focus": []}
        return rivals[team]

    for o in book_offers:
        team = o.get("team")
        if not team or is_us(team) or not str(team).startswith("t"):
            continue
        k = o["kind"]
        if k == "bid":
            for r in _refs(o.get("want")):
                h = rv(team)["hunting"].setdefault(r, {"bid": 0, "venue": None, "offer": None})
                if _cash(o.get("give")) > h["bid"]:
                    h.update(bid=_cash(o.get("give")), venue=o.get("venue"), offer=o.get("id"), to=o.get("to"))
        elif k == "swap":
            for r in _refs(o.get("want")):
                rv(team)["hunting"].setdefault(r, {"bid": 0, "venue": o.get("venue"), "offer": o.get("id"),
                                                   "swap_for": _refs(o.get("give"))})
        elif k == "ask":
            for r in _refs(o.get("give")):
                s = rv(team)["selling"].setdefault(r, {"ask": 10 ** 9})
                if _cash(o.get("want")) < s["ask"]:
                    s.update(ask=_cash(o.get("want")), venue=o.get("venue"), offer=o.get("id"))
    for team, hunts in dealer_hunts.items():
        if is_us(team):
            continue
        for r, n in hunts.items():
            rv(team)["hunting"].setdefault(r, {"bid": 0, "dealer_threads": n})
    for team, rows in bought.items():
        if is_us(team) or not str(team).startswith("t"):
            continue
        rv(team)["bought"] = [{"ref": x["ref"], "price": x["price"], "from": x.get("dealer") or x.get("frm")}
                              for x in rows[-12:]]
    for team, r in rivals.items():
        c = Counter(vals.set_of(x["ref"]) for x in bought.get(team, []) if x.get("ref"))
        c.update(vals.set_of(ref) for ref in r["hunting"])
        r["set_focus"] = [s for s, _ in c.most_common(3)]

    # --- opportunities ---
    opps: list[dict] = []
    spare_by_ref = {s["ref"]: s for s in spares}
    # (a) our spares that rivals want
    for team, r in rivals.items():
        for ref, h in r["hunting"].items():
            if ref in spare_by_ref and h.get("bid"):
                sv = spare_by_ref[ref]["spare_value"]
                fee = _fee(venues.get(h.get("venue")), h["bid"]) if h.get("venue") else 0
                gain = round(h["bid"] - fee - sv, 1)
                if gain >= MIN_GAIN_P:
                    opps.append({"kind": "sell_to_bid", "ref": ref, "team": team, "offer": h.get("offer"),
                                 "venue": h.get("venue"), "their_bid": h["bid"], "fee": round(fee, 1),
                                 "our_value": sv, "gain": gain, "addressed_to_us": h.get("to") == us,
                                 "why": f"{team} bids {h['bid']} P for {ref}; our spare is worth {sv} P to us"})
            elif ref in spare_by_ref and (h.get("dealer_threads") or h.get("swap_for")):
                opps.append({"kind": "rival_wants_our_spare", "ref": ref, "team": team, "gain": 0.0,
                             "our_value": spare_by_ref[ref]["spare_value"],
                             "why": f"{team} hunts {ref} (dealer threads/swap) and we hold a spare: list it for them"})
    # (b) cards we need sold below our value
    for ref, row in missing_all.items():
        for a in row.get("available") or []:
            if "cost" in a and row["value"] - a["cost"] >= MIN_GAIN_P:
                opps.append({"kind": "buy_below_value", "ref": ref, "team": a.get("team"), "offer": a.get("offer"),
                             "venue": a.get("venue"), "price": a["price"], "cost": a["cost"], "our_value": row["value"],
                             "gain": round(row["value"] - a["cost"], 1),
                             "why": f"{ref} asked at {a['price']} P (+fee = {a['cost']}) on {a.get('venue')}; worth {row['value']} P to us"})
    # (b2) cards outside the pages (epics, legendaries) or extra copies worth a lot to us, asked below that value
    cash_now = float(me.get("cash") or 0)
    for o in book_offers:
        if is_us(o.get("team")) or o["kind"] != "ask":
            continue
        price = _cash(o.get("want"))
        cost = round(price + _fee(venues.get(o.get("venue")), price), 1)
        for ref in _refs(o.get("give")):
            if ref in missing_all:
                continue
            try:
                v = round(float(vals.next_copy(ref)), 1)
            except Exception:  # noqa: BLE001
                continue
            if v >= EXTRA_MIN_VALUE and v - cost >= MIN_GAIN_P:
                gap = round(max(0.0, cost - cash_now), 1)
                opps.append({"kind": "buy_below_value", "ref": ref, "team": o.get("team"), "offer": o.get("id"),
                             "venue": o.get("venue"), "price": price, "cost": cost, "our_value": v,
                             "gain": round(v - cost, 1), "non_page": True, "cash_gap": gap,
                             "why": f"{ref} ({rarity_of.get(ref) or 'card'}, not a page card) asked at {price} P "
                                    f"(+fee = {cost}) on {o.get('venue')}; worth {v} P to us"
                                    + (f"; we are {gap} P short: fund it" if gap else "")})
    # (c) swaps both sides gain: rival hunts our spare AND sells a card we're missing
    for team, r in rivals.items():
        want_ours = [ref for ref in r["hunting"] if ref in spare_by_ref]
        they_sell = [ref for ref in r["selling"] if ref in missing_all]
        for give in want_ours:
            for get in they_sell:
                gain = round(missing_all[get]["value"] - spare_by_ref[give]["spare_value"], 1)
                if gain >= MIN_GAIN_P:
                    opps.append({"kind": "swap", "team": team, "give": give, "get": get, "gain": gain,
                                 "why": f"{team} hunts {give} (our spare, {spare_by_ref[give]['spare_value']} P) and sells {get} "
                                        f"(worth {missing_all[get]['value']} P to us)"})
    # (d) competition for cards we need: one row per card, every rival hunting it, the highest bid first
    comp: dict[str, list] = defaultdict(list)
    for team, r in rivals.items():
        for ref, h in r["hunting"].items():
            if ref in missing_all and missing_all[ref]["value"] >= 20:
                comp[ref].append((h.get("bid") or 0, team))
    for ref, lst in comp.items():
        lst.sort(reverse=True)
        row, (bid, top) = missing_all[ref], lst[0]
        who = ", ".join(f"{t}" + (f"@{b}" if b else "") for b, t in lst[:5])
        opps.append({"kind": "competition", "ref": ref, "team": top, "teams": [t for _, t in lst], "their_bid": bid,
                     "our_value": row["value"], "best_price": row.get("best_price"), "gain": 0.0,
                     "why": f"{len(lst)} rival(s) hunt {ref} ({who}); worth {row['value']} P to us — "
                            + (f"cheapest source {row['best_price']} P: buy before them if cash allows"
                               if row.get("best_price") is not None and row["best_price"] < row["value"] else
                               f"outbid up to ~{math.floor(row['value'] * 0.95)} P or wait for a dealer")})
    # (e) avoid buying: low affinity, far from the page
    for sid, s in ours_sets.items():
        if _avoid(s):
            avg = round(sum(m["value"] for m in s["missing"]) / max(1, len(s["missing"])), 1)
            opps.append({"kind": "avoid_set", "set": sid, "gain": 0.0, "held": s["held"], "page": s["page"],
                         "affinity": s["affinity"],
                         "why": f"{sid}: {s['held']}/{s['page']} page cards held, affinity {s['affinity']}, "
                                f"avg missing card worth {avg} P to us — buying it barely moves our score"})
    order = {"sell_to_bid": 0, "buy_below_value": 1, "swap": 2, "avoid_set": 3, "competition": 4, "rival_wants_our_spare": 5}
    opps.sort(key=lambda o: (-(o.get("gain") or 0), order.get(o["kind"], 9), -(o.get("their_bid") or 0)))

    return {"us": us, "tick": lb.get("tick") or me.get("tick"), "cash": me.get("cash"), "affinity": affinity,
            "ours": {"sets": ours_sets, "spares": sorted(spares, key=lambda s: s["spare_value"]),
                     "page_completers": [m for s in ours_sets.values() if s["completes_page"] for m in s["missing"]]},
            "rivals": rivals, "opportunities": opps,
            "watch": sorted(({**w, "our_value": round(float(vals.next_copy(w["ref"])), 1)} for w in watch.values()),
                            key=lambda w: -w["our_value"])}


# ----------------------------------------------------------------------------- summary
def summary_text(report: dict, max_chars: int = 4000) -> str:
    L = []
    L.append(f"NEEDS · tick {report.get('tick')} · cash {report.get('cash')} P · affinity {report.get('affinity')}")
    for sid, s in (report.get("ours") or {}).get("sets", {}).items():
        miss = ", ".join(f"{m['ref']}({m['value']}P" + (f", best {m['best_price']}" if m.get('best_price') else "") + ")"
                         for m in s["missing"][:6])
        L.append(f"- {sid} {s['held']}/{s['page']} aff {s['affinity']}{' NEAR PAGE' if s['completes_page'] else ''}: missing {miss}")
    sp = (report.get("ours") or {}).get("spares") or []
    if sp:
        L.append("Spares: " + ", ".join(f"{s['ref']}x{s['copies']}({s['spare_value']}P)" for s in sp[:12]))
    L.append("OPPORTUNITIES (gain P, cited):")
    for o in (report.get("opportunities") or [])[:15]:
        L.append(f"- [{o['kind']}] gain {o.get('gain')}: {o['why']}" + (f" (offer #{o['offer']})" if o.get("offer") else ""))
    if report.get("watch"):
        L.append("WATCH (epics / legendaries seen): " + "; ".join(
            f"{w['ref']} worth {w['our_value']}P to us, holder {w.get('holder') or '?'}"
            + (f", last ask {w['asks'][-1]['price']}P" if w.get("asks") else "")
            + (f", sold at {w['last_sale']['price']}P to {w['last_sale']['to']}" if w.get("last_sale") else "")
            + (f", bids {[(b['team'], b['cash']) for b in w['bids'][-3:]]}" if w.get("bids") else "")
            for w in report["watch"][:6]))
    L.append("RIVALS:")
    riv = sorted((report.get("rivals") or {}).values(), key=lambda r: -(r.get("score") or 0))
    for r in riv[:10]:
        hunt = ", ".join(f"{k}" + (f"@{v['bid']}" if v.get("bid") else "") for k, v in list(r["hunting"].items())[:6])
        sell = ", ".join(f"{k}@{v['ask']}" for k, v in list(r["selling"].items())[:5])
        L.append(f"- {r['team']} score {r.get('score')} (neg {r.get('negotiating')}, mkt {r.get('market')}), album {r.get('album')}, "
                 f"pages {r.get('pages')}, focus {r.get('set_focus')}; hunts [{hunt}]; sells [{sell}]")
    out = "\n".join(L)
    return out if len(out) <= max_chars else out[: max_chars - 20] + "\n…(truncated)"
