"""El taller: el cerebro's code requests (outbox kind "code") -> tested, pushed and deployed changes.

The code itself is written by a fork of the main Claude Code conversation (the user's subscription), started from
a /loop in that session. The taller hands out the work and closes it safely:

    python -m bazaar.taller.run --next                         # claim the next eligible request, print it as JSON
    python -m bazaar.taller.run --finish ID --commit HASH      # tests on a clean checkout, push, deploy, watch,
                                                               # revert on errors, close the outbox item
    python -m bazaar.taller.run --fail ID --reason "..."       # give it back with the reason
    python -m bazaar.taller.run --list                         # what is eligible now (changes nothing)

Policy chosen by the team (Saturday 3 Oct): "auto + deploy if the tests pass".
- Auto class: low/medium severity requests that don't touch money, rails or keys; taken while "open".
- Gated class: critical severity, or anything about rails, the executor, cash/caps/never-lose, LLM keys/router or
  .env; they wait until a human sets the outbox item to "accepted" (dashboard "Aceptar"). A commit that touches the
  gated files without acceptance is reverted locally and parked.
Every step goes to data/live/taller.jsonl and the outbox item's note.

(--once / --loop-claude are an older headless mode that runs `claude -p`; it is not used.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from bazaar import config
from bazaar.outbox import Outbox

REPO = Path(config.REPO) if hasattr(config, "REPO") else config.ROOT.parent
LIVE = config.LIVE
WORK = config.ROOT / "data" / "taller"
PY = str(REPO / ".venv" / "bin" / "python")
BRANCH = "feat/bazaar-v2"
REMOTE = "origin"
POLL_S = 60
CLAUDE_TIMEOUT_S = 20 * 60
TEST_TIMEOUT_S = 15 * 60
CLAUDE_BUDGET_USD = "4"
WATCH_S = 95                     # ~3 ticks of 30 s
RESTART_WAIT_S = 60
CO_AUTHOR = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
TEST_CMD = [PY, "-m", "unittest", "discover", "-s", "bazaar", "-t", "."]

GATED_PATHS = ("bazaar/core/rails.py", "bazaar/core/executor.py", "bazaar/llm/", "bazaar/config.py", ".env")
GATED_WORDS = re.compile(r"\b(rails?|executor|never[ _-]?lose|cash|caps?|reserve|budgets?|spend(ing)?|"
                         r"api[ _-]?keys?|keys?|router|\.env|money|secrets?)\b", re.I)
FORBIDDEN_PATHS = re.compile(r"(^|/)\.env|secret|credential|\.pem$|\.key$", re.I)

# changed path prefix -> services to restart (dashboard files are static: nothing to restart)
SERVICE_OF = [
    ("bazaar/dashboard/", ()),
    ("bazaar/taller/", ()),
    ("bazaar/api/", ("api",)),
    ("bazaar/broker/", ("broker",)),
    ("bazaar/lab/", ("lab",)),
    ("bazaar/recorder/", ("recorder",)),
    ("bazaar/intel/official", ("official",)),
    ("bazaar/intel/", ("strategist",)),
    ("bazaar/strategist/", ("strategist",)),
    ("bazaar/outbox/", ("strategist", "api")),
    ("bazaar/brain/", ("strategist", "bot")),
    ("bazaar/llm/", ("bot", "broker", "lab", "strategist")),
    ("bazaar/config.py", ("bot", "broker", "lab", "strategist", "api")),
    ("bazaar/", ("bot",)),                       # core, market, dealers, duels, run.py ...
]
MODULE_OF = {"api": "bazaar.api.server", "bot": "bazaar.run", "broker": "bazaar.broker.run", "lab": "bazaar.lab.run",
             "recorder": "bazaar.recorder.run", "strategist": "bazaar.strategist.run",
             "official": "bazaar.intel.official"}

TERMINAL = {"done", "rejected", "failed", "needs_accept", "pending_integration"}


# --------------------------------------------------------------------------- pure helpers
# Claude Code must run on the Mac's logged-in Claude subscription, never on the game's API keys (the supervisor
# loads .env into the environment). These variables would switch it to API billing or another provider.
_AUTH_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
              "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "AWS_BEARER_TOKEN_BEDROCK",
              "CLAUDE_CODE_API_KEY_HELPER_TTL_MS", "ANTHROPIC_CUSTOM_HEADERS")


def claude_env(environ: dict) -> dict:
    """The environment for `claude -p`: everything (HOME, PATH...) except API keys and provider switches."""
    return {k: v for k, v in environ.items()
            if not (k in _AUTH_VARS or k.startswith("ANTHROPIC_API_KEY") or k.startswith("ANTHROPIC_WORKSPACE"))}



def is_gated(item: dict) -> bool:
    if (item.get("severity") or "medium") == "critical":
        return True
    text = " ".join(str(item.get(k) or "") for k in ("title", "diagnosis", "proposed_change", "patch_sketch"))
    return bool(GATED_WORDS.search(text)) or any(p in text for p in GATED_PATHS)


def touches_gated(paths: list[str]) -> list[str]:
    return [p for p in paths if any(p == g or p.startswith(g) for g in GATED_PATHS)]


def services_for(paths: list[str]) -> list[str]:
    out: list[str] = []
    for p in paths:
        if p.endswith(("README.md", ".md")) or "/tests/" in p:
            continue
        for prefix, svcs in SERVICE_OF:
            if p.startswith(prefix):
                out += [s for s in svcs if s not in out]
                break
    return out


def slug(text: str, n: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:n].strip("-") or "cambio"


def eligible(item: dict, state: dict, now: float | None = None) -> str | None:
    """Why this request should be taken now ("auto" | "accepted"), or None.

    A request the taller already handled (done, failed, parked for acceptance...) runs again only when a human
    sets it to "accepted" after the taller's last word on it (item.updated > state.at)."""
    if item.get("kind") != "code":
        return None
    st = state.get(item["id"]) or {}
    status = item.get("status")
    fresh_human = float(item.get("updated") or 0) > float(st.get("at") or 0) + 0.5
    if st.get("state") == "running":
        stale = (now or time.time()) - float(st.get("at") or 0) > 2 * CLAUDE_TIMEOUT_S
        return "accepted" if stale and status == "accepted" and fresh_human else None
    if st.get("state") in TERMINAL:
        return "accepted" if status == "accepted" and fresh_human else None
    if status == "open" and not is_gated(item):
        return "auto"
    if status == "accepted":
        return "accepted"
    return None


def build_prompt(item: dict) -> str:
    ev = item.get("evidence") or []
    ev = "\n".join(f"- {e}" for e in (ev if isinstance(ev, list) else [ev]))[:3000]
    return f"""You are fixing one code request filed by el cerebro, the strategist of Team 10's Bazaar bot.
You work in an isolated git worktree of the repository (current directory). Make the MINIMAL change that solves it,
add or update unit tests for it, and run the test suite until it passes.

REQUEST {item.get('id')}: {item.get('title')}
Severity: {item.get('severity')}
Diagnosis: {item.get('diagnosis')}
Proposed change: {item.get('proposed_change')}
Patch sketch:
{item.get('patch_sketch') or '(none)'}
Evidence:
{ev or '- (none)'}
Expected impact: {item.get('impact') or '(not stated)'}

Rules:
- Keep the change small and in the style of the surrounding code; tests are required.
- Run the tests with: {' '.join(TEST_CMD)}
- Never touch .env, secrets, keys or credentials; never change git identity; never commit or push (the taller does).
- Do not edit bazaar/dashboard/ unless the request is about the dashboard.
- When done, write a Conventional Commit message (subject `type(scope): imperative summary` under 72 chars, a blank
  line, then 2-4 lines on why) to the file .taller_commit_msg in the repository root. Do not add a Co-Authored-By line.
- If the request is wrong or impossible, change nothing and write the reason to .taller_commit_msg starting with
  "SKIP:".
"""


# --------------------------------------------------------------------------- the workshop
class Taller:
    def __init__(self, outbox: Outbox | None = None, repo: Path = REPO, work: Path = WORK, live: Path = LIVE,
                 sh: Callable[..., subprocess.CompletedProcess] | None = None,
                 claude: Callable[[Path, str], dict] | None = None,
                 restart: Callable[[str], bool] | None = None,
                 watch: Callable[[list[str], float], list[str]] | None = None,
                 clock: Callable[[], float] = time.time, dry_run: bool = False):
        self.box = outbox or Outbox()
        self.repo, self.work, self.live = Path(repo), Path(work), Path(live)
        self.sh = sh or self._sh
        self.claude = claude or self._claude
        self.restart = restart or self._restart
        self.watch = watch or self._watch
        self.clock = clock
        self.dry_run = dry_run
        self.work.mkdir(parents=True, exist_ok=True)
        self.state_path = self.work / "state.json"
        self.lock = self.work / "lock"
        self.log_path = self.live / "taller.jsonl"

    # ---- io
    def _sh(self, args: list[str], cwd: Path | None = None, timeout: float = 300, check: bool = False,
            env: dict | None = None) -> subprocess.CompletedProcess:
        r = subprocess.run(args, cwd=str(cwd or self.repo), capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, **(env or {})})
        if check and r.returncode != 0:
            raise RuntimeError(f"{' '.join(args[:4])}: {(r.stderr or r.stdout)[-400:]}")
        return r

    def _claude(self, wt: Path, prompt: str) -> dict:
        tools = ["Read", "Edit", "Write", "Grep", "Glob",
                 f"Bash({PY} -m unittest:*)", "Bash(git diff:*)", "Bash(git status:*)"]
        args = ["claude", "-p", prompt, "--output-format", "json", "--permission-mode", "acceptEdits",
                "--settings", json.dumps({"apiKeyHelper": None}),
                "--allowedTools", *tools, "--max-budget-usd", CLAUDE_BUDGET_USD, "--no-session-persistence"]
        env = claude_env(os.environ)
        try:
            r = subprocess.run(args, cwd=str(wt), capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_S, env=env)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"claude: more than {CLAUDE_TIMEOUT_S // 60} min"}
        try:
            out = json.loads(r.stdout or "{}")
        except ValueError:
            out = {"result": (r.stdout or "")[-1500:]}
        auth = {k: out[k] for k in ("apiKeySource", "api_key_source", "subscription", "account", "auth")
                if k in out}
        return {"ok": r.returncode == 0 and not out.get("is_error"), "result": str(out.get("result") or "")[-1500:],
                "cost_usd": out.get("total_cost_usd"), "auth": auth or "subscription (no API key in env)",
                "error": (r.stderr or "")[-600:] if r.returncode else ""}

    def _pids(self, service: str) -> list[int]:
        mod = MODULE_OF.get(service)
        if not mod:
            return []
        r = subprocess.run(["pgrep", "-f", "--", f"-m {mod}"], capture_output=True, text=True)
        return [int(x) for x in r.stdout.split() if x.strip().isdigit() and int(x) != os.getpid()]

    def _restart(self, service: str) -> bool:
        """SIGTERM the service; bazaar.supervise starts it again. True when a new process shows up."""
        old = set(self._pids(service))
        for pid in old:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        end = time.time() + RESTART_WAIT_S
        while time.time() < end:
            time.sleep(3)
            now = set(self._pids(service))
            if now and not (now & old):
                return True
        return False

    def _watch(self, services: list[str], since: float) -> list[str]:
        """Watch the services' logs for ~3 ticks; return new error lines."""
        offsets = {}
        for s in services:
            p = self.live / f"{s}.out"
            offsets[s] = p.stat().st_size if p.exists() else 0
        time.sleep(WATCH_S)
        errors = []
        for s in services:
            p = self.live / f"{s}.out"
            if not p.exists():
                continue
            with open(p, encoding="utf-8", errors="replace") as f:
                f.seek(offsets[s])
                for line in f.read().splitlines():
                    if "Traceback" in line or re.search(r"\b(ERROR|CRITICAL)\b", line):
                        errors.append(f"{s}: {line.strip()[:200]}")
            if not self._pids(s):
                errors.append(f"{s}: not running after the restart")
        return errors[:10]

    # ---- state + log
    def load_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {}

    def save_state(self, state: dict) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1))
        tmp.replace(self.state_path)

    def set_state(self, item_id: str, st: str, **extra) -> None:
        state = self.load_state()
        state[item_id] = {**(state.get(item_id) or {}), "state": st, "at": self.clock(), **extra}
        self.save_state(state)

    def log(self, item_id: str, step: str, **data) -> None:
        row = {"ts": self.clock(), "id": item_id, "step": step, **data}
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def finish(self, item_id: str, st: str, text: str, status: str | None = None, **extra) -> None:
        """The taller's last word on a request: outbox note first, then the state (so a later human change is
        newer than state.at)."""
        self.note(item_id, text, status=status)
        self.set_state(item_id, st, **extra)

    def note(self, item_id: str, text: str, status: str | None = None) -> None:
        try:
            self.box.update(item_id, status=status, note=f"taller: {text}"[:2000])
        except (KeyError, ValueError) as e:
            self.log(item_id, "note_error", error=str(e))

    def acquire(self) -> bool:
        try:
            fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                info = json.loads(self.lock.read_text() or "{}")
                pid = int(info.get("pid") or 0)
                os.kill(pid, 0)                      # alive: busy
                return False
            except (OSError, ValueError):
                self.lock.unlink(missing_ok=True)    # stale lock from a dead run
                return self.acquire()
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"pid": os.getpid(), "at": self.clock()}))
        return True

    def release(self) -> None:
        self.lock.unlink(missing_ok=True)

    # ---- selection
    def candidates(self) -> list[tuple[dict, str]]:
        state = self.load_state()
        out = []
        for it in sorted(self.box.list(kind="code"), key=lambda x: float(x.get("ts") or 0)):
            why = eligible(it, state, self.clock())
            if why:
                out.append((it, why))
        return out

    def poll_once(self) -> dict | None:
        cands = self.candidates()
        if self.dry_run:
            for it, why in cands:
                print(f"{it['id']} [{why}] {it.get('severity')} {it.get('title')}")
            return None
        if not cands:
            return None
        if not self.acquire():
            return None
        try:
            item, why = cands[0]
            return self.run_job(item, why)
        finally:
            self.release()

    # ---- one job
    def run_job(self, item: dict, why: str) -> dict:
        iid = item["id"]
        branch = f"taller/{iid}-{slug(item.get('title'))}"
        wt = self.work / f"wt-{iid}"
        self.note(iid, "en curso", status="accepted")
        self.set_state(iid, "running", branch=branch)
        self.log(iid, "claimed", why=why, title=item.get("title"), severity=item.get("severity"))
        try:
            return self._job(item, why, branch, wt)
        except Exception as e:  # noqa: BLE001 - a job never kills the workshop
            self.log(iid, "error", error=f"{type(e).__name__}: {e}"[:600])
            self.finish(iid, "failed", f"falló: {type(e).__name__}: {str(e)[:300]}", status="open", error=str(e)[:300])
            return {"id": iid, "result": "failed", "error": str(e)}
        finally:
            if wt.exists():
                self.sh(["git", "worktree", "remove", "--force", str(wt)])

    def _tests(self, wt: Path) -> tuple[bool, str]:
        r = self.sh(TEST_CMD, cwd=wt, timeout=TEST_TIMEOUT_S, env={"PYTHONPATH": str(wt)})
        tail = (r.stderr or r.stdout or "")[-800:]
        return r.returncode == 0, tail

    def _job(self, item: dict, why: str, branch: str, wt: Path) -> dict:
        iid = item["id"]
        self.sh(["git", "fetch", REMOTE, BRANCH], check=True)
        if wt.exists():
            self.sh(["git", "worktree", "remove", "--force", str(wt)])
        self.sh(["git", "branch", "-D", branch])
        self.sh(["git", "worktree", "add", "-b", branch, str(wt), f"{REMOTE}/{BRANCH}"], check=True)
        friday = self.repo / "bazaar" / "data" / "friday"        # untracked read-only fixtures some tests need
        if friday.exists() and (wt / "bazaar").exists():
            (wt / "bazaar" / "data").mkdir(parents=True, exist_ok=True)
            link = wt / "bazaar" / "data" / "friday"
            if not link.exists():
                link.symlink_to(friday, target_is_directory=True)
        self.log(iid, "worktree", path=str(wt), branch=branch)

        res = self.claude(wt, build_prompt(item))
        self.log(iid, "claude", ok=res.get("ok"), auth=res.get("auth"), cost_usd_reported=res.get("cost_usd"),
                 result=res.get("result", "")[:600],
                 error=res.get("error", "")[:300])
        msg_file = wt / ".taller_commit_msg"
        msg = msg_file.read_text().strip() if msg_file.exists() else ""
        msg_file.unlink(missing_ok=True)
        if msg.startswith("SKIP:"):
            self.finish(iid, "failed", f"no aplicado: {msg[5:].strip()[:400]}", status="rejected", reason=msg)
            return {"id": iid, "result": "skipped", "reason": msg}
        self.sh(["git", "add", "-A"], cwd=wt, check=True)
        changed = [p for p in self.sh(["git", "diff", "--cached", "--name-only"], cwd=wt).stdout.split() if p]
        self.log(iid, "diff", files=changed)
        if not changed:
            raise RuntimeError("Claude Code no cambió ningún fichero" + (f" ({res.get('error')})" if res.get("error") else ""))
        bad = [p for p in changed if FORBIDDEN_PATHS.search(p)]
        if bad:
            raise RuntimeError(f"toca ficheros prohibidos: {bad}")
        gated = touches_gated(changed)
        if gated and why != "accepted":
            self.finish(iid, "needs_accept", f"el cambio toca {', '.join(gated)} (dinero/raíles/claves): pulsa "
                        "Aceptar para aplicarlo", status="open", files=gated)
            self.log(iid, "needs_accept", files=gated)
            return {"id": iid, "result": "needs_accept", "files": gated}

        ok, tail = self._tests(wt)
        self.log(iid, "tests", ok=ok, tail=tail[-300:])
        if not ok:
            raise RuntimeError(f"los tests fallan: {tail[-300:]}")
        subject = msg or f"fix(bot): {item.get('title', 'cambio pedido por el cerebro')[:60]}"
        body = f"{subject}\n\nRequested by el cerebro ({iid}); implemented by the taller.\n\n{CO_AUTHOR}\n"
        (self.work / f"msg-{iid}.txt").write_text(body)
        self.sh(["git", "commit", "-q", "-F", str(self.work / f"msg-{iid}.txt")], cwd=wt, check=True)

        head = self._integrate(iid, wt, branch)
        if head is None:
            return {"id": iid, "result": "failed"}
        local = self._update_local(iid, changed)
        services = services_for(changed)
        if not local:
            self.finish(iid, "pending_integration", f"subido en {head}; pendiente de integrar en la copia local (hay "
                        "cambios sin commit en los mismos ficheros), no desplegado", status="accepted", commit=head)
            return {"id": iid, "result": "pending_integration", "commit": head}
        errors = self._deploy(iid, services)
        if errors:
            self._revert(iid, wt, head, services, errors)
            return {"id": iid, "result": "reverted", "commit": head, "errors": errors}
        summary = subject.splitlines()[0][:160]
        self.finish(iid, "done", f"hecho en {head} ({summary}); desplegado: {', '.join(services) or 'nada que reiniciar'}",
                    status="done", commit=head, services=services)
        self.log(iid, "done", commit=head, services=services)
        return {"id": iid, "result": "done", "commit": head, "services": services}

    def _integrate(self, iid: str, wt: Path, branch: str) -> str | None:
        """Rebase on the latest feat/bazaar-v2, test again if it moved, push the branch and fast-forward."""
        for attempt in range(3):
            base = self.sh(["git", "rev-parse", f"{REMOTE}/{BRANCH}"], cwd=wt).stdout.strip()
            self.sh(["git", "fetch", REMOTE, BRANCH], cwd=wt, check=True)
            new_base = self.sh(["git", "rev-parse", f"{REMOTE}/{BRANCH}"], cwd=wt).stdout.strip()
            if new_base != base or attempt:
                r = self.sh(["git", "rebase", f"{REMOTE}/{BRANCH}"], cwd=wt)
                if r.returncode != 0:
                    self.sh(["git", "rebase", "--abort"], cwd=wt)
                    raise RuntimeError(f"conflicto al rebasar sobre {BRANCH}")
                ok, tail = self._tests(wt)
                self.log(iid, "tests_after_rebase", ok=ok, tail=tail[-300:])
                if not ok:
                    raise RuntimeError(f"los tests fallan tras rebasar: {tail[-300:]}")
            self.sh(["git", "push", "-q", REMOTE, f"HEAD:refs/heads/{branch}"], cwd=wt)   # record; never forced
            r = self.sh(["git", "push", "-q", REMOTE, f"HEAD:{BRANCH}"], cwd=wt)
            if r.returncode == 0:
                head = self.sh(["git", "rev-parse", "--short", "HEAD"], cwd=wt).stdout.strip()
                self.log(iid, "pushed", commit=head, branch=branch)
                return head
            self.log(iid, "push_retry", attempt=attempt, error=(r.stderr or "")[-300:])
        raise RuntimeError(f"no se pudo hacer fast-forward de {BRANCH}")

    def _update_local(self, iid: str, changed: list[str]) -> bool:
        cur = self.sh(["git", "branch", "--show-current"]).stdout.strip()
        dirty = [p for p in self.sh(["git", "status", "--porcelain", "--", *changed]).stdout.splitlines() if p.strip()]
        if cur != BRANCH or dirty:
            self.log(iid, "local_pending", branch=cur, dirty=dirty[:10])
            return False
        r = self.sh(["git", "pull", "-q", "--ff-only", REMOTE, BRANCH])
        self.log(iid, "local_pull", ok=r.returncode == 0, error=(r.stderr or "")[-300:])
        return r.returncode == 0

    def _deploy(self, iid: str, services: list[str]) -> list[str]:
        if not services:
            self.log(iid, "deploy", services=[])
            return []
        started = self.clock()
        for s in services:
            ok = self.restart(s)
            self.log(iid, "restart", service=s, ok=ok)
            if not ok:
                return [f"{s}: no volvió a arrancar"]
        errors = self.watch(services, started)
        self.log(iid, "watch", services=services, errors=errors)
        return errors

    def _revert(self, iid: str, wt: Path, head: str, services: list[str], errors: list[str]) -> None:
        self.sh(["git", "fetch", REMOTE, BRANCH], cwd=wt, check=True)
        self.sh(["git", "checkout", "-q", "--detach", f"{REMOTE}/{BRANCH}"], cwd=wt, check=True)
        r = self.sh(["git", "revert", "--no-edit", head], cwd=wt)
        if r.returncode == 0:
            self.sh(["git", "push", "-q", REMOTE, f"HEAD:{BRANCH}"], cwd=wt)
            self.sh(["git", "pull", "-q", "--ff-only", REMOTE, BRANCH])
            for s in services:
                self.restart(s)
        self.log(iid, "reverted", commit=head, errors=errors, revert_ok=r.returncode == 0)
        self.finish(iid, "rejected", f"desplegado {head} pero dio errores, revertido: {'; '.join(errors)[:600]}",
                    status="rejected", commit=head, errors=errors)

    # ---- fork mode: a fork of the main Claude Code conversation (user's subscription) writes the code ----------
    def next_job(self) -> dict | None:
        """Claim the next eligible request and describe it for the fork that will implement it."""
        cands = self.candidates()
        if not cands:
            return None
        item, why = cands[0]
        iid = item["id"]
        text = " ".join(str(item.get(k) or "") for k in ("title", "diagnosis", "proposed_change", "patch_sketch"))
        paths = sorted(set(re.findall(r"bazaar/[\w/.-]+\.py", text)))
        self.note(iid, "en curso (fork)", status="accepted")
        self.set_state(iid, "running", mode="fork", why=why)
        self.log(iid, "claimed", why=why, mode="fork", title=item.get("title"), severity=item.get("severity"))
        return {"id": iid, "class": "gated" if is_gated(item) else "auto", "why": why,
                "severity": item.get("severity"), "title": item.get("title"), "diagnosis": item.get("diagnosis"),
                "evidence": item.get("evidence"), "proposed_change": item.get("proposed_change"),
                "patch_sketch": item.get("patch_sketch"), "impact": item.get("impact"),
                "paths_mentioned": paths, "affected_processes_guess": services_for(paths),
                "gated_paths": list(GATED_PATHS),
                "finish": f"python -m bazaar.taller.run --finish {iid} --commit <hash>",
                "fail": f"python -m bazaar.taller.run --fail {iid} --reason '<why>'"}

    def fail_job(self, iid: str, reason: str) -> dict:
        self.log(iid, "fail", reason=reason[:600])
        self.finish(iid, "failed", f"no aplicado: {reason[:500]}", status="open", reason=reason[:300])
        return {"id": iid, "result": "failed"}

    def finish_job(self, iid: str, commit: str) -> dict:
        """The fork committed its change locally: test it on a clean checkout, push, deploy, watch, revert on errors."""
        item = self.box.get(iid)
        if not item:
            raise KeyError(iid)
        st = self.load_state().get(iid) or {}
        r = self.sh(["git", "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"])
        if r.returncode != 0:
            raise RuntimeError(f"no existe el commit {commit}")
        full = r.stdout.strip()
        files = [p for p in self.sh(["git", "show", "--name-only", "--format=", full]).stdout.split() if p]
        self.log(iid, "finish_start", commit=full[:10], files=files)
        bad = [p for p in files if FORBIDDEN_PATHS.search(p)]
        gated = touches_gated(files)
        if bad or (gated and st.get("why") != "accepted"):
            self.sh(["git", "revert", "--no-edit", full])         # undo locally, nothing pushed
            why = f"toca ficheros prohibidos: {bad}" if bad else \
                f"toca {', '.join(gated)} (dinero/raíles/claves): pulsa Aceptar y se volverá a intentar"
            self.finish(iid, "needs_accept" if not bad else "failed", f"no aplicado: {why}", status="open", files=files)
            return {"id": iid, "result": "needs_accept" if not bad else "failed", "reason": why}
        wt = self.work / f"check-{iid}"
        if wt.exists():
            self.sh(["git", "worktree", "remove", "--force", str(wt)])
        self.sh(["git", "worktree", "add", "--detach", str(wt), full], check=True)
        try:
            friday = self.repo / "bazaar" / "data" / "friday"
            if friday.exists() and (wt / "bazaar").exists():
                (wt / "bazaar" / "data").mkdir(parents=True, exist_ok=True)
                (wt / "bazaar" / "data" / "friday").symlink_to(friday, target_is_directory=True)
            ok, tail = self._tests(wt)
        finally:
            self.sh(["git", "worktree", "remove", "--force", str(wt)])
        self.log(iid, "tests", ok=ok, tail=tail[-300:])
        if not ok:
            self.sh(["git", "revert", "--no-edit", full])
            self.finish(iid, "failed", f"los tests fallan con {full[:7]} (revertido en local): {tail[-300:]}",
                        status="open")
            return {"id": iid, "result": "failed", "tests": tail[-300:]}
        r = self.sh(["git", "push", "-q", REMOTE, f"{full}:refs/heads/{BRANCH}"])
        if r.returncode != 0:
            self.log(iid, "push_failed", error=(r.stderr or "")[-300:])
            return {"id": iid, "result": "push_failed",
                    "error": "origin/feat/bazaar-v2 moved: `git pull --rebase origin feat/bazaar-v2` (no stash) and run "
                             "--finish again with the new hash"}
        head = full[:7]
        self.log(iid, "pushed", commit=head)
        services = services_for(files)
        errors = self._deploy(iid, services)
        if errors:
            rv = self.sh(["git", "revert", "--no-edit", full])
            if rv.returncode == 0:
                self.sh(["git", "push", "-q", REMOTE, f"HEAD:{BRANCH}"])
                for s in services:
                    self.restart(s)
            self.log(iid, "reverted", commit=head, errors=errors, revert_ok=rv.returncode == 0)
            self.finish(iid, "rejected", f"desplegado {head} pero dio errores, revertido: {'; '.join(errors)[:600]}",
                        status="rejected", commit=head, errors=errors)
            return {"id": iid, "result": "reverted", "commit": head, "errors": errors}
        subject = self.sh(["git", "log", "-1", "--format=%s", full]).stdout.strip()[:160]
        self.finish(iid, "done", f"hecho en {head} ({subject}); desplegado: {', '.join(services) or 'nada que reiniciar'}",
                    status="done", commit=head, services=services)
        self.log(iid, "done", commit=head, services=services)
        return {"id": iid, "result": "done", "commit": head, "services": services}

    # ---- loop
    def heartbeat(self, extra: dict | None = None) -> None:
        p = self.live / "taller_status.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"updated": self.clock(), "pid": os.getpid(), **(extra or {})}))
        tmp.replace(p)

    def loop(self) -> None:
        stop = {"v": False}
        signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("v", True))
        while not stop["v"]:
            try:
                res = self.poll_once()
                self.heartbeat({"last": res})
            except Exception as e:  # noqa: BLE001
                self.log("-", "loop_error", error=f"{type(e).__name__}: {e}"[:400])
            for _ in range(POLL_S):
                if stop["v"]:
                    break
                time.sleep(1)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--next", action="store_true", help="claim the next eligible request and print it as JSON")
    ap.add_argument("--finish", metavar="ID", help="test, push, deploy and close a request (needs --commit)")
    ap.add_argument("--commit", metavar="HASH", help="the fork's local commit for --finish")
    ap.add_argument("--fail", metavar="ID", help="give a request back (needs --reason)")
    ap.add_argument("--reason", default="", help="why --fail")
    ap.add_argument("--list", action="store_true", help="list eligible requests, change nothing")
    ap.add_argument("--loop-claude", action="store_true",
                    help="(not used) the old headless mode: poll and run `claude -p` on each request")
    ap.add_argument("--once", metavar="ID", help="(not used) one request with `claude -p`")
    a = ap.parse_args(argv)
    t = Taller(dry_run=a.list)
    out: Any
    if a.list:
        t.poll_once()
        return
    if a.next:
        if not t.acquire():
            sys.exit("another taller job is running")
        try:
            out = t.next_job()
        finally:
            t.release()
        print(json.dumps(out, ensure_ascii=False, default=str) if out else "null")
        return
    if a.finish:
        if not a.commit:
            sys.exit("--finish needs --commit <hash>")
        if not t.acquire():
            sys.exit("another taller job is running")
        try:
            out = t.finish_job(a.finish, a.commit)
        finally:
            t.release()
        print(json.dumps(out, ensure_ascii=False, default=str))
        return
    if a.fail:
        print(json.dumps(t.fail_job(a.fail, a.reason or "sin motivo"), ensure_ascii=False))
        return
    if a.once:
        it = t.box.get(a.once)
        why = eligible(it, t.load_state()) if it else None
        if not why:
            sys.exit(f"{a.once} is not eligible")
        if not t.acquire():
            sys.exit("another taller job is running")
        try:
            print(json.dumps(t.run_job(it, why), ensure_ascii=False, default=str))
        finally:
            t.release()
        return
    if a.loop_claude:
        t.loop()
        return
    ap.print_help()


if __name__ == "__main__":
    main()
