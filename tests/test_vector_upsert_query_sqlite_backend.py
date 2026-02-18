import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
AI_DIR = ROOT_DIR / "services" / "ai"
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))


class VectorSQLiteRoundtripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_vector_sqlite_"))
        self.db_path = self.temp_dir / "vector.db"
        os.environ["WKV_AI_DB_PATH"] = str(self.db_path)
        os.environ["WKV_SCHEMA_DIR"] = str(ROOT_DIR / "schemas" / "sqlite")
        os.environ["WKV_VECTOR_BACKEND"] = "sqlite"
        os.environ["WKV_EMBED_DIM"] = "64"
        for name in ("knowledge_service", "vector_store"):
            sys.modules.pop(name, None)
        self.ks = importlib.import_module("knowledge_service")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_vector_upsert_and_query_sqlite_backend(self) -> None:
        self.ks.ensure_db()

        upsert = self.ks.upsert_vectors(
            {
                "docs": [
                    {
                        "doc_id": "doc-ed-1",
                        "domain": "lore",
                        "title": "Galnet",
                        "text_content": "Thargoid activity increased near HIP 22460.",
                        "source_id": "seed",
                        "metadata": {"era": "war"},
                    },
                    {
                        "doc_id": "doc-ed-2",
                        "domain": "lore",
                        "title": "Pilots Federation",
                        "text_content": "Frame Shift Drive tips and route planning.",
                        "source_id": "seed",
                        "metadata": {"era": "guide"},
                    },
                ]
            }
        )
        self.assertEqual(upsert["backend"], "sqlite")
        self.assertEqual(upsert["upserted"], 2)

        result = self.ks.query_vectors(
            {
                "query_text": "Thargoid war updates",
                "domain": "lore",
                "top_k": 2,
                "min_score": -1.0,
                "include_text": True,
                "include_embedding": False,
            }
        )
        self.assertEqual(result["backend"], "sqlite")
        self.assertGreaterEqual(result["count"], 1)
        doc_ids = [row["doc_id"] for row in result["items"]]
        self.assertIn("doc-ed-1", doc_ids)


if __name__ == "__main__":
    unittest.main()
