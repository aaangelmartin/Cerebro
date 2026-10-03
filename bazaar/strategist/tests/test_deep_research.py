"""The strategist starts one bounded research session when due or when the team asks ('investiga: ...')."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from bazaar.llm import cli_backend
from bazaar.strategist import brainio as B
from bazaar.strategist.run import Strategist


class DeepResearchTest(unittest.TestCase):
    def _st(self, d):
        live, rec = Path(d) / "live", Path(d) / "rec"
        live.mkdir(); rec.mkdir()
        (rec / "clock.json").write_text(json.dumps({"paused": False, "doors": "open", "tick": 800}))
        (live / "control.json").write_text(json.dumps({"brain_backend": "auto", "mac_calls_per_hour": 60}))
        st = Strategist(live=live, record=rec, llm=object())
        return st, live

    def test_team_request_runs_a_session_and_files_the_finding(self):
        with tempfile.TemporaryDirectory() as d:
            st, live = self._st(d)
            seen = {}

            def fake(brief, **kw):
                seen["brief"] = brief
                return {"text": "FINDINGS\n- t05 holds MAL-09 (record/feed:1)", "latency_s": 3.0, "turns": 5}
            with mock.patch.object(st, "_mac_free", lambda: True), \
                    mock.patch.object(cli_backend, "run_research", fake):
                st.research_last = time.time()
                self.assertIsNone(st.maybe_research())                  # nothing due yet: the last one just ran
                B.chat_post(live, "investiga: quién tiene MAL-09", by="angel", role="user", now=time.time() + 1)
                state = st.maybe_research()
                self.assertTrue(state["asked_by_team"])
                st.research_thread.join(5)
            self.assertEqual(seen["brief"], "quién tiene MAL-09")
            rows = [json.loads(l) for l in (live / "strategist_findings.jsonl").read_text().splitlines()]
            self.assertEqual(rows[-1]["topic"], "investigacion")
            self.assertIn("MAL-09", rows[-1]["finding"])
            self.assertTrue(any(m.get("role") == "brain" and "Investigación" in m.get("text", "")
                                for m in B.chat_since(live, None, 10)))
            self.assertTrue(st.research_state["ok"])

    def test_scheduled_every_20_minutes_and_switchable(self):
        with tempfile.TemporaryDirectory() as d:
            st, live = self._st(d)
            n = []
            with mock.patch.object(st, "_mac_free", lambda: True), \
                    mock.patch.object(cli_backend, "run_research",
                                      lambda brief, **kw: n.append(brief) or {"text": "ok", "latency_s": 1, "turns": 1}):
                st.research_last = time.time() - 1300
                st.research_brief = "why did t12 jump at tick 690"
                self.assertIsNotNone(st.maybe_research())
                st.research_thread.join(5)
                self.assertEqual(n, ["why did t12 jump at tick 690"])
                self.assertIsNone(st.maybe_research())                  # not again for 20 minutes
                st.research_last = time.time() - 1300
                (live / "control.json").write_text(json.dumps({"brain_backend": "auto", "brain_deep_research": False}))
                self.assertIsNone(st.maybe_research())                  # switched off

    def test_not_without_the_mac(self):
        with tempfile.TemporaryDirectory() as d:
            st, _ = self._st(d)
            st.research_last = time.time() - 1300
            self.assertIsNone(st.maybe_research())                      # an injected llm never uses the Mac


if __name__ == "__main__":
    unittest.main()
