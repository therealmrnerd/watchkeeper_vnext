# Operations Guide

## Unified Stack Control

Use `scripts/run_stack.ps1` for managed start/stop/status of the vNext runtime.

Managed services:
- `brainstem` (`services/brainstem/run.ps1`)
- `knowledge` (`services/ai/run_knowledge.ps1`)
- `assist_router` (`services/ai/run_assist_router.ps1`)
- `supervisor` (`services/brainstem/run_supervisor.ps1`)
- `state_collector` (`services/adapters/run_state_collector.ps1`)

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
