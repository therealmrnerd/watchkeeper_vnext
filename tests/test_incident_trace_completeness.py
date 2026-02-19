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


class IncidentTraceCompletenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.modules.pop("app", None)
        advisory_app = importlib.import_module("app")
        cls.advisory_server = ThreadingHTTPServer(("127.0.0.1", 0), advisory_app.AdvisoryHandler)
        cls.advisory_port = int(cls.advisory_server.server_address[1])
        cls.advisory_thread = threading.Thread(target=cls.advisory_server.serve_forever, daemon=True)
        cls.advisory_thread.start()

        cls.temp_dir = Path(tempfile.mkdtemp(prefix="incident_trace_"))
        cls.db_path = cls.temp_dir / "watchkeeper_trace.db"

        os.environ["WKV_DB_PATH"] = str(cls.db_path)
        os.environ["WKV_SCHEMA_PATH"] = str(ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
        os.environ["WKV_STANDING_ORDERS_PATH"] = str(ROOT_DIR / "config" / "standing_orders.json")
        os.environ["WKV_ENABLE_ACTUATORS"] = "0"
        os.environ["WKV_ENABLE_KEYPRESS"] = "0"
        os.environ["WKV_EDPARSER_ENABLED"] = "0"
        os.environ["WKV_ADVISORY_ENABLED"] = "1"
        os.environ["WKV_ADVISORY_URL"] = f"http://127.0.0.1:{cls.advisory_port}/assist"
        os.environ["WKV_ADVISORY_TIMEOUT_SEC"] = "5"

        for name in ("runtime", "validators", "queries", "actions", "handlers"):
            sys.modules.pop(name, None)

        cls.runtime = importlib.import_module("runtime")
        cls.actions = importlib.import_module("actions")
        cls.handlers = importlib.import_module("handlers")
        cls.runtime.ensure_db()
        cls.actions._get_foreground_process_name = lambda: "EliteDangerous64.exe"

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

    def test_incident_trace_has_full_assist_chain(self) -> None:
        request_id = "req-trace-001"
        incident_id = "inc-trace-001"

        status, assist = self._request(
            "POST",
            "/assist",
            {
                "schema_version": "1.0",
                "request_id": request_id,
                "session_id": "sess-trace-1",
                "timestamp_utc": "2026-02-19T10:00:00Z",
                "mode": "game",
                "domain": "general",
                "urgency": "normal",
                "watch_condition": "GAME",
                "incident_id": incident_id,
                "user_text": "press space",
                "stt_confidence": 0.95,
                "foreground_process": "EliteDangerous64.exe",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(assist.get("ok"))
        preview = assist.get("policy_preview", [])
        self.assertTrue(preview)
        confirm_token = str(preview[0].get("confirm_token") or "")
        self.assertTrue(confirm_token)

        status, confirmed = self._request(
            "POST",
            "/confirm",
            {
                "incident_id": incident_id,
                "tool_name": "keypress",
                "user_confirm_token": confirm_token,
                "request_id": request_id,
                "session_id": "sess-trace-1",
                "mode": "game",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(confirmed.get("ok"))

        status, executed = self._request(
            "POST",
            "/execute",
            {
                "request_id": request_id,
                "incident_id": incident_id,
                "dry_run": True,
                "allow_high_risk": True,
                "user_confirmed": True,
                "user_confirm_token": confirm_token,
                "watch_condition": "GAME",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(executed.get("ok"))

        with sqlite3.connect(self.db_path) as con:
            rows = con.execute(
                """
                SELECT event_type
                FROM event_log
                WHERE correlation_id=?
                ORDER BY id ASC
                """,
                (request_id,),
            ).fetchall()
        event_types = [row[0] for row in rows]

        required_order = [
            "ASSIST_REQUEST_SUMMARY",
            "ASSIST_PROPOSAL_RECEIVED",
            "ASSIST_PROPOSAL_VALIDATED",
            "ASSIST_CONFIRM_ISSUED",
            "ASSIST_POLICY_PREVIEW",
            "ASSIST_PROPOSAL",
            "ASSIST_CONFIRM_ACCEPTED",
            "ACTION_APPROVED",
            "ACTION_EXECUTED",
        ]
        for event_type in required_order:
            self.assertIn(event_type, event_types)

        last_index = -1
        for event_type in required_order:
            idx = event_types.index(event_type)
            self.assertGreater(idx, last_index)
            last_index = idx


if __name__ == "__main__":
    unittest.main()
