"""The practice market: the reference agent, given only what a cold agent is given, closes on v07 over HTTP."""
import os
import unittest

from bazaar.plaza import agent_example as E
from bazaar.plaza import sandbox as S


class SandboxTest(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.get("PLAZA_PUBLIC_URL")
        self.info = S.start(port=0, game_port=0, tick=0.15)

    def tearDown(self):
        self.info["stop"].set()
        self.info["game_server"].shutdown()
        self.info["game_server"].server_close()
        self.info["rig"].stop()
        if self.old is None:
            os.environ.pop("PLAZA_PUBLIC_URL", None)
        else:
            os.environ["PLAZA_PUBLIC_URL"] = self.old

    def test_the_guest_connects_proves_and_settles_on_v07(self):
        rig, info = self.info["rig"], self.info
        guest = info["game_obj"].guest()
        self.assertIn(guest["code"], guest["prompt"])
        self.assertIn(info["plaza"], guest["prompt"])
        self.assertTrue(guest["game_key"].startswith("SIMKEY-"))
        before = S.status(rig)
        self.assertFalse(before["passed"])
        self.assertFalse(before["teams"]["t01"]["verified"])

        st, out = E.http_json("GET", info["game"] + "/api/me")                 # the game wants a key
        self.assertEqual(st, 401)
        st, out = E.http_json("POST", info["game"] + "/api/threads", {"with": "t10", "venue": "v07"},
                              {"X-Team-Key": guest["game_key"]})               # the host's own venue: refused,
        self.assertEqual(st, 409)                                              # as the real game does (self_venue)
        self.assertIn("self_venue", str(out))
        st, out = E.http_json("POST", info["game"] + "/api/threads", {"with": "t10", "venue": "rastro"},
                              {"X-Team-Key": guest["game_key"]})               # the real game's two calls
        self.assertEqual(st, 200)
        self.assertIsInstance(out["id"], int)

        a = E.Agent("t01", info["plaza"], game=info["game"], key=guest["game_key"], log=lambda *_: None,
                    sleep=__import__("time").sleep)
        a.connect(guest["code"])
        self.assertTrue(a.prove(guest["code"]))
        self.assertTrue(a.wait_verified(tries=80, pause=0.1))   # nothing is written before the market saw the code
        import time
        deadline = time.time() + 20
        while time.time() < deadline and not S.status(rig)["passed"]:
            a.publish()
            a.step()
            time.sleep(0.15)
        after = S.status(rig)
        self.assertTrue(after["passed"], after["matches"])
        mine = after["teams"]["t01"]
        self.assertTrue(mine["connected"] and mine["verified"] and mine["sheet_published"])
        self.assertTrue(all(m["settled_venue"] == "v07" for m in after["matches"] if m["state"] == "settled"))


if __name__ == "__main__":
    unittest.main()
