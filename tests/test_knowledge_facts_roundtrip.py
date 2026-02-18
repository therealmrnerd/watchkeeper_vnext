import importlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
AI_DIR = ROOT_DIR / "services" / "ai"
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))


class KnowledgeFactsRoundtripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_knowledge_facts_"))
        self.db_path = self.temp_dir / "knowledge.db"
        os.environ["WKV_AI_DB_PATH"] = str(self.db_path)
        os.environ["WKV_SCHEMA_DIR"] = str(ROOT_DIR / "schemas" / "sqlite")
        os.environ["WKV_VECTOR_BACKEND"] = "sqlite"
        os.environ["WKV_EMBED_DIM"] = "64"
        for name in ("knowledge_service", "vector_store"):
            sys.modules.pop(name, None)
        self.ks = importlib.import_module("knowledge_service")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_facts_roundtrip_and_schema_init(self) -> None:
        self.ks.ensure_db()

        with sqlite3.connect(self.db_path) as con:
            tables = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('facts_triples','vector_documents')"
                ).fetchall()
            }
        self.assertEqual(tables, {"facts_triples", "vector_documents"})

        upsert = self.ks.upsert_facts(
            {
                "triples": [
                    {
                        "subject": "Jameson Memorial",
                        "predicate": "located_in",
                        "object": "Shinrarta Dezhra",
                        "source": "test",
                        "confidence": 0.98,
                        "metadata": {"category": "station"},
                    }
                ]
            }
        )
        self.assertEqual(upsert["upserted"], 1)

        queried = self.ks.query_facts({"subject": "Jameson Memorial", "limit": 5})
        self.assertEqual(queried["count"], 1)
        row = queried["items"][0]
        self.assertEqual(row["predicate"], "located_in")
        self.assertEqual(row["object"], "Shinrarta Dezhra")


if __name__ == "__main__":
    unittest.main()
