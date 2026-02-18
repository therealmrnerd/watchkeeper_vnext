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

from db_service import BrainstemDB


class MigrationApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_migrations_"))
        self.db_path = self.temp_dir / "migrations_test.db"
        self.schema_path = ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql"
        self.db = BrainstemDB(self.db_path, self.schema_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_apply_migrations_creates_core_tables_and_schema_version(self) -> None:
        self.db.ensure_schema()

        with sqlite3.connect(self.db_path) as con:
            for table_name in ("state_current", "event_log", "intent_log", "action_log"):
                row = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,),
                ).fetchone()
                self.assertIsNotNone(row, f"expected table {table_name} to exist")

            schema_version_row = con.execute(
                "SELECT value_json FROM config WHERE key='schema_version'"
            ).fetchone()
            self.assertIsNotNone(schema_version_row, "expected config.schema_version to exist")

            migration_rows = con.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
            self.assertGreaterEqual(len(migration_rows), 2)
            self.assertEqual(migration_rows[0][0], "001")
            self.assertEqual(migration_rows[1][0], "002")


if __name__ == "__main__":
    unittest.main()
