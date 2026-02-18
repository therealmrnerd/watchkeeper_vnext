import ctypes
import json
import sqlite3
import subprocess
import time
import uuid
from ctypes import windll
from typing import Any
from urllib import error, request
from urllib.parse import quote

from runtime import (
    DB_SERVICE,
    DEFAULT_WATCH_CONDITION,
    EDPARSER_TOOL,
    ENABLE_ACTUATORS,
    ENABLE_KEYPRESS,
    KEYPRESS_ALLOWED_PROCESSES,
    KEYEVENTF_KEYUP,
    LIGHTS_WEBHOOK_TIMEOUT_SEC,
    LIGHTS_WEBHOOK_URL,
    LIGHTS_WEBHOOK_URL_TEMPLATE,
    LOGBOOK,
    SPECIAL_VK_MAP,
    TOOL_ROUTER,
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    connect_db,
    iso8601_utc_to_epoch,
    parse_iso8601_utc,
    parse_json,
    utc_now_iso,
)


def _list_process_names() -> set[str]:
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
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


def record_confirmation(payload: dict[str, Any], source: str) -> dict[str, Any]:
    incident_id = payload["incident_id"].strip()
    tool_name = payload["tool_name"].strip()
    tool_key = TOOL_ROUTER.policy_engine.canonical_tool_name(tool_name)
    confirm_token = (payload.get("user_confirm_token") or "").strip()
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
                        event_type="ACTION_CONFIRMATION_REQUIRED",
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
                LOGBOOK.log_execute_result(
                    incident_id=incident_id_value,
                    tool_name=row["tool_name"],
                    ok=True,
                    result_or_error=output,
                    req_context={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "session_id": intent["session_id"],
                        "mode": intent["mode"],
                    },
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
                LOGBOOK.log_execute_result(
                    incident_id=incident_id_value,
                    tool_name=row["tool_name"],
                    ok=False,
                    result_or_error=error_message,
                    req_context={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "session_id": intent["session_id"],
                        "mode": intent["mode"],
                    },
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
