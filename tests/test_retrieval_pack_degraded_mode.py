import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ADVISORY_DIR = ROOT_DIR / "services" / "advisory"
if str(ADVISORY_DIR) not in sys.path:
    sys.path.insert(0, str(ADVISORY_DIR))

from retrieval import RetrievalPackBuilder


class BrokenVectorBuilder(RetrievalPackBuilder):
    def _fetch_vector_chunks(self, con, *, user_text, domain, retrieval_domains):
        raise RuntimeError("vector backend unavailable")


class RetrievalPackDegradedModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_retrieval_degraded_"))
        self.db_path = self.temp_dir / "retrieval_degraded.db"
        self._create_schema()
        self._seed_data()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_schema(self) -> None:
        schema_files = [
            ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql",
            ROOT_DIR / "schemas" / "sqlite" / "002_ai_knowledge.sql",
        ]
        with sqlite3.connect(self.db_path) as con:
            for schema_file in schema_files:
                con.executescript(schema_file.read_text(encoding="utf-8"))
            con.commit()

    def _seed_data(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                INSERT INTO state_current(state_key,state_value_json,source,confidence,observed_at_utc,updated_at_utc)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    "policy.watch_condition",
                    '"GAME"',
                    "test",
                    1.0,
                    "2026-02-19T12:00:00Z",
                    "2026-02-19T12:00:00Z",
                ),
            )
            con.execute(
                """
                INSERT INTO facts_triples(
                    triple_id,subject,predicate,object,source,confidence,metadata_json,created_at_utc,updated_at_utc
                )
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    "tr-001",
                    "guardian",
                    "technology",
                    "ancient synthetic structures",
                    "lore_feed",
                    0.92,
                    "{}",
                    "2026-02-19T12:00:00Z",
                    "2026-02-19T12:00:00Z",
                ),
            )
            con.commit()

    def test_pack_builds_when_vector_retrieval_fails(self) -> None:
        builder = BrokenVectorBuilder(
            db_path=self.db_path,
            max_chunks=3,
            max_facts=3,
            max_chars=1200,
            max_tokens_approx=250,
        )
        pack = builder.build(
            request_id="req-degraded-001",
            user_text="guardian technology",
            mode="game",
            domain="lore",
            retrieval_domains=["lore"],
        )

        self.assertTrue(pack["metadata"]["degraded"])
        self.assertEqual(pack["metadata"]["vector_status"], "degraded")
        self.assertGreaterEqual(len(pack["facts"]), 1)
        self.assertIn("policy.watch_condition", pack["sitrep"]["state"])
        self.assertIsInstance(pack["citations"], list)


if __name__ == "__main__":
    unittest.main()

