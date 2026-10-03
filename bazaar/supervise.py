"""Keep the new bot's processes running unattended.

    .venv/bin/python -m bazaar.supervise          # Ctrl-C stops the supervisor and its children

Services (each logs to data/live/<name>.out):
  api     python -m bazaar.api.server     always up, even with bazaar/STOP
  bot     python -m bazaar.run --live     not started (and stopped) while bazaar/STOP exists;
                                          restarted when status.json is older than 3 ticks
  broker  python -m bazaar.broker.run     restarted when broker_status.json `updated` is older than 2 ticks
  lab     python -m bazaar.lab.run

A crashed service restarts after a short backoff (doubling up to 5 min). Heartbeats only count while
the doors are open. The legacy gateway on :8787 is not managed here. Set BAZAAR_SUPERVISE_SKIP=lab,broker
to leave services alone. Log: data/live/supervise.log.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config

PY = sys.executable
CHECK_EVERY_S = 10.0
GRACE_S = 90.0                  # after a (re)start, heartbeats are not judged for this long
MAX_BACKOFF_S = 300.0


def log(msg: str, path: Path | None = None):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with (path or config.LIVE / "supervise.log").open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _read_json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


@dataclass
class Service:
    name: str
    cmd: list[str]
    heartbeat: str | None = None      # file under live with an `updated` epoch
    stale_ticks: float = 0.0
    obeys_stop: bool = False
    env: dict = field(default_factory=dict)
    proc: subprocess.Popen | None = None
    started: float = 0.0
    failures: int = 0
    next_try: float = 0.0


def default_services() -> list[Service]:
    return [
        Service("api", [PY, "-u", "-m", "bazaar.api.server"]),
        Service("bot", [PY, "-u", "-m", "bazaar.run", "--live"], heartbeat="status.json", stale_ticks=3,
                obeys_stop=True),
        Service("broker", [PY, "-u", "-m", "bazaar.broker.run"], heartbeat="broker_status.json", stale_ticks=2),
        Service("lab", [PY, "-u", "-m", "bazaar.lab.run"]),
    ]


class Supervisor:
    def __init__(self, services: list[Service], live: Path | None = None, stop_file: Path | None = None,
                 now=time.time, grace_s: float = GRACE_S):
        self.services = services
        self.live = Path(live or config.LIVE)
        self.stop_file = Path(stop_file or config.STOP_FILE)
        self.now = now
        self.grace_s = grace_s

    def _log(self, msg):
        log(msg, self.live / "supervise.log")

    def tick_seconds(self) -> tuple[float, bool]:
        """(tick length, doors open) from the bot's status.json, with safe defaults."""
        st = _read_json(self.live / "status.json")
        ts = float(st.get("tick_seconds") or 30.0)
        open_ = st.get("doors") == "open" and not st.get("paused") and st.get("state") == "running"
        return ts, open_

    def start(self, s: Service):
        out = open(self.live / f"{s.name}.out", "a")
        s.proc = subprocess.Popen(s.cmd, cwd=config.REPO, stdout=out, stderr=subprocess.STDOUT,
                                  start_new_session=True, env={**os.environ, **s.env})
        out.close()
        s.started = self.now()
        self._log(f"started {s.name} (pid {s.proc.pid})")

    def stop(self, s: Service, why: str):
        if s.proc is None or s.proc.poll() is not None:
            s.proc = None
            return
        self._log(f"stopping {s.name}: {why}")
        try:
            os.killpg(s.proc.pid, signal.SIGTERM)
            s.proc.wait(timeout=10)
        except (ProcessLookupError, PermissionError):
            pass
        except subprocess.TimeoutExpired:
            try:
                os.killpg(s.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        s.proc = None

    def stale(self, s: Service) -> str | None:
        if not s.heartbeat or self.now() - s.started < self.grace_s:
            return None
        ts, open_ = self.tick_seconds()
        if not open_ and s.name != "bot":
            return None
        hb = _read_json(self.live / s.heartbeat)
        updated = hb.get("updated")
        if updated is None:
            try:
                updated = (self.live / s.heartbeat).stat().st_mtime
            except OSError:
                return f"no {s.heartbeat}"
        age = self.now() - float(updated)
        # The bot writes status.json while waiting too, so it is judged with the doors closed (60 s floor).
        limit = max(s.stale_ticks * ts, 60.0 if not open_ else 0.0)
        if age > limit:
            return f"heartbeat {s.heartbeat} is {age:.0f}s old (> {limit:.0f}s)"
        return None

    def check(self):
        stopped = self.stop_file.exists()
        for s in self.services:
            try:
                if s.obeys_stop and stopped:
                    if s.proc is not None:
                        self.stop(s, "bazaar/STOP exists")
                    continue
                alive = s.proc is not None and s.proc.poll() is None
                if alive:
                    why = self.stale(s)
                    if why:
                        self.stop(s, why)
                        s.failures += 1
                        alive = False
                elif s.proc is not None:
                    self._log(f"{s.name} exited with code {s.proc.returncode}")
                    s.failures += 1 if self.now() - s.started < 120 else 0
                    s.proc = None
                    s.next_try = self.now() + min(MAX_BACKOFF_S, 2.0 * (2 ** min(s.failures, 8)))
                if not alive and self.now() >= s.next_try:
                    self.start(s)
            except Exception as e:  # noqa: BLE001 - the supervisor itself must never die
                self._log(f"{s.name}: check failed: {e}")

    def shutdown(self):
        for s in self.services:
            self.stop(s, "supervisor exiting")


def main():
    skip = {x.strip() for x in os.environ.get("BAZAAR_SUPERVISE_SKIP", "").split(",") if x.strip()}
    sup = Supervisor([s for s in default_services() if s.name not in skip])
    awake = None
    try:
        awake = subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())])
    except OSError:
        pass
    log(f"supervisor up (pid {os.getpid()}); services {[s.name for s in sup.services]}; skipping {sorted(skip)}")
    try:
        while True:
            sup.check()
            time.sleep(CHECK_EVERY_S)
    except KeyboardInterrupt:
        sup.shutdown()
        if awake:
            awake.terminate()


if __name__ == "__main__":
    main()
