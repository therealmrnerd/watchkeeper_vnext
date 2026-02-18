# AI Service

LLM orchestration layer that proposes actions but does not execute them.

## Initial Responsibilities

- Route request by mode/domain/urgency.
- Produce `IntentEnvelope` conforming to `contracts/v1/intent.schema.json`.
- Attach candidate `ProposedAction[]`.
- Consume core execution results and narrate outcomes.
