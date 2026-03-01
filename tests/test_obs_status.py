import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from settings_store import save_runtime_settings
import queries


class ObsStatusQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="obs_status_"))
        self.db_path = self.temp_dir / "obs_status.db"
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE config (
                  key TEXT PRIMARY KEY,
                  value_json TEXT NOT NULL,
                  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                )
                """
            )
            con.commit()
        self.original_db_path = queries.DB_PATH
        self.original_fetch = queries.fetch_obs_status
        queries.DB_PATH = self.db_path

    def tearDown(self) -> None:
        queries.DB_PATH = self.original_db_path
        queries.fetch_obs_status = self.original_fetch

    def test_obs_status_disabled_by_default(self) -> None:
        called = []
        queries.fetch_obs_status = lambda **kwargs: called.append(kwargs) or {"ok": True, "status": "up"}

        result = queries.query_obs_status({})

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(called, [])

    def test_obs_status_calls_client_when_enabled(self) -> None:
        save_runtime_settings(
            self.db_path,
            {
                "providers": {"obs": {"enabled": True}},
                "syncs": {"obs_status": {"enabled": True}},
            },
        )
        called = []
        queries.fetch_obs_status = lambda **kwargs: called.append(kwargs) or {
            "ok": True,
            "status": "up",
            "endpoint": {"host": "127.0.0.1", "port": 4455, "latency_ms": 9},
            "versions": {"obs_studio": "32.0.4"},
        }

        result = queries.query_obs_status({})

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "up")
        self.assertEqual(len(called), 1)
        self.assertTrue(result["enabled"]["provider"])
        self.assertTrue(result["enabled"]["status_polling"])


if __name__ == "__main__":
    unittest.main()
