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


class RetrievalPackLimitsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_retrieval_limits_"))
        self.db_path = self.temp_dir / "retrieval_limits.db"
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
        giant_text = ("thargoid battle frame shift drive lore " * 250).strip()
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                INSERT INTO state_current(state_key,state_value_json,source,confidence,observed_at_utc,updated_at_utc)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    "ed.status.running",
                    "true",
                    "test",
                    1.0,
                    "2026-02-19T12:00:00Z",
                    "2026-02-19T12:00:00Z",
                ),
            )
            con.execute(
                """
                INSERT INTO state_current(state_key,state_value_json,source,confidence,observed_at_utc,updated_at_utc)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    "music.now_playing.title",
                    '"Very Long Test Song"',
                    "test",
                    1.0,
                    "2026-02-19T12:00:00Z",
                    "2026-02-19T12:00:00Z",
                ),
            )
            for i in range(12):
                con.execute(
                    """
                    INSERT INTO vector_documents(
                        doc_id,domain,title,text_content,source_id,metadata_json,embedding_json,embedding_model,dimension,created_at_utc,updated_at_utc
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        f"doc-{i:02d}",
                        "lore" if i % 2 == 0 else "gameplay",
                        f"Doc {i}",
                        giant_text,
                        f"source-{i}",
                        "{}",
                        "[0.0,1.0]",
                        "hash-v1",
                        2,
                        "2026-02-19T12:00:00Z",
                        f"2026-02-19T12:{i:02d}:00Z",
                    ),
                )
            for i in range(20):
                con.execute(
                    """
                    INSERT INTO facts_triples(
                        triple_id,subject,predicate,object,source,confidence,metadata_json,created_at_utc,updated_at_utc
                    )
                    VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        f"tr-{i:02d}",
                        "thargoid",
                        "threat_level",
                        f"high-threat-{i}-" + ("x" * 300),
                        "lore_feed",
                        0.95,
                        "{}",
                        "2026-02-19T12:00:00Z",
                        f"2026-02-19T12:{i:02d}:30Z",
                    ),
                )
            con.commit()

    def test_retrieval_pack_never_exceeds_limits(self) -> None:
        builder = RetrievalPackBuilder(
            db_path=self.db_path,
            max_chunks=3,
            max_facts=4,
            max_chars=900,
            max_tokens_approx=180,
            max_chunk_chars=180,
            max_fact_chars=80,
            max_state_chars=180,
        )
        pack = builder.build(
            request_id="req-pack-limits",
            user_text="thargoid battle frame shift drive",
            mode="game",
            domain="lore",
            retrieval_domains=["lore"],
        )

        self.assertLessEqual(len(pack["chunks"]), 3)
        self.assertLessEqual(len(pack["facts"]), 4)
        self.assertLessEqual(pack["metadata"]["total_chars"], 720)
        self.assertLessEqual(pack["metadata"]["approx_tokens"], 180)
        for chunk in pack["chunks"]:
            self.assertLessEqual(len(chunk["text"]), 180)
        for fact in pack["facts"]:
            self.assertLessEqual(len(fact["object"]), 80)

    def test_retrieval_pack_is_deterministic_for_same_input(self) -> None:
        builder = RetrievalPackBuilder(
            db_path=self.db_path,
            max_chunks=2,
            max_facts=2,
            max_chars=800,
            max_tokens_approx=200,
            max_chunk_chars=160,
            max_fact_chars=70,
            max_state_chars=200,
        )
        pack_a = builder.build(
            request_id="req-pack-a",
            user_text="thargoid battle",
            mode="game",
            domain="lore",
            retrieval_domains=["lore"],
        )
        pack_b = builder.build(
            request_id="req-pack-b",
            user_text="thargoid battle",
            mode="game",
            domain="lore",
            retrieval_domains=["lore"],
        )

        self.assertEqual(
            [c["doc_id"] for c in pack_a["chunks"]],
            [c["doc_id"] for c in pack_b["chunks"]],
        )
        self.assertEqual(
            [f["triple_id"] for f in pack_a["facts"]],
            [f["triple_id"] for f in pack_b["facts"]],
        )
        self.assertEqual(pack_a["metadata"]["context_hash"], pack_b["metadata"]["context_hash"])


if __name__ == "__main__":
    unittest.main()

