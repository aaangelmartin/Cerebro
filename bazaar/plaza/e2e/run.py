"""Everything, with one command:

    .venv/bin/python -m bazaar.plaza.e2e.run            # simulation (strict) + every page in the browser
    .venv/bin/python -m bazaar.plaza.e2e.run --quick    # desktop only, shorter waits
    .venv/bin/python -m bazaar.plaza.e2e.run --no-browser

1. The simulation suite with PLAZA_E2E_STRICT=1: every gap against CONTRACT.md fails, with its owner's name.
2. A market with a scene in it (`serve.py`, its own port and temporary folder) and `browser.js` over every page.
It writes `e2e/last_run.json` and prints a summary; the exit code is 0 only when both parts are clean."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parents[2]


def simulation() -> dict:
    env = {**os.environ, "PLAZA_E2E_STRICT": "1"}
    p = subprocess.run([sys.executable, "-m", "unittest", "-v", "bazaar.plaza.tests.test_e2e_sim"], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=600)
    out = p.stderr + p.stdout
    ran = re.search(r"Ran (\d+) tests", out)
    failed = re.findall(r"^(?:FAIL|ERROR): (\w+)", out, re.M)
    findings = sorted({f.strip() for block in re.findall(r"open findings: (.*)", out) for f in block.split(" | ")})
    other = [n for n in failed if not re.search(rf"(?:FAIL|ERROR): {n} .*?\n(?:.*\n)*?AssertionError: open findings", out)]
    return {"ran": int(ran.group(1)) if ran else 0, "failed": failed, "findings": findings, "hard": other,
            "ok": p.returncode == 0}


def browser(quick: bool) -> dict:
    srv = subprocess.Popen([sys.executable, "-m", "bazaar.plaza.e2e.serve"], cwd=REPO, stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = srv.stdout.readline()
        if not line.strip().startswith("{"):
            return {"ok": False, "hard": ["the scene did not start: " + (srv.stderr.read() or "")[-400:]], "findings": []}
        cmd = ["node", str(HERE / "browser.js"), line.strip()] + (["--quick"] if quick else [])
        p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=1500)
        info = json.loads(line)
        try:
            rep = json.loads((Path(p.stdout.splitlines()[0] and json.loads(p.stdout.splitlines()[0])["out"]) / "report.json").read_text())
        except (ValueError, OSError, IndexError, KeyError):
            rep = {"pages": 0, "hard": ["the browser run printed no report: " + (p.stderr or p.stdout)[-400:]], "findings": []}
        return {"ok": p.returncode == 0, "pages": rep.get("pages"), "hard": rep.get("hard", []),
                "findings": rep.get("findings", []), "out": rep.get("out"), "base": info.get("base")}
    finally:
        try:
            srv.stdin.close()
            srv.wait(timeout=10)
        except Exception:  # noqa: BLE001
            srv.kill()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    started = time.time()
    sim = simulation()
    web = {"ok": True, "skipped": True, "hard": [], "findings": []} if args.no_browser else browser(args.quick)
    result = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(time.time() - started, 1),
              "simulation": sim, "browser": web}
    (HERE / "last_run.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"simulation: {sim['ran']} cases, {len(sim['failed'])} not clean "
          f"({len(sim['hard'])} hard, {len(sim['findings'])} open findings)")
    for f in sim["hard"]:
        print("  HARD  " + f)
    for f in sim["findings"]:
        print("  open  " + f)
    if not args.no_browser:
        print(f"browser: {web.get('pages')} pages, {len(web['hard'])} hard, {len(web['findings'])} notes -> {web.get('out')}")
        for f in web["hard"]:
            print("  HARD  " + f)
        for f in web["findings"][:60]:
            print("  note  " + f)
    return 0 if sim["ok"] and web["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
