# Watchkeeper vNext

Fresh repository scaffold for the rebuild, based on lessons learned from the current prototype.

## Design Rules

- Brainstem is deterministic, event-driven, and always-on.
- AI proposes structured intents; Brainstem approves and executes.
- Speech is independent from LLM lifecycle.
- Everything is an event; latest truth is current state.

## Repository Layout

- `contracts/v1`: JSON schemas for AI/Core contracts.
- `schemas/sqlite`: SQLite DDL migrations for core data model.
- `config`: policy and runtime configuration (including standing orders).
- `core`: policy contracts, policy engine, and tool routing logic.
- `db`: logbook helpers for policy/execute event logging.
- `services/brainstem`: Brainstem service.
- `services/ai`: AI orchestration and knowledge services.
- `services/adapters`: external collector adapters.
- `services/speech`: STT/TTS service placeholder.
- `tests`: unit tests for deterministic core behavior.
- `tools`: local CLI harnesses (including standing-orders simulation).
- `docs`: architecture, migration, and lessons learned.
- `scripts`: helper scripts for local setup.

## Quick Start

1. Create or migrate DB:
   - `scripts/create_db.ps1`
   - or let service launchers auto-wire env + DB via `scripts/set_runtime_env.ps1`
2. Start Brainstem:
   - `python services/brainstem/app.py`
3. Start Knowledge API:
   - `python services/ai/knowledge_service.py`
4. Start Assist Router:
   - `python services/ai/assist_router.py`
5. Start state collector:
   - `python services/adapters/state_collector.py`

Launcher scripts (`services/*/run*.ps1`) now auto-load `scripts/set_runtime_env.ps1`
so model paths, DB paths, and repo-local runtime directories are wired by default.

Current status:
- Brainstem API stubs are implemented in `services/brainstem/app.py` with SQLite-backed intent/action/event logging.
- Brainstem DB contract layer implemented in `services/brainstem/db_service.py`:
  - `set_state`, `get_state`, `batch_set_state`, `append_event`
- Standing Orders policy layer implemented in:
  - `core/policy_types.py`
  - `core/policy_engine.py`
  - `core/tool_router.py`
  - `db/logbook.py`
  - config file: `config/standing_orders.json`
  - watch-condition gating + tool policy checks + incident logging
- Brainstem execution now supports real actuators for:
  - `set_lights` (webhook)
  - `music_next`, `music_pause`, `music_resume` (media keys)
  - `keypress` (guarded; disabled by default)
  - `edparser.start`, `edparser.stop`, `edparser.status` (external tool control)
- `/execute` request contract is defined in `contracts/v1/execute_request.schema.json`.
- `/confirm` request contract is defined in `contracts/v1/confirm_request.schema.json`.
- ED parser telemetry contract is defined in `contracts/v1/edparser_telemetry.schema.json`.
- `/state` ingest and `/feedback` capture contracts are defined in:
  - `contracts/v1/state_ingest_request.schema.json`
  - `contracts/v1/feedback_request.schema.json`
- Knowledge API stubs are implemented in `services/ai/knowledge_service.py`:
  - Triple facts: `/facts/upsert`, `/facts/query`
  - Vector retrieval: `/vector/upsert`, `/vector/query`
  - Vector backend: `sqlite` (default) or `qdrant` via `WKV_VECTOR_BACKEND`
  - Qdrant runtime lifecycle: auto-start/auto-stop for managed local dependency
  - Qdrant scripts: `scripts/start_qdrant.ps1`, `scripts/qdrant_status.ps1`, `scripts/stop_qdrant.ps1`
  - Contracts:
    - `contracts/v1/facts_upsert_request.schema.json`
    - `contracts/v1/facts_query_request.schema.json`
    - `contracts/v1/vector_upsert_request.schema.json`
    - `contracts/v1/vector_query_request.schema.json`
- Assist Router bridge implemented in `services/ai/assist_router.py`:
  - `POST /assist` -> Brainstem `POST /intent` and optional `POST /execute`
  - Contract: `contracts/v1/assist_request.schema.json`
- Adapter collector implemented in `services/adapters/state_collector.py`:
  - ED/music/system ingest into Brainstem `POST /state`
- ED parser adapter implemented in `services/adapters/edparser_vnext.py`:
  - low-overhead `Status.json` + Journal parse to `data/ed_telemetry.json`
  - controlled by Brainstem tool actions: `edparser.start`, `edparser.stop`, `edparser.status`
- Legacy Node wrapper added in `services/adapters/edparser_compat.mjs`:
  - keeps old Node launch workflows while delegating to vNext adapter
  - now the default Brainstem ED parser launch target
- Brainstem supervisor loops implemented in `services/brainstem/supervisor.py`:
  - Hardware probe cadence + threshold events
  - ED on/off cadence + minimal telemetry states
  - ED parser tool supervision (start when ED active, stop when ED inactive)
  - YTM now playing cadence + track change events
  - watch-condition transitions + handover notes logbook events

## Notes

- `git` was not available in this shell session, so this scaffold includes `scripts/init_repo.ps1` for repo initialization on your machine where Git is installed.
