"""Operator control of the live bot: the arm switch, the override queue and the telemetry files.

Files in the bot's data dir (bot/data for the live bot):

  control.json        written by the control API only: {"armed", "mode", "review_seconds", "manual_seconds",
                      "updated", "by"}. Missing = disarmed. The bot re-reads it every tick.
  pending.jsonl       written by the bot only: one line per proposed action (and its final state).
  overrides/<id>.json written by the control API only: the operator's verdict on one proposal,
                      {"decision": "approve"|"reject"|"edit", "args": [...]?, "kwargs": {...}?}.

Modes once armed:
  auto    every action is sent at once.
  review  every action waits `review_seconds` for an override, then is sent as proposed.
  manual  every action waits up to `manual_seconds` for approval; no verdict means it is dropped.
Disarmed (the default), the bot runs as a dry run: it decides and logs, and sends nothing.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

DEFAULT = {"armed": False, "mode": "review", "review_seconds": 12, "manual_seconds": 40}
MODES = ("auto", "review", "manual")


class OperatorRejected(Exception):
    """The operator rejected (or did not approve in time) a proposed action."""


class Control:
    def __init__(self, data: Path):
        self.data = data
        self.path = data / "control.json"
        self.pending_path = data / "pending.jsonl"
        self.overrides = data / "overrides"
        self.overrides.mkdir(parents=True, exist_ok=True)

    def state(self) -> dict:
        try:
            st = {**DEFAULT, **json.loads(self.path.read_text())}
        except (OSError, ValueError):
            st = dict(DEFAULT)
        if st["mode"] not in MODES:
            st["mode"] = "review"
        return st

    def set(self, by: str = "operator", **changes) -> dict:
        st = self.state()
        for k in ("armed", "mode", "review_seconds", "manual_seconds"):
            if k in changes and changes[k] is not None:
                st[k] = changes[k]
        if st["mode"] not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        st["armed"] = bool(st["armed"])
        st["review_seconds"] = max(0, min(int(st["review_seconds"]), 50))
        st["manual_seconds"] = max(5, min(int(st["manual_seconds"]), 55))
        st.update(updated=time.strftime("%Y-%m-%d %H:%M:%S"), by=by)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1))
        tmp.replace(self.path)
        return st

    # --- the bot side -----------------------------------------------------
    def _log(self, rec: dict):
        with self.pending_path.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def gate(self, strategy: str, action: str, args: list, kwargs: dict, context: dict | None,
             deadline: float | None = None) -> tuple[list, dict]:
        """Hold one action for the operator according to the mode. Returns the (possibly edited)
        args/kwargs to send, or raises OperatorRejected."""
        st = self.state()
        if st["mode"] == "auto":
            return args, kwargs
        pid = uuid.uuid4().hex[:10]
        wait = st["review_seconds"] if st["mode"] == "review" else st["manual_seconds"]
        if deadline:
            wait = max(0.0, min(wait, deadline - time.time()))
        rec = {"id": pid, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "expires": time.time() + wait,
               "mode": st["mode"], "strategy": strategy, "action": action, "args": args, "kwargs": kwargs,
               "context": context or {}, "status": "pending"}
        self._log(rec)
        verdict_path = self.overrides / f"{pid}.json"
        end = time.time() + wait
        verdict = None
        while time.time() < end:
            if verdict_path.exists():
                try:
                    verdict = json.loads(verdict_path.read_text())
                    break
                except ValueError:
                    pass
            time.sleep(0.4)
        if verdict is None:
            if st["mode"] == "manual":
                self._log({"id": pid, "status": "expired"})
                raise OperatorRejected("not approved in time")
            self._log({"id": pid, "status": "auto-approved"})
            return args, kwargs
        decision = verdict.get("decision")
        if decision == "reject":
            self._log({"id": pid, "status": "rejected", "by": verdict.get("by")})
            raise OperatorRejected("rejected by operator")
        if decision == "edit":
            args = verdict.get("args", args)
            kwargs = {**kwargs, **verdict.get("kwargs", {})}
            self._log({"id": pid, "status": "edited", "args": args, "kwargs": kwargs, "by": verdict.get("by")})
            return args, kwargs
        self._log({"id": pid, "status": "approved", "by": verdict.get("by")})
        return args, kwargs

    def sent(self, pid_or_none, result=None, error=None):
        if pid_or_none:
            self._log({"id": pid_or_none, "status": "error" if error else "sent", "error": error})

    # --- the API side -----------------------------------------------------
    def proposals(self, limit: int = 50) -> list[dict]:
        """Proposals with their latest status, newest first."""
        merged: dict[str, dict] = {}
        order: list[str] = []
        try:
            lines = self.pending_path.read_text().splitlines()[-2000:]
        except OSError:
            return []
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            pid = rec.get("id")
            if pid not in merged:
                merged[pid] = {}
                order.append(pid)
            merged[pid].update({k: v for k, v in rec.items() if v is not None})
        out = [merged[p] for p in reversed(order)]
        now = time.time()
        for p in out:
            if p.get("status") == "pending" and p.get("expires", 0) < now - 2:
                p["status"] = "stale"
        return out[:limit]

    def decide(self, pid: str, decision: str, by: str = "operator", args=None, kwargs=None) -> dict:
        if decision not in ("approve", "reject", "edit"):
            raise ValueError("decision must be approve, reject or edit")
        if not pid or len(pid) > 32 or not pid.isalnum():
            raise ValueError("bad id")
        verdict = {"decision": decision, "by": by, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        if decision == "edit":
            if args is not None:
                verdict["args"] = args
            if kwargs is not None:
                verdict["kwargs"] = kwargs
        tmp = self.overrides / f"{pid}.tmp"
        tmp.write_text(json.dumps(verdict))
        tmp.replace(self.overrides / f"{pid}.json")
        return verdict
