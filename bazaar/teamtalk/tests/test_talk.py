import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bazaar.teamtalk import talk as T


class FakeValues:
    def __init__(self, values):
        self.values = values

    def asset_value(self, aid):
        return self.values[aid]


def sit(tick=100, threads=(), assets=(), offers=()):
    return SimpleNamespace(tick=tick, me={"id": "t10", "cash": 50, "assets": list(assets)}, threads=list(threads),
                           my_offers=list(offers))


def thread(tid=7, team="t03", msgs=(), topic=None, created=99):
    return {"id": tid, "kind": "team", "team": team, "with": "t10", "venue": "v02", "status": "open",
            "topic": topic or {}, "created_tick": created, "messages": list(msgs)}


SAL10 = {"id": 797, "kind": "card", "ref": "SAL-10", "rarity": "rare", "set": "SAL"}
ASK = {"id": 1, "tick": 100, "sender": "t03", "text": "Hola Team 10, we would like your SAL-10. 66 P attached.",
       "offer": {"id": 11423, "give": {"cash": 66}, "want": {"types": ["card:SAL-10"]}, "venue": "v02"}}
OK = SimpleNamespace(ok=True)
NO = SimpleNamespace(ok=False)


class TeamTalkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name)
        self.tt = T.TeamTalk(live=self.live, use_llm=False)

    def tearDown(self):
        self.tmp.cleanup()

    def kinds(self, acts):
        return [a.kind for a in acts]

    def test_answers_with_an_addressed_offer_instead_of_closing(self):
        s = sit(threads=[thread(msgs=[ASK])], assets=[SAL10])
        acts = self.tt.actions(s, None, values=FakeValues({797: 63.0}), check=lambda a: OK)
        self.assertEqual(self.kinds(acts), ["thread_message", "post_offer"])
        post = acts[1].params
        self.assertEqual((post["to"], post["venue"], post["give"]["assets"]), ("t03", "rastro", [797]))
        self.assertGreaterEqual(post["want"]["cash"], 70)          # never below value + margin
        rows = T.recent(self.live)
        self.assertEqual((rows[0]["team"], rows[0]["action"], rows[0]["refs"]["SAL-10"]["value"]), ("t03", "offer", 63.0))
        self.assertIn("<untrusted", T.event_text(rows[0]))
        # the same message is not answered twice
        self.assertEqual(self.tt.actions(sit(101, [thread(msgs=[ASK])], [SAL10]), None,
                                         values=FakeValues({797: 63.0}), check=lambda a: OK), [])

    def test_offers_the_copy_control_does_not_protect(self):
        two = [{"id": 627, "kind": "card", "ref": "RET-03"}, {"id": 1062, "kind": "card", "ref": "RET-03"}]
        vals = FakeValues({627: 2.8, 1062: 2.8})
        s = sit(assets=two)
        for kept, free in ((627, 1062), (1062, 627)):
            c = self.tt._cards(["RET-03"], s, {"protected": [str(kept)]}, vals)["RET-03"]
            self.assertEqual((c["asset"], c["committed"]), (free, False))
        # protected by name: no copy may go
        self.assertTrue(self.tt._cards(["RET-03"], s, {"protected": ["RET-03"]}, vals)["RET-03"]["committed"])
        # no protection: as before
        c = self.tt._cards(["RET-03"], s, {}, vals)["RET-03"]
        self.assertEqual((c["asset"], c["committed"]), (1062, False))

    def test_committed_card_is_not_offered_again(self):
        mine = {"id": 12189, "maker": "t10", "status": "open", "to": "t08", "venue": "v10",
                "give": {"assets": [SAL10]}, "want": {"cash": 160}}
        acts = self.tt.actions(sit(threads=[thread(msgs=[ASK])], assets=[SAL10], offers=[mine]), None,
                               values=FakeValues({797: 63.0}), check=lambda a: OK)
        self.assertEqual(self.kinds(acts), ["thread_message"])
        self.assertIn("tied to another offer", acts[0].params["text"])

    def _plan(self, **plan):
        import json, time
        (self.live / "strategy.json").write_text(json.dumps({"updated": time.time(), "plan": plan}))

    def test_card_a_pending_brain_post_needs_is_not_offered(self):          # code-78f932d2
        self._plan(post_offers=[{"give": "SAL-10", "want_card": "LAT-09", "want_cash": None, "to": "t15",
                                 "venue": "rastro", "why": "swap"}])
        acts = self.tt.actions(sit(threads=[thread(msgs=[ASK])], assets=[SAL10]), None,
                               values=FakeValues({797: 63.0}), check=lambda a: OK)
        self.assertEqual(self.kinds(acts), ["thread_message"])
        self.assertIn("tied to another offer", acts[0].params["text"])

    def test_reserved_ref_is_not_offered(self):
        self._plan(reserved_refs=["SAL-10"])
        acts = self.tt.actions(sit(threads=[thread(msgs=[ASK])], assets=[SAL10]), None,
                               values=FakeValues({797: 63.0}), check=lambda a: OK)
        self.assertEqual(self.kinds(acts), ["thread_message"])

    def test_brain_post_to_the_same_team_or_a_second_copy_still_offers(self):
        self._plan(post_offers=[{"give": "SAL-10", "want_card": None, "want_cash": 90, "to": "t03",
                                 "venue": "rastro", "why": "them"}])
        acts = self.tt.actions(sit(threads=[thread(msgs=[ASK])], assets=[SAL10]), None,
                               values=FakeValues({797: 63.0}), check=lambda a: OK)
        self.assertEqual(self.kinds(acts), ["thread_message", "post_offer"])
        self._plan(post_offers=[{"give": "SAL-10", "want_card": "LAT-09", "want_cash": None, "to": "t15",
                                 "venue": "rastro", "why": "swap"}])
        tt = T.TeamTalk(live=self.live, use_llm=False)
        spare = dict(SAL10, id=798)
        acts = tt.actions(sit(threads=[thread(tid=8, msgs=[ASK])], assets=[SAL10, spare]), None,
                          values=FakeValues({797: 63.0, 798: 63.0}), check=lambda a: OK)
        self.assertEqual(self.kinds(acts), ["thread_message", "post_offer"])

    def test_rail_veto_turns_into_a_polite_decline_then_a_close(self):
        s = sit(threads=[thread(msgs=[ASK])], assets=[SAL10])
        acts = self.tt.actions(s, None, values=FakeValues({797: 63.0}), check=lambda a: NO)
        self.assertEqual(self.kinds(acts), ["thread_message"])
        acts = self.tt.actions(sit(101, [thread(msgs=[ASK])], [SAL10]), None, values=FakeValues({797: 63.0}))
        self.assertEqual(self.kinds(acts), ["close_thread"])

    def test_nothing_they_want_declines(self):
        m = {**ASK, "text": "Sell us LAV-11?", "offer": None}
        acts = self.tt.actions(sit(threads=[thread(msgs=[m])]), None, values=FakeValues({}))
        self.assertEqual(self.kinds(acts), ["thread_message"])
        self.assertIn("El Rastro", acts[0].params["text"])

    def test_silence_closes_and_only_two_threads_stay_open(self):
        acts = self.tt.actions(sit(110, [thread(msgs=[], created=100)]), None, values=FakeValues({}))
        self.assertEqual(self.kinds(acts), [])                     # first seen now: give it six ticks
        acts = self.tt.actions(sit(116, [thread(msgs=[], created=100)]), None, values=FakeValues({}))
        self.assertEqual(self.kinds(acts), ["close_thread"])
        three = [thread(tid=i, team=f"t0{i}", msgs=[], created=100) for i in (1, 2, 3)]
        acts = T.TeamTalk(live=self.live, use_llm=False).actions(sit(100, three), None, values=FakeValues({}))
        self.assertEqual([(a.kind, a.params["thread"]) for a in acts], [("close_thread", 1)])

    def test_dry_run_keeps_no_state(self):
        s = sit(threads=[thread(msgs=[ASK])], assets=[SAL10])
        self.tt.actions(s, None, values=FakeValues({797: 63.0}), can_write=False)
        self.assertEqual(T.recent(self.live), [])
        self.assertEqual(self.kinds(self.tt.actions(s, None, values=FakeValues({797: 63.0}))),
                         ["thread_message", "post_offer"])

    def test_brain_opens_one_thread_then_sends_its_text(self):
        want = [{"to": "t05", "text": "Swap our SAL-10 for your MAL-09?", "venue": "rastro", "why": "page"}]
        acts = self.tt.actions(sit(100), None, team_messages=want, values=FakeValues({}))
        self.assertEqual([(a.kind, a.params) for a in acts], [("open_thread", {"with": "t05", "venue": "rastro"})])
        self.assertEqual(self.tt.actions(sit(101), None, team_messages=want, values=FakeValues({})), [])
        ours = {"id": 9, "kind": "team", "team": "t10", "with": "t05", "venue": "rastro", "status": "open",
                "messages": [], "created_tick": 101}
        acts = self.tt.actions(sit(102, [ours]), None, team_messages=want, values=FakeValues({}))
        self.assertEqual([(a.kind, a.params["text"]) for a in acts],
                         [("thread_message", "Swap our SAL-10 for your MAL-09?")])
        # sent once: never re-opened for the same text, and not within 10 ticks for another
        again = self.tt.actions(sit(120), None, team_messages=want, values=FakeValues({}))
        self.assertEqual(again, [])

    def test_llm_price_is_clamped_to_the_floor(self):
        class LLM:
            def ask(self, **kw):
                assert "<untrusted" in kw["messages"][0]["content"]
                return SimpleNamespace(tool_calls=[{"name": "team_reply", "input": {
                    "action": "offer", "ref": "SAL-10", "price": 10, "text": "Deal at 10?"}}])
        tt = T.TeamTalk(live=self.live, llm=LLM())
        acts = tt.actions(sit(threads=[thread(msgs=[ASK])], assets=[SAL10]), SimpleNamespace(llm_ok=True, control={
            "min_asks": {"SAL-10": 105}}), values=FakeValues({797: 63.0}), check=lambda a: OK)
        self.assertEqual(acts[1].params["want"]["cash"], 105)
        self.assertEqual(acts[1].source, "opus")

    def test_llm_is_told_the_teams_we_never_route_cards_to(self):
        seen = {}

        class LLM:
            def ask(self, **kw):
                seen.update(system=kw["system"], user=kw["messages"][0]["content"])
                return SimpleNamespace(tool_calls=[{"name": "team_reply", "input": {
                    "action": "offer", "ref": "SAL-10", "price": 120, "text": "120 P."}}])
        tt = T.TeamTalk(live=self.live, llm=LLM())
        tt.actions(sit(threads=[thread(msgs=[ASK])], assets=[SAL10]), SimpleNamespace(llm_ok=True, control={
            "min_asks": {"SAL-10": 105}, "blocked_teams": ["T06"]}), values=FakeValues({797: 63.0}), check=lambda a: OK)
        self.assertIn('"never_route_to": ["t06"]', seen["user"])
        self.assertIn("never_route_to", seen["system"])


if __name__ == "__main__":
    unittest.main()


class PlanFieldTest(unittest.TestCase):
    def test_team_messages_are_sanitised(self):
        from bazaar.brain.strategy import _team_messages
        out = _team_messages([{"to": "t05", "text": " Swap? ", "venue": "v07"}, {"to": "pilar", "text": "x"},
                              {"to": "t08", "text": ""}, {"to": "t03", "text": "a"}, {"to": "t04", "text": "b"}])
        self.assertEqual(out, [{"to": "t05", "text": "Swap?", "venue": "rastro", "why": ""}])
