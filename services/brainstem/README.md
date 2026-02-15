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
- DB service layer: `services/brainstem/db_service.py`
  - `set_state`
  - `get_state`
  - `batch_set_state`
  - `append_event`
- Actuation:
  - `set_lights` via webhook
  - `music_next` / `music_pause` / `music_resume` via media keys
  - `keypress` via virtual key event (disabled by default)

## Actuator Config

- `WKV_ENABLE_ACTUATORS=1` global actuator on/off
- `WKV_ENABLE_KEYPRESS=0` extra guard for `keypress` tool
- `WKV_LIGHTS_WEBHOOK_URL=` fixed endpoint for `set_lights`
- `WKV_LIGHTS_WEBHOOK_URL_TEMPLATE=` optional template with `{scene}`
- `WKV_LIGHTS_WEBHOOK_TIMEOUT_SEC=5`
- `WKV_KEYPRESS_ALLOWED_PROCESSES=EliteDangerous64.exe,EliteDangerous.exe`

## Standing Orders

- Policy file: `config/standing_orders.json`
- Override path: `WKV_STANDING_ORDERS_PATH`
- Execute pipeline enforces:
  - watch condition allow/deny tool lists (wildcards)
  - tool policy guards (foreground, confidence, confirmation, rate limits)
  - incident ID requirement (`incident_id`)
  - deny/execute logging with reason payloads

## Run

1. Initialize DB (once): `scripts/create_db.ps1`
2. Start service:
   - `python services/brainstem/app.py`
   - or `services/brainstem/run.ps1`
3. Start supervisor loops:
   - `python services/brainstem/supervisor.py`
   - or `services/brainstem/run_supervisor.ps1`
4. Optional smoke tests:
   - `python scripts/smoke_test_brainstem_db_layer.py`
   - `python scripts/smoke_test_supervisor_once.py`

## Supervisor Loops

Minimum viable DB-validation ingest sources:
- Hardware probe:
  - `hardware.*` state updates
  - threshold events (`HARDWARE_THRESHOLD`) when memory usage crosses configured threshold
- ED:
  - `ed.running`
  - `ed.telemetry.system_name`
  - `ed.telemetry.hull_percent`
  - lifecycle events (`ED_STARTED`, `ED_STOPPED`)
- YTM now playing:
  - `music.track.title`
  - `music.track.artist`
  - `music.playing`
  - track/lifecycle events (`TRACK_CHANGED`, `MUSIC_STARTED`, `MUSIC_STOPPED`)
  - watch-condition change logbook:
    - `WATCH_CONDITION_CHANGED`
    - `HANDOVER_NOTE` (equipment, alarms, ED/music/AI status)

Loop cadence knobs:
- `WKV_SUP_HARDWARE_SEC`
- `WKV_SUP_ED_ACTIVE_SEC`, `WKV_SUP_ED_IDLE_SEC`
- `WKV_SUP_MUSIC_ACTIVE_SEC`, `WKV_SUP_MUSIC_IDLE_SEC`

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

```powershell
$executeBody = @{
  request_id = "req-smoke-001"
  incident_id = "inc-demo-001"
  watch_condition = "GAME"
  stt_confidence = 0.95
  dry_run = $false
  allow_high_risk = $true
  user_confirmed = $true
  confirmed_at_utc = "2026-02-15T12:00:00Z"
}
$executeBodyJson = $executeBody | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8787/execute -ContentType "application/json" -Body $executeBodyJson
```
