from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any


SETTINGS_CONFIG_KEY = "runtime_settings"

DEFAULT_RUNTIME_SETTINGS: dict[str, Any] = {
    "schema_version": "1.0",
    "providers": {
        "spansh": {"enabled": None, "live_applied": True, "label": "Spansh"},
        "edsm": {"enabled": None, "live_applied": True, "label": "EDSM"},
        "inara": {"enabled": None, "live_applied": True, "label": "Inara"},
        "openai": {"enabled": False, "live_applied": False, "label": "OpenAI Cloud Fallback"},
        "obs": {"enabled": False, "live_applied": False, "label": "OBS Status"},
    },
    "syncs": {
        "ed_provider_autocache": {"enabled": True, "live_applied": True, "label": "ED Provider Autocache"},
        "inara_location_sync": {"enabled": True, "live_applied": True, "label": "Inara Location Sync"},
        "jinx_lighting": {"enabled": True, "live_applied": True, "label": "Jinx Lighting Sync"},
        "ytmd_ingest": {"enabled": True, "live_applied": True, "label": "YTMD Ingest"},
        "sammi_bridge": {"enabled": True, "live_applied": True, "label": "SAMMI Bridge"},
        "twitch_ingest": {"enabled": True, "live_applied": True, "label": "Twitch Ingest"},
        "obs_status": {"enabled": False, "live_applied": False, "label": "OBS Status Polling"},
        "obs_effect_triggers": {"enabled": False, "live_applied": False, "label": "OBS Effect Triggers"},
    },
}

ALLOWED_PROVIDER_IDS = set(DEFAULT_RUNTIME_SETTINGS["providers"].keys())
ALLOWED_SYNC_IDS = set(DEFAULT_RUNTIME_SETTINGS["syncs"].keys())


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def _deepcopy_defaults() -> dict[str, Any]:
    return deepcopy(DEFAULT_RUNTIME_SETTINGS)


def _merge_into_defaults(payload: dict[str, Any] | None) -> dict[str, Any]:
    merged = _deepcopy_defaults()
    if not isinstance(payload, dict):
        return merged
    for section_name, allowed_ids in (("providers", ALLOWED_PROVIDER_IDS), ("syncs", ALLOWED_SYNC_IDS)):
        raw_section = payload.get(section_name)
        if not isinstance(raw_section, dict):
            continue
        for item_id, item_value in raw_section.items():
            if item_id not in allowed_ids or not isinstance(item_value, dict):
                continue
            if "enabled" in item_value and isinstance(item_value.get("enabled"), bool):
                merged[section_name][item_id]["enabled"] = item_value.get("enabled")
    return merged


def validate_runtime_settings_update(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("runtime_settings must be a JSON object")
    schema_version = payload.get("schema_version")
    if schema_version is not None and schema_version != "1.0":
        raise ValueError("runtime_settings.schema_version must be '1.0' when supplied")
    if "providers" not in payload and "syncs" not in payload:
        raise ValueError("runtime_settings update must include providers or syncs")

    for section_name, allowed_ids in (("providers", ALLOWED_PROVIDER_IDS), ("syncs", ALLOWED_SYNC_IDS)):
        section = payload.get(section_name)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise ValueError(f"runtime_settings.{section_name} must be an object")
        for item_id, item_value in section.items():
            if item_id not in allowed_ids:
                raise ValueError(f"runtime_settings.{section_name}.{item_id} is not supported")
            if not isinstance(item_value, dict):
                raise ValueError(f"runtime_settings.{section_name}.{item_id} must be an object")
            extra = sorted(set(item_value.keys()) - {"enabled"})
            if extra:
                raise ValueError(
                    f"runtime_settings.{section_name}.{item_id} contains unsupported fields: {', '.join(extra)}"
                )
            if "enabled" not in item_value:
                raise ValueError(f"runtime_settings.{section_name}.{item_id}.enabled is required")
            if not isinstance(item_value.get("enabled"), bool):
                raise ValueError(f"runtime_settings.{section_name}.{item_id}.enabled must be boolean")


def load_runtime_settings(db_path: Path) -> dict[str, Any]:
    try:
        with _connect(Path(db_path)) as con:
            row = con.execute(
                "SELECT value_json FROM config WHERE key=? LIMIT 1",
                (SETTINGS_CONFIG_KEY,),
            ).fetchone()
    except sqlite3.OperationalError:
        return _deepcopy_defaults()
    if not row:
        return _deepcopy_defaults()
    try:
        payload = json.loads(str(row["value_json"]))
    except Exception:
        payload = None
    return _merge_into_defaults(payload)


def save_runtime_settings(db_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    validate_runtime_settings_update(payload)
    current = load_runtime_settings(Path(db_path))
    updated = _merge_into_defaults(
        {
            "providers": {
                **{
                    key: {"enabled": value["enabled"]}
                    for key, value in current.get("providers", {}).items()
                    if isinstance(value, dict) and "enabled" in value
                },
                **(payload.get("providers") if isinstance(payload.get("providers"), dict) else {}),
            },
            "syncs": {
                **{
                    key: {"enabled": value["enabled"]}
                    for key, value in current.get("syncs", {}).items()
                    if isinstance(value, dict) and "enabled" in value
                },
                **(payload.get("syncs") if isinstance(payload.get("syncs"), dict) else {}),
            },
        }
    )
    with _connect(Path(db_path)) as con:
        con.execute(
            """
            INSERT INTO config(key, value_json, updated_at_utc)
            VALUES(?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            ON CONFLICT(key) DO UPDATE SET
              value_json=excluded.value_json,
              updated_at_utc=excluded.updated_at_utc
            """,
            (SETTINGS_CONFIG_KEY, json.dumps(updated, ensure_ascii=False)),
        )
        con.commit()
    return updated


def apply_runtime_settings_overrides(config: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(config)
    providers = merged.get("providers")
    if isinstance(providers, dict):
        provider_settings = settings.get("providers") if isinstance(settings.get("providers"), dict) else {}
        for provider_id, provider_cfg in providers.items():
            setting = provider_settings.get(provider_id)
            if (
                isinstance(provider_cfg, dict)
                and isinstance(setting, dict)
                and isinstance(setting.get("enabled"), bool)
            ):
                provider_cfg["enabled"] = bool(setting.get("enabled"))
    return merged


def runtime_setting_enabled(settings: dict[str, Any], section: str, item_id: str, default: bool) -> bool:
    section_obj = settings.get(section)
    if not isinstance(section_obj, dict):
        return bool(default)
    item = section_obj.get(item_id)
    if not isinstance(item, dict) or "enabled" not in item:
        return bool(default)
    return bool(item.get("enabled"))
