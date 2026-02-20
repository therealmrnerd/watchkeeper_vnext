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
- `GET /sitrep`
- `POST /state`
- `POST /intent`
- `POST /execute`
- `POST /confirm`
- `POST /feedback`
- `GET /twitch/user/{user_id}`
- `GET /twitch/user/{user_id}/redeems/top?limit=5`
- `GET /twitch/recent?limit=50`
- `POST /twitch/send_chat`
- `POST /app/open`

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
  - `edparser.start` / `edparser.stop` / `edparser.status` via local tool runner

## Actuator Config

- `WKV_ENABLE_ACTUATORS=1` global actuator on/off
- `WKV_ENABLE_KEYPRESS=0` extra guard for `keypress` tool
- `WKV_LIGHTS_WEBHOOK_URL=` fixed endpoint for `set_lights`
- `WKV_LIGHTS_WEBHOOK_URL_TEMPLATE=` optional template with `{scene}`
- `WKV_LIGHTS_WEBHOOK_TIMEOUT_SEC=5`
- `WKV_KEYPRESS_ALLOWED_PROCESSES=EliteDangerous64.exe,EliteDangerous.exe`
- `WKV_EDPARSER_ENABLED=1`
- `WKV_EDPARSER_COMMAND=` optional full command override (highest priority)
- `WKV_EDPARSER_PYTHON=` default current Python executable
- `WKV_EDPARSER_NODE=node`
- `WKV_EDPARSER_SCRIPT=` default `services/adapters/edparser_compat.mjs`
- `WKV_EDPARSER_ARGS=` optional args appended to script command
- direct vNext adapter option:
  - `WKV_EDPARSER_SCRIPT="services/adapters/edparser_vnext.py"`
- `WKV_EDPARSER_STOP_TIMEOUT_SEC=4`
- `WKV_EDPARSER_KILL_EXTERNAL_PID=1`

## Standing Orders

- Policy file: `config/standing_orders.json`
- Override path: `WKV_STANDING_ORDERS_PATH`
- Policy engine/contracts:
  - `core/policy_types.py`
  - `core/policy_engine.py`
  - `core/tool_router.py`
  - `db/logbook.py`
- Execute pipeline enforces:
  - watch condition allow/deny tool lists (wildcards)
  - tool policy guards (foreground, confidence, confirmation, rate limits)
  - incident ID requirement (`incident_id`)
  - deny/execute logging with reason payloads

## Twitch Ingest

Brainstem supports Twitch ingest via SAMMI UDP doorbell + variable readback.

- Doorbell token format: `category|timestamp`
- Numeric packed format also supported: `CCC<timestamp>` (for example `101...` for CHAT)
  - chosen to keep SAMMI packet handling deterministic and avoid string-buffer instability
- Commit marker rule (when variable-based): write `wk.<category>.ts` last in SAMMI
- Gate invariant: `no SAMMI -> no UDP bind -> no ingest reads`

Primary knobs:

- `WKV_TWITCH_UDP_ENABLED`, `WKV_TWITCH_UDP_HOST`, `WKV_TWITCH_UDP_PORT`
- `WKV_TWITCH_UDP_ACK_ONLY`
- per-category debounce (ms):
  - `WKV_TWITCH_CHAT_DEBOUNCE_MS`
  - `WKV_TWITCH_REDEEM_DEBOUNCE_MS`
  - `WKV_TWITCH_BITS_DEBOUNCE_MS`
  - `WKV_TWITCH_FOLLOW_DEBOUNCE_MS`
  - `WKV_TWITCH_SUB_DEBOUNCE_MS`
  - `WKV_TWITCH_RAID_DEBOUNCE_MS`
  - `WKV_TWITCH_HYPE_TRAIN_DEBOUNCE_MS`
  - `WKV_TWITCH_POLL_DEBOUNCE_MS`
  - `WKV_TWITCH_PREDICTION_DEBOUNCE_MS`
  - `WKV_TWITCH_SHOUTOUT_DEBOUNCE_MS`
  - `WKV_TWITCH_POWER_UPS_DEBOUNCE_MS`
  - `WKV_TWITCH_HYPE_DEBOUNCE_MS`

Failure handling:

- malformed doorbell tokens are ignored (no ingest write)
- duplicate/old commit markers are ignored via cursor dedupe
- when packet timestamp and commit-marker variable differ, configured commit marker wins
  (single-pass resolution; no retry loop)

Well-known SAMMI runtime state keys:

- `app.sammi.running` (Twitch UDP bind gate)
- `app.sammi.enabled`
- `app.sammi.path`
- `app.sammi.last_error`

Reference: `docs/twitch_ingest.md`

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
   - `python scripts/smoke_test_edparser_vnext_once.py`
   - `python -m unittest tests/test_policy_engine.py`
   - `python tools/policy_sim.py --condition GAME --tool input.keypress --foreground EliteDangerous64.exe --stt 0.93`

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
- `WKV_SUP_EDPARSER_AUTORUN` (default `1`; start parser when ED is running, stop when not)

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

```powershell
$confirmBody = @{
  incident_id = "inc-demo-001"
  tool_name = "twitch.redeem"
  request_id = "req-smoke-001"
}
$confirmBodyJson = $confirmBody | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8787/confirm -ContentType "application/json" -Body $confirmBodyJson
```
