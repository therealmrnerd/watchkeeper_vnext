import json
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
    COMMIT,
    DB_PATH,
    DB_SERVICE,
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

try:
    from tools.diag_report import build_diag_report
except Exception:
    build_diag_report = None  # type: ignore


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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
            "wired": False,
            "ready_for_cloud_fallback": api_key_present,
            "note": (
                "Cloud fallback key is present in the encrypted keystore."
                if api_key_present
                else "Stored for future OpenAI fallback wiring; current advisory runtime does not consume it yet."
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


def query_current_system_provider(query: dict[str, list[str]]) -> dict[str, Any]:
    state = _state_map()
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
    if not system_name and system_address is None:
        raise ValueError("current system is unavailable in state")

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


def _current_system_identity() -> tuple[str | None, int | None]:
    state = _state_map()
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
    result = ED_PROVIDER_QUERY_SERVICE.execute(
        ProviderQuery(
            provider=ProviderId.SPANSH,
            operation=operation,
            params=params,
            max_age_s=max_age_s,
            allow_stale_if_error=allow_stale,
            incident_id=None,
            reason=f"current_system_{operation.value}",
        )
    )
    return result.to_dict()


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

    system_name, system_address = _current_system_identity()
    if not system_name and system_address is None:
        raise ValueError("current system is unavailable in state")

    cached = None if refresh else _query_cached_system_children(
        table="ed_bodies",
        system_name=system_name,
        system_address=system_address,
        limit=limit,
    )
    if cached is not None:
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

    system_name, system_address = _current_system_identity()
    if not system_name and system_address is None:
        raise ValueError("current system is unavailable in state")

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
    events_limit_raw = (query.get("events_limit", ["50"])[0] or "50").strip()
    try:
        events_limit = max(10, min(300, int(events_limit_raw)))
    except ValueError:
        raise ValueError("events_limit must be an integer")

    events = DB_SERVICE.list_events(limit=events_limit)
    state = _state_map()
    capabilities = _query_capabilities()
    now_ts = time.time()
    alarms = [e for e in events if str(e.get("severity") or "").lower() in {"warn", "error"}]
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
    if music_playing is None and any(
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
    ed_system_name = _state_value_with_fallback(state, "ed.status.system_name", "ed.telemetry.system_name")
    ed_system_address = _state_value_with_fallback(state, "ed.status.system_address", "ed.telemetry.system_address")
    ed_ship_name = _state_value_with_fallback(state, "ed.status.ship_name", "ed.telemetry.ship_name")
    ed_ship_model = _state_value_with_fallback(state, "ed.status.ship_model", "ed.telemetry.ship_model")
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
    inara_secret = get_provider_secret_entry("inara", PROVIDER_SECRETS_PATH)
    ed_commander_name = str(inara_secret.get("commander_name") or "").strip() or None
    jinx_running = bool(state.get("app.jinx.running"))
    sammi_running = bool(state.get("app.sammi.running"))
    ytmd_running = bool(state.get("music.app_running"))
    queue_depth = (
        state.get("queue.depth")
        or state.get("brainstem.queue.depth")
        or state.get("ai.queue.depth")
        or 0
    )

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

    services = {
        "brainstem": {
            "name": "brainstem",
            "ok": True,
            "status": "up",
            "url": f"http://127.0.0.1:{PORT}/health",
            "detail": {"version": VERSION, "commit": COMMIT},
        },
        "advisory": advisory_status,
        "knowledge": knowledge_status,
        "qdrant": qdrant_status,
    }
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
                "system_name": ed_system_name,
                "system_address": ed_system_address,
                "docked": ed_dock_state,
                "supercruise": ed_supercruise,
                "landed": ed_landed,
                "shields_up": ed_shields_up,
                "lights_on": ed_lights_on,
                "night_vision": ed_night_vision,
                "flight_assist_off": ed_flight_assist_off,
                "landing_gear_down": ed_landing_gear_down,
            },
            "apps": {
                "ed_running": ed_running,
                "jinx_running": jinx_running,
                "sammi_running": sammi_running,
                "ytmd_running": ytmd_running,
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
                "music.status.playing",
                "music.playing",
                "music.now_playing.title",
                "music.now_playing.artist",
                "music.track.title",
                "music.track.artist",
                "music.now_playing",
                "hw.cpu.temp_c",
                "hw.gpu.temp_c",
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

    text = path.read_text(encoding="utf-8", errors="replace")
    selected = text.splitlines()[-lines:]
    return {
        "ok": True,
        "file": path.name,
        "path": str(path),
        "lines_requested": lines,
        "line_count": len(selected),
        "lines": selected,
    }


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
