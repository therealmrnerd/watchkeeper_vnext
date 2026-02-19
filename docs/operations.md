# Operations Guide

## Unified Stack Control

Use `scripts/run_stack.ps1` for managed start/stop/status of the vNext runtime.

Managed services:
- `brainstem` (`services/brainstem/run.ps1`)
- `knowledge` (`services/ai/run_knowledge.ps1`)
- `assist_router` (`services/ai/run_assist_router.ps1`)
- `supervisor` (`services/brainstem/run_supervisor.ps1`)
- `state_collector` (`services/adapters/run_state_collector.ps1`)

When ED is detected running, supervisor can auto-verify/start auxiliary apps:
- `SAMMI` (`WKV_SUP_SAMMI_EXE`)
- `Jinx` (`WKV_SUP_JINX_EXE`)
- `ed.ahk` (`WKV_SUP_ED_AHK_PATH`, launched via `WKV_SUP_AHK_EXE`)

Control with:
- `WKV_SUP_AUX_APPS_AUTORUN` (`1` default via `set_runtime_env.ps1`)
- `WKV_SUP_ED_AHK_STOP_ON_ED_EXIT` (`1` default; set `0` to keep ED AHK process running)
- `WKV_SUP_ED_AHK_RESTART_BACKOFF_SEC` (default `3`, relaunch delay if `ed.ahk` exits while ED is still running)
- `WKV_SUP_AHK_PROTECTED_SCRIPTS` (default `stack_tray.ahk`; matching AHK scripts are never terminated by supervisor)

Supervisor also bridges ED parser-compatible variables to SAMMI Local API (`/api`)
using `setVariable` with change-only sends.

Coverage mirrors legacy `edparser.mjs` patterns:
- top-level `Status.json` keys (for example `Flags`, `Flags2`, `Fuel`, `GuiFocus`)
- derived flight variables (`landed`, `shields_up`, `lights`, `flags_text`, `flightstatus`, etc.)
- nav route variables (`nav_route`, `nav_route_origin`, `nav_route_destination`)
- journal-derived ship context (`ship_name`, `ship_model`, `ship_id`) when available
- Music: `YTM_Title`, `YTM_Artist`, `YTM_NowPlaying`

SAMMI bridge env:
- `WKV_SAMMI_API_ENABLED` (default `1`)
- `WKV_SAMMI_API_HOST` (default `127.0.0.1`)
- `WKV_SAMMI_API_PORT` (default `9450`)
- optional `WKV_SAMMI_API_PASSWORD`
- `WKV_SAMMI_API_ONLY_WHEN_ED` (default `1`)
- `WKV_SAMMI_API_TIMEOUT_SEC` (default `0.6`)
- `WKV_SAMMI_API_MAX_UPDATES_PER_CYCLE` (default `12`)
- `WKV_SAMMI_NEW_WRITE_VAR` (default `ID116.new_write`)
- `WKV_SAMMI_NEW_WRITE_COMPAT_VAR` (default `ID116.new_write`)
- `WKV_SAMMI_NEW_WRITE_IGNORE_VARS` (default `Heartbeat,timestamp`)
- `WKV_SUP_MUSIC_REQUIRES_PROCESS` (default `1`)
- `WKV_SUP_MUSIC_PROCESS_NAMES` (default `YouTube Music Desktop App.exe,YouTubeMusicDesktopApp.exe,YouTube Music.exe,ytmdesktop.exe`)
- `WKV_YTMD_PROCESS_NAMES` (default `YouTube Music Desktop App.exe,YouTubeMusicDesktopApp.exe,YouTube Music.exe,ytmdesktop.exe`)
- `WKV_SUP_HARDWARE_REQUIRES_JINX` (default `1`)

Runtime gating:
- If ED is not running, supervisor does not poll SAMMI variables or send SAMMI bridge updates.
- If YTMD is not running, now-playing parsing is skipped.
- If Jinx is not running, hardware stats parsing/writes are skipped.

`ID116.new_write` behavior:
- On meaningful SAMMI variable changes, supervisor writes `ID116.new_write=yes`
- Supervisor does not write `no`; reset to `no` is handled in SAMMI after trigger
- Compatibility alias can be changed with `WKV_SAMMI_NEW_WRITE_COMPAT_VAR`
- Pulse trigger ignores noisy variables listed in `WKV_SAMMI_NEW_WRITE_IGNORE_VARS`

Low-latency defaults:
- `WKV_SUP_ED_ACTIVE_SEC=0.35`
- `WKV_EDPARSER_ACTIVE_SEC=0.35`
- `WKV_SUP_LOOP_SLEEP_SEC=0.1`

Legacy stats TXT export (for overlays/widgets):
- `WKV_SUP_STATS_TXT_ENABLED` (default `1`)
- `WKV_SUP_STATS_DIR` (defaults to `C:\ai\Watchkeeper\stats` when present, else `<repo>\stats`)
- `WKV_SUP_STATS_LINE_SEC` (default `10`)
- Files written: `cpu-temp.txt`, `cpu-usage.txt`, `gpu-temp.txt`, `gpu-usage.txt`, `cpu-line.txt`, `gpu-line.txt`

Runtime telemetry for bridge performance:
- `app.sammi.api.last_cycle_ms`
- `app.sammi.api.last_push_count`
- `app.sammi.api.deferred_count`

Jinx sync behavior:
- Polls SAMMI variable `sync` (`on`/`off`)
- `sync=on`: applies effect mapped from current ED environment
- `sync=off`: applies `WKV_SUP_JINX_OFF_EFFECT` (default `S1`)
- Sends Art-Net via `tools/jinxsender.py`

Jinx env:
- `WKV_SUP_JINX_SYNC_ENABLED` (default `1`)
- `WKV_SUP_JINX_ARGS` (default `-m`)
- `WKV_SUP_JINX_SENDER_PATH` (default `tools/jinxsender.py`)
- `WKV_SUP_JINX_ENV_MAP_PATH` (default `config/jinx_envmap.json`)
- `WKV_SUP_JINX_ARTNET_IP` (default `127.0.0.1`)
- `WKV_SUP_JINX_ARTNET_UNIVERSE` (default `1`)
- `WKV_SUP_JINX_BRIGHTNESS` (default `200`)

Manual Jinx control via state keys:
- `jinx.effect` (values like `S7` or `C14`)
- `jinx.scene` (numeric scene, converted to `S<n>`)
- `jinx.chase` (numeric chase, converted to `C<n>`)

The script auto-loads `scripts/set_runtime_env.ps1` before actions, so repo-local
model paths and DB paths are applied consistently.

## Commands

Start:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Action start
```

Status:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Action status
```

Stop:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Action stop
```

Restart:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Action restart
```

Optional flags:
- `-HealthTimeoutSec <seconds>` for startup health wait window (default `45`)
- `-NoHealthChecks` to skip endpoint/process readiness checks on start

## Tray Controller (AutoHotkey)

For quick desktop control, use:
- `scripts/stack_tray.ahk`

It provides tray menu actions for:
- Start stack
- Stop stack
- Restart stack
- Status (opens console)
- Open logs folder

Notes:
- Requires AutoHotkey v1.
- It calls `scripts/run_stack.ps1` in this repo, so behavior stays consistent with CLI operations.

## Runtime State File

Managed process metadata is stored at:
- `data/stack_processes.json`

Service logs are written to:
- `logs/brainstem.out.log`, `logs/brainstem.err.log`
- `logs/knowledge.out.log`, `logs/knowledge.err.log`
- `logs/assist_router.out.log`, `logs/assist_router.err.log`
- `logs/supervisor.out.log`, `logs/supervisor.err.log`
- `logs/state_collector.out.log`, `logs/state_collector.err.log`

If the state file is missing but services are still up, they are treated as
external and are not stopped until managed again by `run_stack.ps1`.

## Health and Shutdown Behavior

- HTTP services are validated using `/health` endpoints.
- Background services (`supervisor`, `state_collector`) are validated by process liveness.
- Stop uses Windows process-tree termination (`taskkill /T /F`) to avoid orphaned
  child Python processes from launcher scripts.

## Recommended Workflow

1. Start stack with `run_stack.ps1 -Action start`.
2. Verify with `run_stack.ps1 -Action status`.
3. Run smoke tests or gameplay/work sessions.
4. Stop stack with `run_stack.ps1 -Action stop`.

## Diagnostics Report

Generate a local report with config, schema versions, policy summary, and latest events:

```powershell
python tools/diag_report.py --pretty
```

Use custom sources if required:

```powershell
python tools/diag_report.py --db-path data/watchkeeper_vnext.db --policy-path config/standing_orders.json --events-limit 50 --pretty
```
