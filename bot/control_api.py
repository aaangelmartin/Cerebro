"""HTTP API for the dashboard's Bot section: live telemetry, the arm switch, overrides, and practice results.

    .venv/bin/python -m bot.control_api        # http://127.0.0.1:8790 (localhost only)

The team gateway (dashboard/server.py) proxies /bot/* here for logged-in dashboard users; this
server itself trusts its callers, so it only listens on 127.0.0.1. Writes need the header
X-Dashboard: 1 (as the gateway's console writes do).

Live (the real bot, data in bot/data):
  GET  /bot/live/view                   a plain live page: what the bot sees and does right now
  GET  /bot/live/snapshot               everything that page shows, in one JSON
  GET  /bot/live/status                 status.json + control.json
  GET  /bot/live/decisions?limit=&strategy=&action=   newest first
  GET  /bot/live/llm?limit=             prompts sent to Claude and its replies
  GET  /bot/live/inbox?limit=           counterparty messages received, with injection labels
  GET  /bot/live/pending?limit=         proposals and their status (pending, approved, edited, rejected, ...)
  POST /bot/live/control                {"armed": bool?, "mode": "auto"|"review"|"manual"?, "review_seconds"?, "manual_seconds"?, "by"?}
  POST /bot/live/pending/<id>           {"decision": "approve"|"reject"|"edit", "args"?, "kwargs"?, "by"?}
Practice (the trainer against the fake Bazaar, data in bot/sim/practice):
  GET  /bot/practice/summary            best.json, per-combo stats, totals and the latest episode
  GET  /bot/practice/episodes?limit=    newest first
  GET  /bot/practice/decisions?limit=   the current episode's decisions
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .control import Control

ROOT = Path(__file__).resolve().parent
LIVE = Path(os.environ.get("BOT_DATA_DIR") or ROOT / "data")
PRACTICE = ROOT / "sim" / "practice"
PORT = int(os.environ.get("BOT_CONTROL_PORT", "8790"))


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def tail_jsonl(path: Path, limit: int, keep=lambda r: True) -> list:
    """The last `limit` matching records of a JSON-lines file, newest first."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if keep(rec):
            out.append(rec)
            if len(out) >= limit:
                break
    return out


def snapshot(control: Control) -> dict:
    """Everything the bot sees right now, in one plain shape for the live view (bot/view.html)."""
    status = read_json(LIVE / "status.json", {})
    intel = read_json(LIVE / "intel.json", {})
    memory = read_json(LIVE / "memory.json", {})
    decisions = tail_jsonl(LIVE / "decisions.jsonl", 600)
    me_id = "t10"
    dealer = memory.get("dealer", {})
    names = {r: c.get("name") for r, c in (intel.get("cards") or {}).items()}

    # Conversations: the bot's open dealer threads, with every line said and heard.
    lines: dict[int, list] = {}
    for d in reversed(decisions):
        if d.get("strategy") != "dealer":
            continue
        if d.get("action") == "say" and d.get("args"):
            tid = d["args"][0]
            lines.setdefault(tid, []).append({"at": d["at"], "from": "bot", "text": d["args"][1] if len(d["args"]) > 1 else "",
                                              "price": (d.get("kwargs") or {}).get("price"), "dry_run": d.get("dry_run")})
        elif d.get("action") == "received":
            lines.setdefault(d.get("thread"), []).append({"at": d["at"], "from": d.get("sender"), "text": d.get("text"),
                                                          "injection": d.get("injection")})
    conversations = []
    for tid, t in (dealer.get("threads") or {}).items():
        tid_i = int(tid)
        conversations.append({
            "thread": tid_i, "with": t.get("dealer"), "kind": "dealer", "status": t.get("status"), "goal": t.get("goal"),
            "item": t.get("item"), "item_name": names.get(t.get("item"), t.get("item")), "limit": t.get("limit"),
            "first": t.get("first"), "ours": t.get("ours"), "theirs": t.get("theirs"), "final": t.get("final"),
            "leak": t.get("leak"), "history": t.get("history", []), "lines": lines.get(tid_i, [])[-12:],
            "closed_reason": t.get("closed_reason")})
    conversations.sort(key=lambda c: (c["status"] != "open", -c["thread"]))

    duel_state = (status.get("strategies") or {}).get("duels") or {}
    sent = [{"at": d["at"], "to": "dealer" if d["strategy"] == "dealer" else d["strategy"], "thread": (d.get("args") or [None])[0],
             "text": (d.get("args") or [None, ""])[1] if len(d.get("args") or []) > 1 else d.get("kwargs", {}).get("text", ""),
             "price": (d.get("kwargs") or {}).get("price"), "dry_run": d.get("dry_run")}
            for d in decisions if d.get("action") in ("say", "duel say", "message")][:30]
    moves = [d for d in decisions if d.get("action") in (
        "deal", "accept", "accept (buy)", "accept (swap)", "sold", "trade settled", "listed", "would list", "open thread",
        "would open", "walk away", "cancel (reprice)", "operator rejected", "refuse malformed offer", "use leaked limit",
        "possible leak", "injection attempt seen", "accepted", "result")][:40]

    cards = intel.get("cards") or {}
    wallet = status.get("wallet") or {}
    owned = set(wallet.get("owned") or [])
    market = memory.get("market", {})
    listings = [{"offer": k, **v, "name": names.get(v.get("ref"), v.get("ref"))} for k, v in (market.get("listings") or {}).items()]
    return {
        "updated": status.get("updated"), "tick": status.get("tick"), "mode": status.get("mode"),
        "armed": status.get("armed"), "real": status.get("real"), "control": control.state(),
        "wallet": wallet, "team": {"cash": status.get("cash"), "score": status.get("score")},
        "conversations": conversations, "duels": duel_state, "sent": sent, "moves": moves,
        "want": [{"ref": r, **{k: c.get(k) for k in ("name", "rarity", "value", "book", "max_buy", "why", "priority", "market")}}
                 for r, c in sorted(cards.items(), key=lambda kv: kv[1].get("priority") or 99) if c.get("role") in ("target", "buy")][:15],
        "listings": listings,
        "owned_cards": [{"id": i} for i in sorted(owned)],
        "to_sell": [{"ref": r, **{k: c.get(k) for k in ("name", "value", "min_sell", "why", "market")}}
                    for r, c in cards.items() if c.get("role") == "sell"],
        "pending": [p for p in control.proposals(20) if p.get("status") == "pending"],
        "errors": (status.get("errors") or [])[-5:], "suspicious": status.get("suspicious") or [],
        "dealer_deals": (dealer.get("deals") or [])[-10:], "market_gain": sum(t.get("gain", 0) for t in market.get("trades", [])
                                                                             if t.get("status") == "done"),
    }


class Handler(BaseHTTPRequestHandler):
    control = Control(LIVE)

    def reply(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parts = urlsplit(self.path)
        q = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        limit = max(1, min(int(q.get("limit", 100)) if q.get("limit", "").isdigit() else 100, 1000))
        p = parts.path
        if p == "/bot/live/view":
            body = (ROOT / "view.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if p == "/bot/live/snapshot":
            return self.reply(200, snapshot(self.control))
        if p == "/bot/live/status":
            return self.reply(200, {"status": read_json(LIVE / "status.json", {}), "control": self.control.state()})
        if p == "/bot/live/decisions":
            def keep(r):
                return (not q.get("strategy") or r.get("strategy") == q["strategy"]) and \
                       (not q.get("action") or r.get("action") == q["action"])
            return self.reply(200, {"decisions": tail_jsonl(LIVE / "decisions.jsonl", limit, keep)})
        if p == "/bot/live/llm":
            return self.reply(200, {"llm": tail_jsonl(LIVE / "decisions.jsonl", limit,
                                                      lambda r: r.get("strategy") == "llm")})
        if p == "/bot/live/inbox":
            return self.reply(200, {"inbox": tail_jsonl(LIVE / "decisions.jsonl", limit,
                                                        lambda r: r.get("action") in ("received", "injection attempt seen",
                                                                                      "suspicious rival message"))})
        if p == "/bot/live/pending":
            return self.reply(200, {"pending": self.control.proposals(limit), "control": self.control.state()})
        if p == "/bot/practice/summary":
            eps = tail_jsonl(PRACTICE / "episodes.jsonl", 100000)
            n = len(eps)
            avg = (lambda k: round(sum(e.get(k, 0) or 0 for e in eps) / n, 3) if n else None)
            return self.reply(200, {"best": read_json(PRACTICE / "best.json", {}),
                                    "stats": read_json(PRACTICE / "stats.json", {}),
                                    "episodes": n, "latest": eps[0] if eps else None,
                                    "averages": {"dealer_capture": avg("dealer_capture"), "duel_score": avg("duel_score"),
                                                 "market_gain": avg("market_gain")},
                                    "running": not (ROOT / "sim" / "STOP_PRACTICE").exists()})
        if p == "/bot/practice/episodes":
            return self.reply(200, {"episodes": tail_jsonl(PRACTICE / "episodes.jsonl", limit)})
        if p == "/bot/practice/decisions":
            return self.reply(200, {"decisions": tail_jsonl(PRACTICE / "run" / "decisions.jsonl", limit)})
        self.reply(404, {"error": "not_found", "message": p})

    def do_POST(self):
        if self.headers.get("X-Dashboard") != "1":
            return self.reply(403, {"error": "forbidden", "message": "X-Dashboard header required"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except ValueError:
            return self.reply(400, {"error": "invalid", "message": "body must be JSON"})
        p = urlsplit(self.path).path
        try:
            if p == "/bot/live/control":
                st = self.control.set(by=str(body.get("by", "dashboard"))[:40], armed=body.get("armed"),
                                      mode=body.get("mode"), review_seconds=body.get("review_seconds"),
                                      manual_seconds=body.get("manual_seconds"))
                return self.reply(200, {"control": st})
            if p.startswith("/bot/live/pending/"):
                pid = p.rsplit("/", 1)[1]
                v = self.control.decide(pid, body.get("decision", ""), by=str(body.get("by", "dashboard"))[:40],
                                        args=body.get("args"), kwargs=body.get("kwargs"))
                return self.reply(200, {"id": pid, "verdict": v})
        except ValueError as e:
            return self.reply(400, {"error": "invalid", "message": str(e)})
        self.reply(404, {"error": "not_found", "message": p})

    def log_message(self, *a):
        pass


def main():
    LIVE.mkdir(parents=True, exist_ok=True)
    print(f"bot control API on http://127.0.0.1:{PORT} (live data {LIVE})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
