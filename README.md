# Watchkeeper vNext

Watchkeeper is a local-first AI + automation stack for Elite Dangerous, stream
operations, and desktop assistance.

## What This Project Is

Watchkeeper combines a deterministic "Brainstem" runtime with policy-gated AI.
The core keeps running and enforcing rules even if AI/cloud/model services fail.
The AI proposes actions, while the core decides and executes safely.

## What It Does Today

- Runs a deterministic Brainstem core with SQLite-backed state and event log.
- Supervises Elite Dangerous, YouTube Music Desktop, and system stat pipelines.
- Applies Standing Orders policy gates with allow/deny, confirmations, and reason codes.
- Supports `/assist` and `/confirm` action flows with incident tracking.
- Exposes operational APIs for state, events, sitrep, execution, and Twitch context.
- Uses local knowledge retrieval with SQLite and optional Qdrant vector backend.
- Provides a browser UI for console operations, policy preview, sitrep, and diagnostics.
- Integrates with Jinx for LED scene/effect/chase control.
- Integrates bidirectionally with SAMMI:
- SAMMI -> Watchkeeper via UDP doorbell Twitch ingest.
- Watchkeeper -> SAMMI via variable writes and button triggers (including Twitch chat send).
- Ingests Twitch event categories (chat, redeem, bits, follow, and extended mappings) with dedupe and persistence.

In human terms: Watchkeeper can now make and gate decisions based on live game
state and live stream interaction state, not just static prompts.

## UI Snapshot (Current)

![Watchkeeper vNext UI Snapshot](docs/assets/watchkeeper-ui-snapshot-2026-02-20.png)

## Why Be Part Of It

- Build a practical local-first assistant that works under real runtime constraints.
- Contribute to a clean "AI proposes, core decides" architecture instead of unsafe direct agent control.
- Help shape reusable contracts for future Go/Rust/C++ migrations.
- Work on a real integration surface: game telemetry, stream tooling, lighting, and policy automation.
- Improve reliability and operator UX for a system designed to be run live.

## Planned Capabilities (Roadmap)

- Harden STT/TTS as independent production services.
- Expand Twitch category coverage as SAMMI mappings are finalized.
- Move Twitch gate condition from "SAMMI running" to "streaming active".
- Add dedicated ED Status and OBS tabs in the web UI.
- Improve expert routing and retrieval pack quality for local LLM assist.
- Continue performance tuning for high-frequency loops and adapters.
- Preserve stable contracts while preparing staged native rewrites.

## External Integrations

- Current external integrations are Jinx (LED lighting sync) and SAMMI Board
  (in-game and streaming control panel, including Twitch data bridge).
- Future integrations may be added for other lighting software and control surfaces (for example Stream Deck and Glass).

## Quick Start

Start full stack:

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Action start`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Action status`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Action stop`

## Status Brief

- Status: Usable (developer alpha, active integration).
- Currently working:
- Brainstem runtime and policy layer.
- ED/music/system ingest loops and stack orchestration.
- Twitch ingest + SAMMI doorbell bridge + policy-gated Twitch send chat.
- Jinx and SAMMI integrations through the core pipeline.
- Web console for assist, policy preview, sitrep, and diagnostics.
- Current focus:
- Operational hardening and integration polish.
- Expanding Twitch and UI feature coverage.
- Next steps (short):
- Finalize streaming-aware Twitch gate condition.
- Expand speech reliability and recovery behavior.
- Continue modular cleanup for future language-port phases.

## Useful Docs

- Operations runbook: `docs/operations.md`
- Brainstem details: `services/brainstem/README.md`
- AI/knowledge details: `services/ai/README.md`
- Adapter details: `services/adapters/README.md`
