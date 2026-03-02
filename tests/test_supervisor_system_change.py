import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.ed_provider_types import (
    ProviderCacheMeta,
    ProviderId,
    ProviderOperationId,
    ProviderProvenance,
    ProviderResult,
)
import supervisor


class _FakeDB:
    def __init__(self) -> None:
        self.batch_calls = []
        self.events = []

    def batch_set_state(self, *, items, emit_events):
        self.batch_calls.append({"items": items, "emit_events": emit_events})
        return {"changed": len(items)}

    def append_event(self, **kwargs):
        self.events.append(kwargs)


class _FakeProviderService:
    def __init__(self, *, ok: bool = True, inara_enabled: bool = False) -> None:
        self.ok = ok
        self.calls = []
        self.config = {"providers": {"inara": {"enabled": inara_enabled}}}

    def execute_priority(
        self,
        *,
        operation,
        params,
        max_age_s,
        allow_stale_if_error,
        incident_id=None,
        reason="",
    ):
        self.calls.append(
            {
                "operation": operation,
                "params": dict(params),
                "max_age_s": max_age_s,
                "allow_stale_if_error": allow_stale_if_error,
                "incident_id": incident_id,
                "reason": reason,
            }
        )
        return ProviderResult(
            ok=self.ok,
            provider=ProviderId.SPANSH,
            operation=operation,
            fetched_at="2026-02-28T12:35:56.000000Z",
            cache=ProviderCacheMeta(hit=not self.ok, age_s=4 if not self.ok else 0, stale_served=not self.ok),
            data=(
                {
                    "name": params.get("system_name"),
                    "system_address": params.get("system_address"),
                    "sync_skipped": False,
                }
                if operation == ProviderOperationId.COMMANDER_LOCATION_PUSH
                else {"name": params.get("system_name"), "system_address": params.get("system_address")}
            ),
            provenance=ProviderProvenance(endpoint="https://spansh.invalid/system", http_code=200 if self.ok else 503),
            error=None if self.ok else "provider unavailable",
            deny_reason=None,
        )


class SupervisorSystemChangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_collect = supervisor.collect_ed_state
        self.original_db_class = supervisor.BrainstemDB
        self.original_process_ed = supervisor.process_ed
        self.original_process_edparser = supervisor.process_edparser
        self.original_process_aux_apps = supervisor.process_aux_apps
        self.original_process_jinx_sync = supervisor.process_jinx_sync
        self.original_process_hardware = supervisor.process_hardware
        self.original_process_sammi_bridge = supervisor.process_sammi_bridge
        self.original_process_music = supervisor.process_music
        self.original_process_watch_condition = supervisor.process_watch_condition
        self.original_jinx_lighting_enabled = supervisor._jinx_lighting_enabled

    def tearDown(self) -> None:
        supervisor.collect_ed_state = self.original_collect
        supervisor.BrainstemDB = self.original_db_class
        supervisor.process_ed = self.original_process_ed
        supervisor.process_edparser = self.original_process_edparser
        supervisor.process_aux_apps = self.original_process_aux_apps
        supervisor.process_jinx_sync = self.original_process_jinx_sync
        supervisor.process_hardware = self.original_process_hardware
        supervisor.process_sammi_bridge = self.original_process_sammi_bridge
        supervisor.process_music = self.original_process_music
        supervisor.process_watch_condition = self.original_process_watch_condition
        supervisor._jinx_lighting_enabled = self.original_jinx_lighting_enabled

    def _set_collect(self, payload):
        supervisor.collect_ed_state = lambda: dict(payload)

    def test_process_ed_ensures_cache_on_first_seen_system(self):
        self._set_collect(
            {
                "ed.running": True,
                "ed.process_name": "EliteDangerous64.exe",
                "ed.telemetry.system_name": "Sol",
                "ed.telemetry.system_address": 10477373803,
                "ed.telemetry.hull_percent": 100,
            }
        )
        db = _FakeDB()
        provider = _FakeProviderService(ok=True)

        running, current_system = supervisor.process_ed(
            db,
            previous_running=None,
            previous_system=None,
            provider_query_service=provider,
        )

        self.assertTrue(running)
        self.assertEqual(current_system, ("Sol", 10477373803))
        self.assertGreaterEqual(len(db.batch_calls), 2)
        semantic_keys = {
            item["state_key"]
            for item in db.batch_calls[1]["items"]
        }
        self.assertIn("ed.semantic.session.online_state", semantic_keys)
        self.assertIn("ed.semantic.flight.flight_status", semantic_keys)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["operation"], ProviderOperationId.SYSTEM_LOOKUP)
        self.assertEqual(provider.calls[0]["params"]["system_name"], "Sol")
        self.assertEqual(provider.calls[0]["params"]["system_address"], 10477373803)
        self.assertEqual(provider.calls[0]["reason"], "system_change")
        self.assertIn("ED_SYSTEM_CACHE_ENSURED", [event["event_type"] for event in db.events])

    def test_process_ed_skips_cache_when_system_unchanged(self):
        self._set_collect(
            {
                "ed.running": True,
                "ed.process_name": "EliteDangerous64.exe",
                "ed.telemetry.system_name": "Sol",
                "ed.telemetry.system_address": 10477373803,
            }
        )
        db = _FakeDB()
        provider = _FakeProviderService(ok=True)

        running, current_system = supervisor.process_ed(
            db,
            previous_running=True,
            previous_system=("Sol", 10477373803),
            provider_query_service=provider,
        )

        self.assertTrue(running)
        self.assertEqual(current_system, ("Sol", 10477373803))
        self.assertEqual(provider.calls, [])
        self.assertNotIn("ED_SYSTEM_CACHE_ENSURED", [event["event_type"] for event in db.events])

    def test_process_ed_logs_cache_failure(self):
        self._set_collect(
            {
                "ed.running": True,
                "ed.process_name": "EliteDangerous64.exe",
                "ed.telemetry.system_name": "Achenar",
                "ed.telemetry.system_address": 6289501754786,
            }
        )
        db = _FakeDB()
        provider = _FakeProviderService(ok=False)

        running, current_system = supervisor.process_ed(
            db,
            previous_running=True,
            previous_system=("Sol", 10477373803),
            provider_query_service=provider,
        )

        self.assertTrue(running)
        self.assertEqual(current_system, ("Achenar", 6289501754786))
        self.assertEqual(len(provider.calls), 1)
        failure_events = [event for event in db.events if event["event_type"] == "ED_SYSTEM_CACHE_FAILED"]
        self.assertEqual(len(failure_events), 1)
        self.assertEqual(failure_events[0]["payload"]["system_name"], "Achenar")
        self.assertEqual(failure_events[0]["payload"]["previous_system_name"], "Sol")
        self.assertEqual(failure_events[0]["payload"]["error"], "provider unavailable")

    def test_process_ed_triggers_inara_sync_when_enabled(self):
        self._set_collect(
            {
                "ed.running": True,
                "ed.process_name": "EliteDangerous64.exe",
                "ed.telemetry.system_name": "Lave",
                "ed.telemetry.system_address": 123456789,
            }
        )
        db = _FakeDB()
        provider = _FakeProviderService(ok=True, inara_enabled=True)

        running, current_system = supervisor.process_ed(
            db,
            previous_running=True,
            previous_system=("Sol", 10477373803),
            provider_query_service=provider,
        )

        self.assertTrue(running)
        self.assertEqual(current_system, ("Lave", 123456789))
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[0]["operation"], ProviderOperationId.SYSTEM_LOOKUP)
        self.assertEqual(provider.calls[1]["operation"], ProviderOperationId.COMMANDER_LOCATION_PUSH)
        self.assertIn("INARA_LOCATION_SYNCED", [event["event_type"] for event in db.events])

    def test_run_supervisor_once_skips_hardware_when_jinx_sync_disabled(self):
        hardware_calls = []

        class _FakeBrainstemDB:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def ensure_schema(self) -> None:
                return None

        supervisor.BrainstemDB = _FakeBrainstemDB
        supervisor.process_ed = lambda *_args, **_kwargs: (False, None)
        supervisor.process_edparser = lambda *_args, **_kwargs: None
        supervisor.process_aux_apps = lambda *_args, **_kwargs: ({"jinx": True}, None)
        supervisor.process_jinx_sync = lambda *_args, **_kwargs: None
        supervisor.process_hardware = lambda *_args, **_kwargs: hardware_calls.append("called")
        supervisor.process_sammi_bridge = lambda *_args, **_kwargs: None
        supervisor.process_music = lambda *_args, **_kwargs: (False, None)
        supervisor.process_watch_condition = lambda *_args, **_kwargs: "standby"
        supervisor._jinx_lighting_enabled = lambda: False

        supervisor.run_supervisor_once()

        self.assertEqual(hardware_calls, [])


if __name__ == "__main__":
    unittest.main()
