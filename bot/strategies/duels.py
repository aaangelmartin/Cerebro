"""Duels: scheduled one-to-one negotiations against every other team, once as seller and once as buyer.

What scores is the share of each deal's pie we capture, and the pie shrinks with every round of talk
(decay ~0.06-0.08 per round), so a slow perfect deal loses to a quick good one. A deal outside our limit
loses points and no deal scores zero.

How we play (all the numbers are tuned with bot/tests/sim_duels.py):

* Everything is worked out in *our surplus*: seller `price - cost`, buyer `value - price`, plus
  `weight * days` when the session negotiates delivery days. The pie is the joint surplus.
* We estimate the pie from a prior (rival limit ~ PRIOR_RATIO away from ours) blended with what the
  rival's offers reveal: their best offer so far is a floor (they never offer outside their limit) and
  their concession steps, extrapolated geometrically, say how much room they still have.
* We open high (OPEN x pie estimate), concede on a schedule that reaches TARGET x pie by ALPHA of the
  deadline, then slide towards END x pie at the deadline. Offers never go backwards, never outside our
  limit (at least MIN_SURPLUS), and never ask for less than the rival already gives us.
* We accept the rival's standing offer when it is inside our limit and worth at least our next offer
  discounted by the decay of the rounds it would take to get it (LOOKAHEAD), or when the deadline is
  near. One accept per tick for the whole team: the most urgent duel gets it.
* With days: the joint-optimal day is an extreme (0 or 10) set by the sign of our weight plus the
  rival's (estimated from the days they ask for). We offer that day and charge for it in price
  (logrolling): we give way on the issue that costs us less and always send days.

The pure decision function `decide()` is shared with the offline simulator.
"""

from __future__ import annotations

import json
import random

from ..core import BazaarError, Ctx

PARAMS = {
    "PRIOR_RATIO": 0.5,    # prior: rival limit ~ our limit * (1 + r) (seller) or / (1 + r) (buyer)
    "OPEN": 1.25,          # first offer, as a multiple of the pie estimate (asks above it: anchors)
    "OPEN_KNOWN": 0.95,    # first offer when the pie is known exactly (mirrored scenario)
    "TARGET": 0.62,        # share of the pie we aim at by ALPHA of the duel
    "ALPHA": 0.40,         # when (share of the deadline) we reach TARGET
    "BETA": 0.8,           # curve shape before ALPHA (1 linear, <1 concede early, >1 hold then concede)
    "END": 0.20,           # share of the pie we still ask for at the deadline
    "LOOKAHEAD": 2,        # rounds we expect it would take to get our own next offer accepted
    "LAST_TICKS": 2,       # within this many ticks of the deadline accept anything inside our limit
    "MIN_SURPLUS": 1,      # never offer or accept less than this over our limit
    "OBS_WEIGHT": 3.0,     # how fast observed rival offers replace the prior (n / (n + OBS_WEIGHT))
    "Q_CAP": 0.75,         # cap on the rival's geometric concession ratio when extrapolating
}

DEFAULT_TICKS = 12
DAYS_MAX = 10

LINES = [
    "Thanks for the offer. I can do {p} P{d}.",
    "Let's find a deal that works for both of us: {p} P{d}.",
    "I've moved towards you again: {p} P{d}.",
    "Fair is fair: {p} P{d}, and we can close now.",
    "We both lose the longer we talk. {p} P{d}?",
    "Meeting you closer: {p} P{d}.",
    "That's a real step from me: {p} P{d}.",
]


# --- parsing the server's duel (shape not confirmed yet: be generous) ---------------------------
def _num(x):
    try:
        return None if x is None or isinstance(x, bool) else float(x)
    except (TypeError, ValueError):
        return None


def parse_offer(x):
    """(price, days) from a number, {"price": .., "days": ..}, {"offer": {...}} or None."""
    if x is None:
        return None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return (float(x), None)
    if isinstance(x, dict):
        if isinstance(x.get("offer"), dict):
            inner = parse_offer(x["offer"])
            if inner:
                return inner
        p = _num(x.get("price", x.get("cash", x.get("amount"))))
        if p is None:
            return None
        d = _num(x.get("days", x.get("delivery_days", x.get("day"))))
        return (p, None if d is None else int(round(d)))
    return None


PRICE_MAX = 10_000_000
OUR_SENDERS = {"you", "us", "me", "self", "ours", "team"}


def valid_offer(off, use_days: bool):
    """Reason the structured offer is unusable, or None. Only structure counts, never words."""
    if off is None:
        return "no offer"
    price, days = off
    if price is None or price != price or not (1 <= price <= PRICE_MAX) or abs(price - round(price)) > 1e-9:
        return f"bad price {price!r}"
    if days is not None and not (0 <= days <= DAYS_MAX):
        return f"bad days {days!r}"
    if use_days and days is None:
        return "no days"
    return None


def rival_messages(duel: dict, our_ids: set) -> list:
    """The rival's messages (structured fields kept, text untouched: it is only ever scanned)."""
    msgs = duel.get("messages")
    if not isinstance(msgs, list):
        return []
    rival = duel.get("rival")
    out = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        who = str(m.get("sender", m.get("from", "")))
        if who.lower() in OUR_SENDERS or who in our_ids:
            continue
        if rival is not None and who not in (str(rival), "rival") and our_ids:
            # An unknown sender: neither us nor the named rival. Ignore it for offers.
            continue
        out.append(m)
    return out


def latest_rival_offer(duel: dict, our_ids: set):
    """(price, days) of the rival's last priced message, or None when the duel has no message list."""
    priced = [m for m in rival_messages(duel, our_ids) if parse_offer(m) is not None]
    return parse_offer(priced[-1]) if priced else None


def observe(duel: dict, tick: int, st: dict) -> dict:
    """The fields decide() needs, from a raw duel and our own memory of it."""
    issues = duel.get("issues") or ["price"]
    if isinstance(issues, str):
        issues = [issues]
    role = str(duel.get("role", "")).lower()
    span = st.get("duel_ticks") or DEFAULT_TICKS
    deadline = None
    if _num(duel.get("ticks_left")) is not None:
        deadline = tick + _num(duel["ticks_left"])
    elif _num(duel.get("deadline")) is not None:
        dl = _num(duel["deadline"])
        deadline = dl if dl >= tick else tick + dl  # absolute tick, or ticks remaining
    if "start" not in st:
        given = _num(duel.get("started_tick", duel.get("start_tick", duel.get("opened_tick"))))
        if given is None and deadline is not None:
            given = min(tick, deadline - span)  # first seen mid-duel: place ourselves on the schedule
        st["start"] = given if given is not None else tick
    start = st["start"]
    if deadline is None:
        deadline = start + span
    st.setdefault("deadline0", deadline)
    return {
        "role": "seller" if role.startswith("sell") else "buyer" if role.startswith("buy") else role,
        "limit": _num(duel.get("your_limit")),
        "rival": _checked_rival(duel, "days" in issues or bool(st.get("needs_days"))),
        "ours": parse_offer(duel.get("your_offer", duel.get("our_offer"))),
        "tick": tick,
        "start": start,
        "deadline": deadline,
        "days": "days" in issues or bool(st.get("needs_days")),
        "w": _num(duel.get("your_days_weight")) or 0.0,
    }


def _checked_rival(duel: dict, use_days: bool):
    """The rival's standing offer from structured fields only, dropped if malformed."""
    off = parse_offer(duel.get("rival_offer"))
    if off is None:
        return None
    if off[1] is not None and not use_days:
        off = (off[0], None)
    return None if valid_offer(off, use_days) not in (None, "no days") else off


# --- the pure negotiator ---------------------------------------------------------------------
def surplus(role: str, limit: float, price: float) -> float:
    return price - limit if role == "seller" else limit - price


def price_for(role: str, limit: float, s: float) -> int:
    """The whole-prima price that gives us surplus `s` (rounded in our favour)."""
    if role == "seller":
        return max(1, int(round(limit + s)))
    return max(1, int(round(limit - s)))


def estimate_pie(role, limit, st, p) -> float:
    """Our best guess of the price pie (the most surplus the rival could ever give us)."""
    r = p["PRIOR_RATIO"]
    prior = limit * r if role == "seller" else limit * r / (1 + r)
    hist = st.get("rival_s", [])
    known = st.get("rival_limit")
    if known is not None:
        # Same scenario seen from the other side: the pie is exact, unless the rival's offers
        # contradict it (they would never offer beyond their own limit).
        pie = surplus(role, limit, known)
        if pie > 0 and (not hist or max(hist) <= pie + 0.5):
            return max(pie, 1.0)
        st["rival_limit"] = None
    if not hist:
        return max(prior, 2.0)
    s_max, s_last = max(hist), hist[-1]
    remaining = 0.0
    steps = [b - a for a, b in zip(hist, hist[1:]) if b - a > 0]
    if len(hist) >= 3 and hist[-1] == hist[-2] == hist[-3]:
        remaining = 0.0  # stuck for two ticks: their offer is near their limit (or they wait for us)
    elif len(steps) >= 2:
        q = min(p["Q_CAP"], steps[-1] / steps[-2]) if steps[-2] > 0 else p["Q_CAP"]
        remaining = steps[-1] * q / (1 - q)
    elif steps:
        remaining = steps[-1] * p["Q_CAP"] / (1 - p["Q_CAP"])
    else:
        remaining = max(0.0, prior - s_last)  # one offer only: trust the prior for the rest
    observed = s_last + remaining
    n = len(hist)
    wobs = n / (n + p["OBS_WEIGHT"])
    est = wobs * observed + (1 - wobs) * prior
    return max(est, s_max + 1, 2.0)


def rival_weight(st, w) -> float:
    """Estimated rival weight per day: sign from the days they ask for, size ~ ours."""
    days = [d for d in st.get("rival_days", []) if d is not None]
    if not days or not w:
        return 0.0
    mean = sum(days) / len(days)
    if abs(mean - DAYS_MAX / 2) < 0.5:
        return 0.0
    sign = 1.0 if mean > DAYS_MAX / 2 else -1.0
    factor = 1.0
    if len(days) >= 2 and abs(days[-1] - days[0]) >= 3:
        factor = 0.5          # they gave ground on days: they care less than us
    elif len(days) >= 3 and len(set(days)) == 1:
        factor = 1.5          # they never move on days: they care
    return sign * abs(w) * factor


def choose_days(w, wr, rival_last_days) -> int:
    joint = w + wr
    if abs(joint) < 1e-9:
        if rival_last_days is not None:
            return int(rival_last_days)
        return DAYS_MAX if w > 0 else 0 if w < 0 else DAYS_MAX // 2
    return DAYS_MAX if joint > 0 else 0


def decide(obs: dict, st: dict, p: dict = PARAMS, decay: float = 0.06) -> dict:
    """One tick of one duel. `st` is the duel's memory (mutated: rival history, our last offer).

    Returns {"accept": bool, "offer": (price, days|None) or None, "why": str, ...}."""
    role, limit = obs["role"], obs["limit"]
    if role not in ("seller", "buyer") or limit is None:
        return {"accept": False, "offer": None, "why": "unknown role/limit", "left": None, "pie": None}
    use_days, w = obs["days"], (obs["w"] if obs["days"] else 0.0)
    T = max(1, obs["deadline"] - obs["start"])
    k = max(0, obs["tick"] - obs["start"])
    left = obs["deadline"] - obs["tick"]

    rival = obs["rival"]
    if rival is not None:
        rp, rd = rival
        if st.get("rival_tick") != obs["tick"]:  # one sample per tick: a repeated price says "stuck"
            st.setdefault("rival_s", []).append(surplus(role, limit, rp))
            st.setdefault("rival_days", []).append(rd)
            st["rival_s"], st["rival_days"] = st["rival_s"][-40:], st["rival_days"][-40:]
            st["rival_tick"] = obs["tick"]

    pie = estimate_pie(role, limit, st, p)
    wr = rival_weight(st, w) if use_days else 0.0
    rival_last_days = st.get("rival_days", [None])[-1] if st.get("rival_days") else None
    d_off = choose_days(w, wr, rival_last_days) if use_days else None
    days_gain = (w * d_off) if use_days else 0.0
    pie_total = pie + (DAYS_MAX * max(0.0, w + wr) if use_days else 0.0)

    # Utility we ask for this tick.
    x = min(1.0, k / max(1e-9, p["ALPHA"] * T))
    open_mult = p["OPEN_KNOWN"] if st.get("rival_limit") is not None else p["OPEN"]
    u_open, u_tgt, u_end = open_mult * pie_total, p["TARGET"] * pie_total, p["END"] * pie_total
    if x < 1.0:
        u = u_open - (u_open - u_tgt) * (x ** p["BETA"])
    else:
        rest = max(1e-9, T - 1 - p["ALPHA"] * T)
        y = min(1.0, (k - p["ALPHA"] * T) / rest)
        u = u_tgt - (u_tgt - u_end) * y
    if st.get("u_last") is not None:
        u = min(u, st["u_last"])  # never go backwards

    s_ask = max(p["MIN_SURPLUS"], u - days_gain)  # price surplus; price always inside our limit

    # The rival's standing offer.
    accept, why = False, ""
    if rival is not None:
        rp, rd = rival
        rs = surplus(role, limit, rp)
        known = (not use_days) or rd is not None
        ru = rs + (w * rd if (use_days and rd is not None) else 0.0)
        inside = rs >= (p["MIN_SURPLUS"] if not use_days else 0) and ru >= p["MIN_SURPLUS"]
        my_next = s_ask + days_gain
        if known and inside:
            if ru >= my_next * (1 - decay) ** p["LOOKAHEAD"]:
                accept, why = True, f"rival gives {ru:.1f} >= our next {my_next:.1f} discounted"
            elif left <= p["LAST_TICKS"]:
                accept, why = True, f"deadline in {left}: take {ru:.1f}"
        # Never ask for less than the rival already offers.
        if known and ru > s_ask + days_gain:
            s_ask = max(s_ask, ru - days_gain)

    price = price_for(role, limit, s_ask)
    s_real = surplus(role, limit, price)
    if s_real < p["MIN_SURPLUS"]:
        price = price_for(role, limit, p["MIN_SURPLUS"])
    st["u_last"] = surplus(role, limit, price) + days_gain
    st["pie_est"] = round(pie_total, 2)
    return {"accept": accept, "offer": (price, d_off), "why": why or f"ask u={st['u_last']:.1f} of pie~{pie_total:.1f}",
            "left": left, "pie": pie_total, "wr": wr}


def verify_accept(duel: dict, obs: dict, our_ids: set):
    """Structural check of the standing offer right before accepting. None = fine, else the reason."""
    use_days = obs["days"]
    raw = parse_offer(duel.get("rival_offer"))
    problem = valid_offer(raw, use_days)
    if problem:
        return problem
    price, days = raw
    role, limit = obs["role"], obs["limit"]
    if limit is None or surplus(role, limit, price) < 0:
        return f"price {price} outside our limit {limit}"
    if obs["rival"] is None or (price, days if use_days else None) != (obs["rival"][0], obs["rival"][1] if use_days else None):
        return "standing offer differs from the one we evaluated"
    if isinstance(duel.get("messages"), list):
        last = latest_rival_offer(duel, our_ids)
        if last is not None and (last[0] != price or (use_days and last[1] != days)):
            return f"standing offer {raw} is not the rival's latest message {last}"
    return None


def redact(d: dict) -> dict:
    """A duel for the log: rival text cleaned and capped, never raw."""
    out = {k: v for k, v in d.items() if k != "messages"}
    msgs = d.get("messages")
    if isinstance(msgs, list):
        try:
            from ..safety import clean
        except Exception:  # noqa: BLE001
            def clean(t):
                return ""
        out["messages"] = [{**{k: v for k, v in m.items() if k != "text"},
                            "text": clean(m.get("text", ""))[:200]} if isinstance(m, dict) else None for m in msgs[-6:]]
    return out


# --- the strategy --------------------------------------------------------------------------
class Strategy:
    name = "duels"

    def tick(self, ctx: Ctx):
        mem = ctx.memory
        mem.setdefault("duels", {})
        mem.setdefault("results", [])
        tick = ctx.clock.get("tick") or 0
        try:
            live = ctx.b.duels().get("duels", []) or []
        except BazaarError as e:
            ctx.journal.set(self.name, {"error": str(e)})
            raise
        duel_ticks = self.session_ticks(ctx, mem)

        our_ids = {str(x) for x in (ctx.me.get("id"), ctx.me.get("team"), ctx.me.get("name")) if x}
        plans = []
        seen = set()
        for d in live:
            did = d.get("id")
            if did is None:
                continue
            seen.add(str(did))
            st = mem["duels"].get(str(did))
            if st is None:
                st = mem["duels"][str(did)] = {"first_tick": tick, "duel_ticks": duel_ticks, "status": "open"}
                ctx.journal.decide(self.name, "first sight", duel=did, raw=redact(d))
            if str(d.get("status", "open")).lower() not in ("open", "live", "active", "running", "negotiating"):
                continue
            self.scan_messages(ctx, d, st, our_ids)
            obs = observe(d, tick, st)
            self.learn_scenario(mem, d, obs, st)
            decay = _num(d.get("decay")) or mem.get("decay") or 0.06
            plan = decide(obs, st, PARAMS, decay)
            plan["duel"], plan["obs"] = did, obs
            if plan["accept"]:
                problem = verify_accept(d, obs, our_ids)
                if problem:
                    plan["accept"], plan["why"] = False, f"not accepting: {problem}"
                    ctx.journal.decide(self.name, "accept blocked", duel=did, reason=problem)
            plans.append(plan)

        # One accept per tick for the whole team: the most urgent duel, then the richest, gets it.
        wants = sorted([pl for pl in plans if pl["accept"]], key=lambda pl: (pl["left"], -(pl["pie"] or 0)))
        accepted = None
        for pl in wants:
            if not ctx.budget.can_accept():
                break
            ctx.budget.use_accept()
            try:
                ctx.write(self.name, "accept", ctx.b.duel_accept, pl["duel"])
                accepted = pl["duel"]
                st = mem["duels"][str(pl["duel"])]
                st["accepted_at"] = tick
                st["accepted_offer"] = list(pl["obs"]["rival"])
                ctx.journal.decide(self.name, "accepted", duel=pl["duel"], offer=pl["obs"]["rival"], why=pl["why"])
            except BazaarError as e:
                ctx.journal.error(self.name, e)
                if e.code == "wait_for_tick":
                    break
            break

        for pl in plans:
            if pl["duel"] == accepted or not pl["offer"]:
                continue
            self.say(ctx, pl)

        self.collect_results(ctx, mem, seen)
        ctx.journal.set(self.name, {
            "tick": tick,
            "live": [{"duel": pl["duel"], "role": pl["obs"]["role"], "limit": pl["obs"]["limit"],
                      "rival": pl["obs"]["rival"], "ours": pl["offer"], "left": pl["left"],
                      "pie_est": round(pl.get("pie") or 0, 1), "accept": pl["accept"], "why": pl["why"]}
                     for pl in plans],
            "results": mem["results"][-12:],
        })

    def scan_messages(self, ctx: Ctx, d: dict, st: dict, our_ids: set):
        """Rival words are untrusted: never parsed for prices or instructions, never sent to an LLM.
        New ones are only scanned, and suspicious ones are remembered (cleaned) for the team."""
        msgs = rival_messages(d, our_ids)
        start = st.get("scanned", 0)
        if start > len(msgs):
            start = 0
        for m in msgs[start:]:
            text = m.get("text")
            if not text:
                continue
            try:
                from .. import safety
                res = safety.scan(text)
                cleaned = safety.clean(text)[:200]
            except Exception:  # noqa: BLE001 - safety is optional; fall back to "do not look"
                continue
            if res.get("suspicious"):
                entry = {"source": "duel", "id": d.get("id"), "labels": res.get("labels", []), "text": cleaned,
                         "tick": ctx.clock.get("tick")}
                sus = ctx.shared.setdefault("suspicious", [])
                if not any(e.get("source") == "duel" and e.get("id") == entry["id"] and e.get("text") == cleaned
                           for e in sus):
                    sus.append(entry)
                    del sus[:-50]
                    ctx.journal.decide(self.name, "suspicious rival message", **entry)
        st["scanned"] = len(msgs)

    def learn_scenario(self, mem: dict, d: dict, obs: dict, st: dict):
        """Every pair plays the same scenario twice with roles swapped: once we have seen an item's limit
        from both sides, the other side's limit is the rival's limit and the pie is known exactly."""
        key = d.get("scenario") or d.get("scenario_id") or d.get("item") or d.get("name")
        if key is None or obs["limit"] is None or obs["role"] not in ("seller", "buyer"):
            return
        sc = mem.setdefault("scenarios", {}).setdefault(str(key), {})
        sc[obs["role"]] = obs["limit"]
        other = sc.get("buyer" if obs["role"] == "seller" else "seller")
        if other is not None and "rival_limit" not in st:
            st["rival_limit"] = other
            mem["scenarios"][str(key)] = sc

    def session_ticks(self, ctx: Ctx, mem: dict) -> int:
        """duel_ticks of the current/next duel session from the schedule (cached), for duels with no deadline."""
        if mem.get("duel_ticks_at") == ctx.clock.get("tick"):
            return mem.get("duel_ticks", DEFAULT_TICKS)
        try:
            sched = ctx.b.schedule()
            now = sched.get("now_hours", 0)
            past = [e for e in sched.get("upcoming", []) + sched.get("past", []) if e.get("action") == "duels"]
            past.sort(key=lambda e: abs(e.get("at_hours", 0) - now))
            if past:
                mem["duel_ticks"] = past[0].get("params", {}).get("duel_ticks", DEFAULT_TICKS)
                mem["decay"] = past[0].get("params", {}).get("decay", 0.06)
        except BazaarError:
            pass
        mem["duel_ticks_at"] = ctx.clock.get("tick")
        return mem.get("duel_ticks", DEFAULT_TICKS)

    def say(self, ctx: Ctx, pl: dict):
        did = pl["duel"]
        st = ctx.memory["duels"][str(did)]
        price, days = pl["offer"]
        sent = st.get("sent", [])
        if sent and sent[-1] == [price, days]:
            return  # our standing offer is unchanged: repeating it adds a round, not information
        if not ctx.budget.can_say(("duel", did)):
            return
        ctx.budget.use_say(("duel", did))
        text = self.text(ctx, st, price, days)
        try:
            ctx.write(self.name, "say", ctx.b.duel_say, did, text, price=price,
                      days=days if pl["obs"]["days"] else None)
        except BazaarError as e:
            if e.code == "missing_days":
                st["needs_days"] = True  # next tick every priced message carries days
            elif e.code not in ("wait_for_tick", "rate_limited"):
                ctx.journal.error(self.name, e)
            return
        if not ctx.dry_run:
            st["sent"] = (sent + [[price, days]])[-30:]

    def text(self, ctx: Ctx, st: dict, price: int, days) -> str:
        try:
            from .. import llm
            fn = getattr(llm, "duel_line", None)
            if fn:
                line = fn(ctx, st, price, days)
                if line:
                    return line
        except Exception as e:  # noqa: BLE001 - words are optional, prices are not
            ctx.journal.error("talk", e)
        used = st.setdefault("lines", [])
        fresh = [i for i in range(len(LINES)) if i not in used[-3:]] or list(range(len(LINES)))
        i = random.choice(fresh)
        used.append(i)
        st["lines"] = used[-10:]
        return LINES[i].format(p=price, d="" if days is None else f", delivery in {days} days")

    def collect_results(self, ctx: Ctx, mem: dict, seen: set):
        """Duels of ours that left the live list are finished: log how they ended (once)."""
        gone = [k for k, st in mem["duels"].items() if st.get("status") == "open" and k not in seen]
        if not gone:
            return
        try:
            done = {str(d.get("id")): d for d in ctx.b.duels(done=True).get("duels", [])}
        except BazaarError as e:
            ctx.journal.error(self.name, e)
            return
        for k in gone:
            st, d = mem["duels"][k], done.get(k)
            if d is None:
                if ctx.clock.get("tick", 0) - st.get("first_tick", 0) > 3 * (st.get("duel_ticks") or DEFAULT_TICKS):
                    st["status"] = "unknown"
                continue
            st["status"] = str(d.get("status", "closed"))
            res = {"duel": k, "role": d.get("role"), "limit": d.get("your_limit"), "status": d.get("status"),
                   "price": d.get("price"), "days": d.get("days"), "captured": d.get("you_captured")}
            mem["results"].append(res)
            ctx.journal.decide(self.name, "result", raw=json.loads(json.dumps(redact(d), default=str)), **res)
