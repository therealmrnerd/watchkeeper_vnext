import shutil
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
ADAPTER_DIR = ROOT_DIR / "services" / "adapters"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))
if str(ADAPTER_DIR) not in sys.path:
    sys.path.insert(0, str(ADAPTER_DIR))

from db_service import BrainstemDB
from state_collector import _build_changed_items


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _prepare_batch_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        out.append(
            {
                "state_key": item["state_key"],
                "state_value": item["state_value"],
                "source": item["source"],
                "confidence": item.get("confidence"),
                "observed_at_utc": item["observed_at_utc"],
                "updated_at_utc": item["observed_at_utc"],
                "event_id": str(uuid.uuid4()),
                "event_type": "STATE_UPDATED",
                "event_source": "test_batch",
                "event_payload": {"state_key": item["state_key"]},
            }
        )
    return out


class BatchSetStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_batch_state_"))
        self.schema_path = ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_batch_write_on_change_updates_state_and_reduces_events(self) -> None:
        optimized_db_path = self.temp_dir / "optimized.db"
        naive_db_path = self.temp_dir / "naive.db"
        optimized = BrainstemDB(optimized_db_path, self.schema_path)
        naive = BrainstemDB(naive_db_path, self.schema_path)
        optimized.ensure_schema()
        naive.ensure_schema()

        baseline = {
            "ed.running": False,
            "music.playing": False,
            "hw.cpu.logical_cores": 8,
        }
        second_poll = {
            "ed.running": True,  # changed
            "music.playing": False,
            "hw.cpu.logical_cores": 8,
        }

        last_hashes: dict[str, str] = {}
        first_items = _build_changed_items(baseline, last_hashes, "collector")
        optimized.batch_set_state(items=_prepare_batch_items(first_items), emit_events=True)

        changed_only_items = _build_changed_items(second_poll, last_hashes, "collector")
        optimized.batch_set_state(items=_prepare_batch_items(changed_only_items), emit_events=True)

        # Naive path writes each key independently each poll, without write-on-change filtering.
        for key, value in baseline.items():
            naive.set_state(
                state_key=key,
                state_value=value,
                source="collector_naive",
                observed_at_utc=_utc_now_iso(),
                emit_event=True,
                event_meta={
                    "event_id": str(uuid.uuid4()),
                    "event_type": "STATE_UPDATED",
                    "event_source": "test_batch",
                },
            )
        naive_second_poll = {
            "ed.running": True,
            "music.playing": True,
            "hw.cpu.logical_cores": 16,
        }
        for key, value in naive_second_poll.items():
            naive.set_state(
                state_key=key,
                state_value=value,
                source="collector_naive",
                observed_at_utc=_utc_now_iso(),
                emit_event=True,
                event_meta={
                    "event_id": str(uuid.uuid4()),
                    "event_type": "STATE_UPDATED",
                    "event_source": "test_batch",
                },
            )

        with sqlite3.connect(optimized_db_path) as con:
            optimized_events = con.execute(
                "SELECT COUNT(*) FROM event_log WHERE event_type='STATE_UPDATED'"
            ).fetchone()[0]
            state_row = con.execute(
                "SELECT state_value_json FROM state_current WHERE state_key='ed.running'"
            ).fetchone()
        self.assertIsNotNone(state_row)
        self.assertIn("true", str(state_row[0]).lower())

        with sqlite3.connect(naive_db_path) as con:
            naive_events = con.execute(
                "SELECT COUNT(*) FROM event_log WHERE event_type='STATE_UPDATED'"
            ).fetchone()[0]

        self.assertGreater(naive_events, optimized_events)


if __name__ == "__main__":
    unittest.main()
