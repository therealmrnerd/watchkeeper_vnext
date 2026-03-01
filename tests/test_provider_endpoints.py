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
        cls.config_path = cls.temp_dir / "providers.json"
        cls.secrets_path = cls.temp_dir / "provider_secrets.dpapi"

        provider_config = json.loads((ROOT_DIR / "config" / "providers.json").read_text(encoding="utf-8"))
        provider_config["providers"]["inara"]["enabled"] = True
        provider_config["providers"]["inara"]["auth"]["app_name"] = "Watchkeeper"
        provider_config["providers"]["inara"]["auth"]["app_key"] = ""
        provider_config["providers"]["inara"]["auth"]["commander_name"] = ""
        provider_config["providers"]["inara"]["auth"]["frontier_id"] = None
        cls.config_path.write_text(json.dumps(provider_config), encoding="utf-8")

        os.environ["WKV_DB_PATH"] = str(cls.db_path)
        os.environ["WKV_SCHEMA_PATH"] = str(ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
        os.environ["WKV_STANDING_ORDERS_PATH"] = str(ROOT_DIR / "config" / "standing_orders.json")
        os.environ["WKV_PROVIDER_CONFIG_PATH"] = str(cls.config_path)
        os.environ["WKV_PROVIDER_SECRETS_PATH"] = str(cls.secrets_path)
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
        cls.runtime.DB_SERVICE.append_event(
            event_id="evt-provider-write-ok",
            timestamp_utc="2026-02-28T12:10:00.000000Z",
            event_type="PROVIDER_WRITE_EXECUTED",
            source="provider_query",
            payload={
                "provider": "inara",
                "operation": "commander_location_push",
                "timestamp_utc": "2026-02-28T12:10:00.000000Z",
                "system_name": "Sol",
            },
            severity="info",
        )
        cls.runtime.DB_SERVICE.append_event(
            event_id="evt-provider-write-fail",
            timestamp_utc="2026-02-28T12:20:00.000000Z",
            event_type="PROVIDER_WRITE_FAILED",
            source="provider_query",
            payload={
                "provider": "inara",
                "operation": "commander_location_push",
                "system_name": "Achenar",
                "message": "provider unavailable",
            },
            severity="warn",
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
        for key in ("WKV_PROVIDER_CONFIG_PATH", "WKV_PROVIDER_SECRETS_PATH"):
            os.environ.pop(key, None)
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
        self.assertIn("activity_summary", body["providers"]["inara"])
        self.assertEqual(
            body["providers"]["inara"]["activity_summary"]["last_success_at"],
            "2026-02-28T12:10:00.000000Z",
        )
        self.assertEqual(
            body["providers"]["inara"]["activity_summary"]["last_failure_at"],
            "2026-02-28T12:20:00.000000Z",
        )

    def test_openai_credentials_round_trip_uses_secure_store(self) -> None:
        status, body = self._request("GET", "/config/openai/credentials")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertFalse(body["credentials"]["api_key_present"])
        self.assertIsNone(body["credentials"]["last_updated_at"])

        status, body = self._request(
            "POST",
            "/config/openai/credentials",
            {"api_key": "openai-test-key"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertTrue(body["credentials"]["api_key_present"])
        self.assertTrue(self.secrets_path.exists())
        self.assertNotIn(b"openai-test-key", self.secrets_path.read_bytes())

        status, body = self._request("GET", "/config/openai/credentials")
        self.assertEqual(status, 200)
        self.assertTrue(body["credentials"]["api_key_present"])
        self.assertEqual(body["credentials"]["api_key_source"], "secure_store")
        self.assertTrue(body["credentials"]["last_updated_at"])
        self.assertEqual(body["credentials"]["last_updated_at"], body["storage"]["last_updated_at"])

        status, body = self._request(
            "POST",
            "/config/openai/credentials",
            {"clear": True},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("cleared_securely"))
        self.assertFalse(body["credentials"]["api_key_present"])

        status, body = self._request("GET", "/config/openai/credentials")
        self.assertEqual(status, 200)
        self.assertFalse(body["credentials"]["api_key_present"])

    def test_get_inara_credentials_returns_secure_summary(self) -> None:
        status, body = self._request("GET", "/providers/inara/credentials")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("provider"), "inara")
        self.assertEqual(body.get("auth", {}).get("app_name"), "Watchkeeper")
        self.assertFalse(body.get("credentials", {}).get("api_key_present"))

    def test_post_inara_credentials_saves_encrypted_file(self) -> None:
        status, body = self._request(
            "POST",
            "/providers/inara/credentials",
            {
                "commander_name": "Cmdr Nerd",
                "frontier_id": "6206398",
                "api_key": "secret-api-key",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("saved_securely"))
        self.assertEqual(body.get("credentials", {}).get("commander_name"), "Cmdr Nerd")
        self.assertEqual(body.get("credentials", {}).get("frontier_id"), "6206398")
        self.assertTrue(body.get("credentials", {}).get("api_key_present"))
        self.assertEqual(body.get("credentials", {}).get("api_key_source"), "secure_store")
        self.assertTrue(self.secrets_path.exists())
        self.assertNotIn(b"secret-api-key", self.secrets_path.read_bytes())

        status, health_body = self._request("GET", "/providers/health")
        self.assertEqual(status, 200)
        self.assertTrue(health_body["providers"]["inara"]["auth_summary"]["configured"])

    def test_inara_credentials_can_be_cleared(self) -> None:
        status, body = self._request(
            "POST",
            "/providers/inara/credentials",
            {
                "commander_name": "Cmdr Nerd",
                "frontier_id": "6206398",
                "api_key": "secret-api-key",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("credentials", {}).get("api_key_present"))

        status, body = self._request(
            "POST",
            "/providers/inara/credentials",
            {"clear": True},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("cleared_securely"))
        self.assertEqual(body.get("credentials", {}).get("commander_name"), "")
        self.assertEqual(body.get("credentials", {}).get("frontier_id"), "")
        self.assertFalse(body.get("credentials", {}).get("api_key_present"))

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
