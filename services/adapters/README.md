# Adapters

Runtime collectors and bridges that connect external signals into Brainstem.

## State Collector

`state_collector.py` pushes ED/music/system state into Brainstem `POST /state`.

### Run

- `python services/adapters/state_collector.py`
- or `services/adapters/run_state_collector.ps1`

### Environment

- `WKV_BRAINSTEM_URL` default `http://127.0.0.1:8787`
- `WKV_PROFILE` default `watchkeeper`
- `WKV_COLLECTOR_SESSION` default `collector-main`
- `WKV_NOW_PLAYING_DIR` default `C:/ai/Watchkeeper/now-playing`
- `WKV_ED_PROCESS_NAMES` default `EliteDangerous64.exe,EliteDangerous.exe`
- `WKV_SYSTEM_INTERVAL_SEC` default `15`
- `WKV_ED_ACTIVE_INTERVAL_SEC` default `2`
- `WKV_ED_IDLE_INTERVAL_SEC` default `8`
- `WKV_MUSIC_ACTIVE_INTERVAL_SEC` default `2`
- `WKV_MUSIC_IDLE_INTERVAL_SEC` default `12`

## ED Parser vNext

`edparser_vnext.py` is the low-overhead ED telemetry adapter used by Brainstem's
`edparser.*` tool control. It parses `Status.json` + latest Journal tail and writes
canonical telemetry to `data/ed_telemetry.json`.

### Run

- `python services/adapters/edparser_vnext.py`
- or `services/adapters/run_edparser_vnext.ps1`
- one-shot check: `python services/adapters/edparser_vnext.py --once`

### Telemetry Contract

- `contracts/v1/edparser_telemetry.schema.json`
- output file: `WKV_ED_TELEMETRY_OUT` (default `data/ed_telemetry.json`)

### Environment

- `WKV_ED_STATUS_PATH` default `%USERPROFILE%/Saved Games/Frontier Developments/Elite Dangerous/Status.json`
- `WKV_ED_JOURNAL_DIR` default `%USERPROFILE%/Saved Games/Frontier Developments/Elite Dangerous`
- `WKV_ED_TELEMETRY_OUT` default `data/ed_telemetry.json`
- `WKV_ED_PROCESS_NAMES` default `EliteDangerous64.exe,EliteDangerous.exe`
- `WKV_EDPARSER_ACTIVE_SEC` default `0.6`
- `WKV_EDPARSER_IDLE_SEC` default `2.5`
- `WKV_EDPARSER_LOG_LEVEL` default `info`
- `WKV_EDPARSER_ASSUME_RUNNING` optional test-only override

## Legacy Compatibility Wrapper

`edparser_compat.mjs` is a thin Node wrapper that forwards to
`services/adapters/edparser_vnext.py` so old "run edparser.mjs" style workflows can
continue during migration.

Brainstem defaults to this wrapper path unless `WKV_EDPARSER_COMMAND` or
`WKV_EDPARSER_SCRIPT` override is supplied.

### Run

- `node services/adapters/edparser_compat.mjs`
- or `services/adapters/run_edparser_compat.ps1`

### Wrapper Environment

- `WKV_EDPARSER_PYTHON` Python executable for the delegated adapter
- `WKV_EDPARSER_VNEXT_SCRIPT` override target script path
- legacy aliases accepted and mapped:
  - `STATUS_PATH` -> `WKV_ED_STATUS_PATH`
  - `JOURNAL_DIR` -> `WKV_ED_JOURNAL_DIR`
  - `ED_TELEMETRY_JSON` -> `WKV_ED_TELEMETRY_OUT`
  - `ED_PROCESS_NAMES` -> `WKV_ED_PROCESS_NAMES`
