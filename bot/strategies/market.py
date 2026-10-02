"""Trade with the other teams on the public venues (El Rastro first): sell our spares for cash, buy cards
that are worth clearly more to us than they cost, and swap spares into offers that pay more than the
spare is worth to us.

What scores is the private value we gain in trades with other teams: a card's value to us is its book
value times our set multiplier times the copy marginal (1st copy 1.0, 2nd 0.25, 3rd 0.1). A spare copy
is worth little to us, so selling it for even half its book is a clear gain; a card we lack in a set we
like is worth far more to us than the commons price everyone lists at.

Conservative by design:
  - one board read per venue per tick at most, one /api/me/value per tick at most (cached per copy count);
  - never accept our own team's offers (the board shows makers as pseudonyms, so "ours" means an id that
    /api/me/offers lists with our team as maker, plus every pseudonym seen on one of those);
  - a cash reserve is never spent (dealers and duels need cash);
  - the first copy of a card in a set we value at 1.0 or more is never sold or swapped away;
  - our open listings stay well below the team cap, since teammates list too.

The fee (5 % + 1 P per card on El Rastro) is paid by the accepting side: it costs us when we accept,
and the buyer pays it when someone accepts our listing.
"""

from __future__ import annotations

import math

from ..core import BazaarError, Ctx

# --- selling -----------------------------------------------------------------
MAX_OWN_LISTINGS = 10      # our listings at once (team cap is 30; leave room for teammates)
TEAM_HEADROOM = 8          # never push the team's open offers above max_offers - this
LISTINGS_PER_TICK = 4      # new listings per tick from this strategy (team-wide budget is 12)
REPRICES_PER_TICK = 2
LIST_EXPIRES = 30          # ticks
REPRICE_AFTER = 10         # ticks a listing may sit unsold before we lower it
REPRICE_STEP = 0.9         # without a cheaper rival, lower the ask by 10 % per reprice
SELL_MIN_MARGIN = 3        # P above our loss, at least
SELL_FLOOR_FRACTION = 0.4  # never ask less than this share of book
FIRST_COPY_MARKUP = 1.25   # a first copy (only in sets we value < 1.0) sells at >= 1.25x its value to us
MAX_ASK_FRACTION = 1.5     # never ask more than 1.5x book (nobody buys it and it blocks a slot)

# --- buying / swapping -------------------------------------------------------
BUY_MIN_GAIN = 1           # P of private value, at least (team: take every profitable trade, 2 Oct)
BUY_MIN_MARGIN = 0.0       # no share threshold: the best trade of each tick wins anyway
CASH_RESERVE = 10          # never let a trade take the bot's wallet below this
MAX_SPEND_SHARE = 0.9      # one trade may use most of the wallet: a LAV/MAL rare is worth 91-112 P to us
MAX_VENUE_BOARDS = 3       # boards read per tick
VENUES_REFRESH = 20        # ticks between /api/venues reads
PENDING_TIMEOUT = 4        # ticks to wait for an accepted trade to show up in /api/me


def _ceil(x: float) -> int:
    return int(math.ceil(x - 1e-9))


def _card_refs_of(side: dict) -> list[str] | None:
    """The card refs on one side of an offer (specific copies and "any copy of"), or None if the side
    holds something we do not price (packs, unknown types)."""
    refs = []
    for a in side.get("assets", []):
        if a.get("kind") != "card" or not a.get("ref"):
            return None
        refs.append(a["ref"])
    for t in side.get("types", []):
        if not isinstance(t, str) or not t.startswith("card:"):
            return None
        refs.append(t.split(":", 1)[1])
    return refs


class Strategy:
    name = "market"

    # ======================================================================== tick
    def tick(self, ctx: Ctx):
        mem = ctx.memory
        for k, d in (("listings", {}), ("trades", []), ("pending", {}), ("aliases", []), ("exact", {})):
            mem.setdefault(k, d)
        self.me_id = ctx.me.get("id")
        self.tick_no = ctx.budget.tick or ctx.clock.get("tick") or 0
        self.cash = ctx.cash  # the bot's own budget, never the team's money
        self.held_ids = {a["id"] for a in ctx.me.get("assets", [])}

        team_offers = [o for o in ctx.b.my_offers().get("offers", []) if o.get("maker") == self.me_id]
        self.team_offer_ids = {o["id"] for o in team_offers}
        self.team_listed_assets = {a["id"] for o in team_offers for a in o.get("give", {}).get("assets", [])}

        self.reconcile(ctx, team_offers)
        venues, boards = self.read_boards(ctx)
        ctx.shared["boards"] = boards  # for the intel snapshot (bot/intel.py)
        self.learn_aliases(ctx, boards)
        accepted = self.buy_or_swap(ctx, venues, boards)
        listed = self.sell(ctx, boards, team_offers)

        gain_total = round(sum(t.get("gain", 0) for t in mem["trades"] if t.get("status") == "done"), 2)
        ctx.journal.set(self.name, {
            "tick": self.tick_no,
            "cash": self.cash,
            "listings": [{"offer": k, **{x: v[x] for x in ("ref", "price", "floor", "loss")}}
                         for k, v in mem["listings"].items()],
            "pending": list(mem["pending"].keys()),
            "accepted_this_tick": accepted,
            "listed_this_tick": listed,
            "trades": len([t for t in mem["trades"] if t.get("status") == "done"]),
            "gain_total": gain_total,
            "last_trades": mem["trades"][-5:],
            "dry_run": ctx.dry_run,
        })

    # ======================================================================== bookkeeping
    def reconcile(self, ctx: Ctx, team_offers: list[dict]):
        """Close out listings that left the book (sold or expired) and accepts that settled."""
        mem = ctx.memory
        present = {o["id"] for o in team_offers}
        for oid, l in list(mem["listings"].items()):
            if int(oid) in present:
                continue
            del mem["listings"][oid]
            if l["asset"] in self.held_ids:
                ctx.journal.decide(self.name, "listing gone, card still ours", offer=int(oid), ref=l["ref"])
                continue
            trade = {"tick": self.tick_no, "kind": "sold", "offer": int(oid), "venue": l.get("venue"),
                     "gave": [l["ref"]], "got_cash": l["price"], "gain": round(l["price"] - l["loss"], 2),
                     "status": "done"}
            mem["trades"].append(trade)
            if ctx.wallet:
                ctx.wallet.record("earn", l["price"], why=f"sold {l['ref']} on {l.get('venue')}", ids_out=[l["asset"]])
            ctx.journal.decide(self.name, "sold", **trade)

        counts = {}
        for a in ctx.me.get("assets", []):
            counts[a.get("ref")] = counts.get(a.get("ref"), 0) + 1
        for oid, p in list(mem["pending"].items()):
            got_ids = [i for i in p.get("in_ids", []) if i in self.held_ids]
            gave_gone = bool(p.get("out_ids")) and not any(i in self.held_ids for i in p["out_ids"])
            refs_up = any(counts.get(r, 0) > p.get("counts_before", {}).get(r, 0) for r in p.get("in_refs", []))
            done = (p.get("in_ids") and got_ids) or (not p.get("in_ids") and p.get("in_refs") and refs_up) \
                or (not p.get("in_refs") and gave_gone)
            if done:
                del mem["pending"][oid]
                trade = {**p["trade"], "status": "done", "settled_tick": self.tick_no}
                mem["trades"].append(trade)
                if ctx.wallet:
                    t = p["trade"]
                    net = (t.get("paid", 0) or 0) + (t.get("fee", 0) or 0) - (t.get("got_cash", 0) or 0)
                    ctx.wallet.record("spend" if net >= 0 else "earn", abs(net), why=f"market trade {t.get('offer')}",
                                      ids_in=got_ids, ids_out=p.get("out_ids", []),
                                      claim=None if got_ids else ((p.get("in_refs") or [None])[0]))
                ctx.journal.decide(self.name, "trade settled", **trade)
            elif self.tick_no - p["tick"] > PENDING_TIMEOUT:
                del mem["pending"][oid]
                trade = {**p["trade"], "status": "unconfirmed"}
                mem["trades"].append(trade)
                ctx.journal.decide(self.name, "trade not seen settling", **trade)
        mem["trades"] = mem["trades"][-300:]

    def read_boards(self, ctx: Ctx):
        mem = ctx.memory
        vc = mem.get("venues")
        if not vc or self.tick_no - vc.get("tick", -999) >= VENUES_REFRESH or self.tick_no < vc.get("tick", 0):
            try:
                vs = ctx.b.venues().get("venues", [])
            except BazaarError as e:
                ctx.journal.error(self.name, e)
                vs = (vc or {}).get("list") or [{"venue": "rastro", "status": "open", "fee_bps": 500, "fee_per_card": 1}]
            vc = mem["venues"] = {"tick": self.tick_no, "list": [
                {k: v.get(k) for k in ("venue", "status", "fee_bps", "fee_per_card", "owner", "house", "trades")}
                for v in vs]}
        own = (ctx.me.get("venue") or {}).get("venue") if isinstance(ctx.me.get("venue"), dict) else ctx.me.get("venue")
        venues = {v["venue"]: v for v in vc["list"]
                  if v.get("status") == "open" and v["venue"] != own and v.get("owner") != self.me_id}
        # El Rastro first, then the busiest team venues; rotate the rest across ticks.
        order = sorted(venues, key=lambda k: (k != "rastro", -(venues[k].get("trades") or 0)))
        if len(order) > MAX_VENUE_BOARDS:
            rest = order[1:]
            start = self.tick_no % len(rest)
            order = [order[0]] + (rest[start:] + rest[:start])[:MAX_VENUE_BOARDS - 1]
        boards = {}
        for name in order[:MAX_VENUE_BOARDS]:
            try:
                boards[name] = ctx.b.board(name).get("offers", [])
            except BazaarError as e:
                ctx.journal.error(self.name, e)
        return venues, boards

    def learn_aliases(self, ctx: Ctx, boards: dict):
        """The board shows makers as pseudonyms; remember the ones that belong to our team."""
        aliases = set(ctx.memory["aliases"])
        for offers in boards.values():
            for o in offers:
                if o["id"] in self.team_offer_ids and o.get("maker"):
                    aliases.add(o["maker"])
        ctx.memory["aliases"] = sorted(aliases)
        self.aliases = aliases | {self.me_id}

    def is_ours(self, o: dict) -> bool:
        return o["id"] in self.team_offer_ids or o.get("maker") in self.aliases

    # ======================================================================== valuation
    def fee(self, venue: dict, cash: int, cards: int, book: float) -> int:
        bps = venue.get("fee_bps", 500) if venue.get("fee_bps") is not None else 500
        per = venue.get("fee_per_card", 1) if venue.get("fee_per_card") is not None else 1
        base = cash if cash > 0 else book  # a cashless swap: assume the % is taken on book (conservative)
        return _ceil(base * bps / 10000) + per * cards

    def card_value(self, ctx: Ctx, ref: str, copy_index: int) -> float:
        """Value to us of holding copy number `copy_index` (0-based) of `ref`; exact when cached."""
        v = ctx.values
        ex = ctx.memory["exact"].get(ref)
        if ex and ex.get("count") == copy_index:
            return float(ex["value"])
        c = v.cards.get(ref)
        if not c:
            return 0.0
        return c["book"] * v.affinity.get(c["set"], 1.0) * v.marginal(copy_index)

    def evaluate(self, ctx: Ctx, o: dict, venue: dict, pending_in: dict) -> dict | None:
        """What accepting `o` would do to our private value, or None when we cannot or should not."""
        v = ctx.values
        give, want = o.get("give", {}), o.get("want", {})
        in_refs = _card_refs_of(give)
        out_refs = _card_refs_of({"assets": [], "types": want.get("types", [])})
        if in_refs is None or out_refs is None or want.get("assets"):
            return None  # packs, unknown types, or a request for specific copies (never ours)
        give_cash, want_cash = int(give.get("cash") or 0), int(want.get("cash") or 0)
        if not in_refs and give_cash <= 0:
            return None

        counts = {r: v.count(r) + pending_in.get(r, 0) for r in set(in_refs) | set(out_refs)}
        # What we hand over: our least valuable copy of each wanted card, never a protected first copy.
        out_ids, loss, used = [], 0.0, set()
        for ref in out_refs:
            c = v.cards.get(ref)
            # Only cards the bot bought itself may be handed over: the team's cards are never the bot's.
            have = [a for a in v.held.get(ref, []) if a["id"] not in used and ctx.mine(a["id"])
                    and a["id"] not in self.team_listed_assets and a["id"] not in self.out_reserved]
            if not c or not have:
                return None
            if counts[ref] <= 1 and v.affinity.get(c["set"], 1.0) >= 1.0:
                return None
            asset = max(have, key=lambda a: a.get("serial", 0))
            counts[ref] -= 1
            loss += c["book"] * v.affinity.get(c["set"], 1.0) * v.marginal(counts[ref])
            used.add(asset["id"])
            out_ids.append(asset["id"])
        # What we receive, copy by copy.
        gain_in = 0.0
        for ref in in_refs:
            gain_in += self.card_value(ctx, ref, counts.get(ref, 0))
            counts[ref] = counts.get(ref, 0) + 1
        book_in = sum(v.cards.get(r, {}).get("book", 0) for r in in_refs)
        fee = self.fee(venue, max(give_cash, want_cash), len(in_refs) + len(out_refs), book_in)
        gain = gain_in + give_cash - want_cash - fee - loss
        cost = want_cash + fee + loss
        spend = want_cash + fee - give_cash
        return {"offer": o["id"], "venue": o.get("venue"), "in_refs": in_refs, "out_refs": out_refs,
                "in_ids": [a["id"] for a in give.get("assets", [])], "out_ids": out_ids,
                "value_in": round(gain_in, 2), "loss": round(loss, 2), "cash_in": give_cash,
                "cash_out": want_cash, "fee": fee, "spend": spend, "gain": round(gain, 2), "cost": round(cost, 2)}

    def worth_it(self, e: dict) -> bool:
        if e["gain"] < max(BUY_MIN_GAIN, BUY_MIN_MARGIN * e["cost"]):
            return False
        if e["spend"] > 0:
            if self.cash - e["spend"] < CASH_RESERVE:
                return False
            if e["spend"] > MAX_SPEND_SHARE * (self.cash - CASH_RESERVE):
                return False
        return True

    # ======================================================================== buy / swap
    def buy_or_swap(self, ctx: Ctx, venues: dict, boards: dict):
        mem = ctx.memory
        pending_in, self.out_reserved = {}, set()
        for p in mem["pending"].values():
            for r in p.get("in_refs", []):
                pending_in[r] = pending_in.get(r, 0) + 1
            self.out_reserved.update(p.get("out_ids", []))
        self.out_reserved.update(l["asset"] for l in mem["listings"].values())

        cands = []
        for vname, offers in boards.items():
            for o in offers:
                if o.get("status") != "open" or self.is_ours(o) or o.get("thread") is not None:
                    continue
                if o.get("to") not in (None, self.me_id):
                    continue
                if o.get("expires_tick") is not None and o["expires_tick"] <= self.tick_no:
                    continue
                e = self.evaluate(ctx, o, venues.get(vname, {}), pending_in)
                if e and self.worth_it(e):
                    cands.append(e)
        cands.sort(key=lambda e: -e["gain"])
        self.seen = len(cands)
        if not cands:
            return None
        if not ctx.budget.can_accept():
            ctx.journal.decide(self.name, "good offer, no accept left this tick", best=cands[0])
            return None

        best = cands[0]
        # Check the incoming card's value exactly (page bonuses etc.) once, when it is a single card.
        if len(best["in_refs"]) == 1:
            ref = best["in_refs"][0]
            n = ctx.values.count(ref) + pending_in.get(ref, 0)
            ex = mem["exact"].get(ref)
            if not ex or ex.get("count") != n:
                try:
                    exact = float(ctx.b.value(ref).get("your_value"))
                    mem["exact"][ref] = {"count": n, "value": exact, "tick": self.tick_no}
                except (BazaarError, TypeError, ValueError) as err:
                    ctx.journal.error(self.name, err)
                else:
                    o = next(x for offers in boards.values() for x in offers if x["id"] == best["offer"])
                    best = self.evaluate(ctx, o, venues.get(best["venue"], {}), pending_in)
                    if not best or not self.worth_it(best):
                        ctx.journal.decide(self.name, "exact value says no", ref=ref, exact=exact)
                        return None

        kind = "swap" if best["out_refs"] else "buy"
        ctx.budget.use_accept()
        try:
            res = ctx.write(self.name, f"accept ({kind})", ctx.b.accept, best["offer"],
                            assets=best["out_ids"] or None)
        except BazaarError as e:
            if e.code in ("wait_for_tick", "insufficient_cash", "not_open", "gone", "not_found", "expired",
                          "offer_closed", "insufficient_assets", "rate_limited"):
                ctx.journal.decide(self.name, "accept refused", offer=best["offer"], code=e.code)
                return None
            raise
        ctx.journal.decide(self.name, f"{kind} chosen", **best, dry_run=ctx.dry_run)
        self.out_reserved.update(best["out_ids"])  # never list what we just handed over
        if ctx.dry_run:
            return best["offer"]
        trade = {"tick": self.tick_no, "kind": kind, "offer": best["offer"], "venue": best["venue"],
                 "got": best["in_refs"], "got_cash": best["cash_in"], "gave": best["out_refs"],
                 "paid": best["cash_out"], "fee": best["fee"], "gain": best["gain"], "result": res}
        mem["pending"][str(best["offer"])] = {
            "tick": self.tick_no, "in_ids": best["in_ids"], "in_refs": best["in_refs"], "out_ids": best["out_ids"],
            "counts_before": {r: ctx.values.count(r) for r in best["in_refs"]}, "trade": trade}
        self.cash -= max(0, best["spend"])
        return best["offer"]

    # ======================================================================== sell
    def sale_candidates(self, ctx: Ctx) -> list[dict]:
        v = ctx.values
        out = [{**s, "first": False} for s in v.spares()]
        for ref, copies in v.held.items():
            c = v.cards.get(ref)
            if len(copies) == 1 and c and v.affinity.get(c["set"], 1.0) < 1.0:
                loss = copies[0]["your_value"] if copies[0].get("your_value") is not None else v.spare_value(ref)
                out.append({**copies[0], "loss": float(loss), "first": True})
        busy = self.team_listed_assets | self.out_reserved | set(ctx.shared.get("reserved", []))
        mine = [{**a, "loss": float(v.spare_value(a["ref"])), "first": v.count(a["ref"]) == 1}
                for a in ctx.me.get("assets", []) if a.get("kind") == "card" and ctx.mine(a["id"])]
        seen = {a["id"] for a in out}
        out = [a for a in out if ctx.mine(a["id"])] + [a for a in mine if a["id"] not in seen]
        return [a for a in out if a["id"] not in busy and a.get("kind") == "card"]

    def market_ask(self, boards: dict, ref: str) -> int | None:
        """The cheapest rival cash ask for a single copy of `ref` across the boards we read."""
        best = None
        for offers in boards.values():
            for o in offers:
                g, w = o.get("give", {}), o.get("want", {})
                if (o.get("status") != "open" or self.is_ours(o) or g.get("types") or g.get("cash")
                        or len(g.get("assets", [])) != 1 or g["assets"][0].get("ref") != ref
                        or w.get("types") or w.get("assets") or not w.get("cash")):
                    continue
                best = w["cash"] if best is None else min(best, w["cash"])
        return best

    def price(self, ctx: Ctx, boards: dict, a: dict) -> tuple[int, int]:
        book = ctx.values.cards.get(a["ref"], {}).get("book", 10)
        floor = max(_ceil(a["loss"] + SELL_MIN_MARGIN), _ceil(SELL_FLOOR_FRACTION * book))
        if a.get("first"):
            floor = max(floor, _ceil(a["loss"] * FIRST_COPY_MARKUP))
        rival = self.market_ask(boards, a["ref"])
        ask = book if rival is None else min(rival - 1, _ceil(book * MAX_ASK_FRACTION))
        return max(ask, floor), floor

    def sell(self, ctx: Ctx, boards: dict, team_offers: list[dict]):
        mem = ctx.memory
        listed = []
        team_open = len(team_offers)
        room = min(MAX_OWN_LISTINGS - len(mem["listings"]),
                   ctx.budget.max_offers - TEAM_HEADROOM - team_open,
                   LISTINGS_PER_TICK)

        # Re-price stale listings first (cancel + relist; the relist uses a listing slot).
        reprices = 0
        for oid, l in sorted(mem["listings"].items(), key=lambda kv: kv[1]["tick"]):
            if reprices >= REPRICES_PER_TICK or ctx.budget.listings <= 0:
                break
            if self.tick_no - l["tick"] < REPRICE_AFTER:
                continue
            rival = self.market_ask(boards, l["ref"])
            target = rival - 1 if rival is not None and rival <= l["price"] else round(l["price"] * REPRICE_STEP)
            new = max(l["floor"], min(target, l["price"] - 1))
            if new >= l["price"]:
                l["tick"] = self.tick_no  # at the floor already: leave it, look again later
                continue
            try:
                ctx.write(self.name, "cancel (reprice)", ctx.b.cancel, int(oid))
            except BazaarError as e:
                ctx.journal.decide(self.name, "cancel refused", offer=int(oid), code=e.code)
                continue
            reprices += 1
            if ctx.dry_run:
                ctx.journal.decide(self.name, "would relist", ref=l["ref"], old=l["price"], new=new)
                continue
            del mem["listings"][oid]
            res = self.list_one(ctx, {"id": l["asset"], "ref": l["ref"], "loss": l["loss"]}, new, l["floor"])
            if res:
                listed.append(res)

        if room <= 0:
            return listed
        cands = []
        for a in self.sale_candidates(ctx):
            ask, floor = self.price(ctx, boards, a)
            cands.append((a, ask, floor))
        # Spares before first copies, then the biggest private-value gain first.
        cands.sort(key=lambda c: (c[0]["first"], -(c[1] - c[0]["loss"])))
        seen_refs = set()
        for a, ask, floor in cands:
            if room <= 0 or ctx.budget.listings <= 0:
                break
            if a["ref"] in seen_refs:
                continue  # one listing per card at a time: two copies would undercut each other
            if any(l["ref"] == a["ref"] for l in mem["listings"].values()):
                continue
            seen_refs.add(a["ref"])
            res = self.list_one(ctx, a, ask, floor)
            if res is not False:
                room -= 1
                listed.append(res or {"ref": a["ref"], "price": ask})
        return listed

    def list_one(self, ctx: Ctx, a: dict, ask: int, floor: int):
        """List one card for cash on El Rastro. Returns the listing, None in dry run, False if refused."""
        ctx.budget.listings -= 1
        try:
            res = ctx.write(self.name, "list", ctx.b.list_offer, {"assets": [a["id"]]}, {"cash": int(ask)},
                            venue="rastro", expires_in_ticks=LIST_EXPIRES)
        except BazaarError as e:
            ctx.journal.decide(self.name, "listing refused", ref=a["ref"], ask=ask, code=e.code)
            return False
        ctx.journal.decide(self.name, "listed" if res else "would list", ref=a["ref"], asset=a["id"], ask=ask,
                           floor=floor, loss=round(a["loss"], 2), gain_if_sold=round(ask - a["loss"], 2))
        if not res:
            return None
        oid = res.get("id") or (res.get("offer") or {}).get("id")
        if oid is None:
            ctx.journal.decide(self.name, "listing without id", result=res)
            return None
        rec = {"asset": a["id"], "ref": a["ref"], "price": int(ask), "floor": int(floor),
               "loss": round(a["loss"], 2), "tick": self.tick_no, "venue": "rastro"}
        ctx.memory["listings"][str(oid)] = rec
        self.team_listed_assets.add(a["id"])
        return {"offer": oid, **rec}
