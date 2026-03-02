import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from settings_store import load_runtime_settings, save_runtime_settings


class RuntimeSettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="runtime_settings_"))
        self.db_path = self.temp_dir / "settings.db"
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

    def test_defaults_load_without_row(self) -> None:
        settings = load_runtime_settings(self.db_path)
        self.assertIsNone(settings["providers"]["spansh"]["enabled"])
        self.assertTrue(settings["providers"]["openai"]["live_applied"])
        self.assertTrue(settings["syncs"]["ed_provider_autocache"]["enabled"])
        self.assertTrue(settings["syncs"]["jinx_lighting"]["live_applied"])
        self.assertTrue(settings["syncs"]["ytmd_ingest"]["live_applied"])
        self.assertTrue(settings["syncs"]["sammi_bridge"]["live_applied"])
        self.assertTrue(settings["syncs"]["twitch_ingest"]["live_applied"])
        self.assertTrue(settings["providers"]["obs"]["live_applied"])
        self.assertTrue(settings["syncs"]["obs_status"]["live_applied"])

    def test_save_updates_selected_flags_and_preserves_defaults(self) -> None:
        saved = save_runtime_settings(
            self.db_path,
            {
                "providers": {
                    "spansh": {"enabled": False},
                    "inara": {"enabled": True},
                },
                "syncs": {
                    "ed_provider_autocache": {"enabled": False},
                },
            },
        )
        self.assertFalse(saved["providers"]["spansh"]["enabled"])
        self.assertTrue(saved["providers"]["inara"]["enabled"])
        self.assertFalse(saved["syncs"]["ed_provider_autocache"]["enabled"])
        self.assertIsNone(saved["providers"]["edsm"]["enabled"])

        reloaded = load_runtime_settings(self.db_path)
        self.assertFalse(reloaded["providers"]["spansh"]["enabled"])
        self.assertIsNone(reloaded["providers"]["edsm"]["enabled"])


if __name__ == "__main__":
    unittest.main()
