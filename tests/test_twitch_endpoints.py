import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))


class TwitchEndpointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_twitch_endpoints_"))
        cls.db_path = cls.temp_dir / "twitch_endpoints.db"

        os.environ["WKV_DB_PATH"] = str(cls.db_path)
        os.environ["WKV_SCHEMA_PATH"] = str(ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
        os.environ["WKV_STANDING_ORDERS_PATH"] = str(ROOT_DIR / "config" / "standing_orders.json")
        os.environ["WKV_ENABLE_ACTUATORS"] = "0"
        os.environ["WKV_EDPARSER_ENABLED"] = "0"
        os.environ["WKV_TWITCH_DEV_INGEST_ENABLED"] = "1"

        for name in ("runtime", "validators", "queries", "actions", "handlers"):
            sys.modules.pop(name, None)

        cls.runtime = importlib.import_module("runtime")
        cls.handlers = importlib.import_module("handlers")
        cls.runtime.ensure_db()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), cls.handlers.BrainstemHandler)
        cls.port = int(cls.server.server_address[1])
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.server.shutdown()
            cls.server.server_close()
        except Exception:
            pass
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            method=method,
            data=body,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = int(getattr(resp, "status", 200))
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            raw = exc.read().decode("utf-8", errors="replace")
        return status, json.loads(raw) if raw else {}

    def test_ingest_mock_and_query_user_and_recent(self) -> None:
        chat_payload = {
            "event_type": "CHAT",
            "payload": {
                "commit_ts": "2026-02-20T15:00:00.000000Z",
                "user_id": "u-endpoint-1",
                "login_name": "endpoint_user",
                "display_name": "Endpoint User",
                "message_id": "chat-endpoint-1",
                "message_text": "hello from endpoint test"
            },
        }
        status, result = self._request("POST", "/twitch/dev/ingest_mock", chat_payload)
        self.assertEqual(status, 200)
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("processed"))

        redeem_payload = {
            "event_type": "REDEEM",
            "payload": {
                "commit_ts": "2026-02-20T15:01:00.000000Z",
                "user_id": "u-endpoint-1",
                "reward_id": "reward-hydrate",
                "reward_title": "Hydrate",
            },
        }
        status, result = self._request("POST", "/twitch/dev/ingest_mock", redeem_payload)
        self.assertEqual(status, 200)
        self.assertTrue(result.get("ok"))

        status, user_data = self._request("GET", "/twitch/user/u-endpoint-1")
        self.assertEqual(status, 200)
        self.assertTrue(user_data.get("ok"))
        self.assertEqual(user_data.get("user_id"), "u-endpoint-1")
        self.assertGreaterEqual(len(user_data.get("last_messages", [])), 1)

        status, top = self._request("GET", "/twitch/user/u-endpoint-1/redeems/top?limit=5")
        self.assertEqual(status, 200)
        self.assertTrue(top.get("ok"))
        self.assertGreaterEqual(len(top.get("items", [])), 1)

        status, recent = self._request("GET", "/twitch/recent?limit=20")
        self.assertEqual(status, 200)
        self.assertTrue(recent.get("ok"))
        self.assertGreaterEqual(int(recent.get("count", 0)), 2)


if __name__ == "__main__":
    unittest.main()
