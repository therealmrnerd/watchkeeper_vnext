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
    ProviderOperationId,
    ProviderProvenance,
    ProviderQuery,
    ProviderRateLimitState,
    ProviderResult,
)
from provider_health import upsert_provider_health


class _FakeProviderService:
    def __init__(self):
        self.requests = []
        self.priority_requests = []

    def execute(self, request_obj: ProviderQuery) -> ProviderResult:
        self.requests.append(request_obj)
        if request_obj.operation == ProviderOperationId.BODIES_LOOKUP:
            data = {
                "system_address": 10477373803,
                "system_name": "Sol",
                "body_count": 2,
                "items": [
                    {"name": "Sol A", "body_type": "Star"},
                    {"name": "Earth", "body_type": "Planet"},
                ],
            }
        elif request_obj.operation == ProviderOperationId.STATIONS_LOOKUP:
            data = {
                "system_address": 10477373803,
                "system_name": "Sol",
                "station_count": 1,
                "items": [
                    {"name": "Galileo", "station_type": "Orbis Starport"},
                ],
            }
        else:
            data = {
                "system_address": 10477373803,
                "name": "Sol",
            }
        return ProviderResult(
            ok=True,
            provider=request_obj.provider,
            operation=request_obj.operation,
            fetched_at="2026-02-28T12:34:56.000000Z",
            data=data,
            provenance=ProviderProvenance(
                endpoint="https://www.spansh.co.uk/api/system/10477373803",
                http_code=200,
            ),
            error=None,
            deny_reason=None,
        )

    def execute_priority(
        self,
        *,
        operation,
        params,
        max_age_s,
        allow_stale_if_error,
        incident_id=None,
        reason="",
    ) -> ProviderResult:
        self.priority_requests.append(
            {
                "operation": operation,
                "params": params,
                "max_age_s": max_age_s,
                "allow_stale_if_error": allow_stale_if_error,
                "incident_id": incident_id,
                "reason": reason,
            }
        )
        return ProviderResult(
            ok=True,
            provider=ProviderId.SPANSH,
            operation=ProviderOperationId.SYSTEM_LOOKUP,
            fetched_at="2026-02-28T12:35:56.000000Z",
            data={
                "system_address": 10477373803,
                "name": params.get("system_name") or "Sol",
            },
            provenance=ProviderProvenance(
                endpoint="https://www.spansh.co.uk/api/system/10477373803",
                http_code=200,
            ),
            error=None,
            deny_reason=None,
        )


class ProviderEndpointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="provider_endpoints_"))
        cls.db_path = cls.temp_dir / "provider_endpoints.db"

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
        cls.actions = importlib.import_module("actions")
        cls.queries = importlib.import_module("queries")
        cls.handlers = importlib.import_module("handlers")
        cls.runtime.ensure_db()
        cls.runtime.DB_SERVICE.set_state(
            state_key="ed.telemetry.system_name",
            state_value="Sol",
            source="test",
            observed_at_utc="2026-02-28T12:00:00Z",
            confidence=1.0,
            emit_event=False,
        )

        upsert_provider_health(
            cls.db_path,
            ProviderHealth(
                provider=ProviderId.SPANSH,
                status=ProviderHealthStatus.OK,
                checked_at="2026-02-28T12:00:00.000000Z",
                latency_ms=42,
                http_code=200,
                rate_limit_state=ProviderRateLimitState.OK,
                retry_after_s=None,
                tool_calls_allowed=True,
                degraded_readonly=True,
                message="healthy",
            ),
        )

        cls.fake_provider_service = _FakeProviderService()
        cls.runtime.ED_PROVIDER_QUERY_SERVICE = cls.fake_provider_service
        cls.actions.ED_PROVIDER_QUERY_SERVICE = cls.fake_provider_service
        cls.queries.ED_PROVIDER_QUERY_SERVICE = cls.fake_provider_service

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
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            method=method,
            data=data,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                status = int(getattr(resp, "status", 200))
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            raw = exc.read().decode("utf-8", errors="replace")
        return status, json.loads(raw) if raw else {}

    def test_get_providers_health_returns_normalized_rows(self) -> None:
        status, body = self._request("GET", "/providers/health")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertIn("spansh", body.get("providers", {}))
        self.assertEqual(body["providers"]["spansh"]["health"]["status"], "ok")
        self.assertEqual(body["providers"]["spansh"]["health"]["latency_ms"], 42)
        self.assertIn("inara", body.get("providers", {}))
        self.assertIn("auth_summary", body["providers"]["inara"])

    def test_post_providers_query_uses_provider_service(self) -> None:
        before = len(self.fake_provider_service.requests)
        status, body = self._request(
            "POST",
            "/providers/query",
            {
                "tool": "ed.provider_query",
                "provider": "spansh",
                "operation": "system_lookup",
                "params": {"system_name": "Sol"},
                "requirements": {"max_age_s": 86400, "allow_stale_if_error": True},
                "trace": {"incident_id": "inc-http-provider", "reason": "endpoint_test"},
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("provider"), "spansh")
        self.assertEqual(body.get("operation"), "system_lookup")
        self.assertEqual(body.get("data", {}).get("name"), "Sol")
        self.assertEqual(len(self.fake_provider_service.requests), before + 1)

    def test_post_providers_query_supports_bodies_lookup(self) -> None:
        status, body = self._request(
            "POST",
            "/providers/query",
            {
                "tool": "ed.provider_query",
                "provider": "spansh",
                "operation": "bodies_lookup",
                "params": {"system_address": 10477373803, "system_name": "Sol"},
                "requirements": {"max_age_s": 86400, "allow_stale_if_error": True},
                "trace": {"incident_id": "inc-http-bodies", "reason": "endpoint_test_bodies"},
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("operation"), "bodies_lookup")
        self.assertEqual(body.get("data", {}).get("body_count"), 2)

    def test_post_providers_query_supports_stations_lookup(self) -> None:
        status, body = self._request(
            "POST",
            "/providers/query",
            {
                "tool": "ed.provider_query",
                "provider": "spansh",
                "operation": "stations_lookup",
                "params": {"system_address": 10477373803, "system_name": "Sol"},
                "requirements": {"max_age_s": 86400, "allow_stale_if_error": True},
                "trace": {"incident_id": "inc-http-stations", "reason": "endpoint_test_stations"},
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("operation"), "stations_lookup")
        self.assertEqual(body.get("data", {}).get("station_count"), 1)

    def test_post_providers_query_supports_inara_location_push(self) -> None:
        status, body = self._request(
            "POST",
            "/providers/query",
            {
                "tool": "ed.provider_query",
                "provider": "inara",
                "operation": "commander_location_push",
                "params": {
                    "system_name": "Sol",
                    "system_address": 10477373803,
                },
                "requirements": {"max_age_s": 0, "allow_stale_if_error": False},
                "trace": {"incident_id": "inc-http-inara", "reason": "endpoint_test_inara"},
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("provider"), "inara")
        self.assertEqual(body.get("operation"), "commander_location_push")

    def test_get_current_system_routes_through_priority_service(self) -> None:
        status, body = self._request("GET", "/providers/current-system")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("provider"), "spansh")
        self.assertEqual(body.get("data", {}).get("name"), "Sol")
        self.assertEqual(body.get("current_system_state", {}).get("system_name"), "Sol")
        self.assertEqual(len(self.fake_provider_service.priority_requests), 1)

    def test_get_current_system_bodies_returns_read_shape(self) -> None:
        status, body = self._request("GET", "/providers/current-system/bodies?limit=10")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("operation"), "bodies_lookup")
        self.assertEqual(body.get("data", {}).get("body_count"), 2)
        self.assertEqual(body.get("data", {}).get("items", [])[1].get("name"), "Earth")

    def test_get_current_system_stations_returns_read_shape(self) -> None:
        status, body = self._request("GET", "/providers/current-system/stations?limit=10")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("operation"), "stations_lookup")
        self.assertEqual(body.get("data", {}).get("station_count"), 1)
        self.assertEqual(body.get("data", {}).get("items", [])[0].get("name"), "Galileo")


if __name__ == "__main__":
    unittest.main()
