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
from pathlib import Path
from http.server import ThreadingHTTPServer


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))


class BrainstemSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="brainstem_smoke_"))
        cls.db_path = cls.temp_dir / "watchkeeper_smoke.db"

        os.environ["WKV_DB_PATH"] = str(cls.db_path)
        os.environ["WKV_SCHEMA_PATH"] = str(ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
        os.environ["WKV_STANDING_ORDERS_PATH"] = str(ROOT_DIR / "config" / "standing_orders.json")
        os.environ["WKV_ENABLE_ACTUATORS"] = "0"
        os.environ["WKV_EDPARSER_ENABLED"] = "0"

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
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = int(getattr(resp, "status", 200))
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            raw = exc.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
        return status, data

    def test_get_routes_health_and_state(self) -> None:
        status, body = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))

        status, body = self._request("GET", "/state")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertIn("items", body)

    def test_post_state_success_and_validation_error(self) -> None:
        status, body = self._request(
            "POST",
            "/state",
            {
                "items": [
                    {
                        "state_key": "hw.smoke_key",
                        "state_value": {"value": 1},
                        "source": "smoke_test",
                    }
                ]
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertIn("state_keys", body)

        status, body = self._request("POST", "/state", {})
        self.assertEqual(status, 400)
        self.assertFalse(body.get("ok"))

    def test_post_intent_validation_error(self) -> None:
        status, body = self._request("POST", "/intent", {"request_id": "x"})
        self.assertEqual(status, 400)
        self.assertFalse(body.get("ok"))

    def test_not_found_route(self) -> None:
        status, body = self._request("GET", "/route_that_does_not_exist")
        self.assertEqual(status, 404)
        self.assertFalse(body.get("ok"))


if __name__ == "__main__":
    unittest.main()
