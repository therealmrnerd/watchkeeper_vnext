import importlib
import json
import os
import shutil
import sqlite3
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
ADVISORY_DIR = ROOT_DIR / "services" / "advisory"
for p in (BRAINSTEM_DIR, ADVISORY_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


class AssistEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.modules.pop("app", None)
        advisory_app = importlib.import_module("app")
        cls.advisory_server = ThreadingHTTPServer(("127.0.0.1", 0), advisory_app.AdvisoryHandler)
        cls.advisory_port = int(cls.advisory_server.server_address[1])
        cls.advisory_thread = threading.Thread(target=cls.advisory_server.serve_forever, daemon=True)
        cls.advisory_thread.start()

        cls.temp_dir = Path(tempfile.mkdtemp(prefix="assist_endpoint_"))
        cls.db_path = cls.temp_dir / "watchkeeper_assist.db"

        os.environ["WKV_DB_PATH"] = str(cls.db_path)
        os.environ["WKV_SCHEMA_PATH"] = str(ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
        os.environ["WKV_STANDING_ORDERS_PATH"] = str(ROOT_DIR / "config" / "standing_orders.json")
        os.environ["WKV_ENABLE_ACTUATORS"] = "0"
        os.environ["WKV_EDPARSER_ENABLED"] = "0"
        os.environ["WKV_ADVISORY_ENABLED"] = "1"
        os.environ["WKV_ADVISORY_URL"] = f"http://127.0.0.1:{cls.advisory_port}/assist"
        os.environ["WKV_ADVISORY_TIMEOUT_SEC"] = "5"

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
        try:
            cls.advisory_server.shutdown()
            cls.advisory_server.server_close()
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

    def test_assist_endpoint_returns_and_logs_proposal(self) -> None:
        request_id = "req-assist-endpoint-001"
        status, body = self._request(
            "POST",
            "/assist",
            {
                "schema_version": "1.0",
                "request_id": request_id,
                "session_id": "sess-01",
                "timestamp_utc": "2026-02-19T10:00:00Z",
                "mode": "game",
                "domain": "general",
                "urgency": "normal",
                "user_text": "set lights combat",
                "stt_confidence": 0.95,
                "foreground_process": "EliteDangerous64.exe",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("request_id"), request_id)
        self.assertIn("proposal", body)
        self.assertIn("policy_preview", body)

        con = sqlite3.connect(self.db_path)
        try:
            row = con.execute(
                "SELECT request_id,proposed_actions_json FROM intent_log WHERE request_id=?",
                (request_id,),
            ).fetchone()
        finally:
            con.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], request_id)
        self.assertTrue(len(str(row[1])) > 2)


if __name__ == "__main__":
    unittest.main()
