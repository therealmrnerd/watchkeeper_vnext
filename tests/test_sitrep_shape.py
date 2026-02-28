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

from core.ed_provider_types import (
    ProviderHealth,
    ProviderHealthStatus,
    ProviderId,
    ProviderRateLimitState,
)
from provider_health import upsert_provider_health


class SitrepShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="sitrep_shape_"))
        cls.db_path = cls.temp_dir / "watchkeeper_sitrep.db"

        os.environ["WKV_DB_PATH"] = str(cls.db_path)
        os.environ["WKV_SCHEMA_PATH"] = str(ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
        os.environ["WKV_STANDING_ORDERS_PATH"] = str(ROOT_DIR / "config" / "standing_orders.json")
        os.environ["WKV_ENABLE_ACTUATORS"] = "0"
        os.environ["WKV_EDPARSER_ENABLED"] = "0"
        os.environ["WKV_ADVISORY_HEALTH_URL"] = ""
        os.environ["WKV_KNOWLEDGE_HEALTH_URL"] = ""
        os.environ["WKV_QDRANT_HEALTH_URL"] = ""

        for name in ("runtime", "validators", "queries", "actions", "handlers"):
            sys.modules.pop(name, None)

        cls.runtime = importlib.import_module("runtime")
        cls.handlers = importlib.import_module("handlers")
        cls.runtime.ensure_db()

        cls.runtime.DB_SERVICE.set_state(
            state_key="policy.watch_condition",
            state_value="GAME",
            source="test",
            observed_at_utc="2026-02-19T10:00:00Z",
            confidence=1.0,
            emit_event=False,
        )
        cls.runtime.DB_SERVICE.set_state(
            state_key="ed.status.running",
            state_value=True,
            source="test",
            observed_at_utc="2026-02-19T10:00:00Z",
            confidence=1.0,
            emit_event=False,
        )
        cls.runtime.DB_SERVICE.set_state(
            state_key="music.status.playing",
            state_value=False,
            source="test",
            observed_at_utc="2026-02-19T10:00:00Z",
            confidence=1.0,
            emit_event=False,
        )

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

    def _request(self, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                status = int(getattr(resp, "status", 200))
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            raw = exc.read().decode("utf-8", errors="replace")
        return status, json.loads(raw) if raw else {}

    def test_sitrep_returns_expected_shape(self) -> None:
        status, body = self._request("/sitrep")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertIn("watch_condition", body)
        self.assertIn("runtime", body)
        self.assertIn("services", body)
        self.assertIn("providers", body)
        self.assertIn("handover", body)
        self.assertIn("last_events", body)
        self.assertIsInstance(body.get("services"), dict)
        self.assertIsInstance(body.get("providers"), dict)
        self.assertIsInstance(body.get("last_events"), list)

    def test_sitrep_music_fallback_keys(self) -> None:
        self.runtime.DB_SERVICE.set_state(
            state_key="music.playing",
            state_value=True,
            source="test",
            observed_at_utc="2026-02-19T10:01:00Z",
            confidence=1.0,
            emit_event=False,
        )
        self.runtime.DB_SERVICE.set_state(
            state_key="music.track.title",
            state_value="Never Enough",
            source="test",
            observed_at_utc="2026-02-19T10:01:00Z",
            confidence=1.0,
            emit_event=False,
        )
        self.runtime.DB_SERVICE.set_state(
            state_key="music.track.artist",
            state_value="Loren Allred",
            source="test",
            observed_at_utc="2026-02-19T10:01:00Z",
            confidence=1.0,
            emit_event=False,
        )

        status, body = self._request("/sitrep")
        self.assertEqual(status, 200)
        music = body.get("handover", {}).get("music_state", {})
        self.assertEqual(music.get("playing"), True)
        self.assertEqual(music.get("title"), "Never Enough")
        self.assertEqual(music.get("artist"), "Loren Allred")

    def test_sitrep_exposes_provider_health(self) -> None:
        upsert_provider_health(
            self.db_path,
            ProviderHealth(
                provider=ProviderId.SPANSH,
                status=ProviderHealthStatus.OK,
                checked_at="2026-02-28T12:00:00.000000Z",
                latency_ms=123,
                http_code=200,
                rate_limit_state=ProviderRateLimitState.OK,
                retry_after_s=None,
                tool_calls_allowed=True,
                degraded_readonly=True,
                message="healthy",
            ),
        )

        status, body = self._request("/sitrep")
        self.assertEqual(status, 200)
        providers = body.get("providers", {})
        self.assertIn("spansh", providers)
        self.assertEqual(providers["spansh"]["status"], "ok")
        self.assertEqual(providers["spansh"]["latency_ms"], 123)
        self.assertEqual(providers["spansh"]["http"]["code"], 200)


if __name__ == "__main__":
    unittest.main()
