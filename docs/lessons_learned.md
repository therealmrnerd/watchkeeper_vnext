# Lessons Learned from Prototype

## What Worked

- Local model on Intel GPU is viable with selective fast paths.
- Process-gated loops reduce unnecessary collectors:
  - If ED not running, parser should be stopped.
  - If music not playing, now-playing poller should be paused.
- SQLite is enough for local-first state and audit history.

## Pain Points

- Multiple APIs with overlapping responsibility.
- Unclear ownership for unsafe tool execution.
- Inconsistent data contracts between components.
- Limited traceability from user request to actual action outcome.

## vNext Design Responses

- Introduce one canonical state store and append-only event log.
- Use strict typed contracts for `intent`, `action`, `tool result`, and `event`.
- Make Brainstem the only executor for unsafe actions.
- Store user `+/-` feedback tied to request/action records for policy tuning.
