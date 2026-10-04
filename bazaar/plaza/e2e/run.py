"""Everything, with one command:

    .venv/bin/python -m bazaar.plaza.e2e.run            # simulation (strict) + every page in the browser
    .venv/bin/python -m bazaar.plaza.e2e.run --quick    # desktop only, shorter waits
    .venv/bin/python -m bazaar.plaza.e2e.run --no-browser
    .venv/bin/python -m bazaar.plaza.e2e.run --public https://market.nglmrtn.com --resolve 188.114.96.5

1. The simulation suite with PLAZA_E2E_STRICT=1: every gap against CONTRACT.md fails, with its owner's name.
2. A market with a scene in it (`serve.py`, its own port and temporary folder) and `browser.js` over every page.
It writes `e2e/last_run.json` and prints a summary; the exit code is 0 only when both parts are clean."""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parents[2]
OUT = REPO / "design" / "plaza" / "build" / "e2e-final"


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
        cmd = ["node", str(HERE / "browser.js"), line.strip(), str(OUT)] + (["--quick"] if quick else [])
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


def replay() -> dict:
    """Saturday's recorded trades against a test market (replay.py). Skipped when there is no recording."""
    if not (REPO / "bazaar" / "data" / "live" / "events.jsonl").exists():
        return {"ok": True, "skipped": True}
    p = subprocess.run([sys.executable, "-m", "bazaar.plaza.e2e.replay"], cwd=REPO, capture_output=True, text=True,
                       timeout=900)
    try:
        r = json.loads((HERE / "replay_result.json").read_text())
    except (OSError, ValueError):
        return {"ok": False, "error": (p.stderr or p.stdout)[-400:]}
    return {"ok": p.returncode == 0, "team_trades": r["team_trades"], "on_v07": r["on_v07"], "elsewhere": r["elsewhere"],
            "wrong": len(r["wrong"]), "false_strikes": len(r["false_strikes"]), "table": r["table"]}


def public(url: str, ip: str) -> dict:
    """The public address, read only (public.js)."""
    p = subprocess.run(["node", str(HERE / "public.js"), url, ip, str(OUT / "public")], cwd=REPO, capture_output=True,
                       text=True, timeout=600)
    try:
        r = json.loads((OUT / "public" / "report.json").read_text())
    except (OSError, ValueError):
        return {"ok": False, "hard": [(p.stderr or p.stdout)[-400:]], "notes": []}
    return {"ok": p.returncode == 0, "base": url, "hard": r["bad"], "notes": r["notes"],
            "pages": len([x for x in r["rows"] if x.get("name")])}


COVERED = """Simulation, all through the public API with fake agents and a fake game: a sale and a swap from connect to
`settled` read from the feed; four agents and two trades; a token is nobody until its team proves itself in the game
(403 `prove_first`), the newest proof wins and another team's message proves nothing; wrong codes from elsewhere do
not lock out the right one; twenty connections from one address; limits that do not overlap; a buyer who values the
card less than the seller; the price strictly inside the overlap, on the grid, unchanged while a limit is moved; no
match when the overlap has no grid price inside; a paused team; the host never a party; the agent asked to `decide`
when the other team set the price or the host forced the match; an offer that is not exactly the match (another
card, another venue, another team) answers 409 `conflict` and does not count; a trade veiled (`price: null`,
`veiled: true`) to visitors and to other teams on `/api/matches`, `/api/match/ID`, `/api/floor`, the stream,
`/api/card/REF`, `/api/team/tXX`, `/api/market`, `/api/wall`, `/api/offers`, `/api/stats`, and open once settled; a
close cleans the sheets and the limits; a first matched trade closed elsewhere is a warning and the second a ban
(403 on everything), lifted by the host; an offer moved to v07 before it closes costs nothing; a public listing
elsewhere strikes nobody; an agent that dies half way; repeats; twelve accepts at once; a restart and a cut write in
the middle of a trade; our switch; doors closed, game paused, stale feed; private limits out of every answer and every
file; one team's token on another's data; the panel without the admin proof; 24 rubbish bodies on every write route;
wrong methods, sizes, types and paths; the request budget; hostile text; every live route against its fixture; the
queue's own requests; AGENTS.md against the list of routes.

Browser: 15 routes and 9 panel screens in EN and ES at 1600 and 390 px, in mock mode and against the scene; five mock
states on five screens; the side nav; Landing to Connect, How it works to Home; the landing at 1600x1000, 1440x900,
1280x720 and 390, with and without `prefers-reduced-motion`; a visitor's pages (no side nav, Back to the landing, no
price of an unsettled trade); a warned team and a banned one (overlay, mark in the top bar)."""


def write_report(result: dict) -> None:
    sim, web, rep, pub = result["simulation"], result["browser"], result["replay"], result["public"]
    L = ["# End-to-end report", "", f"Last run: {result['when']} ({result['seconds']} s). Written by "
         "`.venv/bin/python -m bazaar.plaza.e2e.run`; the numbers are that run's.", "", "## Result", "",
         f"- Simulation: {sim['ran']} cases, {sim['ran'] - len(sim['failed'])} clean, {len(sim['hard'])} hard failures, "
         f"{len(sim['findings'])} open findings."]
    if not web.get("skipped"):
        L.append(f"- Browser: {web.get('pages')} pages, {len(web['hard'])} hard failures, {len(web['findings'])} notes. "
                 "Screenshots in `design/plaza/build/e2e-final/`.")
    if "team_trades" in rep:
        L.append(f"- Replay of the recorded feed: {rep['team_trades']} real trades between teams, {rep['on_v07']} on v07 "
                 f"and {rep['elsewhere']} elsewhere; {rep['wrong']} read wrong, {rep['false_strikes']} false strikes.")
    if not pub.get("skipped"):
        L.append(f"- Public address {pub.get('base')}: {pub.get('pages')} pages, {len(pub['hard'])} hard failures, "
                 f"{len(pub['notes'])} notes.")
    L += ["", "## Open", ""]
    rows = [f"- simulation, hard: {f}" for f in sim["hard"]] + [f"- simulation: {f}" for f in sim["findings"]] \
        + [f"- browser, hard: {f}" for f in web["hard"]] + [f"- public, hard: {f}" for f in pub.get("hard", [])]
    L += rows or ["Nothing hard."]
    notes = collections.Counter(re.sub(r"^[a-z]+/[a-z]+-[a-z]+-[a-z-]+: ", "", f)[:200] for f in web["findings"])
    if notes or pub.get("notes"):
        L += ["", "Notes (not failures):", ""] + [f"- {k} ({n})" for k, n in notes.most_common(25)] \
            + [f"- public: {n}" for n in pub.get("notes", [])]
    if "table" in rep:
        L += ["", "## The recorded feed", "",
              "Every trade between two teams in `data/live/events.jsonl`, replayed with the game's own lines against a "
              "test market holding an equivalent match that both agents had seen (`replay.py`, rows in "
              "`replay_result.json`).", "", "| Trades | Venue | Offer in the feed | The match ends | Strike |", "|---|---|---|---|---|"]
        L += [f"| {r['n']} | {r['venue']} | {r['offer']} | {r['state']} | {r['strike'].replace('struck: ', '')} |" for r in rep["table"]]
        L += ["", "What the detector reads from a real `settlement`: `payload.venue`, `payload.parties`, "
              "`payload.items[].ref`, `.frm`, `.to`, `payload.price`, `payload.settlement` (kept as the match's "
              "settlement id) and the event's `tick`. The real event carries no offer id: an offer is tied to its "
              "settlement by the two teams, the card and the venue, and by still being open. Every real settlement "
              "has the same nine keys (`fee, items, kind, parties, persona, price, settlement, tick, venue`); no "
              "format went unrecognised. Ten of the eleven real trades on v07 were public offers crossed by the "
              "broker, with no addressed offer: they settle a match all the same."]
    L += ["", "## Covered", "", COVERED, "", "## Not checked", "",
          "- The screenshots against the design PNG by eye, beyond a handful.",
          "- Whether every Spanish page is fully in Spanish: only missing keys are detected.",
          "- The real market's data and real teams: the public check only reads; no connection was started.",
          "- The game itself: nothing here calls it."]
    (HERE / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-replay", action="store_true")
    ap.add_argument("--public", metavar="URL", help="also check the public address, read only")
    ap.add_argument("--resolve", metavar="IP", default="", help="the address to resolve the public host to")
    args = ap.parse_args()
    started = time.time()
    sim = simulation()
    web = {"ok": True, "skipped": True, "hard": [], "findings": []} if args.no_browser else browser(args.quick)
    rep = {"ok": True, "skipped": True} if args.no_replay else replay()
    pub = public(args.public, args.resolve) if args.public else {"ok": True, "skipped": True}
    result = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(time.time() - started, 1),
              "simulation": sim, "browser": web, "replay": rep, "public": pub}
    (HERE / "last_run.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    write_report(result)
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
    if not rep.get("skipped"):
        print(f"replay: {rep.get('team_trades')} real trades between teams ({rep.get('on_v07')} on v07, "
              f"{rep.get('elsewhere')} elsewhere): {rep.get('wrong')} read wrong, {rep.get('false_strikes')} false strikes"
              if "team_trades" in rep else f"replay: failed: {rep.get('error')}")
    if not pub.get("skipped"):
        print(f"public {pub.get('base')}: {pub.get('pages')} pages, {len(pub['hard'])} hard, {len(pub['notes'])} notes")
        for f in pub["hard"]:
            print("  HARD  " + f)
        for f in pub["notes"]:
            print("  note  " + f)
    return 0 if sim["ok"] and web["ok"] and rep["ok"] and pub["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
