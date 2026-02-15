import json
import os
import re
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error, request
from urllib.parse import urlparse


HOST = os.getenv("WKV_ASSIST_HOST", "127.0.0.1")
PORT = int(os.getenv("WKV_ASSIST_PORT", "8791"))
BRAINSTEM_BASE_URL = os.getenv("WKV_BRAINSTEM_URL", "http://127.0.0.1:8787").rstrip("/")
KNOWLEDGE_BASE_URL = os.getenv("WKV_KNOWLEDGE_URL", "http://127.0.0.1:8790").rstrip("/")
ASSIST_DEFAULT_MODE = os.getenv("WKV_ASSIST_DEFAULT_MODE", "standby")
ASSIST_SOURCE = "assist_router"

MODE_SET = {"game", "work", "standby", "tutor"}
URGENCY_SET = {"low", "normal", "high"}
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

ASSIST_ALLOWED_KEYS = {
    "incident_id",
    "user_text",
    "mode",
    "domain",
    "urgency",
    "watch_condition",
    "stt_confidence",
    "session_id",
    "auto_execute",
    "dry_run",
    "allow_high_risk",
    "user_confirmed",
    "confirmed_at_utc",
    "use_knowledge",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso8601_utc(value: str) -> None:
    normalized = value.replace("Z", "+00:00")
    datetime.fromisoformat(normalized)


def _check_extra_keys(obj: dict[str, Any], allowed: set[str], obj_name: str) -> None:
    extra = sorted(set(obj.keys()) - allowed)
    if extra:
        raise ValueError(f"{obj_name} contains unsupported fields: {', '.join(extra)}")


def post_json(url: str, payload: dict[str, Any], source: str, timeout: int = 12) -> dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Source": source,
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc


def validate_assist_request(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    _check_extra_keys(payload, ASSIST_ALLOWED_KEYS, "assist_request")

    user_text = payload.get("user_text")
    if not isinstance(user_text, str) or not user_text.strip():
        raise ValueError("user_text is required and must be a non-empty string")

    mode = payload.get("mode", ASSIST_DEFAULT_MODE)
    if mode not in MODE_SET:
        raise ValueError(f"mode must be one of: {', '.join(sorted(MODE_SET))}")

    domain = payload.get("domain")
    if domain is not None and domain not in DOMAIN_SET:
        raise ValueError(f"domain must be one of: {', '.join(sorted(DOMAIN_SET))}")

    urgency = payload.get("urgency", "normal")
    if urgency not in URGENCY_SET:
        raise ValueError(f"urgency must be one of: {', '.join(sorted(URGENCY_SET))}")

    incident_id = payload.get("incident_id")
    if incident_id is not None and (not isinstance(incident_id, str) or not incident_id.strip()):
        raise ValueError("incident_id must be a non-empty string when supplied")

    watch_condition = payload.get("watch_condition")
    if watch_condition is not None:
        if not isinstance(watch_condition, str) or not watch_condition.strip():
            raise ValueError("watch_condition must be a non-empty string when supplied")
        allowed = {"STANDBY", "GAME", "WORK", "TUTOR", "RESTRICTED", "DEGRADED"}
        if watch_condition.strip().upper() not in allowed:
            raise ValueError(f"watch_condition must be one of: {', '.join(sorted(allowed))}")

    stt_confidence = payload.get("stt_confidence")
    if stt_confidence is not None:
        if not isinstance(stt_confidence, (int, float)) or stt_confidence < 0 or stt_confidence > 1:
            raise ValueError("stt_confidence must be number 0..1 when supplied")

    for key in ("auto_execute", "dry_run", "allow_high_risk", "user_confirmed", "use_knowledge"):
        if key in payload and not isinstance(payload[key], bool):
            raise ValueError(f"{key} must be boolean when supplied")

    session_id = payload.get("session_id")
    if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
        raise ValueError("session_id must be a non-empty string when supplied")

    confirmed_at_utc = payload.get("confirmed_at_utc")
    if confirmed_at_utc is not None:
        if not isinstance(confirmed_at_utc, str) or not confirmed_at_utc.strip():
            raise ValueError("confirmed_at_utc must be a non-empty string when supplied")
        try:
            parse_iso8601_utc(confirmed_at_utc)
        except Exception as exc:
            raise ValueError("confirmed_at_utc must be ISO-8601") from exc


def infer_domain(user_text: str) -> str:
    text = user_text.lower()
    if any(t in text for t in ["thargoid", "guardian", "lore", "galnet"]):
        return "lore"
    if any(t in text for t in ["python", "golang", "rust", "code", "coding", "compile"]):
        return "coding"
    if any(t in text for t in ["network", "dns", "router", "switch"]):
        return "networking"
    if any(t in text for t in ["music", "track", "song", "album"]):
        return "music"
    if any(t in text for t in ["ship", "jump", "hardpoint", "lights", "supercruise"]):
        return "gameplay"
    if any(t in text for t in ["cpu", "memory", "temperature", "system"]):
        return "system"
    return "general"


def infer_urgency(user_text: str) -> str:
    text = user_text.lower()
    if any(t in text for t in ["urgent", "immediately", "now now", "emergency"]):
        return "high"
    return "normal"


def propose_actions(user_text: str) -> list[dict[str, Any]]:
    text = user_text.lower()
    actions: list[dict[str, Any]] = []

    if "light" in text:
        scene = "default"
        if "combat" in text:
            scene = "combat"
        elif "exploration" in text:
            scene = "exploration"
        elif "docking" in text:
            scene = "docking"
        actions.append(
            {
                "action_id": "action_set_lights",
                "tool_name": "set_lights",
                "parameters": {"scene": scene},
                "safety_level": "low_risk",
                "mode_constraints": ["game", "standby"],
                "requires_confirmation": False,
                "timeout_ms": 1200,
                "reason": "User requested lighting change.",
                "confidence": 0.92,
            }
        )

    if any(p in text for p in ["pause music", "stop music", "music off"]):
        actions.append(
            {
                "action_id": "action_music_pause",
                "tool_name": "music_pause",
                "parameters": {},
                "safety_level": "low_risk",
                "mode_constraints": ["game", "work", "standby"],
                "requires_confirmation": False,
                "timeout_ms": 1200,
                "reason": "User requested music pause.",
                "confidence": 0.91,
            }
        )

    if any(p in text for p in ["resume music", "play music", "music on"]):
        actions.append(
            {
                "action_id": "action_music_resume",
                "tool_name": "music_resume",
                "parameters": {},
                "safety_level": "low_risk",
                "mode_constraints": ["game", "work", "standby"],
                "requires_confirmation": False,
                "timeout_ms": 1200,
                "reason": "User requested music resume.",
                "confidence": 0.9,
            }
        )

    if any(p in text for p in ["next track", "skip track", "skip song"]):
        actions.append(
            {
                "action_id": "action_music_next",
                "tool_name": "music_next",
                "parameters": {},
                "safety_level": "low_risk",
                "mode_constraints": ["game", "work", "standby"],
                "requires_confirmation": False,
                "timeout_ms": 1200,
                "reason": "User requested next track.",
                "confidence": 0.9,
            }
        )

    key_match = re.search(r"\bpress\s+([a-z0-9]+)\b", text)
    if key_match:
        key_name = key_match.group(1)
        actions.append(
            {
                "action_id": f"action_keypress_{key_name}",
                "tool_name": "keypress",
                "parameters": {"key": key_name},
                "safety_level": "high_risk",
                "mode_constraints": ["game"],
                "requires_confirmation": True,
                "timeout_ms": 800,
                "reason": "User requested keypress action.",
                "confidence": 0.78,
            }
        )

    return actions


def retrieve_context(user_text: str, domain: str) -> tuple[list[str], dict[str, Any]]:
    citations: list[str] = []
    meta: dict[str, Any] = {"facts_hits": 0, "vector_hits": 0}
    try:
        facts_result = post_json(
            f"{KNOWLEDGE_BASE_URL}/facts/query",
            {"q": user_text, "limit": 3},
            source=ASSIST_SOURCE,
        )
        facts_items = facts_result.get("items", []) if isinstance(facts_result, dict) else []
        for item in facts_items:
            triple_id = item.get("triple_id")
            if isinstance(triple_id, str) and triple_id:
                citations.append(triple_id)
        meta["facts_hits"] = len(facts_items)
    except Exception as exc:
        meta["facts_error"] = str(exc)

    try:
        vector_result = post_json(
            f"{KNOWLEDGE_BASE_URL}/vector/query",
            {
                "query_text": user_text,
                "domain": domain,
                "top_k": 3,
                "include_text": False,
            },
            source=ASSIST_SOURCE,
        )
        vector_items = vector_result.get("items", []) if isinstance(vector_result, dict) else []
        for item in vector_items:
            doc_id = item.get("doc_id")
            if isinstance(doc_id, str) and doc_id:
                citations.append(doc_id)
        meta["vector_hits"] = len(vector_items)
        if isinstance(vector_result, dict):
            meta["vector_backend"] = vector_result.get("backend")
    except Exception as exc:
        meta["vector_error"] = str(exc)

    # preserve order while removing duplicates
    deduped = list(dict.fromkeys(citations))
    return deduped, meta


def build_response_text(user_text: str, actions: list[dict[str, Any]]) -> str:
    if actions:
        tool_names = ", ".join(a["tool_name"] for a in actions)
        return f"Understood. I will run: {tool_names}."
    return f"Understood. No tool action required for: {user_text.strip()}"


def build_intent(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    user_text = payload["user_text"].strip()
    mode = payload.get("mode", ASSIST_DEFAULT_MODE)
    domain = payload.get("domain") or infer_domain(user_text)
    urgency = payload.get("urgency") or infer_urgency(user_text)
    session_id = payload.get("session_id") or f"assist-{uuid.uuid4().hex[:8]}"
    use_knowledge = payload.get("use_knowledge", True)

    actions = propose_actions(user_text)
    citations: list[str] = []
    retrieval_meta: dict[str, Any] = {"facts_hits": 0, "vector_hits": 0}
    retrieval_confidence = 0.0

    if use_knowledge:
        citations, retrieval_meta = retrieve_context(user_text, domain)
        total_hits = retrieval_meta.get("facts_hits", 0) + retrieval_meta.get("vector_hits", 0)
        retrieval_confidence = min(total_hits / 4.0, 1.0)

    intent = {
        "schema_version": "1.0",
        "request_id": str(uuid.uuid4()),
        "session_id": session_id,
        "timestamp_utc": utc_now_iso(),
        "mode": mode,
        "domain": domain,
        "urgency": urgency,
        "user_text": user_text,
        "needs_tools": bool(actions),
        "needs_clarification": False,
        "clarification_questions": [],
        "retrieval": {
            "citation_ids": citations,
            "confidence": retrieval_confidence,
        },
        "proposed_actions": actions,
        "response_text": build_response_text(user_text, actions),
    }
    return intent, retrieval_meta


def route_assist(payload: dict[str, Any]) -> dict[str, Any]:
    validate_assist_request(payload)
    auto_execute = payload.get("auto_execute", True)
    dry_run = payload.get("dry_run", True)
    allow_high_risk = payload.get("allow_high_risk", False)
    user_confirmed = payload.get("user_confirmed", False)
    watch_condition = (
        str(payload.get("watch_condition")).strip().upper() if payload.get("watch_condition") else None
    )
    incident_id = (payload.get("incident_id") or str(uuid.uuid4())).strip()
    stt_confidence = payload.get("stt_confidence")
    confirmed_at_utc = payload.get("confirmed_at_utc")
    if user_confirmed and not confirmed_at_utc:
        confirmed_at_utc = utc_now_iso()

    intent, retrieval_meta = build_intent(payload)
    intent_result = post_json(
        f"{BRAINSTEM_BASE_URL}/intent",
        intent,
        source=ASSIST_SOURCE,
    )

    execution_result: dict[str, Any] | None = None
    if auto_execute and intent["proposed_actions"]:
        execution_result = post_json(
            f"{BRAINSTEM_BASE_URL}/execute",
            {
                "request_id": intent["request_id"],
                "incident_id": incident_id,
                "dry_run": dry_run,
                "allow_high_risk": allow_high_risk,
                "user_confirmed": user_confirmed,
                "confirmed_at_utc": confirmed_at_utc,
                "watch_condition": watch_condition,
                "stt_confidence": stt_confidence,
            },
            source=ASSIST_SOURCE,
        )

    return {
        "ok": True,
        "request_id": intent["request_id"],
        "incident_id": incident_id,
        "mode": intent["mode"],
        "domain": intent["domain"],
        "urgency": intent["urgency"],
        "response_text": intent["response_text"],
        "proposed_actions": intent["proposed_actions"],
        "retrieval": intent["retrieval"],
        "retrieval_meta": retrieval_meta,
        "intent_result": intent_result,
        "execution_result": execution_result,
        "dry_run": dry_run,
    }


class AssistRouterHandler(BaseHTTPRequestHandler):
    server_version = "WatchkeeperAssistRouter/0.1"

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
        if parsed.path == "/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "assist_router",
                    "ts": utc_now_iso(),
                    "brainstem_url": BRAINSTEM_BASE_URL,
                    "knowledge_url": KNOWLEDGE_BASE_URL,
                },
            )
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/assist":
                body = self._read_json_body()
                result = route_assist(body)
                self._send_json(200, result)
                return
            self._send_json(404, {"ok": False, "error": "not_found"})
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), AssistRouterHandler)
    print(f"Assist router listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
