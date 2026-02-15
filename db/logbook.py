import json
import uuid
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Logbook:
    def __init__(self, db_service: Any | None = None, source: str = "policy_engine") -> None:
        self.db_service = db_service
        self.source = source

    def _emit(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        severity: str = "info",
        req_context: dict[str, Any] | None = None,
    ) -> None:
        req_context = req_context or {}
        timestamp_utc = _utc_now_iso()
        event_id = str(uuid.uuid4())
        session_id = req_context.get("session_id")
        correlation_id = req_context.get("request_id") or req_context.get("incident_id")
        mode = req_context.get("mode")
        tags = ["policy", "standing_orders"]

        if self.db_service is not None and hasattr(self.db_service, "append_event"):
            try:
                self.db_service.append_event(
                    event_id=event_id,
                    timestamp_utc=timestamp_utc,
                    event_type=event_type,
                    source=self.source,
                    payload=payload,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    mode=mode,
                    severity=severity,
                    tags=tags,
                )
                return
            except Exception:
                pass

        entry = {
            "event_id": event_id,
            "timestamp_utc": timestamp_utc,
            "event_type": event_type,
            "source": self.source,
            "severity": severity,
            "payload": payload,
            "context": req_context,
        }
        print(json.dumps(entry, ensure_ascii=False))

    def log_decision(
        self,
        *,
        incident_id: str,
        tool_name: str,
        decision: dict[str, Any],
        req_context: dict[str, Any] | None = None,
    ) -> None:
        req_context = req_context or {}
        self._emit(
            event_type="POLICY_DECISION",
            severity="warn" if not decision.get("allowed", False) else "info",
            payload={
                "incident_id": incident_id,
                "tool_name": tool_name,
                "decision": decision,
            },
            req_context=req_context | {"incident_id": incident_id},
        )

    def log_execute_result(
        self,
        *,
        incident_id: str,
        tool_name: str,
        ok: bool,
        result_or_error: Any,
        req_context: dict[str, Any] | None = None,
    ) -> None:
        req_context = req_context or {}
        self._emit(
            event_type="TOOL_EXECUTE_RESULT",
            severity="info" if ok else "error",
            payload={
                "incident_id": incident_id,
                "tool_name": tool_name,
                "ok": ok,
                "result_or_error": result_or_error,
            },
            req_context=req_context | {"incident_id": incident_id},
        )
