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
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db.logbook import Logbook
from db_service import BrainstemDB


class LogbookWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_logbook_"))
        self.db_path = self.temp_dir / "logbook_test.db"
        self.schema_path = ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql"
        self.db = BrainstemDB(self.db_path, self.schema_path)
        self.db.ensure_schema()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_log_decision_writes_policy_event(self) -> None:
        logbook = Logbook(db_service=self.db, source="test_policy")
        logbook.log_decision(
            incident_id="inc-001",
            tool_name="input.keypress",
            decision={
                "allowed": False,
                "requires_confirmation": True,
                "deny_reason_code": "DENY_NEEDS_CONFIRMATION",
            },
            req_context={"mode": "game", "session_id": "session-1"},
        )

        with sqlite3.connect(self.db_path) as con:
            row = con.execute(
                """
                SELECT event_type, source, payload_json
                FROM event_log
                WHERE event_type='POLICY_DECISION'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "POLICY_DECISION")
        self.assertEqual(row[1], "test_policy")

        payload = json.loads(row[2])
        self.assertEqual(payload["payload"]["incident_id"], "inc-001")
        self.assertEqual(payload["payload"]["tool_name"], "input.keypress")


if __name__ == "__main__":
    unittest.main()
