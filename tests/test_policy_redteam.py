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
import uuid
from pathlib import Path
from unittest import mock
from http.server import ThreadingHTTPServer


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))


class PolicyRedteamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="brainstem_redteam_"))
        self.db_path = self.temp_dir / "watchkeeper_redteam.db"

        os.environ["WKV_DB_PATH"] = str(self.db_path)
        os.environ["WKV_SCHEMA_PATH"] = str(ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
        os.environ["WKV_STANDING_ORDERS_PATH"] = str(ROOT_DIR / "config" / "standing_orders.json")
        os.environ["WKV_ENABLE_ACTUATORS"] = "0"
        os.environ["WKV_EDPARSER_ENABLED"] = "0"

        for name in ("runtime", "validators", "queries", "actions", "handlers"):
            sys.modules.pop(name, None)

        self.runtime = importlib.import_module("runtime")
        self.actions = importlib.import_module("actions")
        self.handlers = importlib.import_module("handlers")
        self.runtime.ensure_db()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handlers.BrainstemHandler)
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

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
            with urllib.request.urlopen(req, timeout=20) as resp:
                status = int(getattr(resp, "status", 200))
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            raw = exc.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
        return status, data

    def _post_intent(
        self,
        *,
        request_id: str,
        mode: str,
        tool_name: str,
        action_count: int = 1,
    ) -> None:
        actions = []
        for idx in range(action_count):
            actions.append(
                {
                    "action_id": f"a{idx + 1}",
                    "tool_name": tool_name,
                    "parameters": {"q": f"test-{idx + 1}"} if tool_name == "web.search" else {"key": "space"},
                    "safety_level": "low_risk",
                    "timeout_ms": 1500,
                    "confidence": 0.95,
                }
            )
        payload = {
            "schema_version": "1.0",
            "request_id": request_id,
            "session_id": "redteam-session",
            "timestamp_utc": "2026-02-18T00:00:00.000Z",
            "mode": mode,
            "domain": "system",
            "urgency": "normal",
            "user_text": "run action",
            "needs_tools": True,
            "needs_clarification": False,
            "proposed_actions": actions,
            "response_text": "ok",
        }
        status, body = self._request("POST", "/intent", payload)
        self.assertEqual(status, 200, body)
        self.assertTrue(body.get("ok"), body)

    def test_direct_execute_denied_tool_is_logged(self) -> None:
        request_id = f"rq-{uuid.uuid4().hex}"
        self._post_intent(request_id=request_id, mode="work", tool_name="keypress")

        status, body = self._request(
            "POST",
            "/execute",
            {
                "request_id": request_id,
                "incident_id": "inc-deny-1",
                "dry_run": True,
                "stt_confidence": 0.95,
            },
        )
        self.assertEqual(status, 200, body)
        self.assertTrue(body.get("ok"), body)
        result = body["results"][0]
        self.assertEqual(result["status"], "denied")

        with sqlite3.connect(self.db_path) as con:
            row = con.execute(
                """
                SELECT payload_json
                FROM event_log
                WHERE event_type='ACTION_DENIED'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        self.assertIsNotNone(row)
        payload = json.loads(row[0])
        self.assertIn("reason_code", payload)

    def test_replay_confirm_token_after_expiry_denied(self) -> None:
        request_id = f"rq-{uuid.uuid4().hex}"
        incident_id = "inc-expired-1"
        tool_name = "twitch.redeem"
        self._post_intent(request_id=request_id, mode="game", tool_name=tool_name)

        status, first = self._request(
            "POST",
            "/execute",
            {
                "request_id": request_id,
                "incident_id": incident_id,
                "dry_run": True,
                "stt_confidence": 0.95,
            },
        )
        self.assertEqual(status, 200, first)
        self.assertEqual(first["results"][0]["status"], "requires_confirmation")
        confirm_token = first["results"][0]["confirm_token"]

        status, confirm = self._request(
            "POST",
            "/confirm",
            {
                "incident_id": incident_id,
                "tool_name": tool_name,
                "user_confirm_token": confirm_token,
                "confirmed_at_utc": "2020-01-01T00:00:00.000Z",
                "request_id": request_id,
                "session_id": "redteam-session",
                "mode": "game",
            },
        )
        self.assertEqual(status, 200, confirm)

        status, second = self._request(
            "POST",
            "/execute",
            {
                "request_id": request_id,
                "incident_id": incident_id,
                "dry_run": True,
                "stt_confidence": 0.95,
                "user_confirm_token": confirm_token,
            },
        )
        self.assertEqual(status, 200, second)
        self.assertEqual(second["results"][0]["status"], "requires_confirmation")
        self.assertEqual(second["results"][0]["reason_code"], "DENY_CONFIRMATION_EXPIRED")

    def test_wrong_foreground_process_denied(self) -> None:
        request_id = f"rq-{uuid.uuid4().hex}"
        self._post_intent(request_id=request_id, mode="game", tool_name="keypress")

        with mock.patch.object(self.actions, "_get_foreground_process_name", return_value="chrome.exe"):
            status, body = self._request(
                "POST",
                "/execute",
                {
                    "request_id": request_id,
                    "incident_id": "inc-foreground-1",
                    "dry_run": True,
                    "stt_confidence": 0.95,
                },
            )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["results"][0]["status"], "denied")
        self.assertEqual(body["results"][0]["reason_code"], "DENY_FOREGROUND_MISMATCH")

    def test_rate_limit_enforced_under_repeated_calls(self) -> None:
        denied_reason_codes: list[str] = []
        with mock.patch.object(
            self.actions.LOGBOOK, "log_execute_result", return_value=None
        ), mock.patch.object(self.actions.TOOL_ROUTER.logbook, "log_decision", return_value=None):
            for idx in range(13):
                request_id = f"rq-{uuid.uuid4().hex}"
                self._post_intent(request_id=request_id, mode="work", tool_name="web.search")
                status, body = self._request(
                    "POST",
                    "/execute",
                    {
                        "request_id": request_id,
                        "incident_id": f"inc-rl-{idx + 1}",
                        "dry_run": True,
                    },
                )
                self.assertEqual(status, 200, body)
                for row in body.get("results", []):
                    if row.get("status") == "denied":
                        denied_reason_codes.append(str(row.get("reason_code")))

        self.assertIn("DENY_RATE_LIMIT", denied_reason_codes)


if __name__ == "__main__":
    unittest.main()
