import json
import re
import time
import sqlite3
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime import (
    ADVISORY_HEALTH_URL,
    ADVISORY_LLM_STATUS_URL,
    COMMIT,
    DB_PATH,
    DB_SERVICE,
    ENABLE_KEYPRESS,
    ED_PROVIDER_QUERY_SERVICE,
    KNOWLEDGE_HEALTH_URL,
    LOG_DIR,
    PORT,
    PROVIDER_CONFIG_PATH,
    PROVIDER_SECRETS_PATH,
    QDRANT_HEALTH_URL,
    SNAPSHOT_DIR,
    START_TS,
    STANDING_ORDERS_PATH,
    TWITCH_REPO,
    VERSION,
    connect_db,
    parse_iso8601_utc,
)
from core.ed_provider_types import ProviderId, ProviderOperationId, ProviderQuery
from provider_config import load_runtime_provider_config
from provider_health import list_provider_health
from provider_query import query_provider_health
from obs_client import fetch_obs_status, OBS_HOST, OBS_PORT, OBS_TIMEOUT_SEC
from provider_secrets import get_provider_secret_entry
from settings_store import apply_runtime_settings_overrides, load_runtime_settings, runtime_setting_enabled
from mfd_layout_store import (
    BUTTON_REGIONS,
    CONTEXT_IDS,
    CONTROL_IDS,
    PANE_IDS,
    get_layout,
    get_output_layout,
    list_layouts,
    list_outputs,
)

try:
    from tools.diag_report import build_diag_report
except Exception:
    build_diag_report = None  # type: ignore


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def query_mfd_layouts(query: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "ok": True,
        "layouts": list_layouts(Path(DB_PATH)),
        "catalog": {
            "panes": sorted(PANE_IDS),
            "controls": sorted(CONTROL_IDS),
            "contexts": sorted(CONTEXT_IDS),
            "button_regions": list(BUTTON_REGIONS),
        },
    }


def query_mfd_layout(layout_id: str) -> dict[str, Any]:
    layout = get_layout(Path(DB_PATH), layout_id)
    if not layout:
        raise ValueError("mfd layout not found")
    return {"ok": True, "layout": layout}


def query_mfd_outputs(query: dict[str, list[str]]) -> dict[str, Any]:
    return {"ok": True, "outputs": list_outputs(Path(DB_PATH))}


def query_mfd_output_layout(output_id: int) -> dict[str, Any]:
    output = get_output_layout(Path(DB_PATH), output_id)
    if not output:
        raise ValueError("mfd output not found")
    return {"ok": True, "output": output}


def _as_json(raw: Any, fallback: Any) -> Any:
    if raw is None:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _probe_service(name: str, url: str, timeout_sec: float = 1.0) -> dict[str, Any]:
    if not url:
        return {"name": name, "ok": False, "status": "disabled", "url": url}
    req = urllib.request.Request(url, method="GET")
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            status = int(getattr(resp, "status", 200))
            body = resp.read().decode("utf-8", errors="replace")
        latency_ms = int((time.time() - started) * 1000)
        parsed = {}
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {}
        return {
            "name": name,
            "ok": status < 400,
            "status": "up" if status < 400 else "degraded",
            "url": url,
            "http_status": status,
            "latency_ms": latency_ms,
            "detail": parsed if isinstance(parsed, dict) else {},
        }
    except urllib.error.HTTPError as exc:
        return {
            "name": name,
            "ok": False,
            "status": "down",
            "url": url,
            "http_status": int(exc.code),
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "status": "down",
            "url": url,
            "error": str(exc),
        }


def _fetch_json(url: str, *, timeout_sec: float = 4.0) -> dict[str, Any]:
    if not url:
        raise ValueError("url is required")
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    parsed = json.loads(body) if body else {}
    if not isinstance(parsed, dict):
        raise ValueError("response must be a JSON object")
    return parsed


def _state_map() -> dict[str, Any]:
    rows = DB_SERVICE.list_state()
    out: dict[str, Any] = {}
    for row in rows:
        key = str(row.get("state_key") or "").strip()
        if key:
            out[key] = row.get("state_value")
    return out


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _state_value_with_fallback(state: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in state:
            return state.get(key)
    return None


def _empty_nav_route() -> dict[str, Any]:
    return {}


def _route_system_name(value: Any) -> str:
    return str(value or "").strip().casefold()


def _route_system_address(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nav_route_current_index(
    route: list[Any],
    *,
    current_system: Any = None,
    current_system_address: Any = None,
) -> int:
    current_address = _route_system_address(current_system_address)
    if current_address is not None:
        for index, step in enumerate(route):
            if isinstance(step, dict) and _route_system_address(step.get("SystemAddress")) == current_address:
                return index
    current_name = _route_system_name(current_system)
    if current_name:
        for index, step in enumerate(route):
            if isinstance(step, dict) and _route_system_name(step.get("StarSystem")) == current_name:
                return index
    return 0


def _route_distance_ly(origin: Any, destination: Any) -> float | str:
    first_pos = origin.get("StarPos") if isinstance(origin, dict) else None
    last_pos = destination.get("StarPos") if isinstance(destination, dict) else None
    if (
        isinstance(first_pos, list)
        and isinstance(last_pos, list)
        and len(first_pos) >= 3
        and len(last_pos) >= 3
        and all(isinstance(value, (int, float)) for value in first_pos[:3] + last_pos[:3])
    ):
        return round(sum((float(last_pos[i]) - float(first_pos[i])) ** 2 for i in range(3)) ** 0.5, 2)
    return ""


def _read_nav_route_fallback(*, current_system: Any = None, current_system_address: Any = None) -> dict[str, Any]:
    path = Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous" / "NavRoute.json"
    if not path.exists():
        return _empty_nav_route()
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_nav_route()
    route = parsed.get("Route")
    if not isinstance(route, list):
        return _empty_nav_route()
    systems = [
        step.get("StarSystem")
        for step in route
        if isinstance(step, dict) and isinstance(step.get("StarSystem"), str) and step.get("StarSystem").strip()
    ]
    if not systems:
        return _empty_nav_route()
    current_index = _nav_route_current_index(
        route,
        current_system=current_system,
        current_system_address=current_system_address,
    )
    current_index = max(0, min(current_index, len(systems) - 1))
    first = route[current_index] if current_index < len(route) and isinstance(route[current_index], dict) else {}
    last = route[-1] if isinstance(route[-1], dict) else {}
    distance_ly = _route_distance_ly(first, last)
    origin = systems[current_index]
    destination = systems[-1]
    next_jump = systems[current_index + 1] if current_index + 1 < len(systems) else ""
    upcoming_jumps = systems[current_index + 1:current_index + 4]
    remaining_jumps = max(0, len(systems) - current_index - 1)
    if remaining_jumps <= 0 or not next_jump:
        return _empty_nav_route()
    if remaining_jumps == 0:
        text = f"Course set for {destination}"
    elif remaining_jumps == 1:
        text = f"Course set for {destination} from {origin}"
    else:
        text = f"Course set for {destination} from {origin} via {', '.join(systems[current_index + 1:-1])}"
    return {
        "nav_route": text,
        "nav_route_origin": origin,
        "nav_route_destination": destination,
        "nav_route_next_jump": next_jump,
        "nav_route_upcoming_jumps": upcoming_jumps,
        "nav_route_remaining_jumps": remaining_jumps,
        "nav_route_distance_ly": distance_ly,
    }


def _ed_running_from_state(state: dict[str, Any]) -> bool:
    value = _state_value_with_fallback(
        state,
        "ed.status.running",
        "ed.running",
        "ed.telemetry.running",
    )
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _provider_unavailable_payload(
    *,
    operation: str,
    reason: str,
    error: str,
    system_name: str | None = None,
    system_address: int | str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_block = {
        "system_name": system_name,
        "system_address": system_address,
    }
    return {
        "ok": False,
        "provider": None,
        "operation": operation,
        "fetched_at": _utc_now_iso(),
        "cache": {"hit": False, "age_s": None, "ttl_s": None, "stale_served": False},
        "provenance": {"endpoint": None, "http_code": None},
        "data": data or {},
        "error": error,
        "deny_reason": reason,
        "current_system_state": state_block,
    }


def _clean_name(value: Any) -> str:
    return " ".join(str(value or "").replace("$", " ").split()).strip()


def _names_match(left: Any, right: Any) -> bool:
    a = _clean_name(left).casefold()
    b = _clean_name(right).casefold()
    if not a or not b:
        return False
    return a == b or a.endswith(f" {b}") or b.endswith(f" {a}")


def _lookup_edsm_target_context(
    *,
    system_name: Any,
    target_name: Any,
    target: dict[str, Any],
    semantic: dict[str, Any],
) -> dict[str, Any] | None:
    name = _clean_name(target_name)
    system = _clean_name(system_name)
    if not name or not system:
        return None
    if target.get("ship") or target.get("ship_localised"):
        return None
    target_type = str(semantic.get("target_type") or "").strip().lower()
    if target_type in {"ship", "vessel", "fighter", "srv"}:
        return None
    params = {"system_name": system}
    common = {
        "max_age_s": 86400,
        "allow_stale_if_error": True,
        "incident_id": None,
        "reason": "mfd_non_vessel_target_context",
    }
    try:
        stations = ED_PROVIDER_QUERY_SERVICE.execute(
            ProviderQuery(
                provider=ProviderId.EDSM,
                operation=ProviderOperationId.STATIONS_LOOKUP,
                params=params,
                **common,
            )
        ).to_dict()
        station_items = ((stations.get("data") or {}).get("items") or []) if isinstance(stations, dict) else []
        for item in station_items:
            if isinstance(item, dict) and _names_match(item.get("name"), name):
                return {
                    "kind": "station",
                    "source": "edsm",
                    "query": {"system_name": system, "target_name": name},
                    "data": item,
                    "provider": stations.get("provider"),
                    "fetched_at": stations.get("fetched_at"),
                }
    except Exception:
        pass

    try:
        bodies = ED_PROVIDER_QUERY_SERVICE.execute(
            ProviderQuery(
                provider=ProviderId.EDSM,
                operation=ProviderOperationId.BODIES_LOOKUP,
                params=params,
                **common,
            )
        ).to_dict()
        body_items = ((bodies.get("data") or {}).get("items") or []) if isinstance(bodies, dict) else []
        for item in body_items:
            if isinstance(item, dict) and _names_match(item.get("name"), name):
                return {
                    "kind": "body",
                    "source": "edsm",
                    "query": {"system_name": system, "target_name": name},
                    "data": item,
                    "provider": bodies.get("provider"),
                    "fetched_at": bodies.get("fetched_at"),
                }
    except Exception:
        pass
    return None


def _query_capabilities() -> list[dict[str, Any]]:
    with connect_db() as con:
        rows = con.execute(
            """
            SELECT capability_name,status,source,details_json,updated_at_utc
            FROM capabilities
            ORDER BY capability_name ASC
            """
        ).fetchall()
    return [
        {
            "capability_name": row["capability_name"],
            "status": row["status"],
            "source": row["source"],
            "details": _as_json(row["details_json"], {}),
            "updated_at_utc": row["updated_at_utc"],
        }
        for row in rows
    ]


def _schema_version() -> str:
    with connect_db() as con:
        row = con.execute(
            "SELECT value_json FROM config WHERE key='schema_version' LIMIT 1"
        ).fetchone()
    if not row:
        return "unknown"
    return str(_as_json(row["value_json"], row["value_json"]))


def _last_error(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events:
        if str(event.get("severity") or "").lower() == "error":
            return {
                "event_type": event.get("event_type"),
                "timestamp_utc": event.get("timestamp_utc"),
                "source": event.get("source"),
                "payload": event.get("payload"),
            }
    return None


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


def query_twitch_user(user_id: str, *, redeem_limit: int = 5) -> dict[str, Any]:
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required")
    context = TWITCH_REPO.get_user_context(uid, redeem_limit=redeem_limit)
    return {"ok": True, "user_id": uid, **context}


def query_twitch_redeems_top(user_id: str, *, limit: int = 5) -> dict[str, Any]:
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required")
    capped = max(1, min(50, int(limit or 5)))
    items = TWITCH_REPO.get_top_redeems(uid, limit=capped)
    return {"ok": True, "user_id": uid, "limit": capped, "items": items}


def query_twitch_recent(query: dict[str, list[str]]) -> dict[str, Any]:
    limit_raw = (query.get("limit", ["50"])[0] or "50").strip()
    event_type = (query.get("type", [None])[0] or "").strip()
    try:
        limit = max(1, min(500, int(limit_raw)))
    except ValueError:
        raise ValueError("limit must be an integer")
    items = TWITCH_REPO.list_recent(limit=limit, event_type=event_type or None)
    return {"ok": True, "limit": limit, "count": len(items), "items": items}


def query_providers_health(query: dict[str, list[str]]) -> dict[str, Any]:
    payload = query_provider_health(Path(DB_PATH), PROVIDER_CONFIG_PATH, PROVIDER_SECRETS_PATH)
    provider_filter = str((query.get("provider", [""])[0] or "")).strip().lower()
    if provider_filter:
        return {
            "ok": True,
            "provider": provider_filter,
            "item": payload.get("providers", {}).get(provider_filter),
        }
    return payload


def query_inara_credentials(query: dict[str, list[str]]) -> dict[str, Any]:
    settings = load_runtime_settings(Path(DB_PATH))
    config = apply_runtime_settings_overrides(
        load_runtime_provider_config(PROVIDER_CONFIG_PATH, PROVIDER_SECRETS_PATH),
        settings,
    )
    providers = config.get("providers", {})
    inara_cfg = providers.get("inara") if isinstance(providers, dict) else {}
    if not isinstance(inara_cfg, dict):
        inara_cfg = {}
    auth = inara_cfg.get("auth") if isinstance(inara_cfg.get("auth"), dict) else {}
    secure_auth = get_provider_secret_entry("inara", PROVIDER_SECRETS_PATH)

    commander_name = str(secure_auth.get("commander_name") or auth.get("commander_name") or "").strip()
    frontier_id_raw = secure_auth.get("frontier_id")
    if frontier_id_raw in (None, ""):
        frontier_id_raw = auth.get("frontier_id")
    frontier_id = str(frontier_id_raw).strip() if frontier_id_raw not in (None, "") else ""
    app_key_present = bool(str(secure_auth.get("app_key") or auth.get("app_key") or "").strip())
    secret_updated_at = str(secure_auth.get("_updated_at_utc") or "").strip() or None
    app_name = str(auth.get("app_name") or "").strip()

    return {
        "ok": True,
        "provider": "inara",
        "enabled": bool(inara_cfg.get("enabled")),
        "storage": {
            "encrypted": True,
            "path": str(Path(PROVIDER_SECRETS_PATH).resolve()),
            "exists": Path(PROVIDER_SECRETS_PATH).exists(),
            "secure_store_present": bool(secure_auth),
            "last_updated_at": secret_updated_at,
        },
        "auth": {
            "app_name": app_name or None,
            "configured": bool(app_name and app_key_present and commander_name),
        },
        "credentials": {
            "commander_name": commander_name,
            "frontier_id": frontier_id,
            "api_key_present": app_key_present,
            "api_key_source": (
                "secure_store"
                if bool(str(secure_auth.get("app_key") or "").strip())
                else ("config" if bool(str(auth.get("app_key") or "").strip()) else None)
            ),
            "last_updated_at": secret_updated_at,
        },
    }


def query_edsm_credentials(query: dict[str, list[str]]) -> dict[str, Any]:
    settings = load_runtime_settings(Path(DB_PATH))
    config = apply_runtime_settings_overrides(
        load_runtime_provider_config(PROVIDER_CONFIG_PATH, PROVIDER_SECRETS_PATH),
        settings,
    )
    providers = config.get("providers", {})
    edsm_cfg = providers.get("edsm") if isinstance(providers, dict) else {}
    if not isinstance(edsm_cfg, dict):
        edsm_cfg = {}
    auth = edsm_cfg.get("auth") if isinstance(edsm_cfg.get("auth"), dict) else {}
    secure_auth = get_provider_secret_entry("edsm", PROVIDER_SECRETS_PATH)

    commander_name = str(secure_auth.get("commander_name") or auth.get("commander_name") or "").strip()
    api_key_present = bool(str(secure_auth.get("api_key") or auth.get("api_key") or "").strip())
    secret_updated_at = str(secure_auth.get("_updated_at_utc") or "").strip() or None

    return {
        "ok": True,
        "provider": "edsm",
        "enabled": bool(edsm_cfg.get("enabled")),
        "storage": {
            "encrypted": True,
            "path": str(Path(PROVIDER_SECRETS_PATH).resolve()),
            "exists": Path(PROVIDER_SECRETS_PATH).exists(),
            "secure_store_present": bool(secure_auth),
            "last_updated_at": secret_updated_at,
        },
        "auth": {
            "configured": bool(api_key_present and commander_name),
        },
        "credentials": {
            "commander_name": commander_name,
            "api_key_present": api_key_present,
            "api_key_source": (
                "secure_store"
                if bool(str(secure_auth.get("api_key") or "").strip())
                else ("config" if bool(str(auth.get("api_key") or "").strip()) else None)
            ),
            "last_updated_at": secret_updated_at,
        },
    }


def query_openai_credentials(query: dict[str, list[str]]) -> dict[str, Any]:
    secure_auth = get_provider_secret_entry("openai", PROVIDER_SECRETS_PATH)
    api_key_present = bool(str(secure_auth.get("api_key") or "").strip())
    secret_updated_at = str(secure_auth.get("_updated_at_utc") or "").strip() or None
    return {
        "ok": True,
        "provider": "openai",
        "storage": {
            "encrypted": True,
            "path": str(Path(PROVIDER_SECRETS_PATH).resolve()),
            "exists": Path(PROVIDER_SECRETS_PATH).exists(),
            "secure_store_present": bool(secure_auth),
            "last_updated_at": secret_updated_at,
        },
        "credentials": {
            "api_key_present": api_key_present,
            "api_key_source": "secure_store" if api_key_present else None,
            "last_updated_at": secret_updated_at,
        },
        "usage": {
            "wired": True,
            "ready_for_cloud_fallback": api_key_present,
            "note": (
                "Cloud fallback key is present in the encrypted keystore and advisory can use it when enabled."
                if api_key_present
                else "OpenAI cloud fallback is wired, but no encrypted API key is stored."
            ),
        },
    }


def query_runtime_settings(query: dict[str, list[str]]) -> dict[str, Any]:
    settings = load_runtime_settings(Path(DB_PATH))
    effective_provider_config = apply_runtime_settings_overrides(
        load_runtime_provider_config(PROVIDER_CONFIG_PATH, PROVIDER_SECRETS_PATH),
        settings,
    )
    providers_cfg = effective_provider_config.get("providers", {})
    if isinstance(settings.get("providers"), dict):
        for provider_id, item in settings["providers"].items():
            provider_cfg = providers_cfg.get(provider_id) if isinstance(providers_cfg, dict) else None
            if isinstance(item, dict) and isinstance(provider_cfg, dict):
                item["enabled"] = bool(provider_cfg.get("enabled"))
    return {
        "ok": True,
        "settings": settings,
    }


def query_llm_status(query: dict[str, list[str]]) -> dict[str, Any]:
    del query
    try:
        payload = _fetch_json(ADVISORY_LLM_STATUS_URL, timeout_sec=4.0)
        return payload if isinstance(payload, dict) else {"ok": False, "error": "invalid_response"}
    except Exception as exc:
        return {
            "ok": False,
            "status": "down",
            "error": str(exc),
            "llm": {"loaded": False, "loading": False},
        }


def query_obs_status(query: dict[str, list[str]]) -> dict[str, Any]:
    settings = load_runtime_settings(Path(DB_PATH))
    obs_provider_enabled = runtime_setting_enabled(settings, "providers", "obs", False)
    obs_status_enabled = runtime_setting_enabled(settings, "syncs", "obs_status", False)
    if not obs_provider_enabled or not obs_status_enabled:
        reasons = []
        if not obs_provider_enabled:
            reasons.append("provider disabled")
        if not obs_status_enabled:
            reasons.append("status polling disabled")
        return {
            "ok": True,
            "status": "disabled",
            "enabled": {
                "provider": obs_provider_enabled,
                "status_polling": obs_status_enabled,
            },
            "endpoint": {
                "host": OBS_HOST,
                "port": OBS_PORT,
            },
            "message": " | ".join(reasons) if reasons else "disabled by settings",
        }

    payload = fetch_obs_status(host=OBS_HOST, port=OBS_PORT, timeout_sec=OBS_TIMEOUT_SEC)
    payload["enabled"] = {
        "provider": obs_provider_enabled,
        "status_polling": obs_status_enabled,
    }
    return payload


def query_ed_control_profile(query: dict[str, list[str]]) -> dict[str, Any]:
    del query
    state = _state_map()
    ed_running = _ed_running_from_state(state)
    semantic = {
        "player_platform": state.get("ed.semantic.context.player_platform"),
        "on_foot_area": state.get("ed.semantic.context.on_foot_area"),
        "control_profile": state.get("ed.semantic.interface.control_profile"),
        "no_fire_zone": state.get("ed.semantic.station.no_fire_zone"),
        "station_services_available": state.get("ed.semantic.opportunity.station_services_available"),
        "market_access_available": state.get("ed.semantic.opportunity.market_access_available"),
    }
    return {
        "ok": True,
        "ed_running": ed_running,
        "recommended_profile": semantic["control_profile"] or "unknown",
        "semantic": semantic,
        "note": "Read-only recommendation endpoint for future SAMMI deck switching.",
    }


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _cockpit_action_intent(
    *,
    tool: str,
    action: str,
    parameters: dict[str, Any] | None = None,
    requires_confirmation: bool = True,
) -> dict[str, Any]:
    return {
        "recommended_action": {
            "tool": tool,
            "action": action,
            "parameters": parameters or {},
            "requires_confirmation": bool(requires_confirmation),
        }
    }


def query_cockpit_state(query: dict[str, list[str]]) -> dict[str, Any]:
    del query
    state = _state_map()
    ed_running = _ed_running_from_state(state)
    semantic_safe_for_keypress = _as_bool(
        _state_value_with_fallback(
            state,
            "ed.semantic.interaction.safe_for_keypress",
            "ed.running",
        )
    )
    obs_status = query_obs_status({})
    obs_up = bool(obs_status.get("ok")) and str(obs_status.get("status") or "").lower() == "up"

    module_items = state.get("ed.modules.items") if isinstance(state.get("ed.modules.items"), list) else []
    hardpoints = [
        item
        for item in module_items
        if isinstance(item, dict)
        and (
            re.search(r"(small|medium|large|huge)hardpoint\d+", str(item.get("slot") or ""), re.IGNORECASE)
            or (
                str(item.get("item") or "").lower().startswith("hpt_")
                and not re.search(
                    r"shieldbooster|chaff|heatsink|pointdefen[cs]e|ecm|killwarrant|wake|xenoscanner|manifest|shutdownfield|causticsink|pulsewave|dockingcomputer|supercruiseassist",
                    str(item.get("item") or ""),
                    re.IGNORECASE,
                )
            )
        )
        and str(item.get("item") or "").strip()
    ]
    has_limpet_controller = any(
        isinstance(item, dict) and "dronecontrol" in str(item.get("item") or "").lower()
        for item in module_items
    )
    has_cargo_rack = any(
        isinstance(item, dict) and "cargorack" in str(item.get("item") or "").lower()
        for item in module_items
    )

    journal_fighter_active = _as_bool(state.get("ed.fighter.active"))
    journal_srv_active = _as_bool(state.get("ed.srv.active"))
    on_foot = bool(ed_running and _as_bool(state.get("ed.status.on_foot")))
    on_foot_in_station = bool(ed_running and _as_bool(state.get("ed.status.on_foot_in_station")))
    on_foot_on_planet = bool(ed_running and _as_bool(state.get("ed.status.on_foot_on_planet")))
    on_foot_in_hangar = bool(ed_running and _as_bool(state.get("ed.status.on_foot_in_hangar")))
    on_foot_social_space = bool(ed_running and _as_bool(state.get("ed.status.on_foot_social_space")))
    on_foot_exterior = bool(ed_running and _as_bool(state.get("ed.status.on_foot_exterior")))
    in_fighter = bool(ed_running and not on_foot and (_as_bool(state.get("ed.status.in_fighter")) or journal_fighter_active))
    in_srv = bool(ed_running and not on_foot and (_as_bool(state.get("ed.status.in_srv")) or journal_srv_active))
    in_main_ship = _as_bool(state.get("ed.status.in_main_ship"))
    has_lat_long = bool(ed_running and _as_bool(state.get("ed.status.has_lat_long")))
    supercruise = bool(ed_running and _as_bool(state.get("ed.status.supercruise")))
    glide_mode = bool(ed_running and _as_bool(state.get("ed.status.glide_mode")) and not supercruise)
    landed = bool(ed_running and _as_bool(state.get("ed.status.landed")))
    if on_foot_on_planet:
        planetary_status = "On Foot"
    elif landed:
        planetary_status = "Landed"
    elif glide_mode:
        planetary_status = "Glide"
    elif supercruise and has_lat_long:
        planetary_status = "OC"
    elif has_lat_long:
        planetary_status = "Normal Flight"
    else:
        planetary_status = None
    fighter_model = _first_present(state.get("ed.fighter.model"), "taipan" if in_fighter else None)
    fighter_name = _first_present(
        state.get("ed.fighter.model_localised"),
        "Taipan" if in_fighter else None,
    )
    srv_model = _first_present(state.get("ed.srv.model"), "scarab-srv" if in_srv else None)
    srv_name = _first_present(state.get("ed.srv.model_localised"), "Scarab SRV" if in_srv else None)
    active_vehicle = "foot" if on_foot else ("fighter" if in_fighter else ("srv" if in_srv else "ship"))
    mothership_model = _first_present(
        state.get("ed.status.ship_model"),
        state.get("ed.telemetry.ship_model"),
        state.get("ed.modules.ship"),
    )
    mothership_name = _first_present(
        state.get("ed.status.ship_name"),
        state.get("ed.telemetry.ship_name"),
        state.get("ed.modules.ship_name"),
    )
    current_system_name = _state_value_with_fallback(
        state,
        "ed.location.system",
        "ed.status.system_name",
        "ed.telemetry.system_name",
    )
    current_system_address = _state_value_with_fallback(
        state,
        "ed.location.system_address",
        "ed.status.system_address",
        "ed.telemetry.system_address",
    )
    raw_docking_state_for_station = str(state.get("ed.station.docking_state") or "").strip().lower()
    station_context_active = bool(
        _as_bool(state.get("ed.status.docked"))
        or on_foot_in_station
        or on_foot_in_hangar
        or on_foot_social_space
        or _as_bool(state.get("ed.semantic.opportunity.station_services_available"))
        or _as_bool(state.get("ed.semantic.station.no_fire_zone"))
        or raw_docking_state_for_station in {"requested", "granted", "approaching", "docking", "docked"}
    )
    station_value = None
    if station_context_active:
        for station_key in (
            "ed.location.station",
            "ed.telemetry.station_name",
            "ed.station.docking_target_name",
            "ed.station.docking_state_station",
            "ed.station.no_fire_zone_station",
        ):
            candidate = state.get(station_key)
            if isinstance(candidate, str) and candidate.strip():
                station_value = candidate.strip()
                break
            if candidate not in (None, ""):
                station_value = candidate
                break
    nav_route_fallback = (
        _read_nav_route_fallback(
            current_system=current_system_name,
            current_system_address=current_system_address,
        )
        if ed_running
        else {}
    )

    telemetry = {
        "running": ed_running,
        "process_name": state.get("ed.process_name"),
        "status_available": _as_bool(state.get("ed.status.available")),
        "ship_name": mothership_name,
        "ship_model": mothership_model,
        "mothership_name": mothership_name,
        "mothership_model": mothership_model,
        "active_vehicle": active_vehicle,
        "in_main_ship": in_main_ship,
        "in_fighter": in_fighter,
        "in_srv": in_srv,
        "on_foot": on_foot,
        "on_foot_in_station": on_foot_in_station,
        "on_foot_on_planet": on_foot_on_planet,
        "on_foot_in_hangar": on_foot_in_hangar,
        "on_foot_social_space": on_foot_social_space,
        "on_foot_exterior": on_foot_exterior,
        "suit": {
            "id": state.get("ed.suit.id"),
            "name": state.get("ed.suit.name"),
            "name_localised": state.get("ed.suit.name_localised"),
            "loadout_id": state.get("ed.suit.loadout_id"),
            "loadout_name": state.get("ed.suit.loadout_name"),
            "modules": state.get("ed.suit.modules") if isinstance(state.get("ed.suit.modules"), list) else [],
            "updated_at": state.get("ed.suit.updated_at"),
            "selected_weapon": state.get("ed.status.selected_weapon"),
            "selected_weapon_localised": state.get("ed.status.selected_weapon_localised"),
            "aim_down_sight": _as_bool(state.get("ed.status.aim_down_sight")),
            "low_oxygen": _as_bool(state.get("ed.status.low_oxygen")),
            "low_health": _as_bool(state.get("ed.status.low_health")),
            "cold": _as_bool(state.get("ed.status.cold")),
            "hot": _as_bool(state.get("ed.status.hot")),
            "very_cold": _as_bool(state.get("ed.status.very_cold")),
            "very_hot": _as_bool(state.get("ed.status.very_hot")),
            "breathable_atmosphere": _as_bool(state.get("ed.status.breathable_atmosphere")),
        },
        "fighter": {
            "active": _as_bool(state.get("ed.fighter.active")) or in_fighter,
            "last_event": state.get("ed.fighter.last_event"),
            "updated_at": state.get("ed.fighter.updated_at"),
            "loadout": state.get("ed.fighter.loadout"),
            "id": state.get("ed.fighter.id"),
            "model": fighter_model if in_fighter else state.get("ed.fighter.model"),
            "model_localised": state.get("ed.fighter.model_localised"),
            "player_controlled": state.get("ed.fighter.player_controlled"),
            "shield_health_percent": _first_present(
                state.get("ed.fighter.shield_health_percent"),
                state.get("ed.fighter.shield_percent"),
                state.get("ed.fighter.shield"),
            ),
            "hull_health_percent": _first_present(
                state.get("ed.fighter.hull_health_percent"),
                state.get("ed.fighter.hull_percent"),
                state.get("ed.fighter.hull"),
            ),
        },
        "srv": {
            "active": in_srv,
            "model": srv_model,
            "model_localised": srv_name,
            "last_event": state.get("ed.srv.last_event"),
            "updated_at": state.get("ed.srv.updated_at"),
            "id": state.get("ed.srv.id"),
            "mothership_name": mothership_name,
            "mothership_model": mothership_model,
        },
        "ship_ident": _first_present(
            state.get("ed.status.ship_ident"),
            state.get("ed.telemetry.ship_ident"),
            state.get("ed.modules.ship_ident"),
        ),
        "system": current_system_name,
        "system_address": current_system_address,
        "station": station_value,
        "body": _state_value_with_fallback(state, "ed.location.body", "ed.status.body_name"),
        "destination_name": state.get("ed.telemetry.destination_name"),
        "destination_system": state.get("ed.telemetry.destination_system"),
        "destination_body": state.get("ed.telemetry.destination_body"),
        "destination_body_type": state.get("ed.telemetry.destination_body_type"),
        "destination_star_class": state.get("ed.telemetry.destination_star_class"),
        "destination_remaining_jumps": state.get("ed.telemetry.destination_remaining_jumps"),
        "star_class": _state_value_with_fallback(
            state,
            "ed.system.star_class",
            "ed.telemetry.star_class",
        ),
        "nav_route": state.get("nav_route") or nav_route_fallback.get("nav_route"),
        "nav_route_origin": state.get("nav_route_origin") or nav_route_fallback.get("nav_route_origin"),
        "nav_route_destination": state.get("nav_route_destination") or nav_route_fallback.get("nav_route_destination"),
        "nav_route_next_jump": state.get("nav_route_next_jump") or nav_route_fallback.get("nav_route_next_jump"),
        "nav_route_upcoming_jumps": (
            state.get("nav_route_upcoming_jumps")
            if isinstance(state.get("nav_route_upcoming_jumps"), list)
            else nav_route_fallback.get("nav_route_upcoming_jumps")
        ),
        "nav_route_remaining_jumps": state.get("nav_route_remaining_jumps") or nav_route_fallback.get("nav_route_remaining_jumps"),
        "nav_route_distance_ly": state.get("nav_route_distance_ly") or nav_route_fallback.get("nav_route_distance_ly"),
        "on_foot_location": state.get("ed.telemetry.on_foot_location"),
        "planetary_status": planetary_status,
        "has_lat_long": has_lat_long,
        "glide_mode": glide_mode,
        "altitude_from_average_radius": _as_bool(state.get("ed.status.altitude_from_average_radius")),
        "last_event": state.get("ed.journal.last_event"),
        "flags": state.get("ed.status.flags"),
        "flags2": state.get("ed.status.flags2"),
        "gui_focus": state.get("ed.status.gui_focus"),
        "pips": state.get("ed.status.pips"),
        "fuel": state.get("ed.status.fuel"),
        "fuel_main": state.get("ed.status.fuel_main"),
        "fuel_reservoir": state.get("ed.status.fuel_reservoir"),
        "cargo": state.get("ed.status.cargo"),
        "legal_state": state.get("ed.status.legal_state"),
        "fire_group": state.get("ed.status.fire_group"),
        "temperature": state.get("ed.status.temperature"),
        "latitude": state.get("ed.status.latitude"),
        "longitude": state.get("ed.status.longitude"),
        "altitude": state.get("ed.status.altitude"),
        "heading": state.get("ed.status.heading"),
        "hull_percent": _state_value_with_fallback(
            state,
            "ed.modules.hull_health_percent",
            "ed.telemetry.hull_percent",
        ),
        "modules_available": _as_bool(state.get("ed.modules.available")),
        "modules_health_available": _as_bool(state.get("ed.modules.health_available")),
        "module_power_capacity_mw": state.get("ed.modules.power_capacity_mw"),
        "module_power_usage_percent": state.get("ed.modules.power_usage_percent"),
        "module_power_percent_basis": state.get("ed.modules.power_percent_basis"),
        "module_source": state.get("ed.modules.source"),
        "module_count": state.get("ed.modules.count"),
        "modules": module_items,
        "hardpoints": hardpoints,
        "has_limpet_controller": has_limpet_controller,
        "has_cargo_rack": has_cargo_rack,
        "cargo_inventory": state.get("ed.cargo.items") if isinstance(state.get("ed.cargo.items"), list) else [],
        "limpet_count": state.get("ed.cargo.limpet_count"),
        "docked": _as_bool(state.get("ed.status.docked")),
        "landed": landed,
        "supercruise": supercruise,
        "in_hyperspace": _as_bool(state.get("ed.status.in_hyperspace")),
        "fsd_mass_locked": _as_bool(state.get("ed.status.fsd_mass_locked")),
        "fsd_charging": _as_bool(state.get("ed.status.fsd_charging")),
        "fsd_hyperdrive_charging": _as_bool(state.get("ed.status.fsd_hyperdrive_charging")),
        "fsd_cooldown": _as_bool(state.get("ed.status.fsd_cooldown")),
        "in_danger": _as_bool(state.get("ed.status.in_danger")),
        "being_interdicted": _as_bool(state.get("ed.status.being_interdicted")),
        "overheating": _as_bool(state.get("ed.status.overheating")),
        "low_fuel": _as_bool(state.get("ed.status.low_fuel")),
        "shields_up": _as_bool(
            _state_value_with_fallback(
                state,
                "ed.status.shields_up",
                "ed.telemetry.shield_up",
            )
        ),
        "hardpoints_deployed": _as_bool(state.get("ed.status.hardpoints_deployed")),
        "landing_gear_down": _as_bool(state.get("ed.status.landing_gear_down")),
        "flight_assist_off": _as_bool(state.get("ed.status.flight_assist_off")),
        "lights_on": _as_bool(state.get("ed.status.lights_on")),
        "cargo_scoop_deployed": _as_bool(state.get("ed.status.cargo_scoop_deployed")),
        "night_vision": _as_bool(state.get("ed.status.night_vision")),
        "analysis_mode": _as_bool(state.get("ed.status.analysis_mode")),
    }
    system_detail = {
        "allegiance": state.get("ed.system.allegiance"),
        "government": state.get("ed.system.government"),
        "security": state.get("ed.system.security"),
        "star_class": _state_value_with_fallback(
            state,
            "ed.system.star_class",
            "ed.telemetry.star_class",
        ),
        "economy": state.get("ed.system.economy"),
        "second_economy": state.get("ed.system.second_economy"),
        "population": state.get("ed.system.population"),
        "faction": state.get("ed.system.faction"),
        "faction_state": state.get("ed.system.faction_state"),
        "faction_influence": state.get("ed.system.faction_influence"),
        "faction_happiness": state.get("ed.system.faction_happiness"),
        "faction_reputation": state.get("ed.system.faction_reputation"),
        "civil_war": _as_bool(state.get("ed.system.civil_war")),
        "conflicts": state.get("ed.system.conflicts") if isinstance(state.get("ed.system.conflicts"), list) else [],
        "squadron_faction": _as_bool(state.get("ed.system.squadron_faction")),
        "controlling_power": state.get("ed.system.controlling_power"),
        "powerplay_state": state.get("ed.system.powerplay_state"),
        "powerplay_control_progress": state.get("ed.system.powerplay_control_progress"),
        "powerplay_reinforcement": state.get("ed.system.powerplay_reinforcement"),
        "powerplay_undermining": state.get("ed.system.powerplay_undermining"),
        "station_faction": state.get("ed.station.faction"),
        "station_government": state.get("ed.station.government"),
        "station_economy": state.get("ed.station.economy"),
        "station_market_id": state.get("ed.station.market_id"),
        "station_name": state.get("ed.station.name") or state.get("ed.telemetry.station_name"),
        "station_type": state.get("ed.station.type") or state.get("ed.telemetry.station_type"),
        "station_is_fleet_carrier": _as_bool(state.get("ed.station.is_fleet_carrier")),
        "docking_target_name": state.get("ed.station.docking_target_name")
        or state.get("ed.station.docking_state_station"),
        "docking_target_type": state.get("ed.station.docking_target_type")
        or state.get("ed.station.docking_state_station_type"),
        "docking_target_market_id": state.get("ed.station.docking_target_market_id")
        or state.get("ed.station.docking_state_market_id"),
        "docking_granted_pad": state.get("ed.station.docking_granted_pad")
        or state.get("ed.station.docking_state_landing_pad"),
        "docking_landing_pads": state.get("ed.station.docking_landing_pads")
        or state.get("ed.station.docking_state_landing_pads"),
        "docking_denied_reason": state.get("ed.station.docking_denied_reason")
        or state.get("ed.station.docking_state_reason"),
    }
    target = {
        "locked": _as_bool(state.get("ed.target.locked")),
        "updated_at": state.get("ed.target.updated_at"),
        "scan_stage": state.get("ed.target.scan_stage"),
        "ship": state.get("ed.target.ship"),
        "ship_localised": state.get("ed.target.ship_localised"),
        "pilot_name": state.get("ed.target.pilot_name"),
        "pilot_rank": state.get("ed.target.pilot_rank"),
        "faction": state.get("ed.target.faction"),
        "legal_status": state.get("ed.target.legal_status"),
        "power": state.get("ed.target.power"),
        "hostility": state.get("ed.target.hostility"),
        "commander_power": state.get("ed.commander.power"),
        "shield_health_percent": state.get("ed.target.shield_health_percent"),
        "hull_health_percent": state.get("ed.target.hull_health_percent"),
    }
    raw_no_fire_zone = _as_bool(state.get("ed.station.no_fire_zone"))
    semantic_no_fire_zone = _as_bool(state.get("ed.semantic.station.no_fire_zone"))
    raw_docking_state = str(state.get("ed.station.docking_state") or "").strip().lower()
    semantic_docking_state = str(state.get("ed.semantic.docking.docking_state") or "").strip().lower()
    autodock_status = str(state.get("ed.autodock.status") or "").strip().lower()
    if autodock_status in {"waiting_for_docked", "docking_requested"}:
        effective_docking_state = "requested"
        docking_state_source = "autodock"
    elif raw_docking_state:
        effective_docking_state = raw_docking_state
        docking_state_source = "raw"
    else:
        effective_docking_state = semantic_docking_state
        docking_state_source = "semantic" if semantic_docking_state else None
    semantic = {
        "no_fire_zone": bool(raw_no_fire_zone or semantic_no_fire_zone),
        "no_fire_zone_source": "raw" if raw_no_fire_zone else ("semantic" if semantic_no_fire_zone else None),
        "can_request_docking": _as_bool(state.get("ed.semantic.opportunity.can_request_docking")),
        "station_services_available": _as_bool(
            state.get("ed.semantic.opportunity.station_services_available")
        ),
        "market_access_available": _as_bool(
            state.get("ed.semantic.opportunity.market_access_available")
        ),
        "target_type": state.get("ed.semantic.target.target_type"),
        "docking_state": effective_docking_state,
        "docking_state_source": docking_state_source,
        "docking_target_name": system_detail.get("docking_target_name"),
        "docking_target_type": system_detail.get("docking_target_type"),
        "docking_target_market_id": system_detail.get("docking_target_market_id"),
        "docking_granted_pad": system_detail.get("docking_granted_pad"),
        "docking_landing_pads": system_detail.get("docking_landing_pads"),
        "docking_denied_reason": system_detail.get("docking_denied_reason"),
        "flight_status": state.get("ed.semantic.flight.flight_status"),
        "fsd_state": state.get("ed.semantic.flight.fsd_state"),
    }
    target_context = _lookup_edsm_target_context(
        system_name=current_system_name,
        target_name=_first_present(
            state.get("ed.telemetry.destination_name"),
            system_detail.get("docking_target_name"),
        ),
        target=target,
        semantic=semantic,
    )

    safety = {
        "advice_first": True,
        "keypress_enabled": bool(ENABLE_KEYPRESS),
        "safe_for_keypress": bool(ed_running),
        "semantic_safe_for_keypress": semantic_safe_for_keypress,
        "input_locked": not (bool(ENABLE_KEYPRESS) and ed_running),
        "message": None,
    }
    if safety["input_locked"]:
        safety["message"] = "Input actions require Elite running and WKV_ENABLE_KEYPRESS=1. Execution still requires Elite as foreground."

    suggestions: list[dict[str, Any]] = []
    docking_request_available = bool(
        not telemetry["docked"]
        and semantic["no_fire_zone"]
        and str(semantic["flight_status"] or "").lower() in {"normal_space", "planetary_flight", "unknown", ""}
        and str(semantic["docking_state"] or "").lower() in {"not_docking", "can_request", "unknown", ""}
    )
    if semantic["can_request_docking"]:
        docking_request_available = True
    if telemetry["docked"]:
        suggestions.append(
            {
                "id": "single_press_auto_launch",
                "priority": "medium",
                "message": "Ready to launch",
                "detail": safety["message"] if safety["input_locked"] else "Single-press action will launch.",
                "disabled": bool(safety["input_locked"]),
                "cockpit_action_intent": _cockpit_action_intent(
                    tool="input.keypress",
                    action="auto_launch",
                    parameters={"mode": "single_press_contextual"},
                    requires_confirmation=True,
                ),
            }
        )
    elif docking_request_available:
        suggestions.append(
            {
                "id": "single_press_request_docking",
                "priority": "high",
                "message": "Docking request available",
                "detail": (
                    safety["message"]
                    if safety["input_locked"]
                    else "Inside station no-fire zone; single-press action will request docking."
                ),
                "disabled": bool(safety["input_locked"]),
                "cockpit_action_intent": _cockpit_action_intent(
                    tool="input.keypress",
                    action="request_docking",
                    parameters={"mode": "single_press_contextual"},
                    requires_confirmation=True,
                ),
            }
        )
    elif str(semantic["target_type"] or "").lower() in {"station", "outpost", "fleet_carrier"}:
        suggestions.append(
            {
                "id": "approach_no_fire_zone",
                "priority": "low",
                "message": "Approach station",
                "detail": "Docking request will unlock after no-fire-zone entry.",
                "disabled": True,
            }
        )

    if telemetry["docked"] and semantic["station_services_available"]:
        suggestions.append(
            {
                "id": "post_dock_repair_refuel",
                "priority": "medium",
                "message": "Station services available",
                "detail": safety["message"] if safety["input_locked"] else "Post-dock repair/refuel macro can run.",
                "disabled": bool(safety["input_locked"]),
                "cockpit_action_intent": _cockpit_action_intent(
                    tool="input.keypress",
                    action="repair_refuel",
                    parameters={"mode": "post_dock_auto_service"},
                    requires_confirmation=True,
                ),
            }
        )

    if telemetry["overheating"]:
        suggestions.append(
            {
                "id": "heat_high_heatsink",
                "priority": "critical",
                "message": "Heat critical",
                "detail": safety["message"] if safety["input_locked"] else "Deploy a heatsink.",
                "disabled": bool(safety["input_locked"]),
                "cockpit_action_intent": _cockpit_action_intent(
                    tool="input.keypress",
                    action="deploy_heatsink",
                    parameters={},
                    requires_confirmation=True,
                ),
            }
        )
    if telemetry["being_interdicted"] or telemetry["in_danger"]:
        suggestions.append(
            {
                "id": "danger_defensive",
                "priority": "critical" if telemetry["being_interdicted"] else "high",
                "message": "Danger state detected",
                "detail": safety["message"] if safety["input_locked"] else "Prepare evasive/defensive controls.",
                "disabled": bool(safety["input_locked"]),
                "cockpit_action_intent": _cockpit_action_intent(
                    tool="input.keypress",
                    action="defensive_manoeuvre",
                    parameters={},
                    requires_confirmation=True,
                ),
            }
        )
    if telemetry["low_fuel"]:
        suggestions.append(
            {
                "id": "low_fuel_warning",
                "priority": "high",
                "message": "Fuel low",
                "detail": "Check route, scoop target, or divert before the next jump.",
            }
        )
    if not obs_up:
        suggestions.append(
            {
                "id": "obs_unavailable",
                "priority": "medium",
                "message": "OBS unavailable",
                "detail": str(obs_status.get("message") or obs_status.get("error") or "OBS status is not up."),
            }
        )
    return {
        "ok": True,
        "updated_at_utc": _utc_now_iso(),
        "telemetry": telemetry,
        "system_detail": system_detail,
        "target": target,
        "target_context": target_context,
        "semantic": semantic,
        "suggestions": suggestions,
        "integrations": {
            "obs": {
                "ok": obs_up,
                "status": obs_status.get("status"),
                "enabled": obs_status.get("enabled"),
            },
        },
        "safety": safety,
    }


def query_current_system_provider(query: dict[str, list[str]]) -> dict[str, Any]:
    state = _state_map()
    ed_running = _ed_running_from_state(state)
    system_name = _first_present(
        state.get("ed.telemetry.system_name"),
        state.get("ed.system.name"),
        state.get("ed.current_system.name"),
    )
    system_address = _first_present(
        state.get("ed.telemetry.system_address"),
        state.get("ed.system.address"),
        state.get("ed.current_system.address"),
    )
    if not ed_running:
        return _provider_unavailable_payload(
            operation=ProviderOperationId.SYSTEM_LOOKUP.value,
            reason="ed_not_running",
            error="Elite Dangerous is not running",
            system_name=system_name,
            system_address=system_address,
        )
    if not system_name and system_address is None:
        return _provider_unavailable_payload(
            operation=ProviderOperationId.SYSTEM_LOOKUP.value,
            reason="current_system_unavailable",
            error="current system is unavailable in state",
            system_name=system_name,
            system_address=system_address,
        )

    provider_hint = str((query.get("provider", ["auto"])[0] or "auto")).strip().lower()
    allow_stale_raw = str((query.get("allow_stale_if_error", ["true"])[0] or "true")).strip().lower()
    allow_stale = allow_stale_raw in {"1", "true", "yes", "on"}
    max_age_raw = str((query.get("max_age_s", ["86400"])[0] or "86400")).strip()
    try:
        max_age_s = max(0, int(max_age_raw))
    except ValueError:
        raise ValueError("max_age_s must be an integer")

    params: dict[str, Any] = {}
    if system_name:
        params["system_name"] = system_name
    if system_address is not None:
        params["system_address"] = system_address

    if provider_hint in {"", "auto"}:
        result = ED_PROVIDER_QUERY_SERVICE.execute_priority(
            operation=ProviderOperationId.SYSTEM_LOOKUP,
            params=params,
            max_age_s=max_age_s,
            allow_stale_if_error=allow_stale,
            incident_id=None,
            reason="current_system",
        )
    else:
        payload = {
            "tool": "ed.provider_query",
            "provider": provider_hint,
            "operation": "system_lookup",
            "params": params,
            "requirements": {
                "max_age_s": max_age_s,
                "allow_stale_if_error": allow_stale,
            },
            "trace": {"incident_id": None, "reason": "current_system"},
        }
        from actions import execute_provider_query

        return execute_provider_query(payload, source="brainstem_query")

    return {
        "ok": result.ok,
        **result.to_dict(),
        "current_system_state": {
            "system_name": system_name,
            "system_address": system_address,
        },
    }


def _current_system_identity(state: dict[str, Any] | None = None) -> tuple[str | None, int | None]:
    state = state if state is not None else _state_map()
    system_name = _first_present(
        state.get("ed.telemetry.system_name"),
        state.get("ed.system.name"),
        state.get("ed.current_system.name"),
    )
    system_address = _first_present(
        state.get("ed.telemetry.system_address"),
        state.get("ed.system.address"),
        state.get("ed.current_system.address"),
    )
    try:
        if system_address is not None:
            system_address = int(system_address)
    except Exception:
        system_address = None
    if isinstance(system_name, str):
        system_name = system_name.strip() or None
    else:
        system_name = None
    return system_name, system_address


def _query_cached_system_children(
    *,
    table: str,
    system_name: str | None,
    system_address: int | None,
    limit: int,
) -> dict[str, Any] | None:
    if table not in {"ed_bodies", "ed_stations"}:
        return None
    with connect_db() as con:
        con.row_factory = sqlite3.Row
        if system_address is not None:
            system_row = con.execute(
                """
                SELECT system_address,name,primary_source,last_refreshed_at,expires_at
                FROM ed_systems
                WHERE system_address=?
                LIMIT 1
                """,
                (system_address,),
            ).fetchone()
        elif system_name:
            system_row = con.execute(
                """
                SELECT system_address,name,primary_source,last_refreshed_at,expires_at
                FROM ed_systems
                WHERE name=?
                ORDER BY updated_at_utc DESC
                LIMIT 1
                """,
                (system_name,),
            ).fetchone()
        else:
            system_row = None
        if not system_row:
            return None
        target_address = int(system_row["system_address"])
        rows = con.execute(
            f"""
            SELECT *
            FROM {table}
            WHERE system_address=?
            ORDER BY name ASC
            LIMIT ?
            """,
            (target_address, limit),
        ).fetchall()
    if not rows:
        return None
    return {
        "system_address": target_address,
        "system_name": str(system_row["name"] or system_name or ""),
        "provider": str(system_row["primary_source"] or ""),
        "refreshed_at": system_row["last_refreshed_at"],
        "expires_at": system_row["expires_at"],
        "rows": rows,
    }


def _cached_body_rows_need_enrichment(rows: list[sqlite3.Row]) -> bool:
    for row in rows:
        if str(row["body_type"] or "").strip().casefold() != "planet":
            continue
        if row["gravity"] is None or row["radius"] is None or row["mass"] is None:
            return True
        extras = _as_json(row["mapped_fields_json"], {})
        if not isinstance(extras, dict) or extras.get("surface_temperature") is None:
            return True
    return False


def _query_live_current_system_children(
    *,
    operation: ProviderOperationId,
    system_name: str | None,
    system_address: int | None,
    max_age_s: int,
    allow_stale: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if system_name:
        params["system_name"] = system_name
    if system_address is not None:
        params["system_address"] = system_address
    result = ED_PROVIDER_QUERY_SERVICE.execute_priority(
        operation=operation,
        params=params,
        max_age_s=max_age_s,
        allow_stale_if_error=allow_stale,
        incident_id=None,
        reason=f"current_system_{operation.value}",
    )
    return result.to_dict()


def _current_station_identity(state: dict[str, Any] | None = None) -> tuple[str | None, str | None, int | None]:
    state = state if state is not None else _state_map()
    docked = bool(_state_value_with_fallback(state, "ed.telemetry.dock_state", "ed.status.docked"))
    station_services_available = bool(state.get("ed.semantic.opportunity.station_services_available"))
    can_request_docking = bool(state.get("ed.semantic.opportunity.can_request_docking"))
    target_type = state.get("ed.semantic.target.target_type")

    station_name = None
    raw_station_name = state.get("ed.telemetry.station_name")
    if docked or station_services_available:
        station_name = raw_station_name
    elif target_type in {"station", "outpost", "fleet_carrier"} or can_request_docking:
        station_name = state.get("ed.telemetry.destination_name")

    system_name, system_address = _current_system_identity(state)
    if isinstance(station_name, str):
        station_name = station_name.strip() or None
    else:
        station_name = None
    return station_name, system_name, system_address


def query_current_station_detail(query: dict[str, list[str]]) -> dict[str, Any]:
    refresh_raw = str((query.get("refresh", ["false"])[0] or "false")).strip().lower()
    refresh = refresh_raw in {"1", "true", "yes", "on"}

    state = _state_map()
    ed_running = _ed_running_from_state(state)
    station_name, system_name, system_address = _current_station_identity(state)
    if not ed_running:
        return {
            "ok": False,
            "current_station_state": {
                "station_name": station_name,
                "system_name": system_name,
                "system_address": system_address,
                "docked": False,
            },
            "semantic": {
                "no_fire_zone": False,
                "station_services_available": False,
                "market_access_available": False,
            },
            "data": {
                "market_id": None,
                "station_id64": None,
                "name": station_name,
                "station_type": None,
                "distance_to_arrival_ls": None,
                "has_docking": False,
                "services": [],
                "provider": None,
                "updated_at_utc": None,
                "market_data": {
                    "available": False,
                    "source": None,
                    "reason": "Elite Dangerous is not running",
                },
            },
            "error": "Elite Dangerous is not running",
            "deny_reason": "ed_not_running",
        }
    if not station_name:
        return {
            "ok": False,
            "current_station_state": {
                "station_name": None,
                "system_name": system_name,
                "system_address": system_address,
                "docked": False,
            },
            "semantic": {
                "no_fire_zone": bool(state.get("ed.semantic.station.no_fire_zone")),
                "station_services_available": False,
                "market_access_available": False,
            },
            "data": {
                "market_id": None,
                "station_id64": None,
                "name": None,
                "station_type": None,
                "distance_to_arrival_ls": None,
                "has_docking": False,
                "services": [],
                "provider": None,
                "updated_at_utc": None,
                "market_data": {
                    "available": False,
                    "source": None,
                    "reason": "current station is unavailable in state",
                },
            },
            "error": "current station is unavailable in state",
            "deny_reason": "current_station_unavailable",
        }

    station_row = None
    if not refresh:
        with connect_db() as con:
            con.row_factory = sqlite3.Row
            if system_address is not None:
                station_row = con.execute(
                    """
                    SELECT *
                    FROM ed_stations
                    WHERE system_address=? AND name=?
                    ORDER BY updated_at_utc DESC
                    LIMIT 1
                    """,
                    (system_address, station_name),
                ).fetchone()
            else:
                station_row = con.execute(
                    """
                    SELECT *
                    FROM ed_stations
                    WHERE name=?
                    ORDER BY updated_at_utc DESC
                    LIMIT 1
                    """,
                    (station_name,),
                ).fetchone()

    services = _as_json(station_row["services_json"], []) if station_row else []
    if not isinstance(services, list):
        services = []

    station_services_available = bool(state.get("ed.semantic.opportunity.station_services_available"))
    market_access_available = bool(state.get("ed.semantic.opportunity.market_access_available"))
    no_fire_zone = bool(state.get("ed.semantic.station.no_fire_zone"))
    docked = bool(_state_value_with_fallback(state, "ed.telemetry.dock_state", "ed.status.docked"))

    return {
        "ok": True,
        "current_station_state": {
            "station_name": station_name,
            "system_name": system_name,
            "system_address": system_address,
            "docked": docked,
        },
        "semantic": {
            "no_fire_zone": no_fire_zone,
            "station_services_available": station_services_available,
            "market_access_available": market_access_available,
        },
        "data": {
            "market_id": station_row["market_id"] if station_row else None,
            "station_id64": station_row["station_id64"] if station_row else None,
            "name": station_name,
            "station_type": station_row["station_type"] if station_row else None,
            "distance_to_arrival_ls": station_row["distance_to_arrival_ls"] if station_row else None,
            "has_docking": bool(station_row["has_docking"]) if station_row else docked,
            "services": services,
            "provider": station_row["source"] if station_row else None,
            "updated_at_utc": station_row["updated_at_utc"] if station_row else None,
            "market_data": {
                "available": False,
                "source": None,
                "reason": "live commodity market board ingestion is not implemented",
            },
        },
        "error": None,
    }


def query_current_system_bodies(query: dict[str, list[str]]) -> dict[str, Any]:
    limit_raw = (query.get("limit", ["20"])[0] or "20").strip()
    max_age_raw = (query.get("max_age_s", ["86400"])[0] or "86400").strip()
    allow_stale_raw = str((query.get("allow_stale_if_error", ["true"])[0] or "true")).strip().lower()
    refresh_raw = str((query.get("refresh", ["false"])[0] or "false")).strip().lower()
    try:
        limit = max(1, min(100, int(limit_raw)))
        max_age_s = max(0, int(max_age_raw))
    except ValueError:
        raise ValueError("limit and max_age_s must be integers")
    allow_stale = allow_stale_raw in {"1", "true", "yes", "on"}
    refresh = refresh_raw in {"1", "true", "yes", "on"}

    state = _state_map()
    ed_running = _ed_running_from_state(state)
    system_name, system_address = _current_system_identity(state)
    if not ed_running:
        return _provider_unavailable_payload(
            operation=ProviderOperationId.BODIES_LOOKUP.value,
            reason="ed_not_running",
            error="Elite Dangerous is not running",
            system_name=system_name,
            system_address=system_address,
            data={"system_name": system_name, "system_address": system_address, "body_count": 0, "items": []},
        )
    if not system_name and system_address is None:
        return _provider_unavailable_payload(
            operation=ProviderOperationId.BODIES_LOOKUP.value,
            reason="current_system_unavailable",
            error="current system is unavailable in state",
            system_name=system_name,
            system_address=system_address,
            data={"system_name": system_name, "system_address": system_address, "body_count": 0, "items": []},
        )

    cached = None if refresh else _query_cached_system_children(
        table="ed_bodies",
        system_name=system_name,
        system_address=system_address,
        limit=limit,
    )
    if cached is not None and not _cached_body_rows_need_enrichment(cached["rows"]):
        items = []
        for row in cached["rows"]:
            items.append(
                {
                    "body_id64": row["body_id64"],
                    "name": row["name"],
                    "body_type": row["body_type"],
                    "subtype": row["subtype"],
                    "distance_to_arrival_ls": row["distance_to_arrival_ls"],
                    "terraform_state": row["terraform_state"],
                    "atmosphere": row["atmosphere"],
                    "gravity": row["gravity"],
                    "radius": row["radius"],
                    "mass": row["mass"],
                    "extras": _as_json(row["mapped_fields_json"], {}),
                }
            )
        return {
            "ok": True,
            "provider": cached["provider"],
            "operation": ProviderOperationId.BODIES_LOOKUP.value,
            "fetched_at": cached["refreshed_at"],
            "cache": {"hit": True, "age_s": None, "ttl_s": None, "stale_served": False},
            "provenance": {"endpoint": None, "http_code": None},
            "data": {
                "system_address": cached["system_address"],
                "system_name": cached["system_name"],
                "body_count": len(items),
                "items": items,
            },
            "error": None,
            "deny_reason": None,
        }
    return _query_live_current_system_children(
        operation=ProviderOperationId.BODIES_LOOKUP,
        system_name=system_name,
        system_address=system_address,
        max_age_s=max_age_s,
        allow_stale=allow_stale,
    )


def query_current_system_stations(query: dict[str, list[str]]) -> dict[str, Any]:
    limit_raw = (query.get("limit", ["20"])[0] or "20").strip()
    max_age_raw = (query.get("max_age_s", ["86400"])[0] or "86400").strip()
    allow_stale_raw = str((query.get("allow_stale_if_error", ["true"])[0] or "true")).strip().lower()
    refresh_raw = str((query.get("refresh", ["false"])[0] or "false")).strip().lower()
    try:
        limit = max(1, min(100, int(limit_raw)))
        max_age_s = max(0, int(max_age_raw))
    except ValueError:
        raise ValueError("limit and max_age_s must be integers")
    allow_stale = allow_stale_raw in {"1", "true", "yes", "on"}
    refresh = refresh_raw in {"1", "true", "yes", "on"}

    state = _state_map()
    ed_running = _ed_running_from_state(state)
    system_name, system_address = _current_system_identity(state)
    if not ed_running:
        return _provider_unavailable_payload(
            operation=ProviderOperationId.STATIONS_LOOKUP.value,
            reason="ed_not_running",
            error="Elite Dangerous is not running",
            system_name=system_name,
            system_address=system_address,
            data={"system_name": system_name, "system_address": system_address, "station_count": 0, "items": []},
        )
    if not system_name and system_address is None:
        return _provider_unavailable_payload(
            operation=ProviderOperationId.STATIONS_LOOKUP.value,
            reason="current_system_unavailable",
            error="current system is unavailable in state",
            system_name=system_name,
            system_address=system_address,
            data={"system_name": system_name, "system_address": system_address, "station_count": 0, "items": []},
        )

    cached = None if refresh else _query_cached_system_children(
        table="ed_stations",
        system_name=system_name,
        system_address=system_address,
        limit=limit,
    )
    if cached is not None:
        items = []
        for row in cached["rows"]:
            items.append(
                {
                    "market_id": row["market_id"],
                    "station_id64": row["station_id64"],
                    "name": row["name"],
                    "station_type": row["station_type"],
                    "distance_to_arrival_ls": row["distance_to_arrival_ls"],
                    "has_docking": bool(row["has_docking"]),
                    "services": _as_json(row["services_json"], []),
                }
            )
        return {
            "ok": True,
            "provider": cached["provider"],
            "operation": ProviderOperationId.STATIONS_LOOKUP.value,
            "fetched_at": cached["refreshed_at"],
            "cache": {"hit": True, "age_s": None, "ttl_s": None, "stale_served": False},
            "provenance": {"endpoint": None, "http_code": None},
            "data": {
                "system_address": cached["system_address"],
                "system_name": cached["system_name"],
                "station_count": len(items),
                "items": items,
            },
            "error": None,
            "deny_reason": None,
        }
    return _query_live_current_system_children(
        operation=ProviderOperationId.STATIONS_LOOKUP,
        system_name=system_name,
        system_address=system_address,
        max_age_s=max_age_s,
        allow_stale=allow_stale,
    )


def query_sitrep(query: dict[str, list[str]]) -> dict[str, Any]:
    fast_raw = str((query.get("fast", ["false"])[0] or "false")).strip().lower()
    fast = fast_raw in {"1", "true", "yes", "on"}
    events_limit_raw = (query.get("events_limit", ["50"])[0] or "50").strip()
    try:
        events_limit = max(0 if fast else 10, min(300, int(events_limit_raw)))
    except ValueError:
        raise ValueError("events_limit must be an integer")

    events = DB_SERVICE.list_events(limit=events_limit) if events_limit > 0 else []
    state = _state_map()
    capabilities = [] if fast else _query_capabilities()
    now_ts = time.time()
    def is_expected_sammi_absent(event: dict[str, Any]) -> bool:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return False
        error = str(payload.get("error") or "").lower()
        return (
            str(event.get("event_type") or "") == "AUX_APP_ERROR"
            and str(payload.get("app") or "").lower() == "sammi"
            and (
                error == "sammi never observed in this session"
                or error.startswith("sammi startup grace active")
                or error.startswith("sammi missing holdoff active")
                or error.startswith("sammi restart suppress active")
                or error.startswith("sammi launch backoff active")
                or error == "sammi autorun disabled"
            )
        )

    alarms = [
        e
        for e in events
        if str(e.get("severity") or "").lower() in {"warn", "error"}
        and not is_expected_sammi_absent(e)
    ]
    music_now_playing = state.get("music.now_playing")
    if not isinstance(music_now_playing, dict):
        music_now_playing = {}
    music_title = _first_present(
        state.get("music.now_playing.title"),
        state.get("music.track.title"),
        music_now_playing.get("title"),
    )
    music_artist = _first_present(
        state.get("music.now_playing.artist"),
        state.get("music.track.artist"),
        music_now_playing.get("artist"),
    )
    music_playing = _first_present(
        state.get("music.playing"),
        state.get("music.status.playing"),
    )
    music_app_running = _as_bool(state.get("music.app_running"))
    if not music_app_running:
        music_playing = False
        music_title = ""
        music_artist = ""
        music_now_playing = {}
    elif music_playing is None and any(
        [music_title, music_artist, music_now_playing.get("now_playing")]
    ):
        music_playing = True

    watch_condition = (
        state.get("policy.watch_condition")
        or state.get("system.watch_condition")
        or "STANDBY"
    )
    ed_running = bool(
        state.get("ed.running")
        or state.get("ed.status.running")
        or state.get("ed.process.running")
    )
    current_station_name, _, _ = _current_station_identity(state)
    ed_system_name = _state_value_with_fallback(state, "ed.status.system_name", "ed.telemetry.system_name")
    ed_system_address = _state_value_with_fallback(state, "ed.status.system_address", "ed.telemetry.system_address")
    ed_destination_name = _state_value_with_fallback(state, "ed.telemetry.destination_name", "ed.telemetry.station_name")
    ed_ship_name = _state_value_with_fallback(state, "ed.status.ship_name", "ed.telemetry.ship_name")
    ed_ship_model = _state_value_with_fallback(state, "ed.status.ship_model", "ed.telemetry.ship_model")
    ed_ship_ident = _state_value_with_fallback(state, "ed.status.ship_ident", "ed.telemetry.ship_ident")
    ed_dock_state = _state_value_with_fallback(state, "ed.status.docked", "ed.telemetry.dock_state")
    ed_supercruise = _state_value_with_fallback(state, "ed.status.supercruise", "ed.telemetry.supercruise")
    ed_landed = _state_value_with_fallback(state, "ed.status.landed", "ed.telemetry.landed")
    ed_shields_up = _state_value_with_fallback(state, "ed.status.shields_up", "ed.telemetry.shield_up")
    ed_lights_on = _state_value_with_fallback(state, "ed.status.lights_on", "ed.telemetry.lights_on")
    ed_night_vision = _state_value_with_fallback(state, "ed.status.night_vision", "ed.telemetry.night_vision")
    ed_flight_assist_off = _state_value_with_fallback(
        state,
        "ed.status.flight_assist_off",
        "ed.telemetry.flight_assist_off",
    )
    ed_landing_gear_down = _state_value_with_fallback(
        state,
        "ed.status.landing_gear_down",
        "ed.telemetry.landing_gear_down",
    )
    ed_semantic_online_state = state.get("ed.semantic.session.online_state")
    ed_semantic_primary_mode = state.get("ed.semantic.context.primary_mode")
    ed_semantic_player_platform = state.get("ed.semantic.context.player_platform")
    ed_semantic_on_foot_area = state.get("ed.semantic.context.on_foot_area")
    ed_semantic_flight_status = state.get("ed.semantic.flight.flight_status")
    ed_semantic_fsd_state = state.get("ed.semantic.flight.fsd_state")
    ed_semantic_docking_state = state.get("ed.semantic.docking.docking_state")
    ed_semantic_landing_state = state.get("ed.semantic.landing.landing_state")
    ed_semantic_combat_state = state.get("ed.semantic.combat.combat_state")
    ed_semantic_heat_state = state.get("ed.semantic.ship.heat_state")
    ed_semantic_fuel_state = state.get("ed.semantic.ship.fuel_state")
    ed_semantic_integrity_state = state.get("ed.semantic.ship.integrity_state")
    ed_semantic_target_type = state.get("ed.semantic.target.target_type")
    ed_semantic_no_fire_zone = state.get("ed.semantic.station.no_fire_zone")
    ed_semantic_risk_level = state.get("ed.semantic.risk.risk_level")
    ed_semantic_primary_risk = state.get("ed.semantic.risk.primary_risk")
    ed_semantic_control_profile = state.get("ed.semantic.interface.control_profile")
    ed_semantic_can_request_docking = state.get("ed.semantic.opportunity.can_request_docking")
    ed_semantic_station_services_available = state.get("ed.semantic.opportunity.station_services_available")
    ed_semantic_market_access_available = state.get("ed.semantic.opportunity.market_access_available")
    ed_semantic_safe_for_keypress = state.get("ed.semantic.interaction.safe_for_keypress")
    inara_secret = get_provider_secret_entry("inara", PROVIDER_SECRETS_PATH)
    ed_commander_name = (
        str(state.get("ed.telemetry.commander_name") or "").strip()
        or str(inara_secret.get("commander_name") or "").strip()
        or None
    )
    jinx_running = bool(state.get("app.jinx.running"))
    sammi_running = bool(state.get("app.sammi.running"))
    sammi_api_last_push_at = state.get("app.sammi.api.last_push_at")
    sammi_api_last_push_count = state.get("app.sammi.api.last_push_count")
    sammi_api_last_cycle_ms = state.get("app.sammi.api.last_cycle_ms")
    sammi_api_deferred_count = state.get("app.sammi.api.deferred_count")
    sammi_api_suppressed_count = state.get("app.sammi.api.suppressed_count")
    ytmd_running = music_app_running
    queue_depth = (
        state.get("queue.depth")
        or state.get("brainstem.queue.depth")
        or state.get("ai.queue.depth")
        or 0
    )

    services = {
        "brainstem": {
            "name": "brainstem",
            "ok": True,
            "status": "up",
            "url": f"http://127.0.0.1:{PORT}/health",
            "detail": {"version": VERSION, "commit": COMMIT},
        }
    }
    providers: dict[str, Any] = {}
    if not fast:
        advisory_status = _probe_service("advisory", ADVISORY_HEALTH_URL)
        knowledge_status = _probe_service("knowledge", KNOWLEDGE_HEALTH_URL)
        knowledge_detail = knowledge_status.get("detail")
        if not isinstance(knowledge_detail, dict):
            knowledge_detail = {}
        vector_backend = str(knowledge_detail.get("vector_backend") or "").strip().lower()

        if vector_backend == "qdrant":
            qdrant_status = _probe_service("qdrant", QDRANT_HEALTH_URL)
        else:
            qdrant_status = {
                "name": "qdrant",
                "ok": True,
                "status": "disabled",
                "url": QDRANT_HEALTH_URL,
                "detail": {
                    "reason": (
                        "vector backend is not qdrant"
                        if vector_backend
                        else "knowledge backend unavailable; qdrant probe skipped"
                    ),
                    "vector_backend": vector_backend or None,
                },
            }

        services.update(
            {
                "advisory": advisory_status,
                "knowledge": knowledge_status,
                "qdrant": qdrant_status,
            }
        )
        try:
            providers = list_provider_health(Path(DB_PATH))
        except sqlite3.Error:
            providers = {}

    return {
        "ok": True,
        "generated_at_utc": _utc_now_iso(),
        "watch_condition": str(watch_condition),
        "runtime": {
            "uptime_seconds": int(max(0, now_ts - START_TS)),
            "version": VERSION,
            "commit": COMMIT,
            "schema_version": _schema_version(),
            "queue_depth": int(queue_depth) if isinstance(queue_depth, (int, float)) else 0,
            "last_error": _last_error(events),
        },
        "services": services,
        "providers": providers,
        "capabilities": capabilities,
        "handover": {
            "ed_running": ed_running,
            "ed_state": {
                "commander_name": ed_commander_name,
                "ship_name": ed_ship_name,
                "ship_model": ed_ship_model,
                "ship_ident": ed_ship_ident,
                "system_name": ed_system_name,
                "system_address": ed_system_address,
                "destination_name": ed_destination_name,
                "station_name": current_station_name,
                "docked": ed_dock_state,
                "supercruise": ed_supercruise,
                "landed": ed_landed,
                "shields_up": ed_shields_up,
                "lights_on": ed_lights_on,
                "night_vision": ed_night_vision,
                "flight_assist_off": ed_flight_assist_off,
                "landing_gear_down": ed_landing_gear_down,
                "semantic": {
                    "online_state": ed_semantic_online_state,
                    "primary_mode": ed_semantic_primary_mode,
                    "player_platform": ed_semantic_player_platform,
                    "on_foot_area": ed_semantic_on_foot_area,
                    "flight_status": ed_semantic_flight_status,
                    "fsd_state": ed_semantic_fsd_state,
                    "docking_state": ed_semantic_docking_state,
                    "landing_state": ed_semantic_landing_state,
                    "combat_state": ed_semantic_combat_state,
                    "heat_state": ed_semantic_heat_state,
                    "fuel_state": ed_semantic_fuel_state,
                    "integrity_state": ed_semantic_integrity_state,
                    "target_type": ed_semantic_target_type,
                    "no_fire_zone": ed_semantic_no_fire_zone,
                    "risk_level": ed_semantic_risk_level,
                    "primary_risk": ed_semantic_primary_risk,
                    "control_profile": ed_semantic_control_profile,
                    "can_request_docking": ed_semantic_can_request_docking,
                    "station_services_available": ed_semantic_station_services_available,
                    "market_access_available": ed_semantic_market_access_available,
                    "safe_for_keypress": ed_semantic_safe_for_keypress,
                },
            },
            "apps": {
                "ed_running": ed_running,
                "jinx_running": jinx_running,
                "sammi_running": sammi_running,
                "ytmd_running": ytmd_running,
                "sammi_api": {
                    "last_push_at": sammi_api_last_push_at,
                    "last_push_count": sammi_api_last_push_count,
                    "last_cycle_ms": sammi_api_last_cycle_ms,
                    "deferred_count": sammi_api_deferred_count,
                    "suppressed_count": sammi_api_suppressed_count,
                },
            },
            "music_state": {
                "playing": music_playing,
                "title": music_title,
                "artist": music_artist,
            },
            "ai_state": {
                "mode": state.get("ai.status.mode"),
                "provider": state.get("ai.status.provider"),
                "degraded": state.get("ai.status.degraded"),
            },
            "active_alarms": alarms[:10],
        },
        "state_highlights": {
            key: state[key]
            for key in (
                "system.time.utc_iso",
                "system.time.local_iso",
                "system.time.local_date",
                "system.time.local_time",
                "system.time.timezone",
                "system.time.utc_offset",
                "system.time.unix_ts",
                "ed.game_time.utc_iso",
                "ed.game_time.date",
                "ed.game_time.time",
                "policy.watch_condition",
                "ed.status.running",
                "ed.status.landed",
                "ed.status.shields_up",
                "ed.status.lights_on",
                "ed.telemetry.system_name",
                "ed.telemetry.system_address",
                "ed.telemetry.dock_state",
                "ed.telemetry.supercruise",
                "ed.telemetry.landed",
                "ed.telemetry.landing_gear_down",
                "ed.telemetry.shield_up",
                "ed.telemetry.lights_on",
                "ed.telemetry.flight_assist_off",
                "ed.telemetry.night_vision",
                "ed.semantic.session.online_state",
                "ed.semantic.context.primary_mode",
                "ed.semantic.context.player_platform",
                "ed.semantic.context.on_foot_area",
                "ed.semantic.flight.flight_status",
                "ed.semantic.flight.fsd_state",
                "ed.semantic.docking.docking_state",
                "ed.semantic.landing.landing_state",
                "ed.semantic.combat.combat_state",
                "ed.semantic.ship.heat_state",
                "ed.semantic.ship.fuel_state",
                "ed.semantic.ship.integrity_state",
                "ed.semantic.target.target_type",
                "ed.semantic.station.no_fire_zone",
                "ed.semantic.risk.risk_level",
                "ed.semantic.risk.primary_risk",
                "ed.semantic.interface.control_profile",
                "ed.semantic.opportunity.can_request_docking",
                "ed.semantic.opportunity.station_services_available",
                "ed.semantic.opportunity.market_access_available",
                "ed.semantic.interaction.safe_for_keypress",
                "music.status.playing",
                "music.playing",
                "music.now_playing.title",
                "music.now_playing.artist",
                "music.track.title",
                "music.track.artist",
                "music.now_playing",
                "hw.cpu.temp_c",
                "hw.gpu.temp_c",
                "hw.memory",
                "hw.uptime_sec",
                "hardware.cpu_percent",
                "hardware.cpu_temp_c",
                "hardware.gpu_percent",
                "hardware.gpu_temp_c",
                "hardware.memory_used_percent",
                "hardware.uptime_sec",
                "ai.status.mode",
                "ai.status.provider",
            )
            if key in state
        },
        "last_events": events[:20],
    }


def query_log_files() -> dict[str, Any]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    for path in sorted(
        LOG_DIR.glob("*"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    ):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "path": str(path.resolve()),
                "size_bytes": stat.st_size,
                "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.%fZ"
                ),
                "href": path.resolve().as_uri(),
            }
        )
    return {"ok": True, "root": str(LOG_DIR.resolve()), "files": files}


def _resolve_log_path(file_value: str) -> Path:
    if not file_value:
        raise ValueError("file query parameter is required")
    root = LOG_DIR.resolve()
    candidate = Path(file_value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if not str(candidate).startswith(str(root)):
        raise ValueError("file must be inside log directory")
    if not candidate.exists() or not candidate.is_file():
        raise ValueError(f"log file not found: {candidate.name}")
    return candidate


def query_log_tail(query: dict[str, list[str]]) -> dict[str, Any]:
    file_value = (query.get("file", [None])[0] or "").strip()
    lines_raw = (query.get("lines", ["100"])[0] or "100").strip()
    try:
        lines = max(1, min(2000, int(lines_raw)))
    except ValueError:
        raise ValueError("lines must be an integer")
    path = _resolve_log_path(file_value)

    selected = _tail_text_lines(path, lines)
    return {
        "ok": True,
        "file": path.name,
        "path": str(path),
        "lines_requested": lines,
        "line_count": len(selected),
        "lines": selected,
    }


def _tail_text_lines(path: Path, lines: int, *, chunk_size: int = 8192) -> list[str]:
    """Read the end of a log file without loading the full file into memory."""
    if lines <= 0:
        return []
    with path.open("rb") as fh:
        fh.seek(0, 2)
        end = fh.tell()
        chunks: list[bytes] = []
        pos = end
        newline_count = 0
        while pos > 0 and newline_count <= lines:
            read_size = min(chunk_size, pos)
            pos -= read_size
            fh.seek(pos)
            block = fh.read(read_size)
            chunks.append(block)
            newline_count += block.count(b"\n")
        data = b"".join(reversed(chunks))
    return data.decode("utf-8", errors="replace").splitlines()[-lines:]


def build_diag_bundle() -> dict[str, Any]:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle_name = f"diag_{stamp}.zip"
    bundle_path = SNAPSHOT_DIR / bundle_name

    if callable(build_diag_report):
        report = build_diag_report(
            db_path=Path(DB_PATH),
            policy_path=Path(STANDING_ORDERS_PATH),
            events_limit=200,
        )
    else:
        report = {"ok": False, "error": "diag_report tool not available"}

    events = DB_SERVICE.list_events(limit=200)
    state = DB_SERVICE.list_state()

    with zipfile.ZipFile(bundle_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("diag_report.json", json.dumps(report, ensure_ascii=False, indent=2))
        zf.writestr("event_tail.json", json.dumps(events, ensure_ascii=False, indent=2))
        zf.writestr("state_current.json", json.dumps(state, ensure_ascii=False, indent=2))

    return {
        "ok": True,
        "bundle_name": bundle_name,
        "bundle_path": str(bundle_path.resolve()),
        "bundle_href": f"/diag/bundle/{bundle_name}",
        "created_at_utc": _utc_now_iso(),
    }


def resolve_diag_bundle(bundle_name: str) -> Path:
    clean = (bundle_name or "").strip()
    if not clean:
        raise ValueError("bundle name is required")
    if "/" in clean or "\\" in clean or ".." in clean:
        raise ValueError("invalid bundle name")
    bundle = (SNAPSHOT_DIR / clean).resolve()
    if not str(bundle).startswith(str(SNAPSHOT_DIR.resolve())):
        raise ValueError("invalid bundle path")
    if not bundle.exists() or not bundle.is_file():
        raise ValueError("bundle not found")
    return bundle
