"""Offline checks of the duels strategy against a fake gateway: python3 -m bot.tests.test_duels"""

from __future__ import annotations

import random

from bot.core import BazaarError, Ctx, Journal, TickBudget
from bot.strategies.duels import PARAMS, Strategy, decide, parse_offer


class FakeB:
    def __init__(self, duels):
        self._duels, self.sent, self.accepted = duels, [], []

    def duels(self, done=False):
        return {"duels": [] if done else self._duels}

    def schedule(self):
        return {"now_hours": 2.0, "upcoming": [{"action": "duels", "at_hours": 2.0,
                                                 "params": {"duel_ticks": 12, "decay": 0.06}}]}

    def duel_say(self, did, text="", price=None, days=None):
        if any(d["id"] == did and "days" in (d.get("issues") or []) for d in self._duels) and days is None:
            raise BazaarError("missing_days")
        self.sent.append((did, price, days, text))
        return {}

    def duel_accept(self, did):
        self.accepted.append(did)
        return {}


class QuietJournal(Journal):
    """Keeps the real bot/data journal clean."""

    def __init__(self):
        self.status, self.log = {"strategies": {}, "errors": []}, []

    def decide(self, strategy, action, **info):
        self.log.append((action, info))

    def error(self, strategy, err):
        self.log.append(("error", str(err)))


def ctx_for(b, tick, memory, dry=False):
    clock = {"tick": tick, "limits": {"accepts_per_team_per_tick": 1}}
    return Ctx(b=b, me={}, clock=clock, catalog={}, values=None, budget=TickBudget(clock), journal=QuietJournal(),
               dry_run=dry, env={}, memory=memory)


def test_parse():
    assert parse_offer(None) is None
    assert parse_offer(60) == (60.0, None)
    assert parse_offer({"price": 60, "days": 3}) == (60.0, 3)
    assert parse_offer({"offer": {"price": 61, "days": 0}}) == (61.0, 0)
    assert parse_offer({"text": "hi"}) is None


def test_tick_paths():
    duels = [
        {"id": 1, "role": "seller", "your_limit": 50, "rival_offer": None, "deadline": 112, "item": "X"},
        {"id": 2, "role": "buyer", "your_limit": 90, "rival_offer": {"price": 70}, "deadline": 101, "item": "X"},
        {"id": 3, "role": "buyer", "your_limit": 80, "rival_offer": {"price": 60, "days": 2}, "deadline": 112,
         "issues": ["price", "days"], "your_days_weight": -1.5},
        {"id": 4, "role": "weird"},  # missing fields: skipped quietly
        {"id": 5, "role": "seller", "your_limit": 50, "rival_offer": 40, "deadline": 101},  # outside our limit
    ]
    b = FakeB(duels)
    mem = {}
    Strategy().tick(ctx_for(b, 100, mem))
    assert b.accepted == [2], b.accepted          # deadline near, inside our limit -> the one accept
    said = {d: (p, days) for d, p, days, _ in b.sent}
    assert 1 in said and said[1][0] > 50          # seller asks above cost
    assert said[3][1] is not None                 # days always sent when issues include days
    assert said[3][0] <= 80                       # buyer never bids above value
    assert 5 in said and said[5][0] >= 51         # never concede below cost
    assert mem["scenarios"]["X"] == {"seller": 50, "buyer": 90}


def test_limits_fuzz():
    rng = random.Random(0)
    for _ in range(3000):
        role = rng.choice(["seller", "buyer"])
        limit = rng.uniform(5, 200)
        st, T = {}, rng.randint(4, 16)
        use_days = rng.random() < 0.5
        w = rng.uniform(-3, 3) if use_days else 0
        for k in range(T):
            rival = (rng.uniform(1, 300), rng.randint(0, 10) if use_days else None) if rng.random() < 0.8 else None
            obs = {"role": role, "limit": limit, "rival": rival, "ours": None, "tick": k, "start": 0, "deadline": T,
                   "days": use_days, "w": w}
            pl = decide(obs, st, PARAMS, 0.06)
            price, days = pl["offer"]
            assert (price >= limit + 0.5) if role == "seller" else (price <= limit - 0.5), (role, limit, price)
            assert (days is not None) == use_days
            if pl["accept"]:
                rp = rival[0]
                assert (rp >= limit) if role == "seller" else (rp <= limit), (role, limit, rp)


def test_injection():
    from bot.tests.sim_duels import injection_check
    assert injection_check()


if __name__ == "__main__":
    test_injection()
    test_parse()
    test_tick_paths()
    test_limits_fuzz()
    print("ok")
