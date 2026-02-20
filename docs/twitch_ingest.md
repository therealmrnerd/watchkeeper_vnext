# Twitch Ingest (SAMMI Doorbell)

Watchkeeper ingests Twitch activity through SAMMI in two steps:

1. SAMMI writes the event payload variables.
2. SAMMI sends one UDP doorbell token using canonical format:
   - `category|timestamp`

Legacy third field (`|seq`) is still accepted but not required.

## Core Invariant

`no SAMMI -> no UDP bind -> no ingest reads`

If `app.sammi.running` is false, Brainstem keeps the Twitch UDP listener unbound.
No doorbell packet can be consumed and no SAMMI variable reads are attempted.

## Doorbell Category Codes (100-series)

Canonical numeric categories:

- `101` = `CHAT`
- `102` = `REDEEM`
- `103` = `BITS`
- `104` = `FOLLOW`
- `105` = `SUB`
- `106` = `RAID`
- `107` = `HYPE_TRAIN`
- `108` = `POLL`
- `109` = `PREDICTION`
- `110` = `SHOUTOUT`
- `111` = `POWER_UPS`
- `112` = `HYPE`

Packed numeric token format is supported:

- `CCC<timestamp>` (example: `101193735314` for CHAT)

Why we chose 100-codes:

- SAMMI string buffer modes were unstable in some flows and could crash under mixed
  text payload usage.
- Numeric category prefix is deterministic and parse-safe.
- It keeps one packet format for all event types while preserving category + commit
  marker in a single atomic token.

## Commit Marker Rule

For variable-based commit markers, use:

- `wk.<category>.ts`

and write that marker variable last in SAMMI.

Current deployments typically use the packet timestamp as the commit marker.
If both packet timestamp and marker variable are present, Watchkeeper prefers the
 marker variable where configured for that category.

## UDP Listener Config

- `WKV_TWITCH_UDP_ENABLED` (default `1`)
- `WKV_TWITCH_UDP_HOST` (default `127.0.0.1`)
- `WKV_TWITCH_UDP_PORT` (default `9765`)
- `WKV_TWITCH_UDP_ACK_ONLY` (default `0`)

## Debounce Config (Per Category)

- `WKV_TWITCH_CHAT_DEBOUNCE_MS` (default `250`)
- `WKV_TWITCH_REDEEM_DEBOUNCE_MS` (default `0`)
- `WKV_TWITCH_BITS_DEBOUNCE_MS` (default `0`)
- `WKV_TWITCH_FOLLOW_DEBOUNCE_MS` (default `0`)
- `WKV_TWITCH_SUB_DEBOUNCE_MS` (default `0`)
- `WKV_TWITCH_RAID_DEBOUNCE_MS` (default `0`)
- `WKV_TWITCH_HYPE_TRAIN_DEBOUNCE_MS` (default `0`)
- `WKV_TWITCH_POLL_DEBOUNCE_MS` (default `0`)
- `WKV_TWITCH_PREDICTION_DEBOUNCE_MS` (default `0`)
- `WKV_TWITCH_SHOUTOUT_DEBOUNCE_MS` (default `0`)
- `WKV_TWITCH_POWER_UPS_DEBOUNCE_MS` (default `0`)
- `WKV_TWITCH_HYPE_DEBOUNCE_MS` (default `0`)

## Variable Index

SAMMI variable names are configured in:

- `config/sammi_variable_index.json`

Runtime override:

- `WKV_TWITCH_VARIABLE_INDEX_PATH`

## Dedupe Rules

- Ignore events with commit marker `<=` stored cursor for that event type.
- Cursor update is atomic (`twitch_event_cursor`).
- Duplicate UDP packets do not duplicate DB updates.

## Quick Manual Verification

- Set `app.sammi.running=false` and confirm UDP port is not bound.
- Set `app.sammi.running=true` and confirm bind occurs once.
- Set `app.sammi.running=false` again and confirm socket closes cleanly.
- Send UDP while false and confirm no ingest event/read occurs.

## API Surface

Dev endpoint (enable with `WKV_TWITCH_DEV_INGEST_ENABLED=1`):

- `POST /twitch/dev/ingest_mock`

Read APIs:

- `GET /twitch/user/{user_id}`
- `GET /twitch/user/{user_id}/redeems/top?limit=5`
- `GET /twitch/recent?limit=50`

Write API:

- `POST /twitch/send_chat`
  - Strict confirm (`WKV_TWITCH_CHAT_STRICT_CONFIRM=1`) is supported via
    `/confirm` then replay with `incident_id + confirm_token`.
