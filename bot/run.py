"""Run the bot: one pass of every strategy per tick.

    python3 -m bot.run                 # dry run: decides and logs, sends nothing
    python3 -m bot.run --live          # plays for real
    python3 -m bot.run --live --only dealer,duels

Stop it with Ctrl-C, or from anywhere by creating bot/STOP (touch bot/STOP); delete it to resume.
Each strategy is a module in bot/strategies/ exposing a class `Strategy` with `name` and
`tick(ctx)`; its `ctx.memory` survives ticks and restarts (bot/data/memory.json).
"""

from __future__ import annotations

import argparse
import importlib
import json
import time
import traceback

from .control import Control
from .core import (DATA, REAL_GATEWAY, STOP_FILE, BazaarError, Ctx, Journal, TickBudget, Values, Wallet, gateway_url,
                   load_env, make_client)

DEFAULT_STRATEGIES = ["duels", "dealer", "market"]  # priority order: duels decay fastest
MEMORY = DATA / "memory.json"


def load_memory() -> dict:
    try:
        return json.loads(MEMORY.read_text())
    except (OSError, ValueError):
        return {}


def save_memory(mem: dict):
    tmp = MEMORY.with_suffix(".tmp")
    tmp.write_text(json.dumps(mem, ensure_ascii=False, indent=1))
    tmp.replace(MEMORY)


def load_strategies(names):
    out = []
    for name in names:
        try:
            out.append(importlib.import_module(f"bot.strategies.{name}").Strategy())
        except ModuleNotFoundError as e:
            print(f"strategy {name!r} not available yet: {e}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="send real actions (default: dry run)")
    ap.add_argument("--only", default=",".join(DEFAULT_STRATEGIES), help="comma-separated strategies")
    ap.add_argument("--once", action="store_true", help="run a single pass and exit")
    args = ap.parse_args()

    env = load_env()
    real = gateway_url(env) == REAL_GATEWAY
    if args.live and real and env.get("BOT_ALLOW_REAL") != "1":
        raise SystemExit("Refusing to play the REAL game: set BOT_ALLOW_REAL=1 to confirm, or point "
                         "BOT_GATEWAY_URL at the simulator (python3 -m bot.sim.fake_bazaar).")
    b = make_client(env)
    journal = Journal()
    control = Control(DATA)
    strategies = load_strategies([s.strip() for s in args.only.split(",") if s.strip()])
    memory = load_memory()
    catalog, catalog_at = None, 0.0
    last_tick = None
    print(f"bot starting: {'LIVE' if args.live else 'DRY RUN'} on {'REAL GAME' if real else gateway_url(env)} · strategies {[s.name for s in strategies]}", flush=True)

    while True:
        if STOP_FILE.exists():
            journal.flush(mode="stopped", live=args.live)
            time.sleep(5)
            continue
        try:
            clock = b.clock()
            if clock.get("paused") or clock.get("doors") != "open":
                journal.flush(mode="waiting", live=args.live, clock=clock)
                time.sleep(min(60, max(5, clock.get("next_tick_in") or 30)))
                continue
            if clock["tick"] == last_tick and not args.once:
                time.sleep(max(0.5, min(clock.get("next_tick_in", 5), 10)))
                continue
            if catalog is None or time.time() - catalog_at > 300:
                catalog, catalog_at = b.catalog(), time.time()
            me = b.me()
            op = control.state()
            armed = args.live and op["armed"]  # live play needs --live AND the operator's arm switch
            ctx = Ctx(b=b, me=me, clock=clock, catalog=catalog, values=Values(me, catalog),
                      budget=TickBudget(clock), journal=journal, dry_run=not armed, env=env,
                      control=control if armed else None,
                      wallet=Wallet(memory.setdefault("_wallet", {}), env, me))
            ctx.shared = memory.setdefault("_shared", {})
            for s in strategies:
                ctx.memory = memory.setdefault(s.name, {})
                try:
                    s.tick(ctx)
                except BazaarError as e:
                    journal.error(s.name, e)
                except Exception as e:  # noqa: BLE001 - one bad strategy must not stop the others
                    journal.error(s.name, e)
                    traceback.print_exc()
            save_memory(memory)
            from .intel import write as write_intel
            write_intel(ctx, memory, DATA / "intel.json")
            last_tick = clock["tick"]
            journal.flush(mode="running" if armed else "disarmed", live=args.live, armed=armed,
                          operator=op, real=real, tick=clock["tick"], cash=me.get("cash"),
                          level=me.get("level"), score=me.get("score"),
                          suspicious=ctx.shared.get("suspicious", [])[-10:],
                          wallet=ctx.wallet.view(me.get("cash", 0)))
            if args.once:
                return
        except BazaarError as e:
            journal.error("loop", e)
            time.sleep(5)
        except KeyboardInterrupt:
            journal.flush(mode="stopped", live=args.live)
            return


if __name__ == "__main__":
    main()
