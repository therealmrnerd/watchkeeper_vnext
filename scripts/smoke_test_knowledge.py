import importlib.util
import os
from pathlib import Path


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("knowledge_service", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    db_path = root / "data" / "knowledge_smoke_test.db"
    os.environ["WKV_AI_DB_PATH"] = str(db_path)

    mod = load_module(root / "services" / "ai" / "knowledge_service.py")
    mod.ensure_db()

    facts_payload = {
        "triples": [
            {
                "subject": "Sol",
                "predicate": "has_star_type",
                "object": "G2V",
                "source": "smoke_test",
                "confidence": 0.99,
            },
            {
                "subject": "Achenar",
                "predicate": "is_capital_of",
                "object": "Empire",
                "source": "smoke_test",
                "confidence": 0.98,
            },
        ]
    }
    mod.validate_facts_upsert(facts_payload)
    facts_upsert_result = mod.upsert_facts(facts_payload)

    vector_payload = {
        "docs": [
            {
                "doc_id": "doc-lore-thargoid",
                "domain": "lore",
                "title": "Thargoid War Summary",
                "text_content": "Thargoid conflict expanded from Pleiades into human core systems.",
                "source_id": "smoke_test",
            },
            {
                "doc_id": "doc-gameplay-mining",
                "domain": "gameplay",
                "title": "Mining Notes",
                "text_content": "Laser mining rewards improve with good hotspots and refinery management.",
                "source_id": "smoke_test",
            },
        ]
    }
    mod.validate_vector_upsert(vector_payload)
    vector_upsert_result = mod.upsert_vectors(vector_payload)

    facts_query_payload = {"subject": "Sol", "limit": 5}
    mod.validate_facts_query(facts_query_payload)
    facts_query_result = mod.query_facts(facts_query_payload)

    vector_query_payload = {"query_text": "Where are Thargoid attacks?", "domain": "lore", "top_k": 3}
    mod.validate_vector_query(vector_query_payload)
    vector_query_result = mod.query_vectors(vector_query_payload)

    print("FACTS_UPSERTED", facts_upsert_result["upserted"])
    print("VECTOR_UPSERTED", vector_upsert_result["upserted"])
    print("FACTS_FOUND", facts_query_result["count"])
    print("VECTOR_FOUND", vector_query_result["count"])
    top = vector_query_result["items"][0] if vector_query_result["items"] else {}
    print("VECTOR_TOP_DOC", top.get("doc_id", "NONE"))


if __name__ == "__main__":
    main()
