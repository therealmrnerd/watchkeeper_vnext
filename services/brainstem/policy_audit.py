from typing import Any


POLICY_EVENT_TYPES = {"POLICY_DECISION", "TOOL_EXECUTE_RESULT"}


def recent_policy_audit(
    db_service: Any,
    *,
    limit: int = 100,
    incident_id: str | None = None,
    tool_name: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    capped_limit = max(1, min(int(limit), 1000))
    rows = db_service.list_events(limit=max(capped_limit * 4, 100), since=since)
    items: list[dict[str, Any]] = []

    for row in rows:
        if row.get("event_type") not in POLICY_EVENT_TYPES:
            continue

        payload = row.get("payload") or {}
        detail = payload.get("payload", payload)
        event_incident = detail.get("incident_id")
        event_tool = detail.get("tool_name")
        if incident_id and event_incident != incident_id:
            continue
        if tool_name and event_tool != tool_name:
            continue

        items.append(
            {
                "event_id": row.get("event_id"),
                "timestamp_utc": row.get("timestamp_utc"),
                "event_type": row.get("event_type"),
                "severity": row.get("severity"),
                "incident_id": event_incident,
                "tool_name": event_tool,
                "detail": detail,
                "context": payload.get("context", {}),
            }
        )
        if len(items) >= capped_limit:
            break

    return {
        "count": len(items),
        "limit": capped_limit,
        "items": items,
    }
