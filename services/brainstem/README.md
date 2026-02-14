# Brainstem Service

Deterministic core runtime. No LLM dependency for baseline operation.

## Initial Responsibilities

- Process supervision (ED/music lifecycle hooks).
- Capability checks and mode gating.
- State updates and event emission.
- Action approval and execution orchestration.

## Required Endpoints

- `GET /health`
- `GET /state`
- `GET /events`
- `POST /state`
- `POST /intent`
- `POST /execute`
- `POST /feedback`

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

```powershell
$stateBody = @{
  items = @(
    @{
      state_key = "music.now_playing"
      state_value = @{
        title = "Example Song"
        artist = "Example Artist"
      }
      source = "ytm_adapter"
      confidence = 0.99
    }
  )
  correlation_id = "demo-001"
}
$stateBodyJson = $stateBody | ConvertTo-Json -Depth 8
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8787/state -ContentType "application/json" -Body $stateBodyJson
```

```powershell
$feedbackBody = @{
  request_id = "req-smoke-001"
  rating = 1
  correction_text = "Good response"
}
$feedbackBodyJson = $feedbackBody | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8787/feedback -ContentType "application/json" -Body $feedbackBodyJson
```
