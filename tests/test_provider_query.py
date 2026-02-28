import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from core.ed_provider_types import ProviderId, ProviderOperationId, ProviderQuery
from db_service import BrainstemDB
from provider_health import upsert_provider_health
from provider_query import ProviderQueryService
from core.ed_provider_types import ProviderHealth, ProviderHealthStatus, ProviderRateLimitState


class _FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.headers = {"Content-Type": "application/json;charset=UTF-8"}

    def read(self, _size=None):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class ProviderQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="provider_query_"))
        self.db_path = self.temp_dir / "provider_query.db"
        self.schema_path = ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql"
        self.config_path = ROOT_DIR / "config" / "providers.json"
        self.db = BrainstemDB(self.db_path, self.schema_path)
        self.db.ensure_schema()
        self.calls = []

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _opener(self, req, timeout=0):
        url = req.full_url
        self.calls.append(url)
        if url == "https://www.spansh.co.uk":
            return _FakeResponse({"ok": True}, status=200)
        if url == "https://www.edsm.net":
            return _FakeResponse({"ok": True}, status=200)
        if url == "https://www.spansh.co.uk/api/search/systems?q=Sol":
            return _FakeResponse(
                {
                    "count": 1,
                    "query": "Sol",
                    "results": [{"id64": 10477373803, "name": "Sol", "x": 0.0, "y": 0.0, "z": 0.0}],
                }
            )
        if url == "https://www.spansh.co.uk/api/system/10477373803":
            return _FakeResponse(
                {
                    "record": {
                        "id64": 10477373803,
                        "name": "Sol",
                        "x": 0.0,
                        "y": 0.0,
                        "z": 0.0,
                        "allegiance": "Federation",
                        "government": "Democracy",
                        "security": "High",
                        "primary_economy": "Service",
                        "secondary_economy": "Tourism",
                        "population": 1000,
                        "body_count": 3,
                        "bodies": [
                            {
                                "id": 1,
                                "id64": 20477373803,
                                "name": "Sol A",
                                "type": "Star",
                                "subtype": "G (White-Yellow) Star",
                                "distance_to_arrival": 0,
                                "solar_mass": 1.0,
                                "radius": 695700000.0,
                                "gravity": 0.0,
                                "is_main_star": True,
                            },
                            {
                                "id": 2,
                                "id64": 20477373804,
                                "name": "Earth",
                                "type": "Planet",
                                "subtype": "Earth-like world",
                                "distance_to_arrival": 499.0,
                                "terraforming_state": "Terraformable",
                                "atmosphere_type": "Suitable for water-based life",
                                "earth_mass": 1.0,
                                "radius": 6371000.0,
                                "gravity": 1.0,
                            },
                        ],
                        "stations": [{"name": "Galileo"}],
                        "updated_at": "2026-02-28T12:00:00Z",
                        "region": "Inner Orion Spur",
                        "known_permit": "Sol Permit",
                        "needs_permit": True,
                    }
                }
            )
        if url == "https://www.edsm.net/api-v1/system?systemName=Sol&showCoordinates=1&showInformation=1&showPermit=1&showId=1":
            return _FakeResponse(
                {
                    "name": "Sol",
                    "id": 27,
                    "id64": 10477373803,
                    "coords": {"x": 0, "y": 0, "z": 0},
                    "requirePermit": True,
                    "permitName": "Sol",
                    "information": {
                        "allegiance": "Federation",
                        "government": "Democracy",
                        "population": 18320926115,
                        "security": "High",
                        "economy": "Refinery",
                        "secondEconomy": "Service",
                    },
                }
            )
        raise AssertionError(f"unexpected URL: {url}")

    def test_spansh_system_lookup_persists_cache_and_world_model(self) -> None:
        service = ProviderQueryService(
            db_path=self.db_path,
            config_path=self.config_path,
            opener=self._opener,
        )
        request_obj = ProviderQuery(
            provider=ProviderId.SPANSH,
            operation=ProviderOperationId.SYSTEM_LOOKUP,
            params={"system_name": "Sol"},
            max_age_s=86400,
            allow_stale_if_error=True,
            incident_id="inc-test-provider",
            reason="unit_test",
        )

        first = service.execute(request_obj)
        second = service.execute(request_obj)

        self.assertTrue(first.ok)
        self.assertEqual(first.data["system_address"], 10477373803)
        self.assertEqual(first.data["name"], "Sol")
        self.assertFalse(first.cache.hit)
        self.assertTrue(second.ok)
        self.assertTrue(second.cache.hit)
        self.assertEqual(
            self.calls,
            [
                "https://www.spansh.co.uk",
                "https://www.spansh.co.uk/api/search/systems?q=Sol",
                "https://www.spansh.co.uk/api/system/10477373803",
            ],
        )

        with sqlite3.connect(self.db_path) as con:
            system_row = con.execute(
                "SELECT name, primary_source FROM ed_systems WHERE system_address=?",
                (10477373803,),
            ).fetchone()
            self.assertIsNotNone(system_row)
            self.assertEqual(system_row[0], "Sol")
            self.assertEqual(system_row[1], "spansh")

            cache_row = con.execute(
                "SELECT provider, operation FROM provider_cache LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(cache_row)
            self.assertEqual(cache_row[0], "spansh")
            self.assertEqual(cache_row[1], "system_lookup")

    def test_spansh_bodies_lookup_persists_body_rows(self) -> None:
        service = ProviderQueryService(
            db_path=self.db_path,
            config_path=self.config_path,
            opener=self._opener,
        )
        result = service.execute(
            ProviderQuery(
                provider=ProviderId.SPANSH,
                operation=ProviderOperationId.BODIES_LOOKUP,
                params={"system_address": 10477373803, "system_name": "Sol"},
                max_age_s=86400,
                allow_stale_if_error=True,
                incident_id="inc-test-bodies",
                reason="unit_test_bodies",
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.operation, ProviderOperationId.BODIES_LOOKUP)
        self.assertEqual(result.data["system_address"], 10477373803)
        self.assertEqual(result.data["body_count"], 2)
        self.assertEqual(result.data["items"][1]["name"], "Earth")

        with sqlite3.connect(self.db_path) as con:
            body_rows = con.execute(
                "SELECT name, body_type, source FROM ed_bodies WHERE system_address=? ORDER BY name ASC",
                (10477373803,),
            ).fetchall()
            self.assertEqual(len(body_rows), 2)
            self.assertEqual(body_rows[0][0], "Earth")
            self.assertEqual(body_rows[0][1], "Planet")
            self.assertEqual(body_rows[0][2], "spansh")

    def test_spansh_stations_lookup_persists_station_rows(self) -> None:
        service = ProviderQueryService(
            db_path=self.db_path,
            config_path=self.config_path,
            opener=self._opener,
        )
        result = service.execute(
            ProviderQuery(
                provider=ProviderId.SPANSH,
                operation=ProviderOperationId.STATIONS_LOOKUP,
                params={"system_address": 10477373803, "system_name": "Sol"},
                max_age_s=86400,
                allow_stale_if_error=True,
                incident_id="inc-test-stations",
                reason="unit_test_stations",
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.operation, ProviderOperationId.STATIONS_LOOKUP)
        self.assertEqual(result.data["station_count"], 1)
        self.assertEqual(result.data["items"][0]["name"], "Galileo")

        with sqlite3.connect(self.db_path) as con:
            station_rows = con.execute(
                "SELECT name, source FROM ed_stations WHERE system_address=?",
                (10477373803,),
            ).fetchall()
            self.assertEqual(len(station_rows), 1)
            self.assertEqual(station_rows[0][0], "Galileo")
            self.assertEqual(station_rows[0][1], "spansh")

    def test_execute_priority_falls_back_to_edsm_when_spansh_is_down(self) -> None:
        service = ProviderQueryService(
            db_path=self.db_path,
            config_path=self.config_path,
            opener=self._opener,
        )
        upsert_provider_health(
            self.db_path,
            ProviderHealth(
                provider=ProviderId.SPANSH,
                status=ProviderHealthStatus.DOWN,
                checked_at="2026-02-28T12:00:00.000000Z",
                latency_ms=None,
                http_code=None,
                rate_limit_state=ProviderRateLimitState.UNKNOWN,
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=True,
                message="forced_down",
            ),
        )

        result = service.execute_priority(
            operation=ProviderOperationId.SYSTEM_LOOKUP,
            params={"system_name": "Sol"},
            max_age_s=86400,
            allow_stale_if_error=True,
            incident_id="inc-fallback",
            reason="fallback_test",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.provider, ProviderId.EDSM)
        self.assertEqual(result.data["name"], "Sol")
        self.assertIn("https://www.edsm.net/api-v1/system?systemName=Sol&showCoordinates=1&showInformation=1&showPermit=1&showId=1", self.calls)


if __name__ == "__main__":
    unittest.main()
