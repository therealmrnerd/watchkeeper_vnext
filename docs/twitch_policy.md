# Twitch Policy (v1)

This policy governs Twitch chat/redeem behavior ingested via SAMMI and executed by Watchkeeper.

## Do
- Personalize responses using observed channel activity only:
  - VIP/mod/sub flags
  - redeem history
  - bits history
- Use short-lived context:
  - last 5 messages per user
  - aggregate counters for trends

## Ask
- Ask for confirmation before disruptive/costly actions:
  - chat announcements
  - mass/multi-user replies
  - external redeem triggers
- Ask before offering "usual redeem" prompts (and apply cooldown).

## Don't
- Do not store full chat logs.
- Do not infer sensitive traits (health, politics, religion, ethnicity, etc.).
- Do not spam "usual?" prompts.

## Policy Engine Contract
`core/policy/twitch_policy.py` exposes:

- `evaluate(context, proposed_action) -> { decision, reason, suggested_question }`
- Decisions:
  - `allow`
  - `ask`
  - `deny`

## Minimum Context Expected
- `chat_storm` boolean
- `auto_replies_last_min` integer
- `usual_prompt_age_sec` integer

## Example Proposed Action
```json
{
  "type": "chat.usual_prompt",
  "user_id": "1234",
  "text": "Usual redeem?"
}
```
