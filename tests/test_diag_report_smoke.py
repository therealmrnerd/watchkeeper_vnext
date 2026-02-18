import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from db_service import BrainstemDB


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class DiagReportSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_diag_report_"))
        self.db_path = self.temp_dir / "diag.db"
        self.schema_path = ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql"
        db = BrainstemDB(self.db_path, self.schema_path)
        db.ensure_schema()
        db.append_event(
            event_id=str(uuid.uuid4()),
            timestamp_utc=_utc_now_iso(),
            event_type="DIAG_TEST",
            source="test",
            payload={"ok": True},
            severity="info",
            tags=["diag"],
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_diag_report_tool_runs(self) -> None:
        cmd = [
            sys.executable,
            str(ROOT_DIR / "tools" / "diag_report.py"),
            "--db-path",
            str(self.db_path),
            "--policy-path",
            str(ROOT_DIR / "config" / "standing_orders.json"),
            "--events-limit",
            "5",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT_DIR, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout.strip())
        self.assertTrue(payload.get("ok"), payload)
        self.assertIn("schema_versions", payload)
        self.assertIn("config", payload)
        self.assertIn("events", payload)
        self.assertGreaterEqual(len(payload["events"]), 1)


if __name__ == "__main__":
    unittest.main()
