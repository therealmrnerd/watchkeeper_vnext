import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable


class VectorStore:
    name = "base"

    def ensure(self) -> None:
        return

    def upsert(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        raise NotImplementedError

    def query(
        self,
        *,
        query_vector: list[float],
        domain: str,
        source_id: str,
        top_k: int,
        min_score: float,
        include_text: bool,
        include_embedding: bool,
    ) -> dict[str, Any]:
        raise NotImplementedError


class SQLiteVectorStore(VectorStore):
    name = "sqlite"

    def __init__(
        self,
        connect_db: Callable[[], sqlite3.Connection],
        parse_json: Callable[[Any, Any], Any],
    ) -> None:
        self._connect_db = connect_db
        self._parse_json = parse_json

    @staticmethod
    def _dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    def upsert(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        upserted = 0
        with self._connect_db() as con:
            for item in docs:
                con.execute(
                    """
                    INSERT INTO vector_documents(
                        doc_id,domain,title,text_content,source_id,metadata_json,embedding_json,embedding_model,dimension,created_at_utc,updated_at_utc
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(doc_id) DO UPDATE SET
                        domain=excluded.domain,
                        title=excluded.title,
                        text_content=excluded.text_content,
                        source_id=excluded.source_id,
                        metadata_json=excluded.metadata_json,
                        embedding_json=excluded.embedding_json,
                        embedding_model=excluded.embedding_model,
                        dimension=excluded.dimension,
                        updated_at_utc=excluded.updated_at_utc
                    """,
                    (
                        item["doc_id"],
                        item["domain"],
                        item["title"],
                        item["text_content"],
                        item["source_id"],
                        json.dumps(item["metadata"], ensure_ascii=False),
                        json.dumps(item["vector"], ensure_ascii=False),
                        item["embedding_model"],
                        len(item["vector"]),
                        item["created_at_utc"],
                        item["updated_at_utc"],
                    ),
                )
                upserted += 1
            con.commit()
        return {"upserted": upserted, "backend": self.name}

    def query(
        self,
        *,
        query_vector: list[float],
        domain: str,
        source_id: str,
        top_k: int,
        min_score: float,
        include_text: bool,
        include_embedding: bool,
    ) -> dict[str, Any]:
        q_dim = len(query_vector)
        clauses = []
        args: list[Any] = []
        if domain:
            clauses.append("domain = ?")
            args.append(domain)
        if source_id:
            clauses.append("source_id = ?")
            args.append(source_id)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        sql = (
            "SELECT doc_id,domain,title,text_content,source_id,metadata_json,embedding_json,embedding_model,dimension,updated_at_utc "
            f"FROM vector_documents {where} ORDER BY updated_at_utc DESC LIMIT 5000"
        )

        with self._connect_db() as con:
            rows = con.execute(sql, args).fetchall()

        scored: list[dict[str, Any]] = []
        for row in rows:
            if row["dimension"] != q_dim:
                continue
            emb = self._parse_json(row["embedding_json"], [])
            if not isinstance(emb, list) or not emb:
                continue
            try:
                emb_vec = [float(v) for v in emb]
            except Exception:
                continue
            score = self._dot(query_vector, emb_vec)
            if score < min_score:
                continue
            result = {
                "doc_id": row["doc_id"],
                "score": score,
                "domain": row["domain"],
                "title": row["title"],
                "source_id": row["source_id"],
                "metadata": self._parse_json(row["metadata_json"], {}),
                "embedding_model": row["embedding_model"],
                "updated_at_utc": row["updated_at_utc"],
            }
            if include_text:
                result["text_content"] = row["text_content"]
            if include_embedding:
                result["embedding"] = emb_vec
            scored.append(result)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return {"count": min(len(scored), top_k), "items": scored[:top_k], "backend": self.name}


class QdrantVectorStore(VectorStore):
    name = "qdrant"

    def __init__(
        self,
        *,
        qdrant_url: str,
        collection: str,
        api_key: str,
        embed_dim: int,
    ) -> None:
        self._qdrant_url = qdrant_url.rstrip("/")
        self._collection = collection
        self._api_key = api_key
        self._embed_dim = embed_dim

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._qdrant_url}{path}"
        data = None
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["api-key"] = self._api_key
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Qdrant HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Qdrant connection failed: {exc}") from exc

    def ensure(self) -> None:
        collection_escaped = urllib.parse.quote(self._collection, safe="")
        try:
            self._request("GET", f"/collections/{collection_escaped}")
            return
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
        self._request(
            "PUT",
            f"/collections/{collection_escaped}",
            {
                "vectors": {
                    "size": self._embed_dim,
                    "distance": "Cosine",
                }
            },
        )

    def upsert(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        points: list[dict[str, Any]] = []
        for item in docs:
            payload = {
                "domain": item["domain"],
                "title": item["title"],
                "text_content": item["text_content"],
                "source_id": item["source_id"],
                "metadata": item["metadata"],
                "embedding_model": item["embedding_model"],
                "updated_at_utc": item["updated_at_utc"],
            }
            points.append(
                {
                    "id": item["doc_id"],
                    "vector": item["vector"],
                    "payload": payload,
                }
            )

        collection_escaped = urllib.parse.quote(self._collection, safe="")
        self._request(
            "PUT",
            f"/collections/{collection_escaped}/points?wait=true",
            {"points": points},
        )
        return {"upserted": len(points), "backend": self.name}

    def query(
        self,
        *,
        query_vector: list[float],
        domain: str,
        source_id: str,
        top_k: int,
        min_score: float,
        include_text: bool,
        include_embedding: bool,
    ) -> dict[str, Any]:
        must = []
        if domain:
            must.append({"key": "domain", "match": {"value": domain}})
        if source_id:
            must.append({"key": "source_id", "match": {"value": source_id}})

        payload: dict[str, Any] = {
            "vector": query_vector,
            "limit": top_k,
            "with_payload": True,
            "with_vector": include_embedding,
        }
        if min_score > -1.0:
            payload["score_threshold"] = min_score
        if must:
            payload["filter"] = {"must": must}

        collection_escaped = urllib.parse.quote(self._collection, safe="")
        result = self._request(
            "POST",
            f"/collections/{collection_escaped}/points/search",
            payload,
        )
        rows = result.get("result", []) or []
        items = []
        for row in rows:
            row_payload = row.get("payload", {}) or {}
            item = {
                "doc_id": str(row.get("id")),
                "score": float(row.get("score", 0.0)),
                "domain": row_payload.get("domain"),
                "title": row_payload.get("title"),
                "source_id": row_payload.get("source_id"),
                "metadata": row_payload.get("metadata", {}),
                "embedding_model": row_payload.get("embedding_model", "qdrant"),
                "updated_at_utc": row_payload.get("updated_at_utc"),
            }
            if include_text:
                item["text_content"] = row_payload.get("text_content", "")
            if include_embedding:
                item["embedding"] = row.get("vector", [])
            items.append(item)
        return {"count": len(items), "items": items, "backend": self.name}
