# Watchkeeper vNext

Watchkeeper is a local-first system assistant for Elite Dangerous workflows and
general desktop control.

## Current Capabilities (Live Now)

- Deterministic Brainstem core with SQLite-backed state + append-only event log.
- Supervisor loops for:
  - Elite Dangerous runtime + parser lifecycle control
  - YouTube Music Desktop now-playing ingest
  - hardware/system stats ingest
- Standing Orders policy engine with allow/deny, confirmations, reason codes, and rate/guard checks.
- Action execution flow with `/assist` proposal handling and `/confirm` approval flow.
- Knowledge layer support for local facts + vectors (SQLite backend and optional Qdrant backend).
- Brainstem web UI with:
  - Console (assist prompt/response + policy preview)
  - Quick SitRep (app status chips, now playing, Twitch summaries)
  - Logs & diagnostics views
- Jinx integration for lighting control/sync (effects/scenes/chases via state/action pipeline).
- SAMMI bidirectional integration:
  - SAMMI -> Watchkeeper: UDP "doorbell" triggers typed Twitch ingest.
  - Watchkeeper -> SAMMI: variable writes + button triggers (including Twitch chat send path).
- Twitch ingest pipeline with persistence and context queries for chat/redeem/bits/follow flows (and extensible event mapping for additional categories).
- Twitch send-chat path is policy-gated and confirm-capable (`twitch.send_chat` through Standing Orders).

As a result, Watchkeeper can now decide and gate actions on live game/runtime
state and stream interaction state (through SAMMI/Twitch events), rather than
just passively observing telemetry.

## Planned Capabilities (Roadmap)

- Harden STT/TTS as independent production services (wake-word, confidence, barge-in, personalization).
- Expand Twitch coverage for newer event classes (power ups, shoutouts, hype train, polls, predictions, raids, subs) as SAMMI mappings are finalized.
- Move Twitch gating from "SAMMI running" to "streaming active" policy condition.
- Add dedicated ED Status and OBS UI tabs.
- Improve expert routing + retrieval packs for local LLM assist quality.
- Continue performance optimization and loop efficiency hardening.
- Keep interface contracts stable to support staged Go/Rust/C++ rewrites.

## Current Stage

This project is in an active vNext rebuild stage (early-to-mid integration).

- Core runtime, policy layer, ED/music/system loops, and stack orchestration are working.
- Knowledge service and vector backend support are working (including Qdrant lifecycle).
- Focus now is operational hardening, integration polish, and expanding live data coverage.

## External Integrations

- Current external integrations are Jinx (LED lighting sync) and SAMMI Board
  (in-game and streaming control panel, including Twitch data bridge).
- Future integrations may be added for other lighting software and control surfaces (for example Stream Deck and Glass).

## Quick Start

Start full stack:

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Action start`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Action status`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_stack.ps1 -Action stop`

## Useful Docs

- Operations runbook: `docs/operations.md`
- Brainstem details: `services/brainstem/README.md`
- AI/knowledge details: `services/ai/README.md`
- Adapter details: `services/adapters/README.md`
