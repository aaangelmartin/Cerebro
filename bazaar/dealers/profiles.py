"""What we know about how each dealer haggles, learned from Friday and from every live thread.

A profile is keyed by dealer and by `kind` = "<our side>:<rarity or pack>" (e.g. "buy:uncommon",
"sell:common", "buy:pack"). For each kind it keeps samples of:

- `open_over_list`: the dealer's opening price / the menu list price;
- `limit_ratio`: the best price the dealer reached / its opening (buy: < 1, sell: > 1). It is our
  estimate of the dealer's secret limit for that kind of item;
- `mirror`: the dealer's concession per P of ours (Abuela ~1 P whatever we give, Chato ~1:1 up to 4 P);
- `patience`: how many of our priced messages until the dealer names its final offer.

Unknown dealers start from a prior built from their public traits (`GET /api/dealers/{id}`), and every
finished live thread adds samples. Everything persists in `config.LIVE / "dealer_memory.json"`.
"""
from __future__ import annotations

import json
import statistics
import threading
import time
from pathlib import Path
from typing import Any

MAX_SAMPLES = 40

# Measured on Friday (bazaar/data/friday: memory.json threads + public thread messages, seed L06-L09, L14).
FRIDAY_SEED: dict[str, dict[str, dict[str, list[float]]]] = {
    "abuela": {
        # 29->21, 29->21, 29->24, 25->21, 23->22 (uncommons); she gives ~1 P per step whatever we give.
        "buy:uncommon": {"open": [29, 29, 29, 25, 23, 29], "limit_ratio": [0.72, 0.72, 0.83, 0.84, 0.81],
                         "mirror": [0.6, 0.5, 0.5, 0.4, 0.33], "patience": [4, 6, 6, 7]},
        # 12->9/10 (commons): SAL-02 12->9 (deal 8), t17 LAV-01 12->10.
        "buy:common": {"open": [12, 12, 12], "limit_ratio": [0.75, 0.83, 0.75], "mirror": [0.5, 0.4], "patience": [4, 5]},
        # sobre_barrio opens 30 (list 26), closes 19-21 after 4-6 steps.
        "buy:pack": {"open": [30, 30, 30], "limit_ratio": [0.63, 0.7, 0.67], "mirror": [0.5, 0.4], "patience": [5, 6]},
        # buys commons at a flat 5, final 5-6 after many steps; uncommons 12->14.
        "sell:common": {"open": [5, 5, 5, 5, 5], "limit_ratio": [1.0, 1.2, 1.0, 1.0], "mirror": [0.05, 0.1], "patience": [5, 7, 7]},
        "sell:uncommon": {"open": [12, 12], "limit_ratio": [1.17, 1.08], "mirror": [0.2, 0.25], "patience": [5, 6]},
    },
    "chato": {
        # rares open 97; t07 steps of 4 got 1,2,4,4,4 (97->82); t06 steps of 2 got 1,1,2,2,2,2 (97->87). Deals 93, 90.
        "buy:rare": {"open": [97, 97, 97, 97], "limit_ratio": [0.845, 0.9, 0.93, 0.85], "mirror": [0.9, 0.8, 1.0, 0.75],
                     "patience": [7, 8]},
        "buy:uncommon": {"open": [29, 31, 29], "limit_ratio": [0.93, 0.94, 0.97], "mirror": [0.5], "patience": [4, 5]},
        # sobre_plata opens 188 (list 150), 188->181 for steps of 10: a trap.
        "buy:pack": {"open": [188, 188], "limit_ratio": [0.96, 0.97], "mirror": [0.25, 0.2], "patience": [5, 6]},
        # buys uncommons at a sticky 13; after 5-6 steps 14-16 (final 15-16).
        "sell:uncommon": {"open": [13, 13, 13, 13], "limit_ratio": [1.23, 1.15, 1.0, 1.0], "mirror": [0.1, 0.08],
                          "patience": [6, 6, 5]},
        # t13 sold LAT-09 (rare) to Chato at 46; opening unknown.
        "sell:rare": {"open": [40], "limit_ratio": [1.15], "mirror": [0.15], "patience": [6]},
    },
}

# Measured on Saturday from the public feed (every team's threads with Chato and Pilar, ticks 160-480).
# Appended once to a live profile (see ProfileStore: "seeds_applied"), so Friday's samples stay too.
SATURDAY_SEED: dict[str, dict[str, dict[str, list[float]]]] = {
    "chato": {
        # buys uncommons: sticky 13, final 14-15 after 5-7 steps (t02 13->14, 13->15; t13 13->14).
        "sell:uncommon": {"open": [13, 13, 13, 13], "limit_ratio": [1.15, 1.08, 1.15, 1.08, 1.15],
                          "mirror": [0.1, 0.1], "patience": [6, 7]},
        # sells uncommons: opens 33; finals 27 (t13 LAV-06), 28 (t13 LAV-07), 30-31 (t18, t05, t14).
        "buy:uncommon": {"open": [33, 33, 33, 33], "limit_ratio": [0.82, 0.85, 0.94, 0.94, 0.91],
                         "mirror": [0.4, 0.5], "patience": [5, 7]},
        # sells rares: opens 97; finals 85-87 (t09 LAV-10 85, t05 RET-10 86, RET-09 87), t17 MAL-09 88.
        "buy:rare": {"open": [97, 97, 97], "limit_ratio": [0.876, 0.887, 0.897], "mirror": [0.8, 0.75],
                     "patience": [6, 7]},
    },
    "pilar": {
        # buys uncommons: opens 16, final 19 after 8 steps of 1 P from the team (t13).
        "sell:uncommon": {"open": [16, 16, 16], "limit_ratio": [1.19, 1.12], "mirror": [0.15, 0.2], "patience": [8]},
        # the cards she loves (SAL, RET): opened 22 for t13; her limit is not seen yet (guess from 16 -> 19).
        "sell:uncommon:loved": {"open": [22], "limit_ratio": [1.18], "mirror": [0.15], "patience": [8]},
    },
}
# Los Pícaros, Saturday afternoon (Team 5's threads): rares list 63, open 73, close at 53-56 after a haggle.
# Our own four threads stalled at the opening (ratio 1.0), which hid the dealer as a source for a rare.
PICAROS_SEED: dict[str, dict[str, dict[str, list[float]]]] = {
    "picaros": {
        "buy:rare": {"open": [73, 73, 73], "limit_ratio": [0.74, 0.74, 0.75, 0.76, 0.77], "mirror": [0.5, 0.5],
                     "patience": [6, 7]},
    },
}
# Saturday evening, our own hand-run threads (1600-1703) and Team 14's: where each ladder ended.
STEPS_SEED: dict[str, dict[str, dict[str, list[float]]]] = {
    "pilar": {
        # buys a rare she loves (SAL, RET): opens 70; finals 84 (asks 105..90), 77 (asks from 108), 80, t14 87.
        "sell:rare:loved": {"open": [70, 70, 70, 70], "limit_ratio": [1.2, 1.1, 1.14, 1.24], "mirror": [0.9, 0.7, 0.9],
                            "patience": [6, 5, 6]},
    },
    "picaros": {
        # sells a rare: opens 73; finals 54, 55, 55 after five or six bids from 32 in steps of 4.
        "buy:rare": {"open": [73, 73, 73], "limit_ratio": [0.74, 0.75, 0.75], "mirror": [1.0, 1.0], "patience": [5, 6, 2]},
    },
    "abuela": {
        # buys an uncommon since tick 979: opens 18, stops at 19-20.
        "sell:uncommon": {"open": [18, 18, 18], "limit_ratio": [1.06, 1.06, 1.11], "mirror": [0.3], "patience": [3]},
    },
}
SEEDS_ONCE = {"sat-feed-1": SATURDAY_SEED, "sat-picaros-1": PICAROS_SEED, "sat-steps-1": STEPS_SEED}

# Hourly quotas measured Friday (the menu says it too).
FRIDAY_QUOTAS = {"abuela": {"deals": 8, "packs": 3}, "chato": {"deals": 6, "packs": 2}}
CONV_QUOTA = 10                  # conversations a dealer opens with one team per hour (the game's refusal says so)
DEFAULT_LIST = {"common": 10, "uncommon": 25, "rare": 77, "epic": 190, "legendary": 480}


def _median(xs: list[float], default: float) -> float:
    xs = [float(x) for x in xs if x is not None]
    return float(statistics.median(xs)) if xs else default


def prior_from_traits(traits: dict | None, kind: str) -> dict[str, float]:
    """A guess for a dealer we have never met, from its public traits (0..1 each)."""
    t = traits or {}
    gen, shrewd, pat = t.get("generosity", 0.5), t.get("shrewdness", 0.5), t.get("patience", 0.5)
    buy = kind.startswith("buy")
    return {
        "open_over_list": 1.15 + 0.15 * shrewd if buy else 0.5 - 0.1 * shrewd,
        "limit_ratio": (0.93 - 0.2 * gen) if buy else (1.05 + 0.2 * gen),
        "mirror": max(0.1, 1.0 - 0.6 * shrewd) if buy else max(0.05, 0.3 - 0.25 * shrewd),
        "patience": round(3 + 7 * pat),
    }


class ProfileStore:
    """Dealer profiles + our dealer history (deals, quotas, cooloffs). Thread-safe, persisted as JSON."""

    def __init__(self, path: Path | None = None, seed: bool = True):
        if path is None:
            from bazaar import config
            path = config.LIVE / "dealer_memory.json"
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data: dict[str, Any] = {"profiles": {}, "deals": [], "cooloff": {}, "quota_hit": {}, "threads": {},
                                     "menus": {}}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text()))
            except (OSError, ValueError):
                pass
        if seed:
            for dealer, kinds in FRIDAY_SEED.items():
                prof = self.data["profiles"].setdefault(dealer, {})
                for kind, samples in kinds.items():
                    k = prof.setdefault(kind, {})
                    for name, xs in samples.items():
                        if not k.get(name):
                            k[name] = list(xs)
            applied = self.data.setdefault("seeds_applied", [])
            for sid, seeds in SEEDS_ONCE.items():       # newer measurements: appended once, newest last
                if sid in applied:
                    continue
                for dealer, kinds in seeds.items():
                    prof = self.data["profiles"].setdefault(dealer, {})
                    for kind, samples in kinds.items():
                        k = prof.setdefault(kind, {})
                        for name, xs in samples.items():
                            k[name] = (list(k.get(name) or []) + list(xs))[-MAX_SAMPLES:]
                applied.append(sid)
        for d in self.data.get("deals") or []:           # deals stored before limit_fallback existed
            if d.get("limit_est") is None and d.get("opening") and d.get("price") is not None:
                buying = d.get("side") == "buy"
                d["limit_est"] = self.limit_fallback(d.get("dealer", ""), d.get("kind") or "?", buying, d["opening"])
                d["capture"] = capture(d["opening"], d["price"], d["limit_est"], buying)

    def save(self) -> None:
        with self.lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.data, indent=1, default=str))
                tmp.replace(self.path)
            except OSError:
                pass

    # --- menus / traits ------------------------------------------------------------
    def remember_menu(self, persona: dict) -> None:
        if persona.get("id"):
            with self.lock:
                self.data["menus"][persona["id"]] = {"menu": persona.get("menu") or {},
                                                     "traits": persona.get("traits") or {},
                                                     "level": persona.get("level"), "at": time.time()}

    def traits(self, dealer: str) -> dict:
        return (self.data["menus"].get(dealer) or {}).get("traits") or {}

    # --- estimates -----------------------------------------------------------------
    def stat(self, dealer: str, kind: str, name: str) -> float:
        samples = ((self.data["profiles"].get(dealer) or {}).get(kind) or {}).get(name) or []
        if not samples and kind.count(":") == 2:          # "sell:uncommon:loved" -> "sell:uncommon"
            return self.stat(dealer, kind.rsplit(":", 1)[0], name)
        if not samples and kind.startswith("buy:") and name != "open":
            # a buy of another rarity from the same dealer is a better prior than the traits
            for other, k in (self.data["profiles"].get(dealer) or {}).items():
                if other.startswith("buy:") and other != "buy:pack" and k.get(name):
                    samples = k[name]
                    break
        prior = prior_from_traits(self.traits(dealer), kind)
        if name == "open":
            return _median(samples, 0.0)
        return _median(samples, prior[name])

    def n(self, dealer: str, kind: str) -> int:
        k = (self.data["profiles"].get(dealer) or {}).get(kind) or {}
        return len(k.get("limit_ratio") or [])

    def expect_opening(self, dealer: str, kind: str, list_price: float | None) -> float:
        """The dealer's likely opening price for this kind of item."""
        seen = self.stat(dealer, kind, "open")
        if list_price:
            ratio = prior_from_traits(self.traits(dealer), kind)["open_over_list"]
            guess = list_price * ratio
            if seen and kind.endswith(("common", "uncommon", "rare")):
                return seen if abs(seen - guess) / max(guess, 1) < 0.5 else guess
            return seen or guess
        return seen or 0.0

    def expect_limit(self, dealer: str, kind: str, opening: float) -> float:
        """Estimated secret limit (buy: lowest the dealer sells at; sell: highest it pays)."""
        return opening * self.stat(dealer, kind, "limit_ratio")

    def limit_fallback(self, dealer: str, kind: str, buying: bool, opening: float) -> float:
        """Limit estimate for a deal the bot never evaluated (closed by hand, or settled while the domain was
        paused): the furthest any thread on that side pushed this dealer, as a share of its opening."""
        side = "buy" if buying else "sell"
        prof = self.data["profiles"].get(dealer) or {}
        kinds = [kind] if (prof.get(kind) or {}).get("limit_ratio") and kind != "?" else \
            [k for k in prof if k.startswith(side + ":") and k != "buy:pack"]
        ratios = [r for k in kinds for r in (prof[k].get("limit_ratio") or [])]
        if not ratios:
            return round(self.expect_limit(dealer, kind if kind != "?" else f"{side}:card", opening), 2)
        return round(opening * (min(ratios) if buying else max(ratios)), 2)

    def summary(self, dealer: str, kind: str) -> dict:
        return {"limit_ratio": round(self.stat(dealer, kind, "limit_ratio"), 3),
                "mirror": round(self.stat(dealer, kind, "mirror"), 2),
                "patience_msgs": round(self.stat(dealer, kind, "patience"), 1), "samples": self.n(dealer, kind)}

    # --- learning ------------------------------------------------------------------
    def learn_thread(self, dealer: str, kind: str, opening: int | None, theirs: list[int], ours: list[int],
                     final: bool, buying: bool) -> None:
        """Add one finished (or final-offer) thread's evidence to the profile."""
        if not opening or not theirs:
            return
        with self.lock:
            k = self.data["profiles"].setdefault(dealer, {}).setdefault(kind, {})

            def add(name: str, x: float) -> None:
                xs = k.setdefault(name, [])
                xs.append(round(float(x), 4))
                del xs[:-MAX_SAMPLES]

            add("open", opening)
            best = min(theirs) if buying else max(theirs)
            add("limit_ratio", best / opening)
            mirrors = []
            # dealer theirs[0]; we ours[0]; dealer theirs[1]; we ours[1] -> dealer answers with theirs[2] ...
            for i in range(1, min(len(ours) - 1, len(theirs) - 2) + 1):
                ours_step = (ours[i] - ours[i - 1]) if buying else (ours[i - 1] - ours[i])
                if ours_step > 0:
                    th = (theirs[i] - theirs[i + 1]) if buying else (theirs[i + 1] - theirs[i])
                    mirrors.append(max(0.0, th) / ours_step)
            if mirrors:
                add("mirror", statistics.median(mirrors))
            if final:
                add("patience", max(1, len(ours)))
            self.save()

    def record_deal(self, dealer: str, level: int, kind: str, item: str, opening: int | None, price: int,
                    limit_est: float | None, buying: bool, value: float | None, thread: int | None = None,
                    tick: int | None = None) -> dict:
        if limit_est is None and opening:        # no estimate on the thread: the slot would read as empty
            limit_est = self.limit_fallback(dealer, kind, buying, opening)
        cap = capture(opening, price, limit_est, buying)
        deal = {"at": time.time(), "tick": tick, "dealer": dealer, "level": level, "kind": kind, "item": item,
                "opening": opening, "price": price, "limit_est": limit_est, "capture": cap, "side": "buy" if buying else "sell",
                "value": value, "thread": thread,
                "negotiated": bool(opening is not None and price != opening)}
        with self.lock:
            if thread is not None and any(d.get("thread") == thread for d in self.data["deals"]):
                return deal
            self.data["deals"].append(deal)
            del self.data["deals"][:-500]
            self.save()
        return deal

    # --- quotas, cooloffs, ladder ----------------------------------------------------
    def deals_last_hour(self, dealer: str, packs_only: bool = False, now: float | None = None) -> int:
        now = now or time.time()
        return sum(1 for d in self.data["deals"] if d["dealer"] == dealer and now - d["at"] < 3600
                   and (not packs_only or d.get("kind") == "buy:pack"))

    def set_cooloff(self, dealer: str, until_tick: int | None, seconds: float = 900) -> None:
        with self.lock:
            self.data["cooloff"][dealer] = {"until_tick": until_tick, "until": time.time() + seconds}
            self.save()

    def in_cooloff(self, dealer: str, tick: int) -> bool:
        c = self.data["cooloff"].get(dealer)
        if not c:
            return False
        if c.get("until_tick") is not None:
            return tick < int(c["until_tick"])
        return time.time() < c.get("until", 0)

    # ---- conversations per hour: the game refuses the 11th thread with a dealer, deals or not
    def note_open(self, dealer: str, now: float | None = None) -> None:
        now = now or time.time()
        with self.lock:
            opens = [o for o in self.data.setdefault("opens", []) if now - o["at"] < 3600]
            opens.append({"dealer": dealer, "at": now})
            self.data["opens"] = opens
            self.save()

    def opens_last_hour(self, dealer: str, now: float | None = None) -> int:
        return opens_last_hour(self.data, dealer, now)

    def conv_quota(self, dealer: str) -> int:
        return conv_quota(self.data, dealer)

    def learn_conv_quota(self, dealer: str, n: int) -> None:
        with self.lock:
            self.data.setdefault("conv_quota", {})[dealer] = int(n)
            self.save()

    def quota_left(self, dealer: str, deals_quota: int, now: float | None = None) -> int:
        """Threads we can still usefully open with this dealer in the rolling hour (deals and conversations)."""
        return quota_left(self.data, dealer, deals_quota, now)

    def set_quota_hit(self, dealer: str) -> None:
        with self.lock:
            self.data["quota_hit"][dealer] = time.time()
            self.save()

    def quota_blocked(self, dealer: str) -> bool:
        return time.time() - self.data["quota_hit"].get(dealer, 0) < 900

    def set_budget_hit(self, dealer: str, until_tick: int) -> None:
        """The dealer closed with `persona_budget`: it has no cash left for us until `until_tick`."""
        with self.lock:
            self.data.setdefault("budget_hit", {})[dealer] = int(until_tick)
            self.save()

    def budget_blocked(self, dealer: str, tick: int) -> bool:
        return int(tick) < int((self.data.get("budget_hit") or {}).get(dealer, 0))

    def recent_sales(self, dealer: str, kind_prefix: str, within_s: float, now: float | None = None) -> list[int]:
        """Prices this dealer paid us for this kind of card lately, oldest first (the resale proof of a loop)."""
        now = now or time.time()
        return [int(d["price"]) for d in self.data["deals"] if d.get("dealer") == dealer and d.get("side") == "sell"
                and str(d.get("kind") or "").startswith(kind_prefix) and now - d.get("at", 0) < within_s]

    def ladder(self, level: int) -> list[float]:
        """Our best three negotiated captures at this level, best first (missing ones are 0)."""
        caps = sorted((d["capture"] for d in self.data["deals"] if d.get("level") == level and d.get("negotiated")),
                      reverse=True)[:3]
        return caps + [0.0] * (3 - len(caps))


def opens_last_hour(mem: dict, dealer: str, now: float | None = None) -> int:
    now = now or time.time()
    return sum(1 for o in mem.get("opens") or [] if o.get("dealer") == dealer and now - o.get("at", 0) < 3600)


def conv_quota(mem: dict, dealer: str) -> int:
    return int((mem.get("conv_quota") or {}).get(dealer) or CONV_QUOTA)


def quota_left(mem: dict, dealer: str, deals_quota: int, now: float | None = None) -> int:
    """min(deals left, conversations left) in the rolling hour; works on the raw dealer_memory.json too."""
    now = now or time.time()
    deals = sum(1 for d in mem.get("deals") or [] if d.get("dealer") == dealer and now - d.get("at", 0) < 3600)
    return max(0, min(int(deals_quota) - deals, conv_quota(mem, dealer) - opens_last_hour(mem, dealer, now)))


def capture(opening: int | None, price: int, limit_est: float | None, buying: bool) -> float:
    """Share of the dealer's price range we captured: opening -> its secret limit (estimated)."""
    if not opening or limit_est is None:
        return 0.0
    span = (opening - limit_est) if buying else (limit_est - opening)
    if span <= 0:
        return 1.0 if ((price < opening) if buying else (price > opening)) else 0.0
    got = (opening - price) if buying else (price - opening)
    return round(max(0.0, min(1.0, got / span)), 3)


def ladder_gain(current: list[float], new_capture: float) -> float:
    """How much the sum of the best three captures grows if this deal lands."""
    worst = min(current) if current else 0.0
    return max(0.0, new_capture - worst)
