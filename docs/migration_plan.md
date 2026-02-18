# vNext Migration Plan

## Phase 0: Freeze and Observe

- Tag prototype.
- Capture real sessions as event traces.
- Define baseline performance and reliability targets.

## Phase 1: Brainstem Foundation

- Implement state store + event log on this schema.
- Add deterministic process supervision for ED/music.
- Expose `/state`, `/events`, `/intent`, `/execute`.

## Phase 2: AI Contract Enforcement

- AI emits only `IntentEnvelope` + `ProposedAction[]`.
- Core approves/denies actions by mode, capability, and safety.
- Log every transition in `event_log` and `action_log`.

## Phase 3: Knowledge and Feedback Loop

- Keep factual triples in SQLite.
- Add vector retrieval service for lore and long-form context.
- Use feedback dataset to tune routing and tool policy.

## Phase 4: Speech Hardening

- Wake-word gating and barge-in behavior.
- STT confidence thresholds and clarification flow.
- STT bias lexicon + context-aware rescoring.

## Phase 5: Language Migration

- Move high-value core services first (Go recommended).
- Migrate hot loops/perf hotspots later (Rust if needed).
- Preserve contracts to keep rewrites low-risk.
