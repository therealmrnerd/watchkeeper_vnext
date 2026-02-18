import re
from typing import Any

from runtime import (
    ACTION_ALLOWED_KEYS,
    CONFIRM_ALLOWED_KEYS,
    DOMAIN_SET,
    FEEDBACK_ALLOWED_KEYS,
    INTENT_ALLOWED_KEYS,
    MAX_ACTIONS,
    MODE_SET,
    SAFETY_SET,
    STATE_INGEST_ALLOWED_KEYS,
    STATE_ITEM_ALLOWED_KEYS,
    URGENCY_SET,
    parse_iso8601_utc,
)

STATE_KEY_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9_]+)+$")
STATE_KEY_PREFIXES = ("ed.", "music.", "hw.", "policy.", "ai.")


def _check_extra_keys(obj: dict[str, Any], allowed: set[str], obj_name: str) -> None:
    extra = sorted(set(obj.keys()) - allowed)
    if extra:
        raise ValueError(f"{obj_name} contains unsupported fields: {', '.join(extra)}")


def validate_action(action: dict[str, Any], index: int) -> None:
    if not isinstance(action, dict):
        raise ValueError(f"proposed_actions[{index}] must be an object")
    _check_extra_keys(action, ACTION_ALLOWED_KEYS, f"proposed_actions[{index}]")

    required = ["action_id", "tool_name", "parameters", "safety_level", "timeout_ms", "confidence"]
    for key in required:
        if key not in action:
            raise ValueError(f"proposed_actions[{index}] missing required field: {key}")

    if not isinstance(action["action_id"], str) or not action["action_id"]:
        raise ValueError(f"proposed_actions[{index}].action_id must be a non-empty string")
    if not isinstance(action["tool_name"], str) or not action["tool_name"]:
        raise ValueError(f"proposed_actions[{index}].tool_name must be a non-empty string")
    if not isinstance(action["parameters"], dict):
        raise ValueError(f"proposed_actions[{index}].parameters must be an object")

    safety_level = action["safety_level"]
    if safety_level not in SAFETY_SET:
        raise ValueError(
            f"proposed_actions[{index}].safety_level must be one of: {', '.join(sorted(SAFETY_SET))}"
        )

    timeout_ms = action["timeout_ms"]
    if not isinstance(timeout_ms, int) or timeout_ms < 100 or timeout_ms > 120000:
        raise ValueError(f"proposed_actions[{index}].timeout_ms must be integer 100..120000")

    confidence = action["confidence"]
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
        raise ValueError(f"proposed_actions[{index}].confidence must be number 0..1")

    mode_constraints = action.get("mode_constraints")
    if mode_constraints is not None:
        if not isinstance(mode_constraints, list):
            raise ValueError(f"proposed_actions[{index}].mode_constraints must be a list")
        for mode in mode_constraints:
            if mode not in MODE_SET:
                raise ValueError(
                    f"proposed_actions[{index}].mode_constraints contains unsupported mode: {mode}"
                )

    requires_confirmation = action.get("requires_confirmation")
    if requires_confirmation is not None and not isinstance(requires_confirmation, bool):
        raise ValueError(f"proposed_actions[{index}].requires_confirmation must be boolean")


def validate_intent(intent: dict[str, Any]) -> None:
    if not isinstance(intent, dict):
        raise ValueError("body must be a JSON object")

    _check_extra_keys(intent, INTENT_ALLOWED_KEYS, "intent")

    required = [
        "schema_version",
        "request_id",
        "timestamp_utc",
        "mode",
        "domain",
        "urgency",
        "user_text",
        "needs_tools",
        "needs_clarification",
        "proposed_actions",
        "response_text",
    ]
    for key in required:
        if key not in intent:
            raise ValueError(f"missing required field: {key}")

    if intent["schema_version"] != "1.0":
        raise ValueError("schema_version must be '1.0'")
    if not isinstance(intent["request_id"], str) or not intent["request_id"]:
        raise ValueError("request_id must be a non-empty string")

    parse_iso8601_utc(intent["timestamp_utc"])

    mode = intent["mode"]
    if mode not in MODE_SET:
        raise ValueError(f"mode must be one of: {', '.join(sorted(MODE_SET))}")

    domain = intent["domain"]
    if domain not in DOMAIN_SET:
        raise ValueError(f"domain must be one of: {', '.join(sorted(DOMAIN_SET))}")

    urgency = intent["urgency"]
    if urgency not in URGENCY_SET:
        raise ValueError(f"urgency must be one of: {', '.join(sorted(URGENCY_SET))}")

    if not isinstance(intent["user_text"], str) or not intent["user_text"].strip():
        raise ValueError("user_text must be a non-empty string")

    if not isinstance(intent["needs_tools"], bool):
        raise ValueError("needs_tools must be boolean")
    if not isinstance(intent["needs_clarification"], bool):
        raise ValueError("needs_clarification must be boolean")

    questions = intent.get("clarification_questions")
    if questions is not None:
        if not isinstance(questions, list):
            raise ValueError("clarification_questions must be an array")
        if len(questions) > 3:
            raise ValueError("clarification_questions must have at most 3 items")
        for idx, question in enumerate(questions):
            if not isinstance(question, str) or not question.strip():
                raise ValueError(f"clarification_questions[{idx}] must be a non-empty string")

    retrieval = intent.get("retrieval")
    if retrieval is not None and not isinstance(retrieval, dict):
        raise ValueError("retrieval must be an object")

    actions = intent["proposed_actions"]
    if not isinstance(actions, list):
        raise ValueError("proposed_actions must be an array")
    if len(actions) > MAX_ACTIONS:
        raise ValueError(f"proposed_actions must have at most {MAX_ACTIONS} items")
    for idx, action in enumerate(actions):
        validate_action(action, idx)

    if not isinstance(intent["response_text"], str):
        raise ValueError("response_text must be a string")


def validate_state_item(item: dict[str, Any], index: int) -> None:
    if not isinstance(item, dict):
        raise ValueError(f"items[{index}] must be an object")
    _check_extra_keys(item, STATE_ITEM_ALLOWED_KEYS, f"items[{index}]")

    if "state_key" not in item:
        raise ValueError(f"items[{index}] missing required field: state_key")
    if "state_value" not in item:
        raise ValueError(f"items[{index}] missing required field: state_value")
    if "source" not in item:
        raise ValueError(f"items[{index}] missing required field: source")

    state_key = item["state_key"]
    if not isinstance(state_key, str) or not state_key.strip():
        raise ValueError(f"items[{index}].state_key must be a non-empty string")
    if not STATE_KEY_RE.match(state_key):
        raise ValueError(
            f"items[{index}].state_key must match pattern: ^[a-z0-9]+(\\.[a-z0-9_]+)+$"
        )
    if not state_key.startswith(STATE_KEY_PREFIXES):
        raise ValueError(
            f"items[{index}].state_key must use one of prefixes: "
            + ", ".join(STATE_KEY_PREFIXES)
        )

    state_source = item["source"]
    if not isinstance(state_source, str) or not state_source.strip():
        raise ValueError(f"items[{index}].source must be a non-empty string")

    confidence = item.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
            raise ValueError(f"items[{index}].confidence must be number 0..1")

    observed_at = item.get("observed_at_utc")
    if observed_at is not None:
        parse_iso8601_utc(observed_at)


def validate_state_ingest(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    _check_extra_keys(payload, STATE_INGEST_ALLOWED_KEYS, "state_ingest")

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items is required and must be a non-empty array")

    for idx, item in enumerate(items):
        validate_state_item(item, idx)

    emit_events = payload.get("emit_events")
    if emit_events is not None and not isinstance(emit_events, bool):
        raise ValueError("emit_events must be boolean when supplied")

    profile = payload.get("profile")
    if profile is not None and (not isinstance(profile, str) or not profile.strip()):
        raise ValueError("profile must be a non-empty string when supplied")

    session_id = payload.get("session_id")
    if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
        raise ValueError("session_id must be a non-empty string when supplied")

    correlation_id = payload.get("correlation_id")
    if correlation_id is not None and (
        not isinstance(correlation_id, str) or not correlation_id.strip()
    ):
        raise ValueError("correlation_id must be a non-empty string when supplied")


def validate_feedback(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    _check_extra_keys(payload, FEEDBACK_ALLOWED_KEYS, "feedback")

    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id is required and must be a non-empty string")

    rating = payload.get("rating")
    if rating not in (-1, 1):
        raise ValueError("rating must be -1 or 1")

    correction_text = payload.get("correction_text")
    if correction_text is not None and not isinstance(correction_text, str):
        raise ValueError("correction_text must be a string when supplied")

    reviewer = payload.get("reviewer")
    if reviewer is not None and (not isinstance(reviewer, str) or not reviewer.strip()):
        raise ValueError("reviewer must be a non-empty string when supplied")

    session_id = payload.get("session_id")
    if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
        raise ValueError("session_id must be a non-empty string when supplied")

    mode = payload.get("mode")
    if mode is not None and mode not in MODE_SET:
        raise ValueError(f"mode must be one of: {', '.join(sorted(MODE_SET))}")


def validate_confirm(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    _check_extra_keys(payload, CONFIRM_ALLOWED_KEYS, "confirm")

    incident_id = payload.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id.strip():
        raise ValueError("incident_id is required and must be a non-empty string")

    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError("tool_name is required and must be a non-empty string")

    user_confirm_token = payload.get("user_confirm_token")
    if user_confirm_token is not None and (
        not isinstance(user_confirm_token, str) or not user_confirm_token.strip()
    ):
        raise ValueError("user_confirm_token must be a non-empty string when supplied")

    confirmed_at_utc = payload.get("confirmed_at_utc")
    if confirmed_at_utc is not None:
        if not isinstance(confirmed_at_utc, str) or not confirmed_at_utc.strip():
            raise ValueError("confirmed_at_utc must be a non-empty string when supplied")
        parse_iso8601_utc(confirmed_at_utc)

    request_id = payload.get("request_id")
    if request_id is not None and (not isinstance(request_id, str) or not request_id.strip()):
        raise ValueError("request_id must be a non-empty string when supplied")

    session_id = payload.get("session_id")
    if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
        raise ValueError("session_id must be a non-empty string when supplied")

    mode = payload.get("mode")
    if mode is not None and mode not in MODE_SET:
        raise ValueError(f"mode must be one of: {', '.join(sorted(MODE_SET))}")
