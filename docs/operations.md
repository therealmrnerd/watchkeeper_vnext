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
