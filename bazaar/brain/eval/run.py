"""Replay this morning's situations through el cerebro and grade what it sees and decides.

    python -m bazaar.brain.eval.run                 # deterministic: picture + detectors, no API call
    python -m bazaar.brain.eval.run --live-llm      # also one real brain plan per scenario (Opus medium,
                                                    # purpose "brain_eval", stops at --cap-usd, default 3 $)
    python -m bazaar.brain.eval.run --only key_b,team5_ret01 --report bazaar/brain/eval/REPORT.md
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from bazaar import config
from bazaar.brain.eval.replay import World
from bazaar.brain.eval.scenarios import SCENARIOS, Scenario

HERE = Path(__file__).resolve().parent
S_DEFAULT_CHECK = 4


class EvalLLM:
    """The brain's llm module with every call booked under purpose "brain_eval"."""

    def __init__(self):
        from bazaar.llm import client
        self.c = client

    def cached_system(self, text):
        return self.c.cached_system(text) if hasattr(self.c, "cached_system") else text

    def ask(self, **kw):
        kw["purpose"] = "brain_eval"
        return self.c.ask(**kw)


def eval_spend() -> float:
    try:
        from bazaar.llm import client
        return float((client.spend_today().get("by_purpose") or {}).get("brain_eval") or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def build_context(sc: Scenario, world: World, tmp: Path, llm=None):
    """(Strategist, picture, ctx) for the scenario's moment."""
    from bazaar.strategist import brainio as B
    from bazaar.strategist.run import EventDetector, Strategist
    ts = world.tick_ts(sc.tick)
    built = world.build(ts, tmp / "now", control=sc.control)
    events = []
    if sc.events_from_tick is not None:
        before = world.build(world.tick_ts(sc.events_from_tick), tmp / "before", control=sc.control)
        a = EventDetector(before["latest"], before["live"]).snapshot()
        b = EventDetector(built["latest"], built["live"]).snapshot()
        events = [B.log_event(built["live"], e["kind"], e["text"], built["tick"], e.get("data"), ts)
                  for e in EventDetector.diff(a, b)]
    st = Strategist(live=built["live"], record=built["latest"], llm=llm, now=lambda: ts)
    st.pending_events = list(events)
    pic = st.picture()
    ctx = {"pic": pic, "text": json.dumps(pic, ensure_ascii=False, default=str).lower(), "events": events,
           "tick": built["tick"], "ts": ts}
    return st, pic, ctx


def run(only: set[str] | None = None, live_llm: bool = False, cap_usd: float = 3.0,
        record: Path | None = None, live: Path | None = None, only_order: list[str] | None = None) -> list[dict]:
    world = World(record or (config.DATA / "record"), live or config.LIVE)
    results = []
    spent0 = eval_spend()
    order = {sid: i for i, sid in enumerate(only_order or [])}
    todo = [s for s in SCENARIOS if not only or s.id in only]
    todo.sort(key=lambda s: order.get(s.id, len(order)))
    for sc in todo:
        row = {"id": sc.id, "title": sc.title, "tick": sc.tick, "expect": sc.expect, "det": [], "llm": [],
               "llm_status": "not run"}
        with tempfile.TemporaryDirectory(prefix=f"brain-eval-{sc.id}-") as d:
            try:
                st, pic, ctx = build_context(sc, world, Path(d), EvalLLM() if live_llm else None)
                row["det"] = [list(c) for c in sc.det(ctx)]
            except Exception as e:  # noqa: BLE001 - one broken scenario must not stop the rest
                row["det"] = [["build picture", False, f"{type(e).__name__}: {e}"[:200]]]
                results.append(row)
                continue
            if live_llm:
                if eval_spend() - spent0 >= cap_usd:
                    row["llm_status"] = f"skipped: eval spend cap {cap_usd} $ reached"
                else:
                    t0 = time.time()
                    try:
                        st.now = time.time               # the call needs a real deadline
                        # neutral reason: the scenario's title would tell the brain the answer
                        reason = (f"{len(ctx['events'])} game event(s)" if ctx["events"]
                                  else f"every {S_DEFAULT_CHECK} ticks")
                        got = st.ask(pic, reason)
                        if got is None:
                            row["llm_status"] = "no plan returned"
                        else:
                            from bazaar.strategist import brainio as B
                            plan = st._plan_from(got)
                            row["plan"] = {k: plan.get(k) for k in ("situation", "priorities", "goal_buys",
                                                                    "cash_policy", "avoid_buy_sets", "accept_offers",
                                                                    "cancel_offers", "findings", "guidance")}
                            row["validation_errors"] = B.validate(plan, pic)
                            row["llm"] = [list(c) for c in sc.llm(plan, ctx)]
                            row["llm_status"] = f"ok in {time.time() - t0:.0f} s"
                    except Exception as e:  # noqa: BLE001
                        row["llm_status"] = f"error: {type(e).__name__}: {e}"[:200]
        results.append(row)
    if live_llm:
        results.append({"id": "_spend", "usd": round(eval_spend() - spent0, 3)})
    return results


def _mark(ok) -> str:
    return "PASS" if ok else "FAIL"


def table(results: list[dict]) -> str:
    lines = ["| scenario | tick | expected | code-side | brain plan |", "|---|---|---|---|---|"]
    for r in results:
        if r["id"].startswith("_"):
            continue
        det = r["det"]
        dpass = sum(1 for c in det if c[1])
        llm = r["llm"]
        lpass = sum(1 for c in llm if c[1])
        lcol = f"{lpass}/{len(llm)} {_mark(lpass == len(llm))}" if llm else r["llm_status"]
        lines.append(f"| {r['id']} | {r['tick']} | {r['expect']} | {dpass}/{len(det)} {_mark(dpass == len(det))} | {lcol} |")
    return "\n".join(lines)


def report_md(results: list[dict], live_llm: bool) -> str:
    spend = next((r.get("usd") for r in results if r["id"] == "_spend"), None)
    out = ["# El cerebro · replay eval", "",
           f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')} · mode: {'deterministic + live LLM (Opus, medium)' if live_llm else 'deterministic'}"
           + (f" · eval spend {spend} $" if spend is not None else ""), "",
           "Each scenario rebuilds the game at that tick from the recorder streams and the bot's logs, builds the "
           "brain's picture with the real `Strategist.picture()`, checks the facts and detectors (code-side), and "
           "with `--live-llm` asks the real brain prompt for a plan and grades it.", "", table(results), ""]
    for r in results:
        if r["id"].startswith("_"):
            continue
        out.append(f"## {r['id']} · {r['title']}")
        out.append(f"Tick {r['tick']} · expected: {r['expect']}")
        for name, ok, detail in r["det"]:
            out.append(f"- code {_mark(ok)}: {name}" + (f" — `{str(detail)[:200]}`" if detail and not ok else ""))
        for name, ok, detail in r["llm"]:
            out.append(f"- plan {_mark(ok)}: {name}" + (f" — `{str(detail)[:200]}`" if detail else ""))
        if r.get("llm_status") and not r["llm"]:
            out.append(f"- plan: {r['llm_status']}")
        if r.get("validation_errors"):
            out.append(f"- validation errors: {r['validation_errors'][:4]}")
        if r.get("plan"):
            pr = r["plan"].get("priorities") or []
            out.append(f"- top priorities: " + " | ".join(str(p)[:140] for p in pr[:3]))
        out.append("")
    return "\n".join(out)


def failures(results: list[dict]) -> list[str]:
    out = []
    for r in results:
        if r["id"].startswith("_"):
            continue
        for kind in ("det", "llm"):
            for name, ok, detail in r[kind]:
                if not ok:
                    out.append(f"{r['id']} [{'code' if kind == 'det' else 'plan'}] {name}" + (f" ({str(detail)[:120]})" if detail else ""))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-llm", action="store_true")
    ap.add_argument("--cap-usd", type=float, default=3.0)
    ap.add_argument("--only", default="")
    ap.add_argument("--report", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    ids = [x for x in a.only.split(",") if x]
    res = run(set(ids) or None, a.live_llm, a.cap_usd, only_order=ids)
    print(table(res))
    fails = failures(res)
    print(f"\n{len(fails)} failing checks" + ("" if not fails else ":\n- " + "\n- ".join(fails)))
    if a.report:
        Path(a.report).write_text(report_md(res, a.live_llm))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
