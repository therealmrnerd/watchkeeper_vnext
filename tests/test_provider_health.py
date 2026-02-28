import shutil
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from core.ed_provider_types import ProviderHealthStatus, ProviderId, ProviderRateLimitState
from db_service import BrainstemDB
from provider_health import HttpProviderHealthProbe, ProviderHealthScheduler, list_provider_health


class _FakeResponse:
    def __init__(self, status: int = 200, body: bytes = b"ok") -> None:
        self.status = status
        self._body = body

    def read(self, _: int | None = None) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class ProviderHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="provider_health_"))
        self.db_path = self.temp_dir / "provider_health.db"
        self.schema_path = ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql"
        self.db = BrainstemDB(self.db_path, self.schema_path)
        self.db.ensure_schema()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_probe_ok_returns_normalized_health(self) -> None:
        probe = HttpProviderHealthProbe(
            provider_id=ProviderId.SPANSH,
            base_url="https://example.invalid/health",
            timeout_sec=1.0,
            opener=lambda req, timeout=0: _FakeResponse(status=200),
        )

        result = probe.probe()

        self.assertEqual(result.provider, ProviderId.SPANSH)
        self.assertEqual(result.status, ProviderHealthStatus.OK)
        self.assertEqual(result.http_code, 200)
        self.assertEqual(result.rate_limit_state, ProviderRateLimitState.OK)
        self.assertTrue(result.tool_calls_allowed)
        self.assertEqual(result.message, "healthy")

    def test_probe_429_returns_throttled(self) -> None:
        def _raise_429(req, timeout=0):
            raise urllib.error.HTTPError(
                url=req.full_url,
                code=429,
                msg="Too Many Requests",
                hdrs={"Retry-After": "60"},
                fp=None,
            )

        probe = HttpProviderHealthProbe(
            provider_id=ProviderId.EDSM,
            base_url="https://example.invalid/health",
            timeout_sec=1.0,
            opener=_raise_429,
        )

        result = probe.probe()

        self.assertEqual(result.status, ProviderHealthStatus.THROTTLED)
        self.assertEqual(result.http_code, 429)
        self.assertEqual(result.rate_limit_state, ProviderRateLimitState.THROTTLED)
        self.assertEqual(result.retry_after_s, 60)
        self.assertFalse(result.tool_calls_allowed)

    def test_probe_exception_returns_down(self) -> None:
        probe = HttpProviderHealthProbe(
            provider_id=ProviderId.EDSM,
            base_url="https://example.invalid/health",
            timeout_sec=1.0,
            opener=lambda req, timeout=0: (_ for _ in ()).throw(OSError("timeout")),
        )

        result = probe.probe()

        self.assertEqual(result.status, ProviderHealthStatus.DOWN)
        self.assertIsNone(result.http_code)
        self.assertFalse(result.tool_calls_allowed)
        self.assertIn("timeout", result.message)

    def test_scheduler_run_once_persists_provider_health(self) -> None:
        spansh_probe = HttpProviderHealthProbe(
            provider_id=ProviderId.SPANSH,
            base_url="https://example.invalid/spansh",
            timeout_sec=1.0,
            opener=lambda req, timeout=0: _FakeResponse(status=200),
        )
        edsm_probe = HttpProviderHealthProbe(
            provider_id=ProviderId.EDSM,
            base_url="https://example.invalid/edsm",
            timeout_sec=1.0,
            opener=lambda req, timeout=0: _FakeResponse(status=200),
        )
        scheduler = ProviderHealthScheduler(
            db_path=self.db_path,
            probes=[spansh_probe, edsm_probe],
            min_interval_sec=1,
            max_interval_sec=1,
            startup_probe=False,
        )

        results = scheduler.run_once()

        self.assertEqual(sorted(results.keys()), ["edsm", "spansh"])
        stored = list_provider_health(self.db_path)
        self.assertEqual(sorted(stored.keys()), ["edsm", "spansh"])
        self.assertEqual(stored["spansh"]["status"], "ok")
        self.assertEqual(stored["edsm"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
