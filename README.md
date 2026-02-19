# Watchkeeper vNext

Watchkeeper is a local-first system assistant for Elite Dangerous workflows and
general desktop control.

## What Watchkeeper Does

- Runs a deterministic core ("Brainstem") that keeps live system state.
- Monitors Elite Dangerous running state and telemetry.
- Monitors music now-playing state.
- Monitors hardware/system status.
- Uses policy gates ("Standing Orders") so actions are allowed/denied safely by mode.
- Exposes APIs for state, events, intents, execution, confirmation, and feedback.
- Supports local knowledge retrieval (facts + vectors) with SQLite or Qdrant.
- Routes assistant requests through a local assist service into Brainstem.

## What It Will Do Next

- Harden speech (STT/TTS) as an independent production service.
- Expand retrieval quality and expert routing.
- Continue optimizing adapters and high-frequency loops.
- Prepare clean module boundaries for later Go/Rust rewrite paths.

## Current Stage

This project is in an active vNext rebuild stage (early-to-mid integration).

- Core runtime, policy layer, ED/music/system loops, and stack orchestration are working.
- Knowledge service and vector backend support are working (including Qdrant lifecycle).
- Focus now is operational hardening, integration polish, and expanding live data coverage.

## External Integrations

- Current external integrations are Jinx (LED lighting sync) and SAMMI Board (in-game and streaming control panel).
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
