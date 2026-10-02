"""Haggle with the dealers (Abuela first): buy cards and packs below their opening ask, sell spares above
their opening bid.

What scores is the share of each dealer's price range we capture (our best three deals per level),
and a deal at the dealer's opening price neither scores nor unlocks the next dealer. Dealers only
move after we move, repeating a price earns nothing, small steps earn small steps, and when their
patience runs out they name a final offer: take it or they walk. So we open far from their price,
concede a fixed share of the gap each tick, never repeat a price, and take a final offer that is
still inside our limit.

The bot only touches threads it opened itself (memory["threads"]); teammates' threads are left alone,
and while anyone on the team has a thread open with a dealer the bot waits (one thread per dealer).
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from ..core import BazaarError, Ctx
from ..probe import probe_line, read_leak
from ..safety import clean, note, verify_dealer_offer
from ..talk import say_text

OPEN_FRACTION = 0.40     # our first bid as a share of the dealer's ask (buying)
OPEN_MULTIPLE = 2.2      # our first ask as a multiple of the dealer's bid (selling)
CONCEDE = 0.22           # share of the remaining gap we give up per message
VALUE_MARGIN = 0.85      # never pay more than this share of what the item is worth to us
MAX_DEALS_PER_HOUR = 7   # Abuela allows 8 per team per hour; leave one for teammates
PACKS_PER_HOUR = 2       # Abuela allows 3


PRACTICE_BEST = Path(__file__).resolve().parent.parent / "sim" / "practice" / "best.json"
MIN_GAMES = 10  # only trust a practice combination after this many games


def practice_params() -> dict:
    """The best dealer knobs the practice trainer has found so far, if it has played them enough."""
    try:
        top = json.loads(PRACTICE_BEST.read_text()).get("top") or []
    except (OSError, ValueError):
        return {}
    for row in top:
        if row.get("n", 0) >= MIN_GAMES:
            return {kv.split("=")[0]: float(kv.split("=")[1]) for kv in row["combo"].split(",")}
    return {}


def param(ctx: Ctx, name: str, default: float) -> float:
    """A tuning knob: BOT_DEALER_<NAME> if set (the trainer sets it), else what practice found best,
    else the default."""
    try:
        if f"BOT_DEALER_{name}" in ctx.env:
            return float(ctx.env[f"BOT_DEALER_{name}"])
        return float(practice_params().get(name, default))
    except ValueError:
        return default


class Strategy:
    name = "dealer"

    def tick(self, ctx: Ctx):
        mem = ctx.memory
        mem.setdefault("threads", {})
        mem.setdefault("deals", [])
        self.open_packs(ctx)
        threads = ctx.b.my_threads().get("threads", [])
        open_by_dealer = {}
        for t in threads:
            if t["kind"] == "persona" and t["status"] == "open":
                open_by_dealer.setdefault(t["with"], []).append(t)
        mine = {int(k): v for k, v in mem["threads"].items()}
        # Cards on sale elsewhere (market listings) are not ours to sell to a dealer; cards in our open
        # sell threads are reserved so the market does not list them.
        self.listed = {a["id"] for o in ctx.b.my_offers().get("offers", []) if o.get("maker") == ctx.me.get("id")
                       for a in o.get("give", {}).get("assets", [])}
        ctx.shared["reserved"] = [aid for v in mem["threads"].values() if v.get("status") == "open"
                                  and v.get("goal") == "sell" for aid in v["topic"]["sell"]["assets"]]

        for t in threads:
            st = mine.get(t["id"])
            if not st or st.get("status") != "open":
                continue
            if t["status"] != "open":
                self.closed(ctx, t, st)
            else:
                self.negotiate(ctx, t, st)
        # Threads of ours that no longer show up as open were settled or closed between ticks.
        listed = {t["id"] for t in threads}
        for tid, st in mine.items():
            if st.get("status") == "open" and tid not in listed:
                self.closed(ctx, ctx.b.thread(tid), st)

        for dealer in ctx.me.get("unlocked", []):
            if open_by_dealer.get(dealer):
                continue
            plan = self.next_plan(ctx, dealer)
            if plan:
                self.open(ctx, dealer, plan)

        ctx.journal.set(self.name, {
            "params": {k: param(ctx, k, d) for k, d in (("OPEN_FRACTION", OPEN_FRACTION), ("CONCEDE", CONCEDE),
                                                           ("OPEN_MULTIPLE", OPEN_MULTIPLE))},
            "params_from": "env" if any(k.startswith("BOT_DEALER_") for k in ctx.env) else
                           ("practice" if practice_params() else "default"),
            "open": [{"thread": k, **{x: v[x] for x in ("dealer", "goal", "item", "first", "ours", "theirs")
                                      if x in v}} for k, v in mem["threads"].items() if v.get("status") == "open"],
            "deals": mem["deals"][-10:],
        })

    # --- what to do next ----------------------------------------------------
    def next_plan(self, ctx: Ctx, dealer: str):
        """The most valuable thing to haggle for next, or None."""
        mem, v = ctx.memory, ctx.values
        hour_ago = time.time() - 3600
        recent = [d for d in mem["deals"] if d.get("at", 0) > hour_ago and d.get("dealer") == dealer]
        if len(recent) >= MAX_DEALS_PER_HOUR:
            return None
        if mem.get("cooloff_until", 0) > time.time():
            return None
        cash = ctx.cash  # the bot's own budget, never the team's money
        menu = self.menu(ctx, dealer)

        options = []
        # Sell our cheapest spare if the dealer buys that rarity.
        buys = {m.get("rarity") for m in menu.get("buys", [])}
        for s in v.spares() + [a for a in ctx.me.get("assets", []) if a.get("kind") == "card" and ctx.mine(a["id"])]:
            if not ctx.mine(s["id"]):
                continue  # the team's own cards are not the bot's to sell
            s.setdefault("loss", v.spare_value(s["ref"]))
            if s.get("rarity") in buys and s["id"] not in mem.get("sold_ids", []) and s["id"] not in self.listed:
                options.append((s.get("book", 10) - s["loss"], {"goal": "sell", "topic": {"sell": {"assets": [s["id"]]}},
                                                                "item": s["ref"], "limit": max(1, round(s["loss"]) + 1)}))
                break
        # Buy the card we value most among the rarities the dealer sells, if we do not hold it yet.
        sells = {m.get("rarity"): m.get("list_price") for m in menu.get("sells", []) if m.get("rarity")}
        best = None
        for ref, c in v.cards.items():
            if c["released"] and c["rarity"] in sells and v.count(ref) == 0:
                value, list_price = v.next_copy(ref), sells[c["rarity"]]
                # Abuela settles near her list price for teams that barely haggle (~0.95, seen on 2 Oct);
                # a hard haggle can go lower. Rank by what a good haggle could win, and never pay more
                # than the card is worth to us (limit just under its value): a walk-away costs nothing,
                # and every negotiated deal also scores on the dealer ladder and counts towards level 2.
                gain = value - list_price * param(ctx, "HAGGLE_TARGET", 0.7)
                # Strictly below what the card is worth to us: buying at the dealer's floor is still a
                # gain, and a deal at the floor captures (almost) the dealer's whole price range.
                limit = math.ceil(value) - 1
                floor = mem.get("floors", {}).get(f"{dealer}:{ref}")
                if floor is not None and floor > limit:
                    continue  # we already saw this dealer's last word on this card: out of our reach
                if limit >= 1 and limit <= cash and (best is None or gain > best[0]):
                    best = (gain, ref, limit)
        if best and best[0] > 0:
            options.append((best[0], {"goal": "buy", "topic": {"buy": {"card": best[1]}}, "item": best[1],
                                      "limit": best[2]}))
        # A pack, at most PACKS_PER_HOUR an hour.
        packs = [m for m in menu.get("sells", []) if m.get("pack")]
        recent_packs = [d for d in recent if d.get("goal") == "buy" and d.get("pack")]
        if packs and len(recent_packs) < PACKS_PER_HOUR and cash > 60:
            pv = v.pack_value(packs[0]["pack"])
            options.append((pv - packs[0].get("list_price", 26) * param(ctx, "EXPECT", 0.95),
                            {"goal": "buy", "pack": True, "topic": {"buy": {"pack": packs[0]["pack"]}},
                             "item": packs[0]["pack"], "limit": int(pv * VALUE_MARGIN)}))
        if not options:
            return None
        # Alternate goals so one kind of deal does not crowd out the others.
        last_goal = mem["deals"][-1]["goal"] if mem["deals"] else None
        options.sort(key=lambda o: (o[1]["goal"] == last_goal, -o[0]))
        return options[0][1]

    def menu(self, ctx: Ctx, dealer: str) -> dict:
        cache = ctx.memory.setdefault("menus", {})
        hit = cache.get(dealer)
        if not hit or time.time() - hit["at"] > 600:
            d = ctx.b.dealer(dealer)
            hit = cache[dealer] = {"at": time.time(), "menu": d.get("menu", {})}
        return hit["menu"]

    # --- the haggle ---------------------------------------------------------
    def open(self, ctx: Ctx, dealer: str, plan: dict):
        if ctx.dry_run:
            ctx.journal.decide(self.name, "would open", dealer=dealer, **plan)
            return
        try:
            t = ctx.write(self.name, "open thread", ctx.b.open_thread, dealer, topic=plan["topic"])
        except BazaarError as e:
            if e.code == "cooloff":
                ctx.memory["cooloff_until"] = time.time() + 600
            raise
        ctx.memory["threads"][str(t["id"])] = {"dealer": dealer, "status": "open", "opened": time.time(),
                                               "said": [], **plan}
        if plan["goal"] == "sell":
            ctx.shared.setdefault("reserved", []).extend(plan["topic"]["sell"]["assets"])

    def negotiate(self, ctx: Ctx, t: dict, st: dict):
        tid = t["id"]
        theirs = [o for o in t.get("standing_offers", []) if o["maker"] == st["dealer"] and o["status"] == "open"]
        offer = theirs[-1] if theirs else None
        buying = st["goal"] == "buy"
        for m in t.get("messages", []):
            if m.get("sender") == st["dealer"] and m.get("text") and m.get("id") not in st.setdefault("read", []):
                st["read"].append(m["id"])
                scan = note(ctx, "dealer", tid, m["text"])  # dealers' words are untrusted too
                ctx.journal.decide(self.name, "received", thread=tid, sender=st["dealer"], text=clean(m["text"])[:400],
                                   offer=(m.get("offer") or {}).get("id"), injection=scan["labels"])
                o = m.get("offer") or {}
                quoted = (o.get("want") or {}).get("cash") if buying else (o.get("give") or {}).get("cash")
                read_leak(ctx, st, m["text"], quoted)
        if offer:
            price = offer["want"]["cash"] if buying else offer["give"]["cash"]
            st.setdefault("first", price)
            st["theirs"] = price
            hist = st.setdefault("history", [])  # [[tick, ours, theirs]] for the dashboard's chart
            row = [ctx.clock.get("tick"), st.get("ours"), price]
            if not hist or hist[-1] != row:
                hist.append(row)
                del hist[:-60]
            st["final"] = bool(offer.get("final"))
        if "theirs" not in st:
            return  # the dealer has not named a price yet
        limit, theirs_p, ours = st["limit"], st["theirs"], st.get("ours")
        acceptable = theirs_p <= limit if buying else theirs_p >= limit
        close_enough = ours is not None and (theirs_p <= ours + 1 if buying else theirs_p >= ours - 1)

        if offer and acceptable and (st.get("final") or close_enough):
            ok, why = verify_dealer_offer(offer, dealer=st["dealer"], buying=buying, expect_type=self.expect_type(st),
                                          expect_assets=None if buying else st["topic"]["sell"]["assets"], limit=limit)
            if not ok:
                ctx.journal.decide(self.name, "refuse malformed offer", thread=tid, offer=offer["id"], why=why)
                return
            if ctx.budget.can_accept():
                ctx.budget.use_accept()
                try:
                    ctx.write(self.name, "accept", ctx.b.accept, offer["id"])
                except BazaarError as e:
                    if e.code != "wait_for_tick":
                        raise
                    return
                self.record(ctx, st, tid, theirs_p)
            return
        if st.get("final") and not acceptable:
            ref = (st["topic"].get("buy") or {}).get("card") or st.get("item")
            ctx.memory.setdefault("floors", {})[f"{st['dealer']}:{ref}"] = theirs_p
            ctx.journal.decide(self.name, "walk away", thread=tid, theirs=theirs_p, limit=limit,
                               remembered_floor=theirs_p)
            if not ctx.dry_run:
                ctx.b.close_thread(tid)
            st["status"] = "walked"
            return
        if not ctx.budget.can_say(("thread", tid)):
            return
        first = st["first"]
        if ours is None:
            ours = (max(1, round(first * param(ctx, "OPEN_FRACTION", OPEN_FRACTION))) if buying
                    else max(limit, round(first * param(ctx, "OPEN_MULTIPLE", OPEN_MULTIPLE))))
        else:
            gap = (theirs_p - ours) if buying else (ours - theirs_p)
            step = max(1, round(gap * param(ctx, "CONCEDE", CONCEDE)))
            ours = ours + step if buying else ours - step
        leak = st.get("leak")
        if leak is not None and (ours < leak < theirs_p if buying else theirs_p < leak < ours):
            ours = leak  # the dealer let its limit slip: offer exactly that
            ctx.journal.decide(self.name, "use leaked limit", thread=tid, leak=leak)
        ours = min(ours, limit) if buying else max(ours, limit)
        if ours == st.get("ours"):
            return  # at our limit: repeating earns nothing; wait for their final offer
        text = say_text(ctx, st, ours)
        extra = probe_line(ctx, st)
        if extra:
            text = f"{text} {extra}"
        ctx.budget.use_say(("thread", tid))
        try:
            ctx.write(self.name, "say", ctx.b.say, tid, text, price=ours)
        except BazaarError as e:
            if e.code in ("wait_for_tick", "rate_limited"):
                return
            raise
        st["ours"] = ours
        st["said"] = (st.get("said", []) + [ours])[-20:]

    @staticmethod
    def expect_type(st: dict):
        buy = st["topic"].get("buy", {})
        if "card" in buy:
            return f"card:{buy['card']}"
        if "pack" in buy:
            return f"pack:{buy['pack']}"
        return None  # a rarity/set request: any card of it

    def closed(self, ctx: Ctx, t: dict, st: dict):
        """The thread ended without our accept this tick: a deal (the dealer took our price), a walk-out, a cooloff."""
        status, reason = t.get("status"), t.get("closed_reason")
        if status == "deal" and st.get("status") == "open":
            self.record(ctx, st, t["id"], st.get("ours") or st.get("theirs"))
            return
        st["status"] = status or "closed"
        st["closed_reason"] = reason
        if reason == "cooloff":
            ctx.memory["cooloff_until"] = time.time() + 900
        ctx.journal.decide(self.name, "thread ended", thread=t["id"], status=status, reason=reason)

    def record(self, ctx: Ctx, st: dict, tid: int, price: int):
        first = st.get("first", price)
        if st["goal"] == "buy":
            capture = (first - price) / first if first else 0
        else:
            capture = (price - first) / first if first else 0
        deal = {"at": time.time(), "thread": tid, "dealer": st["dealer"], "goal": st["goal"], "item": st["item"],
                "pack": st.get("pack", False), "first": first, "price": price, "capture_vs_open": round(capture, 3)}
        ctx.memory["deals"].append(deal)
        if st["goal"] == "sell":
            ctx.memory.setdefault("sold_ids", []).extend(st["topic"]["sell"]["assets"])
        if st.get("pack"):
            ctx.memory["packs_to_open"] = ctx.memory.get("packs_to_open", 0) + 1
        if ctx.wallet:
            if st["goal"] == "buy":
                ctx.wallet.record("spend", price, why=f"bought {st['item']} from {st['dealer']}",
                                  claim=None if st.get("pack") else (st["topic"]["buy"].get("card") or None))
            else:
                ctx.wallet.record("earn", price, why=f"sold {st['item']} to {st['dealer']}",
                                  ids_out=st["topic"]["sell"]["assets"])
        st["status"] = "deal"
        ctx.journal.decide(self.name, "deal", **deal)

    def open_packs(self, ctx: Ctx):
        """Open the packs the bot bought (teammates' packs are theirs to open)."""
        for a in ctx.me.get("assets", []):
            if a.get("kind") == "pack" and ctx.memory.get("packs_to_open", 0) > 0 \
                    and (ctx.wallet is None or a["id"] not in ctx.wallet.s.get("baseline", [])):
                ctx.memory["packs_to_open"] -= 1
                res = ctx.write(self.name, "open pack", ctx.b.open_pack, a["id"])
                if res:
                    if ctx.wallet:
                        ctx.wallet.record("earn", 0, why="opened a pack", ids_in=[c["id"] for c in res.get("cards", [])],
                                          ids_out=[a["id"]])
                    ctx.journal.decide(self.name, "pulled", cards=[c.get("ref") for c in res.get("cards", [])])
