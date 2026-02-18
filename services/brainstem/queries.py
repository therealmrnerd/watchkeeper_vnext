from runtime import DB_SERVICE, parse_iso8601_utc


def query_state(query: dict[str, list[str]]) -> list[dict[str, object]]:
    key = (query.get("key", [None])[0] or "").strip()
    if key:
        item = DB_SERVICE.get_state(key)
        return [item] if item else []
    return DB_SERVICE.list_state(state_key=None)


def query_events(query: dict[str, list[str]]) -> list[dict[str, object]]:
    limit_raw = (query.get("limit", ["100"])[0] or "100").strip()
    event_type = (query.get("type", [None])[0] or "").strip()
    session_id = (query.get("session_id", [None])[0] or "").strip()
    correlation_id = (query.get("correlation_id", [None])[0] or "").strip()
    since = (query.get("since", [None])[0] or "").strip()

    try:
        limit = max(1, min(1000, int(limit_raw)))
    except ValueError:
        raise ValueError("limit must be an integer")

    if since:
        parse_iso8601_utc(since)
    return DB_SERVICE.list_events(
        limit=limit,
        event_type=event_type or None,
        session_id=session_id or None,
        correlation_id=correlation_id or None,
        since=since or None,
    )
