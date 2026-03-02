import re
from typing import Any

from core.ed_provider_types import ProviderId, ProviderOperationId
from runtime import (
    ACTION_ALLOWED_KEYS,
    ASSIST_REQUEST_ALLOWED_KEYS,
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
    WATCH_CONDITION_SET,
    parse_iso8601_utc,
)
from settings_store import validate_runtime_settings_update

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
    if tool_name is not None and (not isinstance(tool_name, str) or not tool_name.strip()):
        raise ValueError("tool_name must be a non-empty string when supplied")

    user_confirm_token = payload.get("user_confirm_token")
    if user_confirm_token is not None and (
        not isinstance(user_confirm_token, str) or not user_confirm_token.strip()
    ):
        raise ValueError("user_confirm_token must be a non-empty string when supplied")

    confirm_token = payload.get("confirm_token")
    if confirm_token is not None and (
        not isinstance(confirm_token, str) or not confirm_token.strip()
    ):
        raise ValueError("confirm_token must be a non-empty string when supplied")

    has_tool = isinstance(tool_name, str) and bool(tool_name.strip())
    has_user_token = isinstance(user_confirm_token, str) and bool(user_confirm_token.strip())
    has_confirm_token = isinstance(confirm_token, str) and bool(confirm_token.strip())
    has_token = has_user_token or has_confirm_token
    if not has_tool and not has_token:
        raise ValueError("confirm requires tool_name or confirm_token/user_confirm_token")

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


def validate_intent_proposal(proposal: dict[str, Any]) -> None:
    validate_intent(proposal)


def validate_assist_request(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    _check_extra_keys(payload, ASSIST_REQUEST_ALLOWED_KEYS, "assist_request")

    required = ["schema_version", "request_id", "timestamp_utc", "mode", "user_text"]
    for key in required:
        if key not in payload:
            raise ValueError(f"missing required field: {key}")

    if payload["schema_version"] != "1.0":
        raise ValueError("schema_version must be '1.0'")

    if not isinstance(payload["request_id"], str) or not payload["request_id"].strip():
        raise ValueError("request_id must be a non-empty string")

    parse_iso8601_utc(payload["timestamp_utc"])

    mode = payload["mode"]
    if mode not in MODE_SET:
        raise ValueError(f"mode must be one of: {', '.join(sorted(MODE_SET))}")

    domain = payload.get("domain")
    if domain is not None and domain not in DOMAIN_SET:
        raise ValueError(f"domain must be one of: {', '.join(sorted(DOMAIN_SET))}")

    urgency = payload.get("urgency")
    if urgency is not None and urgency not in URGENCY_SET:
        raise ValueError(f"urgency must be one of: {', '.join(sorted(URGENCY_SET))}")

    watch_condition = payload.get("watch_condition")
    if watch_condition is not None:
        if not isinstance(watch_condition, str) or not watch_condition.strip():
            raise ValueError("watch_condition must be non-empty string when supplied")
        if watch_condition.strip().upper() not in WATCH_CONDITION_SET:
            raise ValueError(
                "watch_condition must be one of: " + ", ".join(sorted(WATCH_CONDITION_SET))
            )

    incident_id = payload.get("incident_id")
    if incident_id is not None and (not isinstance(incident_id, str) or not incident_id.strip()):
        raise ValueError("incident_id must be a non-empty string when supplied")

    if not isinstance(payload["user_text"], str) or not payload["user_text"].strip():
        raise ValueError("user_text must be a non-empty string")

    stt_confidence = payload.get("stt_confidence")
    if stt_confidence is not None and (
        not isinstance(stt_confidence, (int, float)) or stt_confidence < 0 or stt_confidence > 1
    ):
        raise ValueError("stt_confidence must be number 0..1 when supplied")

    foreground_process = payload.get("foreground_process")
    if foreground_process is not None and (
        not isinstance(foreground_process, str) or not foreground_process.strip()
    ):
        raise ValueError("foreground_process must be non-empty string when supplied")

    max_actions = payload.get("max_actions")
    if max_actions is not None:
        if not isinstance(max_actions, int) or max_actions < 0 or max_actions > MAX_ACTIONS:
            raise ValueError(f"max_actions must be integer 0..{MAX_ACTIONS}")

    context = payload.get("context")
    if context is not None and not isinstance(context, dict):
        raise ValueError("context must be an object when supplied")


def validate_provider_query(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")

    required = {"tool", "provider", "operation", "params", "requirements", "trace"}
    extra = sorted(set(payload.keys()) - required)
    if extra:
        raise ValueError(f"provider_query contains unsupported fields: {', '.join(extra)}")
    missing = sorted(required - set(payload.keys()))
    if missing:
        raise ValueError(f"provider_query missing required fields: {', '.join(missing)}")

    if payload.get("tool") != "ed.provider_query":
        raise ValueError("provider_query.tool must be 'ed.provider_query'")

    try:
        ProviderId(str(payload.get("provider") or "").strip().lower())
    except Exception as exc:
        raise ValueError("provider_query.provider is unsupported") from exc

    try:
        ProviderOperationId(str(payload.get("operation") or "").strip().lower())
    except Exception as exc:
        raise ValueError("provider_query.operation is unsupported") from exc

    params = payload.get("params")
    if not isinstance(params, dict):
        raise ValueError("provider_query.params must be an object")

    requirements = payload.get("requirements")
    if not isinstance(requirements, dict):
        raise ValueError("provider_query.requirements must be an object")
    if "max_age_s" not in requirements or "allow_stale_if_error" not in requirements:
        raise ValueError("provider_query.requirements must include max_age_s and allow_stale_if_error")
    if not isinstance(requirements.get("max_age_s"), int) or int(requirements.get("max_age_s")) < 0:
        raise ValueError("provider_query.requirements.max_age_s must be an integer >= 0")
    if not isinstance(requirements.get("allow_stale_if_error"), bool):
        raise ValueError("provider_query.requirements.allow_stale_if_error must be boolean")

    trace = payload.get("trace")
    if not isinstance(trace, dict):
        raise ValueError("provider_query.trace must be an object")
    if not isinstance(trace.get("reason"), str) or not str(trace.get("reason")).strip():
        raise ValueError("provider_query.trace.reason must be a non-empty string")
    incident_id = trace.get("incident_id")
    if incident_id is not None and (not isinstance(incident_id, str) or not incident_id.strip()):
        raise ValueError("provider_query.trace.incident_id must be a non-empty string when supplied")


def validate_inara_credentials_update(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    allowed = {"commander_name", "frontier_id", "api_key", "clear"}
    _check_extra_keys(payload, allowed, "inara_credentials")
    if not payload:
        raise ValueError("inara_credentials body must not be empty")

    clear = payload.get("clear")
    if clear is not None and not isinstance(clear, bool):
        raise ValueError("clear must be boolean when supplied")
    if clear is True:
        return

    commander_name = payload.get("commander_name")
    if commander_name is not None and not isinstance(commander_name, str):
        raise ValueError("commander_name must be a string when supplied")

    frontier_id = payload.get("frontier_id")
    if frontier_id is not None and not isinstance(frontier_id, (str, int)):
        raise ValueError("frontier_id must be a string or integer when supplied")

    api_key = payload.get("api_key")
    if api_key is not None and not isinstance(api_key, str):
        raise ValueError("api_key must be a string when supplied")


def validate_openai_credentials_update(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    allowed = {"api_key", "clear"}
    _check_extra_keys(payload, allowed, "openai_credentials")
    clear = payload.get("clear")
    if clear is not None and not isinstance(clear, bool):
        raise ValueError("clear must be boolean when supplied")
    if clear is True:
        return
    if "api_key" not in payload:
        raise ValueError("openai_credentials.api_key is required")
    api_key = payload.get("api_key")
    if api_key is not None and not isinstance(api_key, str):
        raise ValueError("api_key must be a string when supplied")


def validate_runtime_settings_payload(payload: dict[str, Any]) -> None:
    validate_runtime_settings_update(payload)


def validate_llm_control_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    action = payload.get("action")
    if not isinstance(action, str) or action.strip().lower() not in {"engage", "disengage"}:
        raise ValueError("action must be 'engage' or 'disengage'")
