import unittest

from bazaar.broker.engine import BenchEngine, Match


class RuleFromMessageTest(unittest.TestCase):
    def test_server_message_settles_quotes_rule(self):
        eng = BenchEngine()
        self.assertEqual(eng.rule, "probe")
        eng.note_refused(Match("s1", "b1", 68, kind="probe"), "bad_match", "price must sit between the ask 114 and the bid 61")
        self.assertEqual((eng.rule, eng.learn_rule), ("quotes", False))
        self.assertEqual(eng.probe_budget(), 0)


if __name__ == "__main__":
    unittest.main()
