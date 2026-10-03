"""Outbox of el cerebro: things the brain decides but only humans can do.

Three kinds of item, all in one append-only file (bazaar/data/live/outbox.jsonl):

- ``code``: a code change the brain asks for. Humans write the code; the brain finds the problem, cites the
  evidence and proposes the change.
  {id, kind: "code", ts, updated, title, severity: low|medium|high|critical, evidence: [str], diagnosis,
   proposed_change, patch_sketch, impact, status: open|accepted|done|rejected, human_note, occurrences, last_seen,
   recurred}
- ``promo``: a message for the WhatsApp group or an in-game announcement.
  {id, kind: "promo", ts, updated, channel: whatsapp|in_game, text, why, status: draft|sent|discarded, human_note}
- ``task``: any other chore only a human can do (rotate a key, restart the tunnel).
  {id, kind: "task", ts, updated, task, why, status: open|done|rejected, human_note, occurrences, last_seen}

Each line of the file is either a full item ({"op": "put", "item": {...}}) or a change
({"op": "update", "id", "ts", "status"?, "note"?, ...}); reading folds them in order, so the file is a log
and nothing is ever rewritten. Filing the same code request or task again (similar title) does not add a
duplicate: it bumps ``occurrences`` and adds the new evidence, and an item that was done or rejected is
reopened with ``recurred: true`` because the problem came back.

API shapes for the dashboard (served by the brain's API):
  GET  /outbox?kind=code|promo|task&status=open&since=<ts>  -> {"items": [item, ...]}  newest first
  POST /outbox/<id>  {"status": "...", "note": "..."}       -> {"item": item}         header X-Dashboard: 1
"""
from __future__ import annotations

import difflib
import fcntl
import json
import re
import time
import uuid
from pathlib import Path

from .. import config

KINDS = ("code", "promo", "task")
STATUSES = {
    "code": ("open", "accepted", "done", "rejected"),
    "promo": ("draft", "sent", "discarded"),
    "task": ("open", "done", "rejected"),
}
OPEN = {"code": ("open", "accepted"), "promo": ("draft",), "task": ("open",)}
CLOSED = {"code": ("done", "rejected"), "task": ("done", "rejected")}
SEVERITIES = ("low", "medium", "high", "critical")
SIMILAR = 0.82                    # titles this alike are the same request
MAX_EVIDENCE = 12                 # keep the newest pieces of evidence per item

DEFAULT_PATH = config.LIVE / "outbox.jsonl"


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9áéíóúñü ]+", " ", str(text or "").lower()).split())


def similar(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a) and difflib.SequenceMatcher(None, a, b).ratio() >= SIMILAR


class Outbox:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else DEFAULT_PATH

    # ------------------------------------------------------------------ file
    def _append(self, rows: list[dict]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _load(self) -> dict[str, dict]:
        items: dict[str, dict] = {}
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return items
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue                                   # a half-written last line
            if row.get("op") == "put" and isinstance(row.get("item"), dict):
                items[row["item"]["id"]] = dict(row["item"])
            elif row.get("op") == "update" and row.get("id") in items:
                it = items[row["id"]]
                for k, v in row.items():
                    if k in ("op", "id"):
                        continue
                    if k == "ts":
                        it["updated"] = v
                    elif k == "note":
                        it["human_note"] = v
                    elif k == "add_evidence":
                        it["evidence"] = (list(it.get("evidence") or []) + list(v))[-MAX_EVIDENCE:]
                    else:
                        it[k] = v
        return items

    # ------------------------------------------------------------------ read
    def list(self, kind: str | None = None, status: str | list | None = None, since: float | None = None) -> list[dict]:
        """Items newest first (by last change). `status` may be one value or a list."""
        want = {status} if isinstance(status, str) else set(status or [])
        out = []
        for it in self._load().values():
            if kind and it.get("kind") != kind:
                continue
            if want and it.get("status") not in want:
                continue
            if since is not None and float(it.get("updated") or it.get("ts") or 0) <= float(since):
                continue
            out.append(it)
        out.sort(key=lambda x: -float(x.get("updated") or x.get("ts") or 0))
        return out

    def get(self, item_id: str) -> dict | None:
        return self._load().get(item_id)

    def open_items(self) -> list[dict]:
        return [it for it in self.list() if it.get("status") in OPEN.get(it.get("kind"), ())]

    # ------------------------------------------------------------------ write
    def update(self, item_id: str, status: str | None = None, note: str | None = None, **fields) -> dict:
        it = self.get(item_id)
        if it is None:
            raise KeyError(item_id)
        if status is not None and status not in STATUSES[it["kind"]]:
            raise ValueError(f"status must be one of {STATUSES[it['kind']]}")
        row = {"op": "update", "id": item_id, "ts": time.time()}
        if status is not None:
            row["status"] = status
        if note is not None:
            row["note"] = str(note)[:2000]
        row.update(fields)
        self._append([row])
        return self.get(item_id)

    def _put(self, item: dict) -> dict:
        now = time.time()
        item.setdefault("id", f"{item['kind']}-{uuid.uuid4().hex[:8]}")
        item.setdefault("ts", now)
        item.setdefault("updated", item["ts"])
        item.setdefault("human_note", "")
        self._append([{"op": "put", "item": item}])
        return item

    def _match(self, kind: str, key: str, text: str) -> dict | None:
        for it in self.list(kind):
            if similar(it.get(key, ""), text):
                return it
        return None

    def _recur(self, it: dict, evidence: list[str]) -> dict:
        fields = {"occurrences": int(it.get("occurrences") or 1) + 1, "last_seen": time.time()}
        if evidence:
            fields["add_evidence"] = [str(e)[:500] for e in evidence]
        status = None
        if it.get("status") in CLOSED.get(it["kind"], ()):
            status = "open"
            fields["recurred"] = True
        return self.update(it["id"], status=status, **fields)

    def file_code(self, title: str, evidence: list[str] | str, diagnosis: str, proposed_change: str,
                  severity: str = "medium", impact: str = "", patch_sketch: str = "", item_id: str | None = None,
                  ts: float | None = None) -> dict:
        """File a code request, or bump the matching one (re-opening it if it was closed)."""
        evidence = [evidence] if isinstance(evidence, str) else list(evidence or [])
        same = self._match("code", "title", title)
        if same:
            return self._recur(same, evidence)
        item = {"kind": "code", "title": str(title)[:200], "severity": severity if severity in SEVERITIES else "medium",
                "evidence": [str(e)[:500] for e in evidence][-MAX_EVIDENCE:], "diagnosis": str(diagnosis)[:3000],
                "proposed_change": str(proposed_change)[:3000], "patch_sketch": str(patch_sketch)[:4000],
                "impact": str(impact)[:1000], "status": "open", "occurrences": 1, "recurred": False}
        if item_id:
            item["id"] = item_id
        if ts:
            item["ts"] = item["last_seen"] = ts
        return self._put(item)

    def draft_promo(self, text: str, why: str = "", channel: str = "whatsapp", item_id: str | None = None,
                    ts: float | None = None, status: str = "draft") -> dict:
        """Draft a message; the same text twice is one draft."""
        for it in self.list("promo"):
            if _norm(it.get("text")) == _norm(text):
                return it
        item = {"kind": "promo", "channel": channel if channel in ("whatsapp", "in_game") else "whatsapp",
                "text": str(text)[:4000], "why": str(why)[:1000],
                "status": status if status in STATUSES["promo"] else "draft"}
        if item_id:
            item["id"] = item_id
        if ts:
            item["ts"] = ts
        return self._put(item)

    def file_task(self, task: str, why: str = "", item_id: str | None = None, ts: float | None = None,
                  evidence: list[str] | None = None) -> dict:
        same = self._match("task", "task", task)
        if same:
            return self._recur(same, list(evidence or []))
        item = {"kind": "task", "task": str(task)[:500], "why": str(why)[:2000], "status": "open",
                "occurrences": 1, "evidence": [str(e)[:500] for e in (evidence or [])]}
        if item_id:
            item["id"] = item_id
        if ts:
            item["ts"] = item["last_seen"] = ts
        return self._put(item)

    def summary_text(self, max_chars: int = 2000) -> str:
        """Open items for the brain's prompt, so it does not file what is already waiting."""
        lines = []
        for it in self.open_items():
            if it["kind"] == "code":
                lines.append(f"- code [{it['status']}, x{it.get('occurrences', 1)}] {it['title']}"
                             + (f" — human: {it['human_note']}" if it.get("human_note") else ""))
            elif it["kind"] == "task":
                lines.append(f"- task [{it['status']}] {it['task']}")
            else:
                lines.append(f"- promo draft ({it['channel']}): {it['text'][:120]}")
        text = "\n".join(lines)
        return text[:max_chars]


# ---------------------------------------------------------------------- today's real items
def seed_examples(box: Outbox) -> list[dict]:
    """Saturday morning's real items, filed once (fixed ids, so seeding twice changes nothing)."""
    have = box._load()
    out = []
    if "code-sat-router-400" not in have:
        out.append(box.file_code(
            "Key router treats a 400 'not scoped to a workspace' as a one-off error", item_id="code-sat-router-400",
            ts=1791013659.0, severity="critical",
            evidence=["llm.jsonl 09:28-09:47: key B 55 calls, all 400 invalid_request_error "
                      "'This API key is not scoped to a workspace'", "every decision source=fallback in that window",
                      "4 live duels (#291 #292 #303 #304) closed with no deal, 0 pts"],
            diagnosis="llm/client.py _classify returned 'fatal' for that 400, so the key was never marked dead and the "
                      "router kept picking it; each domain fell back to code.",
            proposed_change="Classify key-identity errors (workspace / api key / invalid_api_key) as 'dead' and retry on "
                            "the next key.", impact="Claude decisions instead of code for ~20 min; duels answered well.",
            patch_sketch="if 'workspace' in msg or 'api key' in msg: return 'dead', 0.0"))
        box.update("code-sat-router-400", status="done", note="Fixed in 045dbe1")
    if "code-sat-broker-probe" not in have:
        out.append(box.file_code(
            "Broker probe sends prices outside the ask/bid range during the Market Test",
            item_id="code-sat-broker-probe", ts=1791014108.0, severity="medium",
            evidence=["bench/2026-10-03-b7.jsonl t207: probe b7-13/b7-7 at 68 refused bad_match "
                      "'price must sit between the ask 114 and the bid 61'",
                      "t211: probe b7-10/b7-1 at 65 refused (ask 71, bid 56)"],
            diagnosis="rule 'probe' matches pairs whose bid is below the ask; the game refuses any price there.",
            proposed_change="Only probe pairs with bid >= ask, or skip probes and keep crossing pairs.",
            impact="Fewer refused matches during the Market Test; the refused ticks are matches lost."))
    if "code-sat-announce-retry" not in have:
        out.append(box.file_code(
            "Broker announcement retried every tick although the game allows one per 20 ticks",
            item_id="code-sat-announce-retry", ts=1791014050.0, severity="low",
            evidence=["outcomes.jsonl t202-t211: broker_announce refused 429 'one announcement per venue every 20 ticks'"],
            diagnosis="run.py only moved last_announce on success, so a refusal retried at once.",
            proposed_change="After a refusal wait 20 ticks before announcing again.",
            impact="No wasted requests; the dashboard stops showing 'Rechazado' every tick."))
        box.update("code-sat-announce-retry", status="done", note="Fixed in 045dbe1")
    if "promo-sat-v07" not in have:
        out.append(box.draft_promo(
            "⚖️ Team 10 opened its market: Team 10 · fair broker (v07)\n0% fee, 0 P per card.\n\n"
            "Meet in the middle: when your bid is above someone's ask, our broker matches you at the midpoint. "
            "Bid 12, ask 8 → you trade at 10. Nobody overpays, nobody undersells.\n"
            "🃏 Card by card, any copy, every tick.\n\n🤖 Just tell your agent:\n"
            "\"Each tick, read GET /api/venues/v07/offers. Post bids and asks with venue: \"v07\" and "
            "expires_in_ticks: 120.\"\n\nFair price for both sides. 🤝",
            why="Bring other teams' bids and asks to v07: trades on our venue score market-making for us.",
            channel="whatsapp", item_id="promo-sat-v07", ts=1791013560.0, status="sent"))
    if "task-sat-key-b" not in have:
        out.append(box.file_task(
            "Key B: put a key that the API accepts without the anthropic-workspace-id header in .env "
            "(ANTHROPIC_API_KEY_B), then restart the bot",
            why="Key B answered every call with 400 'not scoped to a workspace'; the router dropped it, so only A and C "
                "carry the load.", item_id="task-sat-key-b", ts=1791013700.0))
        box.update("task-sat-key-b", status="done", note="New key B works (tested 10:40); bot and lab restarted")
    return out


if __name__ == "__main__":       # python -m bazaar.outbox.store  -> seed today's items into the live outbox
    box = Outbox()
    filed = seed_examples(box)
    print(f"seeded {len(filed)} items into {box.path}; open: {len(box.open_items())}")
