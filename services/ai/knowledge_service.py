import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
from qdrant_runtime import QdrantRuntimeManager, env_bool
from vector_store import QdrantVectorStore, SQLiteVectorStore, VectorStore


ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("WKV_AI_DB_PATH", ROOT_DIR / "data" / "watchkeeper_vnext.db"))
SCHEMA_DIR = Path(os.getenv("WKV_SCHEMA_DIR", ROOT_DIR / "schemas" / "sqlite"))
HOST = os.getenv("WKV_AI_HOST", "127.0.0.1")
PORT = int(os.getenv("WKV_AI_PORT", "8790"))
EMBED_DIM = int(os.getenv("WKV_EMBED_DIM", "256"))
VECTOR_BACKEND = os.getenv("WKV_VECTOR_BACKEND", "sqlite").strip().lower()
SQLITE_VECTOR_CANDIDATE_LIMIT = int(os.getenv("WKV_SQLITE_VECTOR_CANDIDATE_LIMIT", "5000"))
SQLITE_VECTOR_PREFILTER_THRESHOLD = int(os.getenv("WKV_SQLITE_VECTOR_PREFILTER_THRESHOLD", "50000"))
SQLITE_VECTOR_REQUIRE_PREFILTER = env_bool("WKV_SQLITE_VECTOR_REQUIRE_PREFILTER", "1")
QDRANT_URL = os.getenv("WKV_QDRANT_URL", "http://127.0.0.1:6333").strip()
QDRANT_COLLECTION = os.getenv("WKV_QDRANT_COLLECTION", "watchkeeper_docs").strip()
QDRANT_API_KEY = os.getenv("WKV_QDRANT_API_KEY", "").strip()
QDRANT_AUTOSTART = env_bool("WKV_QDRANT_AUTOSTART", "1")
QDRANT_AUTOSTOP = env_bool("WKV_QDRANT_AUTOSTOP", "1")

FACT_ALLOWED_KEYS = {
    "triple_id",
    "subject",
    "predicate",
    "object",
    "source",
    "as_of_date",
    "confidence",
    "metadata",
}

FACT_UPSERT_ALLOWED_KEYS = {"triples"}
FACT_QUERY_ALLOWED_KEYS = {"subject", "predicate", "object", "source", "q", "limit"}

DOC_ALLOWED_KEYS = {
    "doc_id",
    "domain",
    "title",
    "text_content",
    "source_id",
    "metadata",
    "embedding",
    "embedding_model",
}

VECTOR_UPSERT_ALLOWED_KEYS = {"docs"}
VECTOR_QUERY_ALLOWED_KEYS = {
    "query_text",
    "query_vector",
    "domain",
    "source_id",
    "top_k",
    "min_score",
    "include_text",
    "include_embedding",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def connect_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def ensure_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    sql_files = sorted(SCHEMA_DIR.glob("*.sql"))
    if not sql_files:
        raise RuntimeError(f"No SQL schema files found in {SCHEMA_DIR}")

    with connect_db() as con:
        con.execute("PRAGMA journal_mode=WAL;")
        for sql_file in sql_files:
            schema_sql = sql_file.read_text(encoding="utf-8")
            con.executescript(schema_sql)
        con.commit()


def parse_json(raw: Any, fallback: Any) -> Any:
    if raw is None:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


_VECTOR_STORE: VectorStore | None = None
_QDRANT_RUNTIME: QdrantRuntimeManager | None = None


def get_qdrant_runtime() -> QdrantRuntimeManager:
    global _QDRANT_RUNTIME
    if _QDRANT_RUNTIME is None:
        _QDRANT_RUNTIME = QdrantRuntimeManager(qdrant_url=QDRANT_URL)
    return _QDRANT_RUNTIME


def autostart_qdrant_if_needed() -> dict[str, Any] | None:
    if VECTOR_BACKEND != "qdrant":
        return None
    if not QDRANT_AUTOSTART:
        return get_qdrant_runtime().status() | {"ok": True, "autostart": False}
    return get_qdrant_runtime().ensure_started()


def autostop_qdrant_if_needed() -> dict[str, Any] | None:
    if VECTOR_BACKEND != "qdrant":
        return None
    if not QDRANT_AUTOSTOP:
        return get_qdrant_runtime().status() | {"ok": True, "autostop": False}
    return get_qdrant_runtime().stop(force=True, managed_only=True)


def get_vector_store() -> VectorStore:
    global _VECTOR_STORE
    if _VECTOR_STORE is not None:
        return _VECTOR_STORE

    if VECTOR_BACKEND == "sqlite":
        _VECTOR_STORE = SQLiteVectorStore(
            connect_db=connect_db,
            parse_json=parse_json,
            candidate_limit=SQLITE_VECTOR_CANDIDATE_LIMIT,
            prefilter_threshold=SQLITE_VECTOR_PREFILTER_THRESHOLD,
            require_prefilter=SQLITE_VECTOR_REQUIRE_PREFILTER,
        )
        return _VECTOR_STORE
    if VECTOR_BACKEND == "qdrant":
        _VECTOR_STORE = QdrantVectorStore(
            qdrant_url=QDRANT_URL,
            collection=QDRANT_COLLECTION,
            api_key=QDRANT_API_KEY,
            embed_dim=EMBED_DIM,
        )
        return _VECTOR_STORE

    raise RuntimeError("Unsupported WKV_VECTOR_BACKEND. Use 'sqlite' or 'qdrant'.")


def _check_extra_keys(obj: dict[str, Any], allowed: set[str], obj_name: str) -> None:
    extra = sorted(set(obj.keys()) - allowed)
    if extra:
        raise ValueError(f"{obj_name} contains unsupported fields: {', '.join(extra)}")


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _normalize_vector(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    if norm <= 0:
        return values
    return [v / norm for v in values]


def hash_embed(text: str, dim: int = EMBED_DIM) -> list[float]:
    if dim < 16 or dim > 4096:
        raise ValueError("WKV_EMBED_DIM must be between 16 and 4096")
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vec

    for token in tokens:
        h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(h, byteorder="little", signed=False)
        idx = value % dim
        sign = -1.0 if ((value >> 1) & 1) else 1.0
        vec[idx] += sign
    return _normalize_vector(vec)


def _coerce_vector(raw: Any, field_name: str) -> list[float]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{field_name} must be a non-empty array of numbers")
    vector: list[float] = []
    for idx, value in enumerate(raw):
        if not isinstance(value, (int, float)):
            raise ValueError(f"{field_name}[{idx}] must be numeric")
        vector.append(float(value))
    return _normalize_vector(vector)


def _ensure_embed_dim(vector: list[float], field_name: str) -> None:
    if len(vector) != EMBED_DIM:
        raise ValueError(f"{field_name} dimension must be {EMBED_DIM}, got {len(vector)}")


def validate_fact_item(item: dict[str, Any], index: int) -> None:
    if not isinstance(item, dict):
        raise ValueError(f"triples[{index}] must be an object")
    _check_extra_keys(item, FACT_ALLOWED_KEYS, f"triples[{index}]")

    for key in ("subject", "predicate", "object"):
        if key not in item:
            raise ValueError(f"triples[{index}] missing required field: {key}")
        if not isinstance(item[key], str) or not item[key].strip():
            raise ValueError(f"triples[{index}].{key} must be a non-empty string")

    confidence = item.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
            raise ValueError(f"triples[{index}].confidence must be number 0..1")

    metadata = item.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError(f"triples[{index}].metadata must be an object when supplied")


def validate_facts_upsert(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    _check_extra_keys(payload, FACT_UPSERT_ALLOWED_KEYS, "facts_upsert")

    triples = payload.get("triples")
    if not isinstance(triples, list) or not triples:
        raise ValueError("triples is required and must be a non-empty array")
    if len(triples) > 1000:
        raise ValueError("triples may contain at most 1000 items")
    for idx, item in enumerate(triples):
        validate_fact_item(item, idx)


def validate_facts_query(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    _check_extra_keys(payload, FACT_QUERY_ALLOWED_KEYS, "facts_query")

    limit = payload.get("limit", 20)
    if not isinstance(limit, int) or limit < 1 or limit > 200:
        raise ValueError("limit must be integer 1..200")


def validate_doc_item(item: dict[str, Any], index: int) -> None:
    if not isinstance(item, dict):
        raise ValueError(f"docs[{index}] must be an object")
    _check_extra_keys(item, DOC_ALLOWED_KEYS, f"docs[{index}]")

    if "text_content" not in item:
        raise ValueError(f"docs[{index}] missing required field: text_content")
    if not isinstance(item["text_content"], str) or not item["text_content"].strip():
        raise ValueError(f"docs[{index}].text_content must be a non-empty string")

    for key in ("doc_id", "domain", "title", "source_id", "embedding_model"):
        value = item.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"docs[{index}].{key} must be a non-empty string when supplied")

    metadata = item.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError(f"docs[{index}].metadata must be an object when supplied")

    if "embedding" in item and item["embedding"] is not None:
        vector = _coerce_vector(item["embedding"], f"docs[{index}].embedding")
        _ensure_embed_dim(vector, f"docs[{index}].embedding")


def validate_vector_upsert(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    _check_extra_keys(payload, VECTOR_UPSERT_ALLOWED_KEYS, "vector_upsert")

    docs = payload.get("docs")
    if not isinstance(docs, list) or not docs:
        raise ValueError("docs is required and must be a non-empty array")
    if len(docs) > 500:
        raise ValueError("docs may contain at most 500 items")
    for idx, doc in enumerate(docs):
        validate_doc_item(doc, idx)


def validate_vector_query(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    _check_extra_keys(payload, VECTOR_QUERY_ALLOWED_KEYS, "vector_query")

    query_text = payload.get("query_text")
    query_vector = payload.get("query_vector")
    if query_text is None and query_vector is None:
        raise ValueError("query_text or query_vector is required")
    if query_text is not None and (not isinstance(query_text, str) or not query_text.strip()):
        raise ValueError("query_text must be a non-empty string")
    if query_vector is not None:
        vector = _coerce_vector(query_vector, "query_vector")
        _ensure_embed_dim(vector, "query_vector")

    top_k = payload.get("top_k", 5)
    if not isinstance(top_k, int) or top_k < 1 or top_k > 50:
        raise ValueError("top_k must be integer 1..50")

    min_score = payload.get("min_score", -1.0)
    if not isinstance(min_score, (int, float)) or min_score < -1.0 or min_score > 1.0:
        raise ValueError("min_score must be number -1.0..1.0")

    for key in ("domain", "source_id"):
        value = payload.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{key} must be a non-empty string when supplied")

    for key in ("include_text", "include_embedding"):
        value = payload.get(key)
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"{key} must be boolean when supplied")


def upsert_facts(payload: dict[str, Any]) -> dict[str, Any]:
    triples = payload["triples"]
    upserted = 0

    with connect_db() as con:
        for item in triples:
            triple_id = item.get("triple_id") or str(uuid.uuid4())
            subject = item["subject"].strip()
            predicate = item["predicate"].strip()
            obj = item["object"].strip()
            source = item.get("source")
            as_of_date = item.get("as_of_date")
            confidence = item.get("confidence")
            metadata = item.get("metadata", {})
            now = utc_now_iso()

            con.execute(
                """
                INSERT INTO facts_triples(
                    triple_id,subject,predicate,object,source,as_of_date,confidence,metadata_json,created_at_utc,updated_at_utc
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(subject,predicate,object,ifnull(source,'')) DO UPDATE SET
                    as_of_date=excluded.as_of_date,
                    confidence=excluded.confidence,
                    metadata_json=excluded.metadata_json,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (
                    triple_id,
                    subject,
                    predicate,
                    obj,
                    source,
                    as_of_date,
                    confidence,
                    json.dumps(metadata, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            upserted += 1
        con.commit()

    return {"upserted": upserted}


def query_facts(payload: dict[str, Any]) -> dict[str, Any]:
    subject = (payload.get("subject") or "").strip()
    predicate = (payload.get("predicate") or "").strip()
    obj = (payload.get("object") or "").strip()
    source = (payload.get("source") or "").strip()
    q = (payload.get("q") or "").strip().lower()
    limit = payload.get("limit", 20)

    clauses = []
    args: list[Any] = []
    if subject:
        clauses.append("subject = ?")
        args.append(subject)
    if predicate:
        clauses.append("predicate = ?")
        args.append(predicate)
    if obj:
        clauses.append("object = ?")
        args.append(obj)
    if source:
        clauses.append("source = ?")
        args.append(source)

    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)

    sql = (
        "SELECT triple_id,subject,predicate,object,source,as_of_date,confidence,metadata_json,updated_at_utc "
        f"FROM facts_triples {where} ORDER BY updated_at_utc DESC LIMIT ?"
    )
    args.append(limit)

    with connect_db() as con:
        rows = con.execute(sql, args).fetchall()

    items = []
    for row in rows:
        if q:
            blob = " ".join(
                [
                    row["subject"] or "",
                    row["predicate"] or "",
                    row["object"] or "",
                    row["source"] or "",
                    row["metadata_json"] or "",
                ]
            ).lower()
            if q not in blob:
                continue

        items.append(
            {
                "triple_id": row["triple_id"],
                "subject": row["subject"],
                "predicate": row["predicate"],
                "object": row["object"],
                "source": row["source"],
                "as_of_date": row["as_of_date"],
                "confidence": row["confidence"],
                "metadata": parse_json(row["metadata_json"], {}),
                "updated_at_utc": row["updated_at_utc"],
            }
        )
        if len(items) >= limit:
            break

    return {"count": len(items), "items": items}


def upsert_vectors(payload: dict[str, Any]) -> dict[str, Any]:
    docs = payload["docs"]
    prepared_docs: list[dict[str, Any]] = []
    now = utc_now_iso()
    for item in docs:
        doc_id = (item.get("doc_id") or str(uuid.uuid4())).strip()
        domain = item.get("domain")
        title = item.get("title")
        text_content = item["text_content"].strip()
        source_id = item.get("source_id")
        metadata = item.get("metadata", {})
        embedding_model = item.get("embedding_model") or "hash-v1"

        raw_embedding = item.get("embedding")
        if raw_embedding is None:
            vector = hash_embed(text_content, EMBED_DIM)
        else:
            vector = _coerce_vector(raw_embedding, "embedding")
        _ensure_embed_dim(vector, "embedding")

        prepared_docs.append(
            {
                "doc_id": doc_id,
                "domain": domain,
                "title": title,
                "text_content": text_content,
                "source_id": source_id,
                "metadata": metadata,
                "embedding_model": embedding_model,
                "vector": vector,
                "created_at_utc": now,
                "updated_at_utc": now,
            }
        )

    store = get_vector_store()
    return store.upsert(prepared_docs)


def query_vectors(payload: dict[str, Any]) -> dict[str, Any]:
    query_text = payload.get("query_text")
    query_vector = payload.get("query_vector")
    domain = (payload.get("domain") or "").strip()
    source_id = (payload.get("source_id") or "").strip()
    top_k = payload.get("top_k", 5)
    min_score = float(payload.get("min_score", -1.0))
    include_text = payload.get("include_text", True)
    include_embedding = payload.get("include_embedding", False)

    if query_vector is not None:
        q_vec = _coerce_vector(query_vector, "query_vector")
        _ensure_embed_dim(q_vec, "query_vector")
    else:
        q_vec = hash_embed(str(query_text), EMBED_DIM)
    store = get_vector_store()
    return store.query(
        query_vector=q_vec,
        domain=domain,
        source_id=source_id,
        top_k=top_k,
        min_score=min_score,
        include_text=include_text,
        include_embedding=include_embedding,
    )


class KnowledgeHandler(BaseHTTPRequestHandler):
    server_version = "WatchkeeperKnowledge/0.1"

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("request body is required")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                store = get_vector_store()
                qdrant_runtime = None
                if store.name == "qdrant":
                    qdrant_runtime = get_qdrant_runtime().status()
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "service": "knowledge",
                        "ts": utc_now_iso(),
                        "embed_dim": EMBED_DIM,
                        "vector_backend": store.name,
                        "qdrant_collection": QDRANT_COLLECTION if store.name == "qdrant" else None,
                        "qdrant_runtime": qdrant_runtime,
                    },
                )
                return
            if parsed.path == "/facts/query":
                payload = {k: v[0] for k, v in query.items()}
                if "limit" in payload:
                    payload["limit"] = int(payload["limit"])
                validate_facts_query(payload)
                result = query_facts(payload)
                self._send_json(200, {"ok": True, **result})
                return
            self._send_json(404, {"ok": False, "error": "not_found"})
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/facts/upsert":
                body = self._read_json_body()
                validate_facts_upsert(body)
                result = upsert_facts(body)
                self._send_json(200, {"ok": True, **result})
                return

            if parsed.path == "/facts/query":
                body = self._read_json_body()
                validate_facts_query(body)
                result = query_facts(body)
                self._send_json(200, {"ok": True, **result})
                return

            if parsed.path == "/vector/upsert":
                body = self._read_json_body()
                validate_vector_upsert(body)
                result = upsert_vectors(body)
                self._send_json(200, {"ok": True, **result})
                return

            if parsed.path == "/vector/query":
                body = self._read_json_body()
                validate_vector_query(body)
                result = query_vectors(body)
                self._send_json(200, {"ok": True, **result})
                return

            self._send_json(404, {"ok": False, "error": "not_found"})
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except sqlite3.IntegrityError as exc:
            self._send_json(409, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})


def main() -> None:
    ensure_db()
    qdrant_runtime_result = autostart_qdrant_if_needed()
    if VECTOR_BACKEND == "qdrant" and qdrant_runtime_result and not qdrant_runtime_result.get("ok", False):
        raise RuntimeError(
            f"Qdrant autostart failed: {qdrant_runtime_result.get('last_error') or qdrant_runtime_result}"
        )
    get_vector_store().ensure()
    server = ThreadingHTTPServer((HOST, PORT), KnowledgeHandler)
    print(f"Knowledge API listening on http://{HOST}:{PORT}")
    if qdrant_runtime_result is not None:
        print(
            "Qdrant runtime:",
            json.dumps(
                {
                    "autostart": QDRANT_AUTOSTART,
                    "autostop": QDRANT_AUTOSTOP,
                    "started": qdrant_runtime_result.get("started", False),
                    "already_running": qdrant_runtime_result.get("already_running", False),
                    "url": qdrant_runtime_result.get("url"),
                },
                ensure_ascii=False,
            ),
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        stop_result = autostop_qdrant_if_needed()
        if stop_result is not None:
            print(
                "Qdrant shutdown:",
                json.dumps(
                    {
                        "autostop": QDRANT_AUTOSTOP,
                        "stopped": stop_result.get("stopped"),
                        "ping_ok": stop_result.get("ping_ok"),
                        "url": stop_result.get("url"),
                    },
                    ensure_ascii=False,
                ),
            )


if __name__ == "__main__":
    main()
