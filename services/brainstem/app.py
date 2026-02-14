import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("WKV_DB_PATH", ROOT_DIR / "data" / "watchkeeper_vnext.db"))
SCHEMA_PATH = Path(
    os.getenv("WKV_SCHEMA_PATH", ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
)
HOST = os.getenv("WKV_HOST", "127.0.0.1")
PORT = int(os.getenv("WKV_PORT", "8787"))

INTENT_ALLOWED_KEYS = {
    "schema_version",
    "request_id",
    "session_id",
    "timestamp_utc",
    "mode",
    "domain",
    "urgency",
    "user_text",
    "needs_tools",
    "needs_clarification",
    "clarification_questions",
    "retrieval",
    "proposed_actions",
    "response_text",
}

ACTION_ALLOWED_KEYS = {
    "action_id",
    "tool_name",
    "parameters",
    "safety_level",
    "mode_constraints",
    "requires_confirmation",
    "timeout_ms",
    "reason",
    "confidence",
}

STATE_ITEM_ALLOWED_KEYS = {
    "state_key",
    "state_value",
    "source",
    "confidence",
    "observed_at_utc",
}

STATE_INGEST_ALLOWED_KEYS = {
    "items",
    "emit_events",
    "profile",
    "session_id",
    "correlation_id",
}

FEEDBACK_ALLOWED_KEYS = {
    "request_id",
    "rating",
    "correction_text",
    "reviewer",
    "session_id",
    "mode",
}

MODE_SET = {"game", "work", "standby", "tutor"}
DOMAIN_SET = {
    "gameplay",
    "lore",
    "astrophysics",
    "general_gaming",
    "coding",
    "networking",
    "system",
    "music",
    "speech",
    "general",
}
URGENCY_SET = {"low", "normal", "high"}
SAFETY_SET = {"read_only", "low_risk", "high_risk"}
MAX_ACTIONS = 10


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso8601_utc(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp_utc must be a non-empty string")
    # Accept trailing Z or +00:00.
    normalized = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("timestamp_utc must be ISO-8601") from exc


def connect_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def ensure_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect_db() as con:
        con.execute("PRAGMA journal_mode=WAL;")
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_log'"
        ).fetchone()
        if exists:
            return
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        con.executescript(schema_sql)
        con.commit()


def parse_json(raw: Any, fallback: Any) -> Any:
    if raw is None:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def emit_event(
    con: sqlite3.Connection,
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
    return event_id


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

    upserted = 0
    state_keys: list[str] = []

    with connect_db() as con:
        for item in items:
            state_key = item["state_key"].strip()
            state_value = item["state_value"]
            state_source = item["source"].strip()
            confidence = item.get("confidence")
            observed_at_utc = item.get("observed_at_utc") or utc_now_iso()
            updated_at_utc = utc_now_iso()

            con.execute(
                """
                INSERT INTO state_current(
                    state_key,state_value_json,source,confidence,observed_at_utc,updated_at_utc
                )
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value_json=excluded.state_value_json,
                    source=excluded.source,
                    confidence=excluded.confidence,
                    observed_at_utc=excluded.observed_at_utc,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (
                    state_key,
                    json.dumps(state_value, ensure_ascii=False),
                    state_source,
                    confidence,
                    observed_at_utc,
                    updated_at_utc,
                ),
            )
            upserted += 1
            state_keys.append(state_key)

            if emit_events:
                emit_event(
                    con,
                    event_type="STATE_UPDATED",
                    source=source,
                    payload={
                        "state_key": state_key,
                        "source": state_source,
                        "confidence": confidence,
                        "observed_at_utc": observed_at_utc,
                    },
                    profile=profile,
                    session_id=session_id,
                    correlation_id=correlation_id,
                )

        con.commit()

    return {"upserted": upserted, "state_keys": state_keys}


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


def query_state(query: dict[str, list[str]]) -> list[dict[str, Any]]:
    key = (query.get("key", [None])[0] or "").strip()
    with connect_db() as con:
        if key:
            rows = con.execute(
                """
                SELECT state_key,state_value_json,source,confidence,observed_at_utc,updated_at_utc
                FROM state_current
                WHERE state_key=?
                """,
                (key,),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT state_key,state_value_json,source,confidence,observed_at_utc,updated_at_utc
                FROM state_current
                ORDER BY updated_at_utc DESC
                """
            ).fetchall()

    return [
        {
            "state_key": row["state_key"],
            "state_value": parse_json(row["state_value_json"], row["state_value_json"]),
            "source": row["source"],
            "confidence": row["confidence"],
            "observed_at_utc": row["observed_at_utc"],
            "updated_at_utc": row["updated_at_utc"],
        }
        for row in rows
    ]


def query_events(query: dict[str, list[str]]) -> list[dict[str, Any]]:
    limit_raw = (query.get("limit", ["100"])[0] or "100").strip()
    event_type = (query.get("type", [None])[0] or "").strip()
    session_id = (query.get("session_id", [None])[0] or "").strip()
    correlation_id = (query.get("correlation_id", [None])[0] or "").strip()
    since = (query.get("since", [None])[0] or "").strip()

    try:
        limit = max(1, min(1000, int(limit_raw)))
    except ValueError:
        raise ValueError("limit must be an integer")

    clauses = []
    args: list[Any] = []
    if event_type:
        clauses.append("event_type=?")
        args.append(event_type)
    if session_id:
        clauses.append("session_id=?")
        args.append(session_id)
    if correlation_id:
        clauses.append("correlation_id=?")
        args.append(correlation_id)
    if since:
        parse_iso8601_utc(since)
        clauses.append("timestamp_utc>=?")
        args.append(since)

    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)

    sql = (
        "SELECT event_id,timestamp_utc,event_type,source,profile,session_id,correlation_id,"
        "mode,severity,payload_json,tags_json "
        f"FROM event_log {where} ORDER BY timestamp_utc DESC LIMIT ?"
    )
    args.append(limit)

    with connect_db() as con:
        rows = con.execute(sql, args).fetchall()

    return [
        {
            "event_id": row["event_id"],
            "timestamp_utc": row["timestamp_utc"],
            "event_type": row["event_type"],
            "source": row["source"],
            "profile": row["profile"],
            "session_id": row["session_id"],
            "correlation_id": row["correlation_id"],
            "mode": row["mode"],
            "severity": row["severity"],
            "payload": parse_json(row["payload_json"], {}),
            "tags": parse_json(row["tags_json"], []),
        }
        for row in rows
    ]


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

    with connect_db() as con:
        intent = con.execute(
            "SELECT request_id,mode,session_id FROM intent_log WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if not intent:
            raise ValueError(f"request_id not found: {request_id}")

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

            denied_reason = None
            if row["safety_level"] == "high_risk" and not allow_high_risk:
                denied_reason = "high_risk action requires allow_high_risk=true"

            if denied_reason:
                con.execute(
                    """
                    UPDATE action_log
                    SET status='denied', error_message=?, ended_at_utc=?
                    WHERE id=?
                    """,
                    (denied_reason, utc_now_iso(), row["id"]),
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
                },
                session_id=intent["session_id"],
                correlation_id=request_id,
                mode=intent["mode"],
            )

            log_params = parse_json(row["parameters_json"], {})
            output = {
                "stub_execution": True,
                "dry_run": dry_run,
                "tool_name": row["tool_name"],
                "action_id": row["action_id"],
                "parameters": log_params,
                "result": "No adapter attached. Action simulated.",
            }
            ended_at = utc_now_iso()
            con.execute(
                """
                UPDATE action_log
                SET status='success', output_json=?, ended_at_utc=?
                WHERE id=?
                """,
                (json.dumps(output, ensure_ascii=False), ended_at, row["id"]),
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
                    "result": "simulated",
                },
                session_id=intent["session_id"],
                correlation_id=request_id,
                mode=intent["mode"],
            )
            results.append(
                {
                    "action_id": row["action_id"],
                    "tool_name": row["tool_name"],
                    "status": "success",
                    "output": output,
                }
            )

        con.commit()

    return {"request_id": request_id, "dry_run": dry_run, "results": results}


class BrainstemHandler(BaseHTTPRequestHandler):
    server_version = "WatchkeeperBrainstem/0.1"

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("request body is required")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        try:
            if parsed.path == "/health":
                self._send_json(200, {"ok": True, "service": "brainstem", "ts": utc_now_iso()})
                return

            if parsed.path == "/state":
                items = query_state(query)
                self._send_json(200, {"ok": True, "count": len(items), "items": items})
                return

            if parsed.path == "/events":
                items = query_events(query)
                self._send_json(200, {"ok": True, "count": len(items), "items": items})
                return

            self._send_json(404, {"ok": False, "error": "not_found"})
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        source = self.headers.get("X-Source", "brainstem_api")

        try:
            if parsed.path == "/state":
                body = self._read_json_body()
                validate_state_ingest(body)
                result = ingest_state(body, source=source)
                self._send_json(200, {"ok": True, **result})
                return

            if parsed.path == "/intent":
                body = self._read_json_body()
                validate_intent(body)
                with connect_db() as con:
                    action_count = upsert_intent(con, body, source=source)
                    con.commit()
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "request_id": body["request_id"],
                        "queued_actions": action_count,
                    },
                )
                return

            if parsed.path == "/execute":
                body = self._read_json_body()
                result = execute_actions(body, source=source)
                self._send_json(200, {"ok": True, **result})
                return

            if parsed.path == "/feedback":
                body = self._read_json_body()
                validate_feedback(body)
                result = record_feedback(body, source=source)
                self._send_json(200, {"ok": True, **result})
                return

            self._send_json(404, {"ok": False, "error": "not_found"})
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except sqlite3.IntegrityError as exc:
            self._send_json(409, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})


def main() -> None:
    ensure_db()
    server = ThreadingHTTPServer((HOST, PORT), BrainstemHandler)
    print(f"Brainstem API listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
