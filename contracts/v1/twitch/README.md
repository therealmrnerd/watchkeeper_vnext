# Twitch Contracts (v1)

Contract namespace for Twitch-related Brainstem endpoints used by API clients and UI.

Endpoints covered:

- `GET /twitch/recent`
- `GET /twitch/user/{user_id}`
- `GET /twitch/user/{user_id}/redeems/top`
- `POST /twitch/send_chat`

Schemas in this folder intentionally mirror the top-level `contracts/v1/twitch_*`
files so clients can consume either naming style during transition.
