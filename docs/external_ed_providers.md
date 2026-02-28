# External Elite Dangerous Providers

This document defines the first stable contract layer for external Elite Dangerous providers in Watchkeeper vNext.

The immediate goal is not "wire every API." The goal is to lock:

- provider identity
- health/status shape
- query/response contracts
- local caching expectations
- policy boundaries between read-only and write-ish integrations

That gives Brainstem, the UI, and later adapter implementations one stable surface.

## Provider Catalogue

### Spansh

- Provider ID: `spansh`
- Role: galaxy/system topology
- Auth: none
- Call profile: read-only, cache-first
- Intended use:
  - auto-fetch on first known system visit
  - refresh on revisit only when stale and budget allows

### EDSM

- Provider ID: `edsm`
- Role: galaxy/system topology, optional commander-linked features
- Auth:
  - public read endpoints: none
  - commander-linked: user key + commander name
- Intended use:
  - read-only topology is allowed by default
  - commander-linked calls remain disabled unless explicitly configured

### Inara

- Provider ID: `inara`
- Role: commander-centric sync/location
- Auth: app credentials / whitelist required
- Intended use:
  - opt-in only
  - minimal location push on system change
  - strict debounce and low rate budget

### EDSY

- Provider ID: `edsy`
- Role: ship-build / reference data
- Auth: none
- Intended use:
  - vendored static data only
  - no runtime dependency assumed

### EDDB

- Status: deprecated / unavailable
- Rule: must not be used by Watchkeeper

## Capability Categories

### A. Galaxy / system topology

Providers:

- `spansh`
- `edsm`

Policy:

1. Look up local DB by `system_address`.
2. If missing or stale, fetch.
3. Prefer `spansh`; fallback to `edsm`.
4. Normalize and persist.

### B. Market / commodities / outfitting

Not part of this provider slice.

Rule:

- on-demand only
- no auto-fetch
- requires a separate design for EDDN ingestion/publishing

### C. Commander-linked / write-ish

Providers:

- `inara`
- optional `edsm` commander-linked features

Policy:

- disabled by default
- explicit config required
- strict rate caps
- never auto-enabled by the LLM

### D. Ship builds / reference

Provider:

- `edsy`

Policy:

- static or vendored data only
- on-demand use

## Health Model

All provider health status is normalized into one shape:

- `provider`
- `status`
- `checked_at`
- `latency_ms`
- `http.code`
- `rate_limit.state`
- `capabilities.tool_calls_allowed`
- `message`

Health status enum:

- `ok`
- `degraded`
- `throttled`
- `down`
- `misconfigured`

Important distinction:

- health answers "can this provider answer requests?"
- capability answers "should Brainstem permit this tool path right now?"

Those are related, but not interchangeable.

## Local World Model

The first persistence slice stores normalized topology data locally.

Tables:

- `ed_systems`
- `ed_bodies`
- `ed_stations`
- `provider_health`
- `provider_cache`

Canonical identity rule:

- prefer `system_address` wherever available
- treat `system_name` as descriptive, not primary

Provenance must always be stored:

- provider/source
- fetched timestamp
- expiry timestamp

## TTL Defaults

- system topology: `86400s`
- bodies/stations: `86400s`
- stale-if-error window: `604800s`

Operational rule:

- stale data may be served when the provider is down or throttled
- stale-serving must be surfaced in tool responses

## Tool Policy Boundary

Read-only operations:

- may be auto-allowed within budgets
- require provider health `ok` or `degraded`

Write-ish operations:

- deny by default
- opt-in only
- require explicit config and confirmation path

Standard deny reasons:

- `provider_down`
- `misconfigured`
- `rate_limited`
- `no_intent`
- `write_requires_confirm`
- `call_budget_exceeded`

## Implementation Order

1. Contracts and scaffolding
2. Normalized health pipeline
3. DB world model
4. Spansh adapter
5. EDSM adapter
6. System-change hook
7. Tool gateway and policy
8. Documentation/examples
9. Optional Inara adapter
10. Cache metrics/improvements

## Files Introduced By This Scaffold

- `config/providers.json`
- `contracts/v1/provider_config.schema.json`
- `contracts/v1/provider_health.schema.json`
- `contracts/v1/ed_provider_query.schema.json`
- `contracts/v1/ed_provider_response.schema.json`
- `core/ed_provider_types.py`
- `services/brainstem/provider_config.py`

This is deliberately the minimum useful slice: stable contracts first, adapter code second.
