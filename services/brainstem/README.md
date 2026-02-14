# Brainstem Service

Deterministic core runtime. No LLM dependency for baseline operation.

## Initial Responsibilities

- Process supervision (ED/music lifecycle hooks).
- Capability checks and mode gating.
- State updates and event emission.
- Action approval and execution orchestration.

## Required Endpoints

- `GET /state`
- `GET /events`
- `POST /intent`
- `POST /execute`

## Stub Implementation

- Runtime: standard-library Python (`http.server` + `sqlite3`)
- Entry point: `services/brainstem/app.py`
- Default bind: `127.0.0.1:8787`
- Default DB: `data/watchkeeper_vnext.db`

## Run

1. Initialize DB (once): `scripts/create_db.ps1`
2. Start service:
   - `python services/brainstem/app.py`
   - or `services/brainstem/run.ps1`

## Example Calls

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8787/health
```

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8787/events?limit=10"
```
