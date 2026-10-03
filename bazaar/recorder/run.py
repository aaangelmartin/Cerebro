"""The recorder process: records the whole game (public and our private state) under config.DATA/record/.

    .venv/bin/python -m bazaar.recorder.run                                     # live: public API + gateway
    .venv/bin/python -m bazaar.recorder.run --url http://127.0.0.1:8797 --token sim   # against sim/fake_bazaar
    .venv/bin/python -m bazaar.recorder.run --seconds 60                        # stop after a minute (tests)

Read-only by construction (client.py has no write verb). Live mode holds the singleton pidfile
data/live/recorder.pid and writes the heartbeat data/live/recorder_status.json (`updated`, `state`) every loop,
so the supervisor can restart it. SIGTERM/SIGHUP/Ctrl-C save the state and exit cleanly.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from .. import config
from .client import KEYED_RPS, PUBLIC_RPS, Lane
from .core import Recorder
from .store import Store, write_json

HEARTBEAT_EVERY_S = 2.0
INDEX_EVERY_S = 30.0


class _Stop(BaseException):
    pass


def build(url: str | None = None, token: str | None = None, public_url: str | None = None,
          root: Path | None = None, cards: bool = True) -> Recorder:
    keyed_url = (url or config.GATEWAY_URL).rstrip("/")
    tok = config.GATEWAY_TOKEN if token is None else token
    # Live: public reads go straight to the public API (keyless, its own budget); against a local sim, to the sim.
    pub = public_url or (keyed_url if url else config.PUBLIC_URL)
    public = Lane("public", pub, PUBLIC_RPS, burst=2.0)
    keyed = Lane("keyed", keyed_url, KEYED_RPS, headers={"X-Team-Key": tok}, burst=1.0) if tok else None
    store = Store(root or (config.DATA / "record"))
    links = {"broker_bench": str(config.LIVE / "bench"), "broker_status": str(config.LIVE / "broker_status.json"),
             "bot_ledger": str(config.LIVE), "lab": str(config.LAB)}
    return Recorder(store, public, keyed, links=links, cards=cards)


def loop(rec: Recorder, status_file: Path, seconds: float | None = None) -> None:
    t_end = time.time() + seconds if seconds else None
    hb_at = idx_at = 0.0
    while t_end is None or time.time() < t_end:
        try:
            rec.step()
        except Exception as e:  # noqa: BLE001 - the recorder never dies on a bad read
            rec._err("step", e)
        now = time.time()
        if now - hb_at >= HEARTBEAT_EVERY_S:
            hb_at = now
            try:
                write_json(status_file, rec.status())
            except OSError:
                pass
        if now - idx_at >= INDEX_EVERY_S:
            idx_at = now
            try:
                rec.store.write_index({"links": rec.links, "recorder_status": str(status_file)})
            except OSError as e:
                rec._err("index", e)
        time.sleep(rec.next_wait())


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Team 10 data recorder (read-only)")
    ap.add_argument("--url", help="gateway or fake_bazaar URL (default config.GATEWAY_URL)")
    ap.add_argument("--token", help="X-Team-Key (default config.GATEWAY_TOKEN; '' disables keyed reads)")
    ap.add_argument("--public-url", help="keyless base URL (default: public API live, --url against a sim)")
    ap.add_argument("--seconds", type=float, help="stop after this many seconds")
    ap.add_argument("--no-cards", action="store_true", help="skip the hourly card-history sweep")
    a = ap.parse_args(argv)

    live = not a.url or a.url.rstrip("/") == config.GATEWAY_URL
    if live:
        from ..supervise import singleton
        singleton("recorder")                  # a second live recorder exits here with a clear message
    rec = build(a.url, a.token, a.public_url, cards=not a.no_cards)
    status_file = config.LIVE / "recorder_status.json" if live else rec.store.root / "recorder_status.json"

    def _handler(signum, _frame):
        raise _Stop(signum)
    for sig_ in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig_, _handler)
    print(f"recorder: {'live' if live else 'sim'} | public {rec.lanes['public'].base} | keyed "
          f"{rec.lanes['keyed'].base if 'keyed' in rec.lanes else 'off'} | out {rec.store.root}", flush=True)
    try:
        loop(rec, status_file, a.seconds)
    except (KeyboardInterrupt, _Stop):
        pass
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            rec.save_state(force=True)
            rec.store.append("gaps", {"kind": "recorder_stop", "tick": rec.tick,
                                      "last_event_id": rec.state["last_event_id"]})
            rec.store.write_index({"links": rec.links, "recorder_status": str(status_file)})
            write_json(status_file, {**rec.status(), "state": "stopped"})
        except OSError:
            pass
    sys.stdout.flush()


if __name__ == "__main__":
    main()
