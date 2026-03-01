import importlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ADAPTERS_DIR = ROOT_DIR / "services" / "adapters"
if str(ADAPTERS_DIR) not in sys.path:
    sys.path.insert(0, str(ADAPTERS_DIR))


class StateCollectorRuntimeSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="state_collector_settings_"))
        self.db_path = self.temp_dir / "watchkeeper.db"
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
            con.execute(
                """
                INSERT INTO config(key, value_json)
                VALUES(?, ?)
                """,
                (
                    "runtime_settings",
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "syncs": {
                                "ytmd_ingest": {"enabled": False},
                            },
                        }
                    ),
                ),
            )
            con.commit()
        os.environ["WKV_DB_PATH"] = str(self.db_path)
        sys.modules.pop("state_collector", None)
        self.collector = importlib.import_module("state_collector")

    def test_collect_music_state_respects_disabled_ytmd_ingest(self) -> None:
        process_names = {"youtube music desktop app.exe"}
        result = self.collector.collect_music_state(process_names=process_names)
        self.assertTrue(result["music.app_running"])
        self.assertFalse(result["music.ingest_enabled"])
        self.assertFalse(result["music.playing"])
        self.assertEqual(result["music.track.title"], "")
        self.assertEqual(result["music.track.artist"], "")


if __name__ == "__main__":
    unittest.main()
