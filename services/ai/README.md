# AI Service

LLM orchestration layer that proposes actions but does not execute them.

## Initial Responsibilities

- Route request by mode/domain/urgency.
- Produce `IntentEnvelope` conforming to `contracts/v1/intent.schema.json`.
- Attach candidate `ProposedAction[]`.
- Consume core execution results and narrate outcomes.

## Knowledge API

Local dependency-free service for:
- Fact triples (`facts_triples` table)
- Vector retrieval (`vector_documents` table)

Vector backend is pluggable:
- Default: `sqlite`
- Optional: `qdrant`

### Run

1. Initialize DB schemas:
   - `scripts/create_db.ps1`
2. Start knowledge service:
   - `python services/ai/knowledge_service.py`
   - or `services/ai/run_knowledge.ps1`
3. Optional function-level smoke test (no HTTP server required):
   - `python scripts/smoke_test_knowledge.py`

### Bulk Ingest

Use the unified importer to load `Ingest Data` into facts and vectors:

- `python scripts/import_ingest_knowledge.py`
- include additional legacy dictionary seed:
  - `python scripts/import_ingest_knowledge.py --include-elite-dictionary-seed`
- dry run only:
  - `python scripts/import_ingest_knowledge.py --dry-run`
- import vectors to Qdrant backend:
  - `python scripts/import_ingest_knowledge.py --vector-backend qdrant`

### Backend Config

- `WKV_VECTOR_BACKEND=sqlite|qdrant` (default `sqlite`)
- `WKV_EMBED_DIM=256` (must match stored vectors; for Qdrant this is collection size)
- `WKV_QDRANT_URL=http://127.0.0.1:6333`
- `WKV_QDRANT_COLLECTION=watchkeeper_docs`
- `WKV_QDRANT_API_KEY=` (optional)
- `WKV_QDRANT_AUTOSTART=1` auto-start local Qdrant when backend is `qdrant`
- `WKV_QDRANT_AUTOSTOP=1` stop managed Qdrant when service exits
- `WKV_QDRANT_BIN=tools/qdrant/qdrant.exe` (preferred, repo-local; fallback `C:/ai/tools/qdrant/qdrant.exe`)
- `WKV_QDRANT_WORKDIR=tools/qdrant`
- `WKV_QDRANT_PID_FILE=data/qdrant_runtime.pid.json`

Example Qdrant startup:

```powershell
$env:WKV_VECTOR_BACKEND = "qdrant"
$env:WKV_QDRANT_URL = "http://127.0.0.1:6333"
$env:WKV_QDRANT_COLLECTION = "watchkeeper_docs"
python services/ai/knowledge_service.py
```

### Qdrant Runtime Scripts

- Start managed local Qdrant: `scripts/start_qdrant.ps1`
- Check status: `scripts/qdrant_status.ps1`
- Stop managed local Qdrant: `scripts/stop_qdrant.ps1`

If `WKV_VECTOR_BACKEND=qdrant`, `knowledge_service.py` starts Qdrant automatically
by default and cleanly stops it on service shutdown (managed/local runtime only).

### Endpoints

- `GET /health`
- `POST /facts/upsert`
- `POST /facts/query`
- `GET /facts/query`
- `POST /vector/upsert`
- `POST /vector/query`

## Assist Router Bridge

`assist_router.py` receives user prompts and routes structured intent into Brainstem:
- `POST /assist` -> Brainstem `POST /intent`
- optional auto execute -> Brainstem `POST /execute`
- Request contract: `contracts/v1/assist_request.schema.json`

### Run

- `python services/ai/assist_router.py`
- or `services/ai/run_assist_router.ps1`

### Router Environment

- `WKV_ASSIST_HOST` default `127.0.0.1`
- `WKV_ASSIST_PORT` default `8791`
- `WKV_BRAINSTEM_URL` default `http://127.0.0.1:8787`
- `WKV_KNOWLEDGE_URL` default `http://127.0.0.1:8790`
- `WKV_ASSIST_DEFAULT_MODE` default `standby`

### Assist Example

```powershell
$assistBody = @{
  incident_id = "inc-demo-001"
  user_text = "Set combat lights and skip track"
  mode = "game"
  watch_condition = "GAME"
  stt_confidence = 0.95
  auto_execute = $true
  dry_run = $true
  allow_high_risk = $false
  user_confirmed = $false
  use_knowledge = $true
}
$assistJson = $assistBody | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8791/assist -ContentType "application/json" -Body $assistJson
```

### Example: Facts

```powershell
$factsBody = @{
  triples = @(
    @{
      subject = "Sol"
      predicate = "has_star_type"
      object = "G2V"
      source = "manual_seed"
      confidence = 0.99
    },
    @{
      subject = "Jameson Memorial"
      predicate = "located_in"
      object = "Shinrarta Dezhra"
      source = "manual_seed"
      confidence = 0.99
    }
  )
}
$factsJson = $factsBody | ConvertTo-Json -Depth 8
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8790/facts/upsert -ContentType "application/json" -Body $factsJson

$factsQuery = @{
  subject = "Sol"
  limit = 10
}
$factsQueryJson = $factsQuery | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8790/facts/query -ContentType "application/json" -Body $factsQueryJson
```

### Example: Vector

```powershell
$vectorBody = @{
  docs = @(
    @{
      doc_id = "doc-thargoid-1"
      domain = "lore"
      title = "Thargoid Incursions"
      text_content = "The Thargoids intensified incursions around the Pleiades and core systems."
      source_id = "seed-lore"
    },
    @{
      doc_id = "doc-mining-1"
      domain = "gameplay"
      title = "Laser Mining Basics"
      text_content = "Use prospector limpets, refinery bins, and focus on high-value hotspots."
      source_id = "seed-gameplay"
    }
  )
}
$vectorJson = $vectorBody | ConvertTo-Json -Depth 8
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8790/vector/upsert -ContentType "application/json" -Body $vectorJson

$vectorQuery = @{
  query_text = "Where are the Thargoid attacks happening?"
  domain = "lore"
  top_k = 3
}
$vectorQueryJson = $vectorQuery | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8790/vector/query -ContentType "application/json" -Body $vectorQueryJson
```
