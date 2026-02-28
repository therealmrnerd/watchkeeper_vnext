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
            for table_name in (
                "state_current",
                "event_log",
                "intent_log",
                "action_log",
                "provider_health",
                "provider_cache",
                "ed_systems",
                "ed_bodies",
                "ed_stations",
            ):
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
            self.assertGreaterEqual(len(migration_rows), 4)
            self.assertEqual(migration_rows[0][0], "001")
            self.assertEqual(migration_rows[1][0], "002")
            self.assertEqual(migration_rows[2][0], "003")
            self.assertEqual(migration_rows[3][0], "004")

    def test_apply_migrations_supports_world_model_inserts(self) -> None:
        self.db.ensure_schema()

        with sqlite3.connect(self.db_path) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute(
                """
                INSERT INTO ed_systems(
                    system_address,name,coords_x,coords_y,coords_z,
                    last_refreshed_at,expires_at,primary_source
                )
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    263303726260,
                    "Merope",
                    -78.59375,
                    -149.625,
                    -340.53125,
                    "2026-02-28T12:00:00Z",
                    "2026-02-29T12:00:00Z",
                    "spansh",
                ),
            )
            con.execute(
                """
                INSERT INTO ed_bodies(
                    system_address,name,body_type,last_refreshed_at,expires_at,source
                )
                VALUES(?,?,?,?,?,?)
                """,
                (
                    263303726260,
                    "Merope 1",
                    "planet",
                    "2026-02-28T12:00:00Z",
                    "2026-02-29T12:00:00Z",
                    "spansh",
                ),
            )
            con.execute(
                """
                INSERT INTO ed_stations(
                    system_address,name,station_type,last_refreshed_at,expires_at,source
                )
                VALUES(?,?,?,?,?,?)
                """,
                (
                    263303726260,
                    "Merope Station",
                    "coriolis",
                    "2026-02-28T12:00:00Z",
                    "2026-02-29T12:00:00Z",
                    "spansh",
                ),
            )
            con.commit()

            system_row = con.execute(
                "SELECT name, primary_source FROM ed_systems WHERE system_address=?",
                (263303726260,),
            ).fetchone()
            self.assertIsNotNone(system_row)
            self.assertEqual(system_row[0], "Merope")
            self.assertEqual(system_row[1], "spansh")

            body_row = con.execute(
                "SELECT name, source FROM ed_bodies WHERE system_address=?",
                (263303726260,),
            ).fetchone()
            self.assertIsNotNone(body_row)
            self.assertEqual(body_row[0], "Merope 1")

            station_row = con.execute(
                "SELECT name, source FROM ed_stations WHERE system_address=?",
                (263303726260,),
            ).fetchone()
            self.assertIsNotNone(station_row)
            self.assertEqual(station_row[0], "Merope Station")


if __name__ == "__main__":
    unittest.main()
