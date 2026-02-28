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
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.calls = []

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
            operation=ProviderOperationId.SYSTEM_LOOKUP,
            fetched_at="2026-02-28T12:35:56.000000Z",
            cache=ProviderCacheMeta(hit=not self.ok, age_s=4 if not self.ok else 0, stale_served=not self.ok),
            data={"name": params.get("system_name"), "system_address": params.get("system_address")},
            provenance=ProviderProvenance(endpoint="https://spansh.invalid/system", http_code=200 if self.ok else 503),
            error=None if self.ok else "provider unavailable",
            deny_reason=None,
        )


class SupervisorSystemChangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_collect = supervisor.collect_ed_state

    def tearDown(self) -> None:
        supervisor.collect_ed_state = self.original_collect

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


if __name__ == "__main__":
    unittest.main()
