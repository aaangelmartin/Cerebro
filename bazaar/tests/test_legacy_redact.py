import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[2] / "legacy" / "dashboard" / "server.py"


def _load():
    spec = importlib.util.spec_from_file_location("legacy_dashboard_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LegacyLogRedactTest(unittest.TestCase):
    def test_broker_key_never_reaches_actions_log(self):
        srv = _load()
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "actions.log"
            with mock.patch.object(srv, "ACTIONS_LOG", log):
                resp = json.dumps({"venue": {"id": "v9", "broker_key": "bk-SECRET"}, "list": [{"key": "k-SECRET"}],
                                   "keys_count": 2}).encode()
                srv.log_action("owner", "POST", "/api/venues", b'{"name": "board"}', 201, resp)
                srv.log_action("owner", "POST", "/api/venues", b"", 201, b'oops {"broker_key": "bk-RAW"')
            text = log.read_text()
            self.assertNotIn("SECRET", text)
            self.assertNotIn("bk-RAW", text)
            row = json.loads(text.splitlines()[0])
            self.assertEqual(json.loads(row["response"])["venue"], {"id": "v9", "broker_key": "<redacted>"})
            self.assertEqual(json.loads(row["response"])["keys_count"], 2)
            self.assertEqual(json.loads(row["body"]), {"name": "board"})


if __name__ == "__main__":
    unittest.main()
