import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import shutil


ROOT_DIR = Path(__file__).resolve().parents[1]
AI_DIR = ROOT_DIR / "services" / "ai"
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from vector_store import SQLiteVectorStore


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class VectorCapacityLimitsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_vector_limits_"))
        self.db_path = self.temp_dir / "vector_limits.db"
        schema_sql = (ROOT_DIR / "schemas" / "sqlite" / "002_ai_knowledge.sql").read_text(
            encoding="utf-8"
        )
        with sqlite3.connect(self.db_path) as con:
            con.executescript(schema_sql)
            con.commit()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _connect_db(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10.0)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _parse_json(raw, fallback):
        if raw is None:
            return fallback
        try:
            return json.loads(raw)
        except Exception:
            return fallback

    def test_capacity_guardrails_trip_and_candidate_limit_applies(self) -> None:
        store = SQLiteVectorStore(
            connect_db=self._connect_db,
            parse_json=self._parse_json,
            candidate_limit=2,
            prefilter_threshold=3,
            require_prefilter=True,
        )
        now = _utc_now_iso()
        docs = []
        for idx in range(5):
            docs.append(
                {
                    "doc_id": f"doc-{idx + 1}",
                    "domain": "lore" if idx < 3 else "guide",
                    "title": f"Doc {idx + 1}",
                    "text_content": f"text {idx + 1}",
                    "source_id": "seed-a" if idx % 2 == 0 else "seed-b",
                    "metadata": {"idx": idx + 1},
                    "embedding_model": "test-v1",
                    "vector": [1.0, 0.0, 0.0, 0.0] if idx % 2 == 0 else [0.0, 1.0, 0.0, 0.0],
                    "created_at_utc": now,
                    "updated_at_utc": now,
                }
            )
        upsert = store.upsert(docs)
        self.assertEqual(upsert["upserted"], 5)

        with self.assertRaises(ValueError):
            store.query(
                query_vector=[1.0, 0.0, 0.0, 0.0],
                domain="",
                source_id="",
                top_k=5,
                min_score=-1.0,
                include_text=False,
                include_embedding=False,
            )

        filtered = store.query(
            query_vector=[1.0, 0.0, 0.0, 0.0],
            domain="lore",
            source_id="",
            top_k=5,
            min_score=-1.0,
            include_text=False,
            include_embedding=False,
        )
        self.assertLessEqual(filtered["candidates_scanned"], 2)
        self.assertLessEqual(filtered["count"], 2)


if __name__ == "__main__":
    unittest.main()
