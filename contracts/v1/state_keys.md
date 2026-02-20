# State Key Conventions (v1)

State keys in `/state` ingestion must follow:

- Pattern: `^[a-z0-9]+(\.[a-z0-9_]+)+$`
- Prefix allow-list:
- `ed.*` for Elite Dangerous runtime and telemetry
- `music.*` for now playing/player state
- `hw.*` for hardware/system stats
- `policy.*` for standing orders, watch condition, and safety state
- `ai.*` for assistant/router health and mode state

Note: runtime-managed keys may exist outside `/state` ingestion validation.
Example: `app.sammi.running` is written by internal services and used as a
Twitch UDP ingest gate.

Examples:

- `ed.running`
- `ed.ship.system_name`
- `music.now_playing`
- `hw.cpu.logical_cores`
- `policy.watch_condition`
- `ai.router.health`

Invalid examples:

- `System.CPU` (upper-case)
- `system.cpu` (prefix not allowed)
- `ed` (no dotted path)
- `ed..running` (invalid format)
- `music-now_playing` (invalid separator)
