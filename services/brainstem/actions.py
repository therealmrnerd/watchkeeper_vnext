import ctypes
import json
import os
import runtime
import sqlite3
import subprocess
import time
import uuid
from ctypes import windll
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import quote

from runtime import (
    ADVISORY_ENABLED,
    ADVISORY_TIMEOUT_SEC,
    ADVISORY_URL,
    DB_PATH,
    DB_SERVICE,
    DEFAULT_WATCH_CONDITION,
    ED_PROVIDER_QUERY_SERVICE,
    EDPARSER_TOOL,
    ENABLE_ACTUATORS,
    ENABLE_KEYPRESS,
    KEYPRESS_ALLOWED_PROCESSES,
    KEYEVENTF_KEYUP,
    LIGHTS_WEBHOOK_TIMEOUT_SEC,
    LIGHTS_WEBHOOK_URL,
    LIGHTS_WEBHOOK_URL_TEMPLATE,
    LOGBOOK,
    PROVIDER_CONFIG_PATH,
    PROVIDER_HEALTH_ENABLED,
    PROVIDER_SECRETS_PATH,
    SAMMI_CLIENT,
    SPECIAL_VK_MAP,
    TOOL_ROUTER,
    TWITCH_DEV_INGEST_ENABLED,
    TWITCH_CHAT_SEND_BUTTON,
    TWITCH_CHAT_STRICT_CONFIRM,
    TWITCH_CHAT_SEND_VAR,
    TWITCH_INGEST_SERVICE,
    TWITCH_REPO,
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    connect_db,
    iso8601_utc_to_epoch,
    parse_iso8601_utc,
    parse_json,
    utc_now_iso,
)
from core.ed_provider_types import ProviderId, ProviderOperationId, ProviderQuery
from provider_health import build_provider_health_probes
from provider_secrets import clear_provider_secret_entry, save_inara_secret_entry, save_openai_secret_entry
from settings_store import save_runtime_settings

NO_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _list_process_names() -> set[str]:
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=NO_WINDOW_FLAGS,
        )
        names: set[str] = set()
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith('"'):
                parts = [p.strip('"') for p in line.split('","')]
                if parts:
                    names.add(parts[0].lower())
        return names
    except Exception:
        return set()


def _any_process_running(process_names: list[str]) -> bool:
    if not process_names:
        return True
    running = _list_process_names()
    return any(name in running for name in process_names)


def _get_foreground_process_name() -> str | None:
    try:
        hwnd = windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_ulong(0)
        windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", f"PID eq {pid.value}"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=NO_WINDOW_FLAGS,
        )
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if line.startswith('"'):
                parts = [p.strip('"') for p in line.split('","')]
                if parts and parts[0]:
                    return parts[0]
        return None
    except Exception:
        return None


def _key_to_vk(key_name: str) -> int:
    key = key_name.strip().lower()
    if not key:
        raise ValueError("keypress key parameter is required")
    if key in SPECIAL_VK_MAP:
        return SPECIAL_VK_MAP[key]
    if len(key) == 1 and "a" <= key <= "z":
        return ord(key.upper())
    if len(key) == 1 and "0" <= key <= "9":
        return ord(key)
    raise ValueError(f"Unsupported keypress key: {key_name}")


def _send_virtual_key(vk_code: int) -> None:
    windll.user32.keybd_event(vk_code, 0, 0, 0)
    windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)


def _build_lights_url(scene: str) -> str:
    if LIGHTS_WEBHOOK_URL_TEMPLATE:
        return LIGHTS_WEBHOOK_URL_TEMPLATE.replace("{scene}", quote(scene))
    if LIGHTS_WEBHOOK_URL:
        return LIGHTS_WEBHOOK_URL
    raise ValueError("set_lights is not configured (set WKV_LIGHTS_WEBHOOK_URL[_TEMPLATE])")


def _execute_set_lights(parameters: dict[str, Any], request_id: str, action_id: str) -> dict[str, Any]:
    scene = str(parameters.get("scene", "default")).strip() or "default"
    url = _build_lights_url(scene)
    payload = {
        "scene": scene,
        "request_id": request_id,
        "action_id": action_id,
        "timestamp_utc": utc_now_iso(),
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=raw,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=LIGHTS_WEBHOOK_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"set_lights webhook HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"set_lights webhook request failed: {exc}") from exc
    return {
        "scene": scene,
        "webhook_url": url,
        "http_status": status,
        "response_body": body[:500],
    }


def _execute_music(tool_name: str) -> dict[str, Any]:
    if tool_name == "music_next":
        vk_code = VK_MEDIA_NEXT_TRACK
        vk_name = "VK_MEDIA_NEXT_TRACK"
    elif tool_name in {"music_pause", "music_resume"}:
        vk_code = VK_MEDIA_PLAY_PAUSE
        vk_name = "VK_MEDIA_PLAY_PAUSE"
    else:
        raise ValueError(f"Unsupported music tool: {tool_name}")
    _send_virtual_key(vk_code)
    return {"virtual_key": vk_name, "vk_code": vk_code}


def _execute_keypress(parameters: dict[str, Any]) -> dict[str, Any]:
    if not ENABLE_KEYPRESS:
        raise ValueError("keypress actuator is disabled (set WKV_ENABLE_KEYPRESS=1)")
    if not _any_process_running(KEYPRESS_ALLOWED_PROCESSES):
        raise ValueError("keypress denied: no allowed process is currently running")
    key_name = str(parameters.get("key", "")).strip()
    vk_code = _key_to_vk(key_name)
    _send_virtual_key(vk_code)
    return {"key": key_name, "vk_code": vk_code}


def _execute_edparser(tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
    canonical = tool_name.strip().lower()
    reason = str(parameters.get("reason", "execute_tool")).strip() or "execute_tool"
    force = bool(parameters.get("force", False))
    force_restart = bool(parameters.get("force_restart", False))

    if canonical in {"edparser", "edparser.start", "edparser_start"}:
        return EDPARSER_TOOL.start(reason=reason, force_restart=force_restart)
    if canonical in {"edparser.stop", "edparser_stop"}:
        return EDPARSER_TOOL.stop(reason=reason, force=force)
    if canonical in {"edparser.status", "edparser_status"}:
        return EDPARSER_TOOL.status() | {"ok": True, "reason": reason}
    raise ValueError(f"Unsupported edparser tool: {tool_name}")


def _normalize_jinx_effect(effect: Any) -> str:
    text = str(effect or "").strip().upper()
    if not text:
        raise ValueError("jinx effect is required")
    if text.startswith("S") or text.startswith("C"):
        if len(text) <= 1 or not text[1:].isdigit():
            raise ValueError(f"Invalid jinx effect: {text}")
        return f"{text[0]}{int(text[1:])}"
    if text.isdigit():
        return f"S{int(text)}"
    raise ValueError(f"Invalid jinx effect: {text}")


def _set_state_quick(state_key: str, state_value: Any) -> None:
    DB_SERVICE.set_state(
        state_key=state_key,
        state_value=state_value,
        source="brainstem_execute",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )


def _execute_jinx(tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
    canonical = tool_name.strip().lower()

    if canonical in {"jinx.set_effect", "jinx_set_effect", "jinx.effect"}:
        effect = _normalize_jinx_effect(parameters.get("effect") or parameters.get("mode"))
        _set_state_quick("jinx.effect", effect)
        _set_state_quick("jinx.scene", "")
        _set_state_quick("jinx.chase", "")
        return {"ok": True, "jinx.effect": effect}

    if canonical in {"jinx.set_scene", "jinx_set_scene", "jinx.scene"}:
        scene = str(parameters.get("scene", "")).strip()
        if not scene.isdigit():
            raise ValueError("jinx scene must be numeric")
        _set_state_quick("jinx.scene", int(scene))
        _set_state_quick("jinx.effect", "")
        _set_state_quick("jinx.chase", "")
        return {"ok": True, "jinx.scene": int(scene)}

    if canonical in {"jinx.set_chase", "jinx_set_chase", "jinx.chase"}:
        chase = str(parameters.get("chase", "")).strip()
        if not chase.isdigit():
            raise ValueError("jinx chase must be numeric")
        _set_state_quick("jinx.chase", int(chase))
        _set_state_quick("jinx.effect", "")
        _set_state_quick("jinx.scene", "")
        return {"ok": True, "jinx.chase": int(chase)}

    raise ValueError(f"Unsupported jinx tool: {tool_name}")


def execute_tool(
    *,
    tool_name: str,
    parameters: dict[str, Any],
    request_id: str,
    action_id: str,
    dry_run: bool,
) -> dict[str, Any]:
    if not ENABLE_ACTUATORS:
        return {
            "stub_execution": True,
            "dry_run": True,
            "tool_name": tool_name,
            "action_id": action_id,
            "parameters": parameters,
            "result": "Actuators disabled by configuration (WKV_ENABLE_ACTUATORS=0).",
        }

    if dry_run:
        return {
            "stub_execution": True,
            "dry_run": True,
            "tool_name": tool_name,
            "action_id": action_id,
            "parameters": parameters,
            "result": "Dry run only. No actuator call executed.",
        }

    if tool_name == "set_lights":
        output = _execute_set_lights(parameters, request_id=request_id, action_id=action_id)
    elif tool_name in {"music_next", "music_pause", "music_resume"}:
        output = _execute_music(tool_name)
    elif tool_name == "keypress":
        output = _execute_keypress(parameters)
    elif tool_name.startswith("edparser") or tool_name in {
        "edparser_start",
        "edparser_stop",
        "edparser_status",
    }:
        output = _execute_edparser(tool_name, parameters)
    elif tool_name.startswith("jinx"):
        output = _execute_jinx(tool_name, parameters)
    else:
        raise ValueError(f"Unsupported tool: {tool_name}")

    return {
        "stub_execution": False,
        "dry_run": False,
        "tool_name": tool_name,
        "action_id": action_id,
        "parameters": parameters,
        "result": "Actuator executed.",
        "details": output,
    }


def _mode_to_watch_condition(intent_mode: str) -> str:
    mapping = {
        "standby": "STANDBY",
        "game": "GAME",
        "work": "WORK",
        "tutor": "TUTOR",
    }
    return mapping.get(intent_mode.lower(), DEFAULT_WATCH_CONDITION)


def _resolve_watch_condition(requested: str | None, intent_mode: str) -> str:
    if requested:
        return requested.strip().upper()
    state = DB_SERVICE.get_state("policy.watch_condition") or DB_SERVICE.get_state(
        "system.watch_condition"
    )
    if state and isinstance(state.get("state_value"), str):
        return str(state["state_value"]).strip().upper()
    return _mode_to_watch_condition(intent_mode)


def emit_event(
    con: sqlite3.Connection | None,
    event_type: str,
    source: str,
    payload: dict[str, Any],
    profile: str | None = None,
    session_id: str | None = None,
    correlation_id: str | None = None,
    mode: str | None = None,
    severity: str = "info",
    tags: list[str] | None = None,
) -> str:
    event_id = str(uuid.uuid4())
    if con is not None:
        con.execute(
            """
            INSERT INTO event_log(
                event_id,timestamp_utc,event_type,source,profile,session_id,correlation_id,
                mode,severity,payload_json,tags_json
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                utc_now_iso(),
                event_type,
                source,
                profile,
                session_id,
                correlation_id,
                mode,
                severity,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(tags or [], ensure_ascii=False),
            ),
        )
    else:
        DB_SERVICE.append_event(
            event_id=event_id,
            timestamp_utc=utc_now_iso(),
            event_type=event_type,
            source=source,
            payload=payload,
            profile=profile,
            session_id=session_id,
            correlation_id=correlation_id,
            mode=mode,
            severity=severity,
            tags=tags or [],
        )
    return event_id


def upsert_intent(con: sqlite3.Connection, intent: dict[str, Any], source: str) -> int:
    questions = intent.get("clarification_questions", [])
    retrieval = intent.get("retrieval", {})
    actions = intent["proposed_actions"]

    con.execute(
        """
        INSERT OR REPLACE INTO intent_log(
            request_id,schema_version,timestamp_utc,session_id,mode,domain,urgency,user_text,
            needs_tools,needs_clarification,clarification_questions_json,retrieval_json,
            proposed_actions_json,response_text
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            intent["request_id"],
            intent["schema_version"],
            intent["timestamp_utc"],
            intent.get("session_id"),
            intent["mode"],
            intent["domain"],
            intent["urgency"],
            intent["user_text"],
            1 if intent["needs_tools"] else 0,
            1 if intent["needs_clarification"] else 0,
            json.dumps(questions, ensure_ascii=False),
            json.dumps(retrieval, ensure_ascii=False),
            json.dumps(actions, ensure_ascii=False),
            intent.get("response_text", ""),
        ),
    )

    count = 0
    for action in actions:
        params_for_log = {
            "parameters": action.get("parameters", {}),
            "mode_constraints": action.get("mode_constraints", []),
            "requires_confirmation": action.get("requires_confirmation", False),
            "timeout_ms": action.get("timeout_ms"),
            "confidence": action.get("confidence"),
        }
        con.execute(
            """
            INSERT OR REPLACE INTO action_log(
                request_id,action_id,tool_name,status,safety_level,mode_at_execution,reason,parameters_json
            )
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                intent["request_id"],
                action["action_id"],
                action["tool_name"],
                "queued",
                action["safety_level"],
                intent["mode"],
                action.get("reason"),
                json.dumps(params_for_log, ensure_ascii=False),
            ),
        )
        count += 1

    emit_event(
        con,
        event_type="INTENT_PROPOSED",
        source=source,
        payload={
            "request_id": intent["request_id"],
            "actions": [a["action_id"] for a in actions],
            "domain": intent["domain"],
            "urgency": intent["urgency"],
        },
        session_id=intent.get("session_id"),
        correlation_id=intent["request_id"],
        mode=intent["mode"],
    )

    return count


def ingest_state(payload: dict[str, Any], source: str) -> dict[str, Any]:
    items = payload["items"]
    emit_events = payload.get("emit_events", True)
    profile = payload.get("profile")
    session_id = payload.get("session_id")
    correlation_id = payload.get("correlation_id")
    prepared_items = []
    for item in items:
        state_key = item["state_key"].strip()
        state_value = item["state_value"]
        state_source = item["source"].strip()
        confidence = item.get("confidence")
        observed_at_utc = item.get("observed_at_utc") or utc_now_iso()

        prepared_items.append(
            {
                "state_key": state_key,
                "state_value": state_value,
                "source": state_source,
                "confidence": confidence,
                "observed_at_utc": observed_at_utc,
                "updated_at_utc": utc_now_iso(),
                "event_id": str(uuid.uuid4()),
                "event_type": "STATE_UPDATED",
                "event_source": source,
                "profile": profile,
                "session_id": session_id,
                "correlation_id": correlation_id,
                "event_payload": {
                    "state_key": state_key,
                    "source": state_source,
                    "confidence": confidence,
                    "observed_at_utc": observed_at_utc,
                },
            }
        )

    result = DB_SERVICE.batch_set_state(
        items=prepared_items,
        emit_events=emit_events,
    )
    return {
        "upserted": result["upserted"],
        "changed": result["changed"],
        "state_keys": [item["state_key"] for item in prepared_items],
    }


def record_feedback(payload: dict[str, Any], source: str) -> dict[str, Any]:
    request_id = payload["request_id"].strip()
    rating = payload["rating"]
    correction_text = payload.get("correction_text")
    reviewer = (payload.get("reviewer") or "user").strip()
    session_id = payload.get("session_id")
    mode = payload.get("mode")

    with connect_db() as con:
        intent = con.execute(
            "SELECT request_id,session_id,mode FROM intent_log WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if not intent:
            raise ValueError(f"request_id not found: {request_id}")

        effective_session = session_id or intent["session_id"]
        effective_mode = mode or intent["mode"]

        cur = con.execute(
            """
            INSERT INTO feedback_log(request_id,rating,correction_text,reviewer)
            VALUES(?,?,?,?)
            """,
            (request_id, rating, correction_text, reviewer),
        )
        feedback_id = cur.lastrowid

        emit_event(
            con,
            event_type="USER_FEEDBACK",
            source=source,
            payload={
                "request_id": request_id,
                "feedback_id": feedback_id,
                "rating": rating,
                "has_correction": bool(correction_text),
                "reviewer": reviewer,
            },
            session_id=effective_session,
            correlation_id=request_id,
            mode=effective_mode,
        )
        con.commit()

    return {"feedback_id": feedback_id, "request_id": request_id, "rating": rating}


def ingest_twitch_mock(payload: dict[str, Any], source: str) -> dict[str, Any]:
    if not TWITCH_DEV_INGEST_ENABLED:
        raise ValueError("twitch dev ingest endpoint is disabled")
    event_type = str(payload.get("event_type") or "").strip().upper()
    if not event_type:
        raise ValueError("event_type is required")
    event_payload = payload.get("payload")
    if not isinstance(event_payload, dict):
        event_payload = dict(payload)
        event_payload.pop("event_type", None)
    result = TWITCH_INGEST_SERVICE.ingest_mock(event_type, event_payload)
    emit_event(
        con=None,
        event_type="TWITCH_DEV_INGEST",
        source=source,
        payload={
            "event_type": event_type,
            "processed": bool(result.get("processed")),
            "user_id": result.get("user_id"),
            "commit_ts": result.get("commit_ts"),
        },
        tags=["twitch", "dev", "ingest"],
    )
    return result


def _state_value_text(key: str) -> str:
    row = DB_SERVICE.get_state(str(key or "").strip())
    if not row:
        return ""
    value = row.get("state_value")
    return str(value or "").strip()


def _normalize_app_open_target(app_id: str, target: str) -> str:
    text = str(target or "").strip()
    if not text:
        return ""
    if app_id == "ytmd" and text.lower().startswith("ytmd_api://"):
        return "http://" + text.split("://", 1)[1]
    return text


def open_external_app(payload: dict[str, Any], source: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")

    app_id = str(payload.get("app_id") or "").strip().lower()
    if app_id not in {"elite", "jinx", "sammi", "ytmd"}:
        raise ValueError("app_id must be one of: elite, jinx, sammi, ytmd")

    target_map: dict[str, list[str]] = {
        "elite": ["app.ed.path", "app.elite.path", "app.ed_ahk.path"],
        "jinx": ["app.jinx.path"],
        "sammi": ["app.sammi.path"],
        "ytmd": ["app.ytmd.path", "music.app.path", "music.source_path"],
    }
    target = ""
    for key in target_map.get(app_id, []):
        raw = _state_value_text(key)
        if not raw:
            continue
        normalized = _normalize_app_open_target(app_id, raw)
        if normalized:
            target = normalized
            break

    if not target and app_id == "ytmd":
        target = "http://127.0.0.1:9863"

    if not target:
        raise ValueError(f"no launch target configured for app_id={app_id}")

    if os.name != "nt":
        raise ValueError("app launching is only supported on Windows in this build")

    try:
        os.startfile(target)  # type: ignore[attr-defined]
    except Exception as exc:
        raise RuntimeError(f"failed to open target '{target}': {exc}") from exc

    emit_event(
        con=None,
        event_type="APP_OPEN_REQUESTED",
        source=source,
        payload={"app_id": app_id, "target": target},
        severity="info",
        tags=["ui", "app_open", app_id],
    )
    return {"app_id": app_id, "target": target, "launched": True}


def send_twitch_chat(payload: dict[str, Any], source: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")

    message = str(payload.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")
    if len(message) > 500:
        raise ValueError("message must be <= 500 characters")

    mode = str(payload.get("mode") or "standby").strip().lower() or "standby"
    watch_condition_input = payload.get("watch_condition")
    if watch_condition_input is not None and (
        not isinstance(watch_condition_input, str) or not watch_condition_input.strip()
    ):
        raise ValueError("watch_condition must be a non-empty string when supplied")
    watch_condition = _resolve_watch_condition(
        str(watch_condition_input or "").strip().upper() if watch_condition_input else None,
        mode,
    )

    incident_id = str(payload.get("incident_id") or "").strip() or f"twitch-chat-{uuid.uuid4().hex[:12]}"
    stt_confidence = payload.get("stt_confidence")
    if stt_confidence is not None:
        if not isinstance(stt_confidence, (int, float)) or stt_confidence < 0 or stt_confidence > 1:
            raise ValueError("stt_confidence must be number 0..1 when supplied")
        stt_confidence = float(stt_confidence)
    user_confirmed = bool(payload.get("user_confirmed", False))
    user_confirm_token = str(
        payload.get("user_confirm_token") or payload.get("confirm_token") or ""
    ).strip() or None
    confirmed_at_utc = payload.get("confirmed_at_utc")
    confirmed_at_epoch: float | None = None
    if confirmed_at_utc is not None:
        if not isinstance(confirmed_at_utc, str) or not confirmed_at_utc.strip():
            raise ValueError("confirmed_at_utc must be non-empty string when supplied")
        parse_iso8601_utc(confirmed_at_utc)
        confirmed_at_epoch = iso8601_utc_to_epoch(confirmed_at_utc)

    if TWITCH_CHAT_STRICT_CONFIRM and user_confirmed:
        raise ValueError(
            "strict confirm mode enabled: call /confirm first, then resend with incident_id + confirm_token"
        )

    routed = TOOL_ROUTER.evaluate_action(
        incident_id=incident_id,
        watch_condition=watch_condition,
        tool_name="twitch.send_chat",
        args={"message_len": len(message)},
        source=source,
        stt_confidence=stt_confidence,
        foreground_process=None,
        user_confirmed=False if TWITCH_CHAT_STRICT_CONFIRM else user_confirmed,
        user_confirm_token=user_confirm_token,
        action_requires_confirmation=False,
        now_ts=time.time(),
        confirmation_ts=confirmed_at_epoch,
        req_context={
            "mode": mode,
            "watch_condition": watch_condition,
            "message_len": len(message),
        },
    )
    decision = routed["decision"]
    if not decision.get("allowed"):
        emit_event(
            con=None,
            event_type="TWITCH_CHAT_SEND_DENIED",
            source=source,
            payload={
                "incident_id": incident_id,
                "watch_condition": watch_condition,
                "reason_code": decision.get("deny_reason_code"),
                "reason_text": decision.get("deny_reason_text"),
                "requires_confirmation": bool(decision.get("requires_confirmation")),
                "confirm_token": routed.get("confirm_token"),
            },
            mode=mode,
            severity="warn",
            tags=["twitch", "send_chat", "denied"],
        )
        return {
            "accepted": False,
            "sent": False,
            "incident_id": incident_id,
            "tool_name": "twitch.send_chat",
            "watch_condition": watch_condition,
            "policy": decision,
            "confirm_token": routed.get("confirm_token"),
        }

    ok_set, set_result = SAMMI_CLIENT.call(
        "setVariable",
        {"name": TWITCH_CHAT_SEND_VAR, "value": message},
    )
    if not ok_set:
        raise RuntimeError(f"setVariable failed for {TWITCH_CHAT_SEND_VAR}: {set_result}")

    ok_trigger, trigger_result = SAMMI_CLIENT.call(
        "triggerButton",
        {"buttonID": TWITCH_CHAT_SEND_BUTTON},
    )
    if not ok_trigger:
        raise RuntimeError(f"triggerButton failed for {TWITCH_CHAT_SEND_BUTTON}: {trigger_result}")

    emit_event(
        con=None,
        event_type="TWITCH_CHAT_SENT",
        source=source,
        payload={
            "incident_id": incident_id,
            "watch_condition": watch_condition,
            "message_len": len(message),
            "var_name": TWITCH_CHAT_SEND_VAR,
            "button_id": TWITCH_CHAT_SEND_BUTTON,
        },
        mode=mode,
        tags=["twitch", "send_chat"],
    )
    return {
        "accepted": True,
        "sent": True,
        "incident_id": incident_id,
        "tool_name": "twitch.send_chat",
        "watch_condition": watch_condition,
        "var_name": TWITCH_CHAT_SEND_VAR,
        "button_id": TWITCH_CHAT_SEND_BUTTON,
        "policy": decision,
        "sammi": {
            "set_variable": set_result,
            "trigger_button": trigger_result,
        },
    }


def save_inara_credentials(payload: dict[str, Any], source: str) -> dict[str, Any]:
    clear_requested = bool(payload.get("clear"))
    if clear_requested:
        clear_provider_secret_entry("inara", path=PROVIDER_SECRETS_PATH)
        entry: dict[str, Any] = {}
    else:
        entry = save_inara_secret_entry(
            commander_name=payload.get("commander_name"),
            frontier_id=payload.get("frontier_id"),
            app_key=payload.get("api_key"),
            path=PROVIDER_SECRETS_PATH,
        )

    if hasattr(ED_PROVIDER_QUERY_SERVICE, "reload_config"):
        ED_PROVIDER_QUERY_SERVICE.reload_config()
    if PROVIDER_HEALTH_ENABLED and hasattr(runtime, "ED_PROVIDER_HEALTH_SCHEDULER"):
        runtime.ED_PROVIDER_HEALTH_SCHEDULER.update_probes(
            build_provider_health_probes(PROVIDER_CONFIG_PATH, PROVIDER_SECRETS_PATH, DB_PATH)
        )

    emit_event(
        con=None,
        event_type="PROVIDER_CREDENTIALS_UPDATED",
        source=source,
        payload={
            "provider": "inara",
            "cleared": clear_requested,
            "commander_name_present": bool(str(entry.get("commander_name") or "").strip()),
            "frontier_id_present": bool(str(entry.get("frontier_id") or "").strip()),
            "app_key_present": bool(str(entry.get("app_key") or "").strip()),
            "storage_path": str(PROVIDER_SECRETS_PATH),
        },
        tags=["provider", "inara", "credentials"],
    )

    from queries import query_inara_credentials

    result = query_inara_credentials({})
    result["saved_securely"] = not clear_requested
    result["cleared_securely"] = clear_requested
    return result


def save_openai_credentials(payload: dict[str, Any], source: str) -> dict[str, Any]:
    clear_requested = bool(payload.get("clear"))
    if clear_requested:
        clear_provider_secret_entry("openai", path=PROVIDER_SECRETS_PATH)
        entry: dict[str, Any] = {}
    else:
        entry = save_openai_secret_entry(
            api_key=payload.get("api_key"),
            path=PROVIDER_SECRETS_PATH,
        )
    emit_event(
        con=None,
        event_type="PROVIDER_CREDENTIALS_UPDATED",
        source=source,
        payload={
            "provider": "openai",
            "cleared": clear_requested,
            "api_key_present": bool(str(entry.get("api_key") or "").strip()),
            "storage_path": str(PROVIDER_SECRETS_PATH),
        },
        tags=["provider", "openai", "credentials"],
    )

    from queries import query_openai_credentials

    result = query_openai_credentials({})
    result["saved_securely"] = not clear_requested
    result["cleared_securely"] = clear_requested
    return result


def save_runtime_settings_action(payload: dict[str, Any], source: str) -> dict[str, Any]:
    settings = save_runtime_settings(Path(DB_PATH), payload)
    if hasattr(ED_PROVIDER_QUERY_SERVICE, "reload_config"):
        ED_PROVIDER_QUERY_SERVICE.reload_config()
    if PROVIDER_HEALTH_ENABLED and hasattr(runtime, "ED_PROVIDER_HEALTH_SCHEDULER"):
        runtime.ED_PROVIDER_HEALTH_SCHEDULER.update_probes(
            build_provider_health_probes(PROVIDER_CONFIG_PATH, PROVIDER_SECRETS_PATH, DB_PATH)
        )
    emit_event(
        con=None,
        event_type="RUNTIME_SETTINGS_UPDATED",
        source=source,
        payload={
            "providers": payload.get("providers", {}),
            "syncs": payload.get("syncs", {}),
        },
        tags=["settings", "runtime"],
    )
    return {"ok": True, "settings": settings}


def _safe_twitch_context_pack(payload: dict[str, Any]) -> dict[str, Any]:
    context = payload.get("context")
    if not isinstance(context, dict):
        return {}
    user_id = str(context.get("twitch_user_id") or context.get("user_id") or "").strip()
    if not user_id:
        return {}

    try:
        user_ctx = TWITCH_REPO.get_user_context(user_id, redeem_limit=5)
    except Exception:
        return {}

    user = user_ctx.get("user") or {}
    stats = user_ctx.get("stats") or {}
    last_messages = user_ctx.get("last_messages") or []
    top_redeems = user_ctx.get("top_redeems") or []
    tags: list[str] = []

    redeem_total = int(stats.get("redeem_total") or 0)
    message_count = int(user.get("message_count") or 0)
    bits_total = int(stats.get("bits_total") or 0)
    if redeem_total >= 3:
        tags.append("usual_redeem_candidate")
    if message_count >= 20:
        tags.append("frequent_chatter")
    if bits_total > 0 and str(stats.get("last_bits_ts_utc") or "").strip():
        tags.append("recent_supporter")

    return {
        "user_id": user_id,
        "display_name": user.get("display_name"),
        "flags": user.get("flags") if isinstance(user.get("flags"), dict) else {},
        "last_messages": last_messages[:5] if isinstance(last_messages, list) else [],
        "top_redeems": top_redeems[:5] if isinstance(top_redeems, list) else [],
        "stats": stats if isinstance(stats, dict) else {},
        "heuristic_tags": tags,
    }


def _resolve_tool_from_assist_events(incident_id: str, confirm_token: str) -> str | None:
    token = confirm_token.strip()
    if not token:
        return None

    issued_events = DB_SERVICE.list_events(limit=500, event_type="ASSIST_CONFIRM_ISSUED")
    for row in issued_events:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if str(payload.get("incident_id") or "").strip() != incident_id:
            continue
        if str(payload.get("confirm_token") or "").strip() != token:
            continue
        tool_name = str(payload.get("tool_name") or "").strip()
        if tool_name:
            return TOOL_ROUTER.policy_engine.canonical_tool_name(tool_name)

    preview_events = DB_SERVICE.list_events(limit=500, event_type="ASSIST_POLICY_PREVIEW")
    for row in preview_events:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if str(payload.get("incident_id") or "").strip() != incident_id:
            continue
        actions = payload.get("actions")
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            if str(action.get("confirm_token") or "").strip() != token:
                continue
            tool_name = str(action.get("tool_name") or "").strip()
            if tool_name:
                return TOOL_ROUTER.policy_engine.canonical_tool_name(tool_name)
    return None


def _resolve_tool_name_for_confirmation(
    incident_id: str,
    tool_name: str,
    confirm_token: str,
) -> str:
    tool_text = tool_name.strip()
    if tool_text:
        return TOOL_ROUTER.policy_engine.canonical_tool_name(tool_text)

    from_events = _resolve_tool_from_assist_events(incident_id, confirm_token)
    if from_events:
        return from_events

    token = confirm_token.strip()
    if token.startswith("confirm-"):
        parts = token.split("-", 2)
        if len(parts) == 3 and parts[1] and parts[2]:
            return TOOL_ROUTER.policy_engine.canonical_tool_name(parts[2].replace("-", "."))

    raise ValueError("tool_name could not be resolved from confirm_token")


def record_confirmation(payload: dict[str, Any], source: str) -> dict[str, Any]:
    incident_id = payload["incident_id"].strip()
    confirm_token = (payload.get("confirm_token") or payload.get("user_confirm_token") or "").strip()
    tool_name = str(payload.get("tool_name") or "").strip()
    tool_key = _resolve_tool_name_for_confirmation(incident_id, tool_name, confirm_token)
    if not confirm_token:
        confirm_token = TOOL_ROUTER.build_confirmation_token(incident_id, tool_key)

    confirmed_at_utc = payload.get("confirmed_at_utc") or utc_now_iso()
    confirmed_at_epoch = iso8601_utc_to_epoch(confirmed_at_utc)
    TOOL_ROUTER.policy_engine.record_confirmation(
        incident_id=incident_id,
        tool_name=tool_key,
        token=confirm_token,
        ts=confirmed_at_epoch,
    )

    req_context = {
        "request_id": payload.get("request_id"),
        "session_id": payload.get("session_id"),
        "mode": payload.get("mode"),
        "incident_id": incident_id,
    }
    LOGBOOK.log_decision(
        incident_id=incident_id,
        tool_name=tool_key,
        decision={
            "allowed": True,
            "requires_confirmation": False,
            "deny_reason_code": "ALLOW",
            "deny_reason_text": None,
            "constraints": {
                "recorded_confirmation": True,
                "confirmed_at_utc": confirmed_at_utc,
            },
        },
        req_context=req_context,
    )
    emit_event(
        con=None,
        event_type="USER_CONFIRMATION_RECORDED",
        source=source,
        payload={
            "incident_id": incident_id,
            "tool_name": tool_key,
            "confirm_token": confirm_token,
            "confirmed_at_utc": confirmed_at_utc,
            "request_id": payload.get("request_id"),
        },
        session_id=payload.get("session_id"),
        correlation_id=payload.get("request_id") or incident_id,
        mode=payload.get("mode"),
    )
    emit_event(
        con=None,
        event_type="ASSIST_CONFIRM_ACCEPTED",
        source=source,
        payload={
            "incident_id": incident_id,
            "tool_name": tool_key,
            "confirm_token": confirm_token,
            "confirmed_at_utc": confirmed_at_utc,
            "request_id": payload.get("request_id"),
        },
        session_id=payload.get("session_id"),
        correlation_id=payload.get("request_id") or incident_id,
        mode=payload.get("mode"),
        tags=["assist", "confirm", "accepted"],
    )
    return {
        "incident_id": incident_id,
        "tool_name": tool_key,
        "confirm_token": confirm_token,
        "confirmed_at_utc": confirmed_at_utc,
    }


def execute_actions(payload: dict[str, Any], source: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("request_id is required and must be a non-empty string")

    action_ids = payload.get("action_ids")
    if action_ids is not None:
        if not isinstance(action_ids, list):
            raise ValueError("action_ids must be an array when supplied")
        for idx, action_id in enumerate(action_ids):
            if not isinstance(action_id, str) or not action_id:
                raise ValueError(f"action_ids[{idx}] must be a non-empty string")

    dry_run = payload.get("dry_run", True)
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be boolean")

    allow_high_risk = payload.get("allow_high_risk", False)
    if not isinstance(allow_high_risk, bool):
        raise ValueError("allow_high_risk must be boolean")

    user_confirmed = payload.get("user_confirmed", False)
    if not isinstance(user_confirmed, bool):
        raise ValueError("user_confirmed must be boolean")

    user_confirm_token = payload.get("user_confirm_token")
    if user_confirm_token is None:
        user_confirm_token = payload.get("confirm_token")
    if user_confirm_token is not None and (
        not isinstance(user_confirm_token, str) or not user_confirm_token.strip()
    ):
        raise ValueError("user_confirm_token must be a non-empty string when supplied")

    incident_id = payload.get("incident_id")
    if incident_id is not None and (not isinstance(incident_id, str) or not incident_id.strip()):
        raise ValueError("incident_id must be a non-empty string when supplied")

    watch_condition_input = payload.get("watch_condition")
    if watch_condition_input is not None and (
        not isinstance(watch_condition_input, str) or not watch_condition_input.strip()
    ):
        raise ValueError("watch_condition must be a non-empty string when supplied")

    stt_confidence = payload.get("stt_confidence")
    if stt_confidence is not None:
        if not isinstance(stt_confidence, (int, float)) or stt_confidence < 0 or stt_confidence > 1:
            raise ValueError("stt_confidence must be number 0..1 when supplied")
        stt_confidence = float(stt_confidence)

    confirmed_at_utc = payload.get("confirmed_at_utc")
    confirmed_at_epoch: float | None = None
    if confirmed_at_utc is not None:
        if not isinstance(confirmed_at_utc, str) or not confirmed_at_utc.strip():
            raise ValueError("confirmed_at_utc must be non-empty string when supplied")
        parse_iso8601_utc(confirmed_at_utc)
        confirmed_at_epoch = iso8601_utc_to_epoch(confirmed_at_utc)

    incident_id_value = (incident_id or "").strip()

    with connect_db() as con:
        intent = con.execute(
            "SELECT request_id,mode,session_id FROM intent_log WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if not intent:
            raise ValueError(f"request_id not found: {request_id}")
        watch_condition = _resolve_watch_condition(watch_condition_input, intent["mode"])

        sql = (
            "SELECT id,request_id,action_id,tool_name,status,safety_level,parameters_json,created_at_utc "
            "FROM action_log WHERE request_id=?"
        )
        args: list[Any] = [request_id]
        if action_ids:
            placeholders = ",".join("?" for _ in action_ids)
            sql += f" AND action_id IN ({placeholders})"
            args.extend(action_ids)
        sql += " ORDER BY id ASC"

        rows = con.execute(sql, args).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            status = row["status"]
            if status in {"success", "error", "timeout", "denied"}:
                results.append(
                    {
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "status": status,
                        "message": "already finalized",
                    }
                )
                continue

            action_meta = parse_json(row["parameters_json"], {})
            action_parameters = action_meta.get("parameters", {})
            mode_constraints = action_meta.get("mode_constraints") or []
            requires_confirmation = bool(action_meta.get("requires_confirmation", False))
            if not isinstance(action_parameters, dict):
                action_parameters = {}
            if not isinstance(mode_constraints, list):
                mode_constraints = []
            allowed_modes = [str(m) for m in mode_constraints if isinstance(m, str)]
            if allowed_modes and intent["mode"] not in allowed_modes:
                denied_reason = f"mode '{intent['mode']}' not in action mode_constraints"
                denied_reason_code = "DENY_MODE_CONSTRAINT"
                policy_decision = {
                    "allowed": False,
                    "requires_confirmation": False,
                    "deny_reason_code": denied_reason_code,
                    "deny_reason_text": denied_reason,
                    "constraints": {},
                }
            elif row["safety_level"] == "high_risk" and not allow_high_risk:
                denied_reason = "high_risk action requires allow_high_risk=true"
                denied_reason_code = "DENY_HIGH_RISK_NOT_ALLOWED"
                policy_decision = {
                    "allowed": False,
                    "requires_confirmation": False,
                    "deny_reason_code": denied_reason_code,
                    "deny_reason_text": denied_reason,
                    "constraints": {},
                }
            else:
                foreground_process = _get_foreground_process_name()
                routed = TOOL_ROUTER.evaluate_action(
                    incident_id=incident_id_value,
                    watch_condition=watch_condition,
                    tool_name=row["tool_name"],
                    args=action_parameters,
                    source=source,
                    stt_confidence=stt_confidence,
                    foreground_process=foreground_process,
                    user_confirmed=user_confirmed,
                    user_confirm_token=user_confirm_token,
                    action_requires_confirmation=requires_confirmation,
                    now_ts=time.time(),
                    confirmation_ts=confirmed_at_epoch,
                    req_context={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "session_id": intent["session_id"],
                        "mode": intent["mode"],
                    },
                )
                policy_decision = routed["decision"]
                denied_reason = policy_decision.get("deny_reason_text")
                denied_reason_code = policy_decision.get("deny_reason_code")
                if policy_decision.get("requires_confirmation", False):
                    confirm_event_type = "ACTION_CONFIRMATION_REQUIRED"
                    if denied_reason_code == "DENY_CONFIRMATION_EXPIRED":
                        confirm_event_type = "ACTION_CONFIRMATION_EXPIRED"
                    con.execute(
                        """
                        UPDATE action_log
                        SET status='queued', error_code=?, error_message=?, ended_at_utc=?
                        WHERE id=?
                        """,
                        (denied_reason_code, denied_reason, utc_now_iso(), row["id"]),
                    )
                    emit_event(
                        con,
                        event_type=confirm_event_type,
                        source=source,
                        payload={
                            "request_id": request_id,
                            "action_id": row["action_id"],
                            "tool_name": row["tool_name"],
                            "incident_id": incident_id,
                            "watch_condition": watch_condition,
                            "policy_decision": policy_decision,
                            "confirm_token": routed.get("confirm_token"),
                        },
                        session_id=intent["session_id"],
                        correlation_id=request_id,
                        mode=intent["mode"],
                        severity="warn",
                        tags=["assist", "confirm", "required"]
                        if confirm_event_type == "ACTION_CONFIRMATION_REQUIRED"
                        else ["assist", "confirm", "expired"],
                    )
                    results.append(
                        {
                            "action_id": row["action_id"],
                            "tool_name": row["tool_name"],
                            "status": "requires_confirmation",
                            "reason_code": denied_reason_code,
                            "reason": denied_reason,
                            "confirm_token": routed.get("confirm_token"),
                            "constraints": policy_decision.get("constraints", {}),
                            "incident_id": incident_id,
                            "watch_condition": watch_condition,
                        }
                    )
                    continue

            if denied_reason:
                con.execute(
                    """
                    UPDATE action_log
                    SET status='denied', error_code=?, error_message=?, ended_at_utc=?
                    WHERE id=?
                    """,
                    (denied_reason_code, denied_reason, utc_now_iso(), row["id"]),
                )
                emit_event(
                    con,
                    event_type="ACTION_DENIED",
                    source=source,
                    payload={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "reason": denied_reason,
                        "reason_code": denied_reason_code,
                        "incident_id": incident_id,
                        "watch_condition": watch_condition,
                        "policy_decision": policy_decision,
                    },
                    session_id=intent["session_id"],
                    correlation_id=request_id,
                    mode=intent["mode"],
                    severity="warn",
                )
                results.append(
                    {
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "status": "denied",
                        "reason_code": denied_reason_code,
                        "reason": denied_reason,
                    }
                )
                continue

            started_at = utc_now_iso()
            con.execute(
                """
                UPDATE action_log
                SET status='approved', started_at_utc=?
                WHERE id=?
                """,
                (started_at, row["id"]),
            )
            emit_event(
                con,
                event_type="ACTION_APPROVED",
                source=source,
                payload={
                    "request_id": request_id,
                    "action_id": row["action_id"],
                    "tool_name": row["tool_name"],
                    "incident_id": incident_id,
                    "watch_condition": watch_condition,
                    "policy_decision": policy_decision,
                },
                session_id=intent["session_id"],
                correlation_id=request_id,
                mode=intent["mode"],
            )

            try:
                output = execute_tool(
                    tool_name=row["tool_name"],
                    parameters=action_parameters,
                    request_id=request_id,
                    action_id=row["action_id"],
                    dry_run=dry_run,
                )
                status_after = "success"
                error_code = None
                error_message = None
            except Exception as exc:
                output = {}
                status_after = "error"
                error_code = "execution_error"
                error_message = str(exc)

            ended_at = utc_now_iso()
            con.execute(
                """
                UPDATE action_log
                SET status=?, output_json=?, error_code=?, error_message=?, ended_at_utc=?
                WHERE id=?
                """,
                (
                    status_after,
                    json.dumps(output, ensure_ascii=False),
                    error_code,
                    error_message,
                    ended_at,
                    row["id"],
                ),
            )
            if status_after == "success":
                emit_event(
                    con,
                    event_type="TOOL_EXECUTE_RESULT",
                    source=source,
                    payload={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "incident_id": incident_id,
                        "ok": True,
                        "result_or_error": output,
                    },
                    session_id=intent["session_id"],
                    correlation_id=request_id,
                    mode=intent["mode"],
                )
                emit_event(
                    con,
                    event_type="ACTION_EXECUTED",
                    source=source,
                    payload={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "dry_run": dry_run,
                        "incident_id": incident_id,
                        "watch_condition": watch_condition,
                        "stub_execution": bool(output.get("stub_execution")),
                        "result": output.get("result"),
                    },
                    session_id=intent["session_id"],
                    correlation_id=request_id,
                    mode=intent["mode"],
                )
            else:
                emit_event(
                    con,
                    event_type="TOOL_EXECUTE_RESULT",
                    source=source,
                    payload={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "incident_id": incident_id,
                        "ok": False,
                        "result_or_error": error_message,
                    },
                    session_id=intent["session_id"],
                    correlation_id=request_id,
                    mode=intent["mode"],
                    severity="error",
                )
                emit_event(
                    con,
                    event_type="ACTION_FAILED",
                    source=source,
                    payload={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "incident_id": incident_id,
                        "watch_condition": watch_condition,
                        "error_code": error_code,
                        "error_message": error_message,
                    },
                    session_id=intent["session_id"],
                    correlation_id=request_id,
                    mode=intent["mode"],
                    severity="error",
                )
            result_row = {
                "action_id": row["action_id"],
                "tool_name": row["tool_name"],
                "status": status_after,
            }
            if status_after == "success":
                result_row["output"] = output
            else:
                result_row["error"] = error_message
                result_row["error_code"] = error_code
            result_row["incident_id"] = incident_id
            result_row["watch_condition"] = watch_condition
            results.append(result_row)

        con.commit()

    return {
        "request_id": request_id,
        "incident_id": incident_id,
        "watch_condition": watch_condition,
        "dry_run": dry_run,
        "results": results,
    }


def _fetch_advisory_proposal(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not ADVISORY_ENABLED:
        raise ValueError("advisory service is disabled (WKV_ADVISORY_ENABLED=0)")
    if not ADVISORY_URL:
        raise ValueError("WKV_ADVISORY_URL is not configured")

    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        ADVISORY_URL,
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Source": "brainstem_assist",
        },
    )
    try:
        with request.urlopen(req, timeout=ADVISORY_TIMEOUT_SEC) as resp:
            status = int(getattr(resp, "status", 200))
            body = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"advisory HTTP {exc.code}: {message}") from exc
    except Exception as exc:
        raise ValueError(f"advisory request failed: {exc}") from exc

    try:
        parsed = json.loads(body) if body else {}
    except Exception as exc:
        raise ValueError("advisory returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("advisory response must be a JSON object")

    proposal = parsed.get("proposal")
    if not isinstance(proposal, dict):
        raise ValueError("advisory response missing proposal object")

    meta = {
        "status": status,
        "provider": parsed.get("provider"),
        "service_meta": parsed.get("meta") if isinstance(parsed.get("meta"), dict) else {},
    }
    return proposal, meta


def assist_with_advisory(payload: dict[str, Any], source: str) -> dict[str, Any]:
    payload_for_advisory = dict(payload)
    twitch_context_pack = _safe_twitch_context_pack(payload)
    if twitch_context_pack:
        context = payload.get("context")
        context_obj = dict(context) if isinstance(context, dict) else {}
        context_obj["twitch_context_pack"] = twitch_context_pack
        payload_for_advisory["context"] = context_obj

    request_id_hint = str(payload.get("request_id") or f"req-{uuid.uuid4().hex[:12]}")
    mode_hint = str(payload.get("mode") or "standby")
    emit_event(
        con=None,
        event_type="ASSIST_REQUEST_SUMMARY",
        source=source,
        payload={
            "request_id": request_id_hint,
            "mode": mode_hint,
            "domain": payload.get("domain"),
            "urgency": payload.get("urgency"),
            "watch_condition": payload.get("watch_condition"),
            "max_actions": payload.get("max_actions"),
            "user_text_chars": len(str(payload.get("user_text") or "")),
            "has_context": isinstance(payload_for_advisory.get("context"), dict),
            "has_twitch_context_pack": bool(twitch_context_pack),
        },
        session_id=payload.get("session_id"),
        correlation_id=request_id_hint,
        mode=mode_hint,
        tags=["assist", "request"],
    )

    proposal, advisory_meta = _fetch_advisory_proposal(payload_for_advisory)
    request_id = proposal["request_id"]
    incident_id = (payload.get("incident_id") or f"inc-{request_id}").strip()
    emit_event(
        con=None,
        event_type="ASSIST_PROPOSAL_RECEIVED",
        source=source,
        payload={
            "request_id": request_id,
            "incident_id": incident_id,
            "provider": advisory_meta.get("provider"),
            "advisory_status": advisory_meta.get("status"),
            "service_meta": advisory_meta.get("service_meta", {}),
            "actions_count": len(proposal.get("proposed_actions", []))
            if isinstance(proposal.get("proposed_actions"), list)
            else 0,
        },
        session_id=proposal.get("session_id"),
        correlation_id=request_id,
        mode=proposal.get("mode"),
        tags=["assist", "proposal", "received"],
    )

    from validators import validate_intent_proposal

    try:
        validate_intent_proposal(proposal)
    except Exception as exc:
        emit_event(
            con=None,
            event_type="ASSIST_PROPOSAL_INVALID",
            source=source,
            payload={
                "request_id": request_id,
                "incident_id": incident_id,
                "validation_error": str(exc),
                "provider": advisory_meta.get("provider"),
            },
            session_id=proposal.get("session_id"),
            correlation_id=request_id,
            mode=proposal.get("mode"),
            severity="warn",
            tags=["assist", "proposal", "invalid"],
        )
        raise

    stt_confidence = payload.get("stt_confidence")
    if not isinstance(stt_confidence, (int, float)):
        stt_confidence = None
    else:
        stt_confidence = float(stt_confidence)
    foreground_process = payload.get("foreground_process")
    if not isinstance(foreground_process, str) or not foreground_process.strip():
        foreground_process = None

    watch_condition = _resolve_watch_condition(payload.get("watch_condition"), proposal["mode"])
    retrieval = proposal.get("retrieval")
    if not isinstance(retrieval, dict):
        retrieval = {}
    emit_event(
        con=None,
        event_type="ASSIST_PROPOSAL_VALIDATED",
        source=source,
        payload={
            "request_id": request_id,
            "incident_id": incident_id,
            "watch_condition": watch_condition,
            "actions_count": len(proposal.get("proposed_actions", [])),
            "needs_clarification": bool(proposal.get("needs_clarification", False)),
            "retrieval_context_meta": retrieval.get("context_pack_metadata", {}),
        },
        session_id=proposal.get("session_id"),
        correlation_id=request_id,
        mode=proposal.get("mode"),
        tags=["assist", "proposal", "validated"],
    )

    with connect_db() as con:
        queued_actions = upsert_intent(con, proposal, source=source)
        con.commit()

    policy_preview: list[dict[str, Any]] = []
    needs_confirmation = False
    gated_action_count = 0
    now_ts = time.time()

    for action in proposal.get("proposed_actions", []):
        action_id = str(action.get("action_id") or "")
        tool_name = str(action.get("tool_name") or "")
        params = action.get("parameters")
        if not isinstance(params, dict):
            params = {}
        routed = TOOL_ROUTER.evaluate_action(
            incident_id=incident_id,
            watch_condition=watch_condition,
            tool_name=tool_name,
            args=params,
            source=source,
            stt_confidence=stt_confidence,
            foreground_process=foreground_process,
            user_confirmed=False,
            user_confirm_token=None,
            action_requires_confirmation=bool(action.get("requires_confirmation", False)),
            now_ts=now_ts,
            req_context={
                "request_id": request_id,
                "action_id": action_id,
                "session_id": proposal.get("session_id"),
                "mode": proposal.get("mode"),
                "phase": "assist_proposal",
            },
        )
        decision = routed["decision"]
        if decision.get("requires_confirmation"):
            needs_confirmation = True
            emit_event(
                con=None,
                event_type="ASSIST_CONFIRM_ISSUED",
                source=source,
                payload={
                    "request_id": request_id,
                    "incident_id": incident_id,
                    "action_id": action_id,
                    "tool_name": tool_name,
                    "confirm_token": routed.get("confirm_token"),
                    "reason_code": decision.get("deny_reason_code"),
                    "constraints": decision.get("constraints", {}),
                },
                session_id=proposal.get("session_id"),
                correlation_id=request_id,
                mode=proposal.get("mode"),
                severity="warn",
                tags=["assist", "confirm", "issued"],
            )
        if not decision.get("allowed"):
            gated_action_count += 1
        policy_preview.append(
            {
                "action_id": action_id,
                "tool_name": tool_name,
                "decision": decision,
                "confirm_token": routed.get("confirm_token"),
            }
        )

    emit_event(
        con=None,
        event_type="ASSIST_POLICY_PREVIEW",
        source=source,
        payload={
            "request_id": request_id,
            "incident_id": incident_id,
            "watch_condition": watch_condition,
            "actions": policy_preview,
        },
        session_id=proposal.get("session_id"),
        correlation_id=request_id,
        mode=proposal.get("mode"),
        tags=["assist", "policy", "preview"],
    )

    emit_event(
        con=None,
        event_type="ASSIST_PROPOSAL",
        source=source,
        payload={
            "request_id": request_id,
            "incident_id": incident_id,
            "watch_condition": watch_condition,
            "queued_actions": queued_actions,
            "gated_action_count": gated_action_count,
            "needs_confirmation": needs_confirmation,
            "advisory": advisory_meta,
            "retrieval_context_meta": retrieval.get("context_pack_metadata", {}),
        },
        session_id=proposal.get("session_id"),
        correlation_id=request_id,
        mode=proposal.get("mode"),
        tags=["assist", "proposal"],
    )

    return {
        "request_id": request_id,
        "incident_id": incident_id,
        "watch_condition": watch_condition,
        "proposal": proposal,
        "queued_actions": queued_actions,
        "policy_preview": policy_preview,
        "needs_confirmation": needs_confirmation,
        "advisory": advisory_meta,
    }


def execute_provider_query(payload: dict[str, Any], source: str) -> dict[str, Any]:
    requirements = payload.get("requirements") if isinstance(payload.get("requirements"), dict) else {}
    trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
    request_obj = ProviderQuery(
        provider=ProviderId(str(payload.get("provider") or "").strip().lower()),
        operation=ProviderOperationId(str(payload.get("operation") or "").strip().lower()),
        params=dict(payload.get("params") or {}),
        max_age_s=int(requirements.get("max_age_s", 0)),
        allow_stale_if_error=bool(requirements.get("allow_stale_if_error", False)),
        incident_id=str(trace.get("incident_id") or "").strip() or None,
        reason=str(trace.get("reason") or "api_query").strip() or "api_query",
    )
    result = ED_PROVIDER_QUERY_SERVICE.execute(request_obj)
    emit_event(
        con=None,
        event_type="ED_PROVIDER_QUERY",
        source=source,
        payload={
            "provider": request_obj.provider.value,
            "operation": request_obj.operation.value,
            "incident_id": request_obj.incident_id,
            "reason": request_obj.reason,
            "ok": result.ok,
            "cache": {
                "hit": result.cache.hit,
                "age_s": result.cache.age_s,
                "ttl_s": result.cache.ttl_s,
                "stale_served": result.cache.stale_served,
            },
            "deny_reason": result.deny_reason.value if result.deny_reason else None,
            "error": result.error,
        },
        correlation_id=request_obj.incident_id,
        tags=["provider", request_obj.provider.value, request_obj.operation.value],
    )
    return {"ok": result.ok, **result.to_dict()}
