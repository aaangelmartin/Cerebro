"""Keep the whole team stack running unattended on this machine.

    .venv/bin/python -m bot.supervise        # Ctrl-C stops the supervisor (the services keep running)

Every 15 s it checks each service and starts it again if it is down:

  gateway      dashboard/server.py on :8787 (the team's only link to the Bazaar)
  ngrok        the public tunnel to the gateway
  control-api  bot/control_api.py on :8790 (the dashboard's Bot tabs)
  bot          the real bot (python -m bot.run --live); it keeps its arm switch and wallet
  recorder     bot/recorder.py, which saves the public feed and leaderboard to bot/data/history/
  practice     the practice trainer against the fake Bazaar

It also keeps the Mac awake (caffeinate) while it runs, and logs to bot/data/supervise.log.
A service whose name is listed in BOT_SUPERVISE_SKIP (comma-separated) is left alone.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(REPO / ".venv" / "bin" / "python")
LOGS = REPO / "bot" / "data"
LOG = LOGS / "supervise.log"


def log(msg: str):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def running(pattern: str) -> bool:
    # "--": the patterns start with "-u", which pgrep would otherwise read as an option.
    return subprocess.run(["pgrep", "-f", "--", pattern], capture_output=True).returncode == 0


def ngrok_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=3) as r:
            return b"public_url" in r.read()
    except OSError:
        return False


def start(name: str, cmd: list[str], env: dict | None = None):
    out = open(LOGS / f"{name}.out", "a")
    subprocess.Popen(cmd, cwd=REPO, stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
                     env={**os.environ, **(env or {})})
    log(f"started {name}")


SERVICES = [
    ("gateway", lambda: port_open(8787), lambda: start("gateway", [PY, "-u", "dashboard/server.py"])),
    ("ngrok", ngrok_up, lambda: start("ngrok", ["ngrok", "http", "8787", "--log", "stdout"])),
    ("control-api", lambda: port_open(8790), lambda: start("control-api", [PY, "-u", "-m", "bot.control_api"])),
    # -u only on the real bot: the practice trainer spawns its own "python -m bot.run --live".
    ("bot", lambda: running(r"-u -m bot\.run --live$"),
     lambda: start("bot", [PY, "-u", "-m", "bot.run", "--live"], {"BOT_ALLOW_REAL": "1"})),
    ("recorder", lambda: running(r"-m bot\.recorder"),
     lambda: start("recorder", [PY, "-u", "-m", "bot.recorder"])),
    ("practice", lambda: running(r"-m bot\.sim\.practice"),
     lambda: start("practice", [PY, "-u", "-m", "bot.sim.practice", "--ticks", "40", "--tick", "1.0", "--probe"])),
]


def main():
    LOGS.mkdir(exist_ok=True)
    skip = {s.strip() for s in os.environ.get("BOT_SUPERVISE_SKIP", "").split(",") if s.strip()}
    awake = subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())])
    log(f"supervisor up (pid {os.getpid()}, caffeinate {awake.pid}); skipping {sorted(skip) or 'nothing'}")
    while True:
        for name, is_up, launch in SERVICES:
            if name in skip:
                continue
            try:
                if not is_up():
                    log(f"{name} is down")
                    launch()
                    time.sleep(3)
            except Exception as e:  # noqa: BLE001 - the supervisor itself must never die
                log(f"{name}: check failed: {e}")
        time.sleep(15)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
