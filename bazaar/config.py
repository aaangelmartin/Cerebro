"""Settings for the whole bazaar package: paths, gateway, models, budgets. Read once at import."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # bazaar/
REPO = ROOT.parent


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


ENV = {**_load_env(REPO / ".env"), **os.environ}

# --- paths -----------------------------------------------------------------
# Tests and simulator runs never touch the real bot's data: they get their own folder unless told otherwise.
_TESTING = "unittest" in (sys.argv[0] if sys.argv else "")
_SIM = "--sim" in sys.argv
if ENV.get("BAZAAR_DATA_DIR"):
    DATA = Path(ENV["BAZAAR_DATA_DIR"])
elif _TESTING:
    DATA = Path(tempfile.mkdtemp(prefix="bazaar-test-"))
elif _SIM:
    DATA = ROOT / "data" / "sim"
else:
    DATA = ROOT / "data"
LIVE = DATA / "live"            # everything the running bot writes
FRIDAY = ROOT / "data" / "friday"   # read-only material from Friday (shared by live, sim and tests)
LAB = DATA / "lab"              # lessons, hypotheses, backtests, shadow runs
STOP_FILE = ROOT / "STOP"       # touch to stop every write at once
# API money is real even in a simulation: one spend ledger for everything except unit tests.
SPEND_FILE = (LIVE if _TESTING else ROOT / "data" / "live") / "llm_spend.json"
for _d in (LIVE, LAB):
    _d.mkdir(parents=True, exist_ok=True)

# --- gateway (the only door to the Bazaar) ----------------------------------
GATEWAY_URL = ENV.get("BAZAAR_GATEWAY_URL", "http://127.0.0.1:8787").rstrip("/")
GATEWAY_TOKEN = ENV.get("BAZAAR_GATEWAY_TOKEN") or ENV.get("GATEWAY_TOKEN", "")
PUBLIC_URL = "https://bazaar.causaprima.ai"
# Real writes need this AND the operator's arm switch. Tests and sims never set it.
ALLOW_REAL = ENV.get("BAZAAR_ALLOW_REAL") == "1"

# --- models -----------------------------------------------------------------
OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-4-5-20251001"
DEGRADE_LADDER = [OPUS, SONNET, HAIKU]
# USD per million tokens (input, output). Cache reads cost 10% of input, cache writes 125%.
PRICES = {OPUS: (4.0, 20.0), SONNET: (2.0, 10.0), HAIKU: (1.0, 5.0)}


def anthropic_keys() -> list[tuple[str, str]]:
    """[(label, key)] for the router: ANTHROPIC_API_KEY_A/_B/_C, else ANTHROPIC_API_KEY."""
    keys = [(s, ENV[f"ANTHROPIC_API_KEY_{s}"]) for s in "ABC" if ENV.get(f"ANTHROPIC_API_KEY_{s}")]
    if ENV.get("ANTHROPIC_API_KEY") and ENV["ANTHROPIC_API_KEY"] not in {k for _, k in keys}:
        if "A" not in {lbl for lbl, _ in keys}:
            keys.insert(0, ("A", ENV["ANTHROPIC_API_KEY"]))   # the original key stays in the pool
        else:
            keys.append(("D", ENV["ANTHROPIC_API_KEY"]))
    return keys


KEY_CAP_USD = float(ENV.get("BAZAAR_KEY_CAP_USD", "100"))     # hard cap per key, whole weekend
DAY_CAP_USD = float(ENV.get("BAZAAR_DAY_CAP_USD", "130"))     # all keys together, per Madrid day (default)
DAY_CAP_MIN_USD, DAY_CAP_MAX_USD = 20.0, 200.0                 # control.json "day_cap" is clamped to this range


def madrid_day(now: float | None = None) -> str:
    """'fri' | 'sat' | 'sun' | ... for the Madrid calendar day (the key the spend file uses)."""
    import time as _time
    from datetime import datetime, timezone, timedelta
    try:
        from zoneinfo import ZoneInfo
        d = datetime.fromtimestamp(now or _time.time(), ZoneInfo("Europe/Madrid"))
    except Exception:  # noqa: BLE001
        d = datetime.fromtimestamp(now or _time.time(), timezone(timedelta(hours=2)))
    return d.strftime("%a").lower()


def day_cap_usd() -> float:
    """Today's total cap, clamped to the hard limits: control.json "day_cap" when the team set one; else today's
    share of the event budget, which the brain's governor writes to brain_budget.json; else DAY_CAP_USD."""
    import json as _json

    def _load(name):
        try:
            return _json.loads((LIVE / name).read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            return {}
    ctl = _load("control.json")
    v = ctl.get("day_cap") if ctl.get("caps_day") in (None, madrid_day()) else None   # a hand-set cap lasts one day
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        st = _load("brain_budget.json")
        v = st.get("day_cap_today") if st.get("day") == madrid_day() else None
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return DAY_CAP_USD
    return max(DAY_CAP_MIN_USD, min(DAY_CAP_MAX_USD, float(v)))


DEGRADE_AT = 0.97                                              # share of the day cap that steps Opus -> Sonnet
DEGRADE_HAIKU_AT = 0.99                                        # share of the day cap that steps Sonnet -> Haiku
# Effective day cap = min(DAY_CAP_USD, budget left at the start of the day across live keys x share of the day).
# Saturday may use 55 % of what is left, Sunday everything, Friday/other days 10 %. With one $100 key this keeps
# about $45 for Sunday instead of letting Saturday burn it all. Past 100 % of the effective cap: code only.
DAY_SHARE = {"sat": 0.55, "sun": 1.0, "*": 0.1}

# --- timing -----------------------------------------------------------------
DECISION_DEADLINE = 0.55        # share of the tick after which the fallback is sent
RACE_DAYS = {"sun"}             # days when Opus races Sonnet (decision: only Sunday's 15 s ticks)

# --- money rails --------------------------------------------------------------
CASH_RESERVE = int(ENV.get("BAZAAR_CASH_RESERVE", "15"))   # round-4 strategy: after the venue only ~66 P remain
MAX_SPEND_PER_DEAL = int(ENV.get("BAZAAR_MAX_SPEND_PER_DEAL", "120"))
MAX_SPEND_PER_HOUR = int(ENV.get("BAZAAR_MAX_SPEND_PER_HOUR", "250"))
BIG_DEAL_P = int(ENV.get("BAZAAR_BIG_DEAL_P", "25"))   # buys at or above this (and every goal buy) go to the council

# --- ports --------------------------------------------------------------------
API_PORT = int(ENV.get("BAZAAR_API_PORT", "8791"))   # control + telemetry for the new dashboard
SIM_PORT = int(ENV.get("BAZAAR_SIM_PORT", "8797"))   # the fake Bazaar for tests
