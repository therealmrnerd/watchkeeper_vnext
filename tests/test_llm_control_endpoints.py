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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
for p in (BRAINSTEM_DIR,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


class _FakeAdvisoryLlmHandler(BaseHTTPRequestHandler):
    llm_status = {"loaded": False, "loading": False, "device": "GPU", "last_error": None}

    def log_message(self, fmt, *args):
        return

    def _send_json(self, status_code, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        if self.path == "/llm/status":
            self._send_json(200, {"ok": True, "mode": "openvino_local", "llm": dict(self.llm_status)})
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/llm/control":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
        action = str(body.get("action") or "").strip().lower()
        if action == "engage":
            type(self).llm_status["loaded"] = True
        elif action == "disengage":
            type(self).llm_status["loaded"] = False
        else:
            self._send_json(400, {"ok": False, "error": "bad_action"})
            return
        self._send_json(200, {"ok": True, "action": action, "mode": "openvino_local", "llm": dict(self.llm_status)})


class LlmControlEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.advisory_server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeAdvisoryLlmHandler)
        cls.advisory_port = int(cls.advisory_server.server_address[1])
        cls.advisory_thread = threading.Thread(target=cls.advisory_server.serve_forever, daemon=True)
        cls.advisory_thread.start()

        cls.temp_dir = Path(tempfile.mkdtemp(prefix="llm_control_endpoint_"))
        cls.db_path = cls.temp_dir / "watchkeeper_llm_control.db"

        os.environ["WKV_DB_PATH"] = str(cls.db_path)
        os.environ["WKV_SCHEMA_PATH"] = str(ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
        os.environ["WKV_STANDING_ORDERS_PATH"] = str(ROOT_DIR / "config" / "standing_orders.json")
        os.environ["WKV_ENABLE_ACTUATORS"] = "0"
        os.environ["WKV_EDPARSER_ENABLED"] = "0"
        os.environ["WKV_ADVISORY_LLM_STATUS_URL"] = f"http://127.0.0.1:{cls.advisory_port}/llm/status"
        os.environ["WKV_ADVISORY_LLM_CONTROL_URL"] = f"http://127.0.0.1:{cls.advisory_port}/llm/control"

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

    def test_llm_status_and_control_proxy(self) -> None:
        status, body = self._request("GET", "/llm/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["llm"]["loaded"])

        status, body = self._request("POST", "/llm/control", {"action": "engage"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["llm"]["loaded"])

        status, body = self._request("POST", "/llm/control", {"action": "disengage"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["llm"]["loaded"])


if __name__ == "__main__":
    unittest.main()
