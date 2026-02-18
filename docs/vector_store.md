# Vector Store Guardrails

SQLite remains the default vector backend for small and medium local corpora.

## Capacity Guardrails

Environment variables:

- `WKV_SQLITE_VECTOR_CANDIDATE_LIMIT` (default `5000`)
- `WKV_SQLITE_VECTOR_PREFILTER_THRESHOLD` (default `50000`)
- `WKV_SQLITE_VECTOR_REQUIRE_PREFILTER` (default `1`)

Behavior:

- Query scan is capped at `candidate_limit`.
- If corpus size exceeds `prefilter_threshold`, queries must include `domain` or `source_id` when `require_prefilter=1`.

## When to Switch to Qdrant

Switch from SQLite to Qdrant when one or more are true:

- Corpus is consistently above ~50k chunks and broad queries are common.
- You need lower latency under concurrent query load.
- You need richer ANN controls (HNSW tuning, collection-level scaling, snapshots/replication path).

Set:

- `WKV_VECTOR_BACKEND=qdrant`
- `WKV_QDRANT_URL=http://127.0.0.1:6333`
- `WKV_QDRANT_COLLECTION=watchkeeper_docs`
