"""AGENTS.md says what the server does: every live route, nothing else, with examples of the real shapes."""
import json
import re
import unittest
from pathlib import Path

from bazaar.plaza import agentsdoc as A
from bazaar.plaza import connect as C
from bazaar.plaza import routes as R
from bazaar.plaza.tests import test_connect_deals as T

FIXTURES = Path(A.__file__).parent / "web" / "fixtures"


def entries(md: str) -> dict[tuple[str, str], str]:
    """The text of each route's entry, by (method, path)."""
    parts = re.split(r"^### `([A-Z]+) (/[^`]+)`$", md, flags=re.M)
    out = {}
    for i in range(1, len(parts), 3):
        out[(parts[i], parts[i + 1])] = parts[i + 2].split("\n## ")[0]
    return out


def block(text: str, label: str):
    m = re.search(re.escape(label) + r"\n```json\n(.*?)\n```", text, flags=re.S)
    return json.loads(m.group(1)) if m else None


def same_shape(example, real, where: str) -> list[str]:
    """Every key of the example exists in the real answer with the same kind of value."""
    if isinstance(example, dict):
        if not isinstance(real, dict):
            return [f"{where}: an object in the document, {type(real).__name__} in the answer"]
        bad = []
        for k, v in example.items():
            if k not in real:
                bad.append(f"{where}.{k}: not in the answer")
            else:
                bad += same_shape(v, real[k], f"{where}.{k}")
        return bad
    if isinstance(example, list):
        if not isinstance(real, list):
            return [f"{where}: a list in the document, {type(real).__name__} in the answer"]
        bad = []
        for v in example:                                       # each example item looks like some real item
            tries = [same_shape(v, r, where + "[]") for r in real]
            if tries and all(tries):
                bad += min(tries, key=len)
        return bad
    if example is None or real is None:
        return []
    kinds = (bool,) if isinstance(example, bool) else (int, float) if isinstance(example, (int, float)) else (str,)
    return [] if isinstance(real, kinds) and (kinds == (bool,) or not isinstance(real, bool)) else [
        f"{where}: {type(example).__name__} in the document, {type(real).__name__} in the answer"]


class DocumentTest(unittest.TestCase):
    def setUp(self):
        self.md = A.agents_md()
        self.entries = entries(self.md)
        self.live = {(r.method, r.path): r for r in R.ROUTES if r.live}

    def test_every_live_route_and_no_other(self):
        self.assertEqual(set(self.entries), set(self.live))
        self.assertEqual(A.documented(self.md), set(self.live))
        known = {(r.method, r.path) for r in R.ROUTES}
        self.assertEqual(set(A.NOTES) - known, set(), "a note for a route that is not in the list")
        self.assertEqual(set(A.ANSWERS) - known, set(), "an answer for a route that is not in the list")
        dead = [r for r in R.ROUTES if not r.live]
        for r in dead:                                          # a route that is not built is not even named
            self.assertNotIn(f"`{r.method} {r.path}`", self.md)

    def test_a_route_that_goes_live_appears_and_one_that_dies_leaves(self):
        old = list(R.ROUTES)
        try:
            R.ROUTES[:] = [r._replace(live=not r.live) if r.path == "/api/health" else r for r in old]
            self.assertNotIn("### `GET /api/health`", A.agents_md())
            R.ROUTES.append(R.Route("GET", "/api/brand-new", "anyone", "A new thing.", None, None, "-", "x", True))
            self.assertIn("### `GET /api/brand-new`\nA new thing.", A.agents_md())
        finally:
            R.ROUTES[:] = old

    def test_examples_are_json_and_match_the_fixtures(self):
        for key, r in self.live.items():
            text = self.entries[key]
            self.assertIn(r.what, text)
            if r.body is not None:
                self.assertEqual(block(text, "Request body:"), r.body, key)
            ex = block(text, "Example answer:")
            if r.fixture:
                full = json.loads((FIXTURES / r.fixture).read_text(encoding="utf-8"))
                self.assertIsNotNone(ex, key)
                self.assertEqual(same_shape(ex, full, r.path), [], key)
                self.assertEqual(set(ex), set(full), key)        # no top-level key is dropped from an example
            elif key in A.ANSWERS:
                self.assertEqual(ex, A.ANSWERS[key], key)
        for r in R.public():
            if r.live and r.method != "GET":
                self.assertIsNotNone(A.example(r), f"{r.method} {r.path} has no example answer")

    def test_it_says_what_must_be_said_and_promises_nothing_else(self):
        for needle in ("Never send your game key", "X-Plaza-Token", "X-Plaza-Pin", "X-Team-Key", "venue `v07`",
                       '"venue": "v07"', "/api/agent/next", "/api/agent/ack", "PLAZA-7K2Q9M", "curl -X PUT",
                       "`settled`", "offers_for_you", "429", "Fair play"):
            self.assertIn(needle, self.md)
        low = self.md.lower()
        for cut in ("anonymous", "bundle", "price band", "matched every tick", "best price", "per tick call"):
            self.assertNotIn(cut, low)                           # cut for today in CONTRACT.md: never written
        self.assertNotIn("$PLAZA", A.agents_md(base="https://m.example.org/plaza/"))
        self.assertIn("https://m.example.org/plaza/api/connect/agent", A.agents_md(base="https://m.example.org/plaza/"))
        self.assertIn("Mercado X", A.agents_md(name="Mercado X").splitlines()[0])
        self.assertLess(len(self.md), 60_000)

    def test_the_loop_in_the_document_is_real_python(self):
        compile(A.LOOP, "AGENTS.md loop", "exec")
        self.assertIn(A.LOOP, self.md)
        for secret in ("X-Team-Key", "GAME_KEY"):
            self.assertIn(secret, A.LOOP)
        self.assertNotRegex(A.LOOP, r"PLAZA[^\n]*X-Team-Key")     # the game key is never a header of a market call


class PromptTest(unittest.TestCase):
    def test_both_languages_are_short_and_complete(self):
        base = "https://overhead-silicon-cork-citation.example.com/plaza"
        for lang, own in (("en", "YOUR OWN game key"), ("es", "TU PROPIA clave del juego")):
            p = C.prompt("t16", "PLAZA-7K2Q9M", base, "v07", "v07 Market", lang=lang)
            self.assertLessEqual(len(p), 900, lang)
            for piece in ("Team 16", "PLAZA-7K2Q9M", "/AGENTS.md", "/api/connect/agent", own, "t10", "v07",
                          "/api/team/t16", "/api/agent/next", "/api/agent/ack", "X-Plaza-Token", base + "\n"):
                self.assertIn(piece, p, lang)
        self.assertEqual(C.prompt("t16", "PLAZA-7K2Q9M", base), C.prompt("t16", "PLAZA-7K2Q9M", base, lang="xx"))


class RealAnswersTest(unittest.TestCase):
    """The examples written by hand (routes without a fixture) against what the server answers."""
    setUp, tearDown, call = T.FlowTest.setUp, T.FlowTest.tearDown, T.FlowTest.call
    connect = T.FlowTest.connect

    def match(self, tok7) -> str:
        """A live match of t07, set by hand from our panel so the test does not depend on the matcher's rules."""
        st, out, _ = self.call("POST", "/plaza/admin/api/action", {"action": "force", "seller": "t09", "buyer": "t07",
                                                                   "ref": "LAT-06"}, {"X-Plaza-Admin": "test-admin-token"})
        self.assertEqual(st, 200, out)
        return out["match"]

    def test_served_raw_with_the_public_address(self):
        for path in ("/plaza/AGENTS.md", "/plaza/agents.md", "/AGENTS.md"):
            st, md, h = self.call("GET", path)
            self.assertEqual((st, h["Content-Type"].split(";")[0]), (200, "text/markdown"), path)
            self.assertEqual(A.documented(md), {(r.method, r.path) for r in R.ROUTES if r.live})

    def test_written_examples_have_the_real_shape(self):
        st, s, _ = self.call("POST", "/plaza/api/connect/start", {"team": "t08"})
        st, real, _ = self.call("POST", "/plaza/api/connect/agent", {"team": "t08", "code": s["connect_code"]})
        self.assertEqual(same_shape(A.ANSWERS[("POST", "/api/connect/agent")], real, "agent"), [])
        _, tok7, _ = self.connect("t07")
        h7 = {"X-Plaza-Token": tok7}
        mid = self.match(tok7)
        cases = [
            ("POST", "/api/match/{match}/message", f"/plaza/api/match/{mid}/message", {"action": "counter", "price": 15}),
            ("POST", "/api/me/trade/{match}", f"/plaza/api/me/trade/{mid}", {"order": "counter", "price": 16}),
            ("PUT", "/api/team/{team}", "/plaza/api/team/t07", {"wants": ["LAT-06"], "spares": ["LAT-03"], "for_sale": [{"ref": "LAT-03", "price": 12, "min": 9}]}),
            ("POST", "/api/me/card/{ref}", "/plaza/api/me/card/LAT-03", {"min": 9, "value": 11}),
            ("POST", "/api/floor", "/plaza/api/floor", {"kind": "want", "ref": "LAT-06", "price": 18}),
        ]
        for method, row, path, body in cases:
            if not any(r.live and (r.method, r.path) == (method, row) for r in R.ROUTES):
                continue
            st, real, _ = self.call(method, path, body, h7)
            self.assertEqual(st, 200, (row, real))
            written = json.loads(json.dumps(A.ANSWERS[(method, row)]).replace("m-ba346d6c75", mid))
            self.assertEqual(same_shape(written, real, row), [], row)
        nxt = self.call("GET", "/plaza/api/agent/next", headers=h7)[1]
        self.assertTrue(nxt["actions"], nxt)
        st, real, _ = self.call("POST", "/plaza/api/agent/ack", {"id": nxt["actions"][0]["id"], "status": "done"}, h7)
        self.assertEqual(same_shape(A.ANSWERS[("POST", "/api/agent/ack")], real, "ack"), [])
        st, real, _ = self.call("POST", "/plaza/api/claim", {"team": "t05", "pin": "4821"})
        self.assertEqual(same_shape(A.ANSWERS[("POST", "/api/claim")], real, "claim"), [])

    def test_the_queue_names_only_documented_action_types_and_targets(self):
        _, tok7, _ = self.connect("t07")
        self.match(tok7)
        md = A.agents_md()
        for tok in (tok7,):
            for a in self.call("GET", "/plaza/api/agent/next", headers={"X-Plaza-Token": tok})[1]["actions"]:
                self.assertIn(f"| `{a['type']}`", md.replace("`counter`, `pass`", "`counter` | `pass`"), a["type"])
                self.assertIn(a["request"]["target"], ("game", "plaza"))


if __name__ == "__main__":
    unittest.main()
