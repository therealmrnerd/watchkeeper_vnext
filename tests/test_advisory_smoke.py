import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ADVISORY_DIR = ROOT_DIR / "services" / "advisory"
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
for p in (BRAINSTEM_DIR, ADVISORY_DIR):
    if str(p) in sys.path:
        sys.path.remove(str(p))
for p in (BRAINSTEM_DIR, ADVISORY_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

sys.modules.pop("app", None)
from app import AdvisoryHandler
from validators import validate_intent_proposal


class AdvisorySmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), AdvisoryHandler)
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

    def _request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            method=method,
            data=data,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = int(getattr(resp, "status", 200))
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            raw = exc.read().decode("utf-8", errors="replace")
        return status, json.loads(raw) if raw else {}

    def test_advisory_returns_valid_proposal_with_stub(self) -> None:
        status, body = self._request(
            "POST",
            "/assist",
            {
                "schema_version": "1.0",
                "request_id": "req-adv-001",
                "timestamp_utc": "2026-02-19T10:00:00Z",
                "mode": "game",
                "domain": "general",
                "urgency": "normal",
                "user_text": "press space",
                "max_actions": 3,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        proposal = body.get("proposal")
        self.assertIsInstance(proposal, dict)
        validate_intent_proposal(proposal)


if __name__ == "__main__":
    unittest.main()
