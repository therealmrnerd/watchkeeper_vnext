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
- `services/brainstem`: Brainstem service placeholder.
- `services/ai`: AI orchestration service placeholder.
- `services/speech`: STT/TTS service placeholder.
- `docs`: architecture, migration, and lessons learned.
- `scripts`: helper scripts for local setup.

## Quick Start

1. Create the database with:
   - `sqlite3 data/watchkeeper_vnext.db ".read schemas/sqlite/001_brainstem_core.sql"`
2. Validate payloads against JSON schemas in `contracts/v1`.
3. Implement Brainstem endpoints first:
   - `GET /state`
   - `GET /events`
   - `POST /intent`
   - `POST /execute`

Current status:
- Brainstem API stubs are implemented in `services/brainstem/app.py` with SQLite-backed intent/action/event logging.
- `/execute` request contract is defined in `contracts/v1/execute_request.schema.json`.
- `/state` ingest and `/feedback` capture contracts are defined in:
  - `contracts/v1/state_ingest_request.schema.json`
  - `contracts/v1/feedback_request.schema.json`
- Knowledge API stubs are implemented in `services/ai/knowledge_service.py`:
  - Triple facts: `/facts/upsert`, `/facts/query`
  - Vector retrieval: `/vector/upsert`, `/vector/query`
  - Contracts:
    - `contracts/v1/facts_upsert_request.schema.json`
    - `contracts/v1/facts_query_request.schema.json`
    - `contracts/v1/vector_upsert_request.schema.json`
    - `contracts/v1/vector_query_request.schema.json`

## Notes

- `git` was not available in this shell session, so this scaffold includes `scripts/init_repo.ps1` for repo initialization on your machine where Git is installed.
