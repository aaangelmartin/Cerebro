"""Practice: the bot plays episode after episode against the fake Bazaar and tunes its dealer knobs.

    .venv/bin/python -m bot.sim.practice                # runs until stopped (Ctrl-C or touch bot/sim/STOP_PRACTICE)
    .venv/bin/python -m bot.sim.practice --episodes 10

Each episode starts a fresh fake Bazaar (new seed; every other one negotiates delivery days in
duels), runs the real bot code live against it for a fixed number of ticks, and scores:

- dealer: the share of each dealer's true price range we captured (the simulator knows the limits);
- duels: our pie share discounted by the rounds it took (no deal = 0);
- market: the private-value gain the market strategy reports.

Dealer knobs are chosen epsilon-greedily from a small grid, so the best combination so far is
replayed most of the time and the others keep being explored. Results go to
bot/sim/practice/episodes.jsonl and the current ranking to bot/sim/practice/best.json.

Caveat: the fake dealers follow our own model of the real ones, so tuned numbers are a starting
point to check against the real game, not ground truth.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "practice"
STOP = HERE / "STOP_PRACTICE"
PY = sys.executable

GRID = {
    "OPEN_FRACTION": [0.30, 0.40, 0.50],
    "CONCEDE": [0.12, 0.18, 0.22, 0.30],
    "OPEN_MULTIPLE": [1.8, 2.2, 2.8],
}
COMBOS = [dict(zip(GRID, vals)) for vals in itertools.product(*GRID.values())]
EPSILON = 0.3


def key(combo: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in sorted(combo.items()))


def load_stats() -> dict:
    try:
        return json.loads((OUT / "stats.json").read_text())
    except (OSError, ValueError):
        return {}


def choose(stats: dict, rng: random.Random) -> dict:
    untried = [c for c in COMBOS if key(c) not in stats]
    if untried and rng.random() < 0.5:
        return rng.choice(untried)
    if not stats or rng.random() < EPSILON:
        return rng.choice(COMBOS)
    best = max(stats, key=lambda k: stats[k]["mean"])
    return dict((kv.split("=")[0], float(kv.split("=")[1])) for kv in best.split(","))


def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=10).read())


def episode(n: int, combo: dict, args) -> dict:
    port, data = args.port, OUT / "run"
    shutil.rmtree(data, ignore_errors=True)
    days = n % 2 == 1
    sim = subprocess.Popen([PY, "-m", "bot.sim.fake_bazaar", "--port", str(port), "--tick", str(args.tick),
                            "--seed", str(n)] + (["--days"] if days else []), cwd=REPO,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = {**os.environ, "BOT_GATEWAY_URL": f"http://127.0.0.1:{port}", "BOT_GATEWAY_TOKEN": "sim",
           "BOT_DATA_DIR": str(data), "BOT_PROBE": "1" if args.probe else "0", "ANTHROPIC_API_KEY": "",
           **{f"BOT_DEALER_{k}": str(v) for k, v in combo.items()}}
    time.sleep(1.5)
    bot = subprocess.Popen([PY, "-m", "bot.run", "--live"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(args.ticks * args.tick + 2)
        state = get(f"http://127.0.0.1:{port}/sim/state")
    finally:
        bot.terminate()
        sim.terminate()
        bot.wait(5)
        sim.wait(5)
    captures = [s["capture"] for s in state["settled"] if "capture" in s]
    duels = [d for d in state["duels"]]
    duel_scores = [(d.get("share", 0) * (1 - d.get("decay", 0.06)) ** d.get("round", 0)) if d["status"] == "deal" else 0
                   for d in duels]
    try:
        status = json.loads((data / "status.json").read_text())
        market_gain = status["strategies"].get("market", {}).get("gain_total", 0)
        errors = len(status.get("errors", []))
    except (OSError, ValueError, KeyError):
        market_gain, errors = 0, None
    dealer = sum(captures) / len(captures) if captures else 0.0
    duel = sum(duel_scores) / len(duel_scores) if duel_scores else 0.0
    return {"episode": n, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "days": days, "combo": combo,
            "dealer_capture": round(dealer, 3), "dealer_deals": len(captures),
            "duel_score": round(duel, 3), "duels_closed": sum(1 for d in duels if d["status"] == "deal"),
            "duels": len(duels), "market_gain": market_gain, "cash_end": state["cash"], "errors": errors}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=0, help="0 = until stopped")
    ap.add_argument("--ticks", type=int, default=40, help="ticks per episode")
    ap.add_argument("--tick", type=float, default=1.0, help="seconds per simulated tick")
    ap.add_argument("--port", type=int, default=8796)
    ap.add_argument("--probe", action="store_true", help="also practise dealer probes")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    rng = random.Random()
    stats = load_stats()
    n = max([int(l.split('"episode": ')[1].split(",")[0]) for l in (OUT / "episodes.jsonl").read_text().splitlines()]
            or [0]) + 1 if (OUT / "episodes.jsonl").exists() else 1
    done = 0
    while not STOP.exists() and (not args.episodes or done < args.episodes):
        combo = choose(stats, rng)
        res = episode(n, combo, args)
        with (OUT / "episodes.jsonl").open("a") as f:
            f.write(json.dumps(res) + "\n")
        if res["dealer_deals"]:
            s = stats.setdefault(key(combo), {"n": 0, "mean": 0.0})
            s["n"] += 1
            s["mean"] += (res["dealer_capture"] - s["mean"]) / s["n"]
        (OUT / "stats.json").write_text(json.dumps(stats, indent=1))
        ranking = sorted(({"combo": k, **v} for k, v in stats.items()), key=lambda r: -r["mean"])
        (OUT / "best.json").write_text(json.dumps({"updated": res["at"], "episodes": n, "top": ranking[:5]}, indent=1))
        print(f"ep {n} {key(combo)} dealer {res['dealer_capture']} ({res['dealer_deals']} deals) "
              f"duels {res['duel_score']} ({res['duels_closed']}/{res['duels']}) market +{res['market_gain']} "
              f"errors {res['errors']}", flush=True)
        n += 1
        done += 1


if __name__ == "__main__":
    main()
