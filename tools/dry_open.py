"""Dry run of the bot's first ticks on Sunday, on a COPY of today's real data. Sends nothing, calls no model.

    .venv/bin/python tools/dry_open.py                 # every scenario
    .venv/bin/python tools/dry_open.py jump jump_cash  # only these

It copies bazaar/data (live files, the recorder's latest snapshot, the lab) to a temp folder, serves the recorded
snapshot through a fake gateway with the clock, the cash and the catalog of each scenario, and runs the real
domains, arbiter and rails for a few ticks in dry-run mode. Then it checks the team's standing rules on every
action that passed the rails and prints what the bot would do. Exit code 1 when a rule is broken.

Scenarios:
  jump        09:00, the clock jumped to h16.65: round 3, Chamberí released, cash as it is (340)
  jump_cash   the same three minutes later: +150 P
  no_jump     09:00, the clock did not jump: round 2 at h13.37
  plan        `jump_cash` with the brain's last plan taken as fresh (it is ignored when older than 30 minutes)
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "bazaar" / "data"

# --- the copy and the environment come BEFORE any bazaar import: config reads them once ---------------------------
TMP = Path(tempfile.mkdtemp(prefix="bazaar-dry-open-"))
for name in ("live", "lab"):
    if (SRC / name).is_dir():
        shutil.copytree(SRC / name, TMP / name, ignore=shutil.ignore_patterns("*.out", "*.lock*", "*.pid", "llm.jsonl",
                                                                              "plaza*"))
(TMP / "record").mkdir()
shutil.copytree(SRC / "record" / "latest", TMP / "record" / "latest")
os.environ["BAZAAR_DATA_DIR"] = str(TMP)
os.environ["BAZAAR_ALLOW_REAL"] = "0"
for _k in ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_A", "ANTHROPIC_API_KEY_B", "ANTHROPIC_API_KEY_C"):
    os.environ[_k] = ""                                  # no key, no model call: the code decides
sys.path.insert(0, str(REPO))

from bazaar import config, run as R                       # noqa: E402
from bazaar.core.ledger import Ledger                     # noqa: E402
from bazaar.core.state import perceive                    # noqa: E402

LATEST = TMP / "record" / "latest"
PER_DEAL, PER_HOUR, RESERVE = 210, 550, 5


def _j(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


class SnapGW:
    """A read-only gateway over the recorder's latest snapshot. Writes are recorded, never sent."""

    def __init__(self, clock: dict, cash: int, release: tuple = ()):
        self.clock_doc, self.cash, self.sent = clock, cash, []
        self.cat = _j(LATEST / "catalog.json", {})
        for s in self.cat.get("sets") or []:
            if s.get("id") in release:
                s["released"] = True
        self.me_doc = _j(LATEST / "me.json", {})
        self.exact = {k: v.get("value") for k, v in (_j(TMP / "live" / "exact_values.json", {}) or {}).items()
                      if isinstance(v, dict) and not v.get("count")}

    # the value of ONE MORE copy, as /api/me/value gives it
    def value(self, ref: str):
        held = sum(1 for a in self.me_doc.get("assets") or [] if a.get("ref") == ref)
        if not held and ref in self.exact:
            return float(self.exact[ref])
        for s in self.cat.get("sets") or []:
            for c in s.get("cards") or []:
                if c.get("id") == ref:
                    aff = float((self.me_doc.get("affinity") or {}).get(s["id"], 1.0))
                    marg = (self.cat.get("values") or {}).get("copy_marginals") or [1.0, 0.25, 0.1]
                    return round(float(c.get("book") or 0) * aff * (marg[held] if held < len(marg) else 0.0), 2)
        return None

    def me(self):
        return self.get("/api/me")

    def clock(self):
        return self.get("/api/clock")

    def get(self, path: str, timeout=None, **params):
        path = path.split("?")[0]
        if path == "/api/clock":
            return dict(self.clock_doc)
        if path == "/api/me":
            return {**self.me_doc, "cash": self.cash, "tick": self.clock_doc["tick"],
                    "tick_seconds": self.clock_doc["tick_seconds"]}
        if path == "/api/me/value":
            v = self.value(str(params.get("card")))
            return {"card": params.get("card"), "your_value": v} if v is not None else {}
        if path == "/api/me/threads":
            return {"threads": []}
        if path == "/api/me/offers":
            return {"offers": []}                          # 19999 expires in tick 1446: nothing of ours is open
        if path in ("/api/duels", "/api/feed"):
            return {"duels": [], "events": []}
        if path == "/api/catalog":
            return self.cat
        if path == "/api/dealers":
            return _j(LATEST / "dealers.json", {})
        if path.startswith("/api/dealers/"):
            return _j(LATEST / "dealers" / (path.rsplit("/", 1)[1] + ".json"), {})
        if path in ("/api/levels", "/api/schedule", "/api/venues", "/api/leaderboard"):
            return _j(LATEST / (path.rsplit("/", 1)[1] + ".json"), {})
        if path.startswith("/api/venues/") and path.endswith("/offers"):
            return _j(LATEST / "books" / (path.split("/")[3] + ".json"), {"offers": []})
        return {}

    def post(self, path, body=None, **kw):
        self.sent.append(("POST", path, body))
        return {"id": 900000 + len(self.sent), "status": "open"}

    patch = delete = post


def clock(tick: int, t_hours: float, rnd: int, name: str) -> dict:
    base = _j(LATEST / "clock.json", {})
    return {**base, "tick": tick, "t_hours": t_hours, "tick_seconds": 15.0, "paused": False, "doors": "open",
            "next_tick_in": 14.0, "round": rnd, "round_name": name, "today": "sun", "today_name": "Sunday"}


SCENARIOS = {
    "jump": dict(t=16.65, rnd=3, name="Sunday · Chamberí", cash=340, release=("CHA",), plan=False),
    "jump_cash": dict(t=16.70, rnd=3, name="Sunday · Chamberí", cash=490, release=("CHA",), plan=False),
    "no_jump": dict(t=13.37, rnd=2, name="Saturday · Gran Vía", cash=340, release=(), plan=False),
    "plan": dict(t=16.70, rnd=3, name="Sunday · Chamberí", cash=490, release=("CHA",), plan=True),
}


def _refs(side: dict, assets: dict) -> list[str]:
    out = [assets.get(a.get("id") if isinstance(a, dict) else a, {}).get("ref") or (a.get("ref") if isinstance(a, dict)
                                                                                 else None)
           for a in (side or {}).get("assets") or []]
    out += [str(t).partition(":")[2] for t in (side or {}).get("types") or []]
    out += list((side or {}).get("cards") or [])
    return [r for r in out if r]


def check(action: dict, gw: SnapGW, control: dict) -> list[str]:
    """The team's standing rules, on one action that passed the rails."""
    p, bad = action.get("params") or {}, []
    assets = {a.get("id"): a for a in gw.me_doc.get("assets") or []}
    protected = {str(x) for x in control.get("protected") or []}
    give, want = p.get("give") or {}, p.get("want") or {}
    text = json.dumps(action, ensure_ascii=False).lower()
    gives = _refs(give, assets) + _refs((p.get("offer") or {}).get("give") or {}, assets) + \
        [r for r in [((p.get("sell") or {}) if isinstance(p.get("sell"), dict) else {}).get("card")] if r]
    for r in gives:
        if r in protected or str(next((i for i, a in assets.items() if a.get("ref") == r), "")) in protected:
            bad.append(f"gives the protected card {r}")
    if str(p.get("to") or p.get("with") or "") == "t06":
        bad.append("deals with Team 6")
    if str(p.get("with") or p.get("dealer") or "") == "banco":
        bad.append("opens Don Ernesto without Ángel's OK")
    if "sobre_" in text or '"pack"' in text:
        bad.append("touches a pack")
    cash_out = int(give.get("cash") or 0) or int(((p.get("buy") or {}) if isinstance(p.get("buy"), dict) else {})
                                                 .get("max_price") or p.get("max_price") or 0)
    if cash_out > PER_DEAL:
        bad.append(f"spends {cash_out} P in one deal (cap {PER_DEAL})")
    for r in _refs(want, assets) + [x for x in [((p.get("buy") or {}) if isinstance(p.get("buy"), dict) else {})
                                                .get("card")] if x]:
        v = gw.value(r)
        if cash_out and v is not None and cash_out > v:
            bad.append(f"pays {cash_out} P for {r}, worth {v} to us")
    return bad


def play(name: str, ticks: int = 3) -> tuple[list[dict], list[str]]:
    sc = SCENARIOS[name]
    live = TMP / f"live-{name}"
    shutil.copytree(TMP / "live", live)
    config.LIVE = live                                      # the domains read their files from here
    doc = _j(live / "strategy.json", {})
    if doc:                                                 # at 09:00 the night's plan is hours old: stale, ignored
        doc["updated"] = time.time() - (0 if sc["plan"] else 5 * 3600)
        (live / "strategy.json").write_text(json.dumps(doc))
    gw = SnapGW(clock(1446, sc["t"], sc["rnd"], sc["name"]), sc["cash"], sc["release"])
    domains = R.load_domains(gw=gw)
    for d in domains:
        d.use_llm = False
    runner = R.Runner(gw, domains=domains, mode="live", live=live, make_write_gw=None, ledger=Ledger(live),
                      rails=R._import("bazaar.core.rails"), executor=R._import("bazaar.core.executor"),
                      arbiter=R._import("bazaar.core.arbiter"), council=None,
                      control_defaults=R.DEFAULT_CONTROL)
    control = runner.control()
    rows, broken, prev = [], [], None
    for i in range(ticks):
        gw.clock_doc["tick"] = 1446 + i
        gw.clock_doc["t_hours"] = round(sc["t"] + i / 240.0, 4)
        sit = perceive(gw, prev, live=live, clock=gw.clock())
        report = runner.step(sit)
        prev = sit
        for a in report.get("actions") or []:
            act = a.get("action") or a
            ok = (a.get("verdict") or {}).get("ok", a.get("status") not in ("vetoed",))
            row = {"tick": sit.tick, "domain": act.get("domain"), "kind": act.get("kind"),
                   "params": act.get("params"), "why": str(act.get("reason") or act.get("why") or "")[:140],
                   "status": a.get("status"), "veto": (a.get("verdict") or {}).get("code") or a.get("code")}
            rows.append(row)
            if ok and act.get("kind") != "noop":
                broken += [f"{name} t{sit.tick} {act.get('domain')}.{act.get('kind')}: {b}"
                           for b in check(act, gw, control)]
    for d in runner.pools.values():
        d.shutdown(wait=False)
    if gw.sent:
        broken.append(f"{name}: {len(gw.sent)} write(s) reached the gateway in a dry run")
    return rows, broken


def main(argv: list[str]) -> int:
    names = argv or list(SCENARIOS)
    all_broken = []
    for name in names:
        rows, broken = play(name)
        all_broken += broken
        sc = SCENARIOS[name]
        print(f"\n=== {name}: h{sc['t']} round {sc['rnd']} cash {sc['cash']} P "
              f"{'with the brain plan' if sc['plan'] else 'no plan (code only)'} ===")
        if not rows:
            print("  (the bot would do nothing)")
        for r in rows:
            p = copy.deepcopy(r["params"] or {})
            print(f"  t{r['tick']} {r['domain']}.{r['kind']} [{r['status']}{' ' + str(r['veto']) if r['veto'] else ''}] "
                  f"{json.dumps(p, ensure_ascii=False)[:230]}  // {r['why']}")
    print("\nRULES:", "all kept" if not all_broken else "BROKEN")
    for b in all_broken:
        print("  -", b)
    print(f"(data copy: {TMP})")
    return 1 if all_broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
