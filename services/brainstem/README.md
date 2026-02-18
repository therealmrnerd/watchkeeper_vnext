# Brainstem Service

Deterministic core runtime. No LLM dependency for baseline operation.

## Initial Responsibilities

- Process supervision (ED/music lifecycle hooks).
- Capability checks and mode gating.
- State updates and event emission.
- Action approval and execution orchestration.

## Required Endpoints

- `GET /state`
- `GET /events`
- `POST /intent`
- `POST /execute`
