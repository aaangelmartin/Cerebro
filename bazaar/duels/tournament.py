"""Simulated duel tournament: python -m bazaar.duels.tournament [-n 200] [--days] [--llm --max-calls 40]

Plays N duels (in pairs: same scenario, roles swapped, same rival alias, as the real round-robin does)
against the fake rivals in simulator.py, with the code fallback and optionally with Claude, and prints
average points, deal rate, rounds and pie share per rival type. Never touches the real game.
"""
from __future__ import annotations

import argparse
import random
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

from .domain import DuelsDomain
from .opponent import OpponentMemory
from .simulator import RIVALS, make_scenario, run_duel


class _ShimResult(SimpleNamespace):
    pass


class AnthropicShim:
    """Stand-in for bazaar.llm.client.ask while CORE-A's client is missing (tournament only)."""

    def __init__(self, model: str = "claude-opus-5-5"):
        import anthropic
        from .. import config
        keys = config.anthropic_keys()
        self.client = anthropic.Anthropic(api_key=keys[0][1]) if keys else anthropic.Anthropic()
        self.model = model
        self.usd = 0.0

    def ask(self, *, purpose, system, messages, tools=None, tool_choice=None, model=None, max_tokens=1200,
            deadline=None):
        t0 = time.time()
        timeout = max(5.0, deadline - t0) if deadline else 60.0
        resp = self.client.with_options(timeout=timeout, max_retries=1).messages.create(
            model=model or self.model, max_tokens=max_tokens, system=system, messages=messages,
            tools=tools or [], tool_choice=tool_choice or {"type": "auto"},
            output_config={"effort": "low"})
        calls = [{"name": b.name, "input": b.input} for b in resp.content if b.type == "tool_use"]
        u = resp.usage
        cr = getattr(u, "cache_read_input_tokens", 0) or 0
        cw = getattr(u, "cache_creation_input_tokens", 0) or 0
        cost = (u.input_tokens * 4 + cr * 0.4 + cw * 5 + u.output_tokens * 20) / 1e6
        self.usd += cost
        return _ShimResult(text="".join(b.text for b in resp.content if b.type == "text"), tool_calls=calls,
                           model=resp.model, key="A", usage=u.model_dump(), cost_usd=cost,
                           latency_s=time.time() - t0)


def _llm_client():
    try:
        from ..llm import client
        if hasattr(client, "ask"):
            return client
    except Exception:
        pass
    return AnthropicShim()


def play(n: int, seed: int, days: bool, kinds: list[str], llm=None, max_calls: int | None = None,
         verbose: bool = False) -> list:
    rng = random.Random(seed)
    tmp = Path(tempfile.mkdtemp(prefix="duelmem")) / "duel_memory.json"
    dom = DuelsDomain(memory=OpponentMemory(tmp, autosave=False), llm=llm, use_llm=llm is not None,
                      max_calls=max_calls, llm_every=4)
    results = []
    did = 1
    pairs = max(1, n // 2)
    for i in range(pairs):
        kind = kinds[i % len(kinds)]
        if days and kind == "stepped":
            kind = "days"
        sc = make_scenario(rng, days=days)
        alias = f"Rival {kind.title()}{i}"
        for leg, s in enumerate((sc, sc.swapped())):
            rival = RIVALS[kind](s, random.Random(rng.random()))

            def ctx_factory():
                return SimpleNamespace(tick=0, deadline=time.time() + 25, budget={}, lessons=None,
                                       llm=llm, llm_ok=True)
            r = run_duel(dom, s, rival, did, alias, start_tick=1000 + 20 * did, use_llm=llm is not None,
                         ctx_factory=ctx_factory)
            dom.memory.record_result(did, "deal" if r.deal else "no_deal", price=r.price, rounds=r.rounds,
                                     days=r.days, accepted_by=r.accepted_by or None)
            r.kind, r.leg = kind, leg
            results.append(r)
            if verbose:
                print(f"  #{did} {kind:8} leg{leg} {s.our_role:6} lim {s.our_limit:4} pie {r.pie:5.0f} -> "
                      f"{'deal ' + str(r.price) if r.deal else 'no deal':10} rounds {r.rounds} pts {r.points:6.1f}")
            did += 1
    results_cost = getattr(llm, "usd", None)
    if dom.calls:
        print(f"  claude calls: {dom.calls}, cost ~${(results_cost if results_cost is not None else dom.cost_usd):.2f}")
    return results


def report(title: str, results: list) -> dict:
    by = defaultdict(list)
    for r in results:
        by[r.kind].append(r)
    print(f"\n{title}")
    print(f"  {'rival':10} {'n':>4} {'avg pts':>8} {'deal%':>6} {'rounds':>7} {'pie share':>9} {'leg2 pts':>8}")
    tot = []
    for k in sorted(by):
        rs = by[k]
        deals = [r for r in rs if r.deal]
        leg2 = [r.points for r in rs if r.leg == 1]
        print(f"  {k:10} {len(rs):4} {sum(r.points for r in rs) / len(rs):8.1f} {100 * len(deals) / len(rs):6.0f}"
              f" {sum(r.rounds for r in deals) / max(1, len(deals)):7.1f}"
              f" {sum(r.points / r.pie for r in rs if r.pie > 0) / len(rs):9.2f}"
              f" {sum(leg2) / max(1, len(leg2)):8.1f}")
        tot += rs
    illegal = sum(1 for r in tot if r.illegal)
    summary = {"n": len(tot), "avg_points": sum(r.points for r in tot) / len(tot),
               "deal_rate": sum(1 for r in tot if r.deal) / len(tot),
               "avg_rounds": sum(r.rounds for r in tot if r.deal) / max(1, sum(1 for r in tot if r.deal)),
               "pie_share": sum(r.points / r.pie for r in tot if r.pie > 0) / len(tot), "illegal": illegal}
    print(f"  {'ALL':10} {summary['n']:4} {summary['avg_points']:8.1f} {100 * summary['deal_rate']:6.0f}"
          f" {summary['avg_rounds']:7.1f} {summary['pie_share']:9.2f}   illegal deals: {illegal}")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", type=int, default=280, help="duels with the fallback (pairs of legs)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--days", action="store_true", help="Duels II: price + delivery days, decay 0.08")
    ap.add_argument("--llm", action="store_true", help="also play a few duels with Claude")
    ap.add_argument("--llm-duels", type=int, default=6)
    ap.add_argument("--max-calls", type=int, default=40)
    ap.add_argument("--kinds", default=",".join(k for k in RIVALS if k != "days"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    kinds = a.kinds.split(",")
    report(f"FALLBACK (code only) - {'Duels II' if a.days else 'Duels I'}",
           play(a.n, a.seed, a.days, kinds, verbose=a.verbose))
    if a.llm:
        llm = _llm_client()
        n = a.llm_duels
        print(f"\nClaude on {n} duels (max {a.max_calls} calls); same scenarios with the fallback first:")
        report("FALLBACK on the same duels", play(n, a.seed + 1, a.days, kinds, verbose=True))
        report("CLAUDE (Opus) + guard", play(n, a.seed + 1, a.days, kinds, llm=llm, max_calls=a.max_calls,
                                             verbose=True))


if __name__ == "__main__":
    main()
