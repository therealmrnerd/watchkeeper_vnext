from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from provider_secrets import DEFAULT_PROVIDER_SECRETS_PATH, get_provider_secret_entry


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PROVIDER_CONFIG_PATH = Path(ROOT_DIR / "config" / "providers.json")

KNOWN_PROVIDER_IDS = {"spansh", "edsm", "inara", "edsy"}
KNOWN_RATE_MODES = {"client"}
KNOWN_STATIC_MODES = {"vendored_static"}


def _require_keys(obj: dict[str, Any], required: set[str], obj_name: str) -> None:
    missing = sorted(required - set(obj.keys()))
    if missing:
        raise ValueError(f"{obj_name} missing required fields: {', '.join(missing)}")


def _validate_timeout_block(payload: dict[str, Any], obj_name: str) -> None:
    _require_keys(payload, {"connect", "read"}, obj_name)
    for key in ("connect", "read"):
        value = payload.get(key)
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"{obj_name}.{key} must be a positive integer")


def _validate_cache_block(payload: dict[str, Any], obj_name: str) -> None:
    _require_keys(payload, {"default_ttl_s", "stale_if_error_s"}, obj_name)
    for key in ("default_ttl_s", "stale_if_error_s"):
        value = payload.get(key)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{obj_name}.{key} must be an integer >= 0")


def _validate_rate_limit_block(payload: dict[str, Any], obj_name: str) -> None:
    _require_keys(payload, {"mode", "burst", "max_concurrent", "cooldown_on_fail_s"}, obj_name)
    mode = payload.get("mode")
    if mode not in KNOWN_RATE_MODES:
        raise ValueError(f"{obj_name}.mode must be one of: {', '.join(sorted(KNOWN_RATE_MODES))}")

    has_rps = isinstance(payload.get("rps"), (int, float))
    has_rpm = isinstance(payload.get("rpm"), (int, float))
    if not has_rps and not has_rpm:
        raise ValueError(f"{obj_name} requires rps or rpm")

    for key in ("rps", "rpm"):
        value = payload.get(key)
        if value is not None and (not isinstance(value, (int, float)) or value < 0):
            raise ValueError(f"{obj_name}.{key} must be a number >= 0 when supplied")

    for key in ("burst", "max_concurrent", "cooldown_on_fail_s"):
        value = payload.get(key)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{obj_name}.{key} must be an integer >= 0")
    if payload["burst"] < 1:
        raise ValueError(f"{obj_name}.burst must be >= 1")
    if payload["max_concurrent"] < 1:
        raise ValueError(f"{obj_name}.max_concurrent must be >= 1")


def _validate_http_provider(name: str, payload: dict[str, Any]) -> None:
    obj_name = f"providers.{name}"
    _require_keys(payload, {"enabled", "base_url", "timeouts_ms", "rate_limit", "cache", "features"}, obj_name)

    if not isinstance(payload.get("enabled"), bool):
        raise ValueError(f"{obj_name}.enabled must be boolean")
    if not isinstance(payload.get("base_url"), str) or not payload["base_url"].strip():
        raise ValueError(f"{obj_name}.base_url must be a non-empty string")
    if not isinstance(payload.get("timeouts_ms"), dict):
        raise ValueError(f"{obj_name}.timeouts_ms must be an object")
    if not isinstance(payload.get("rate_limit"), dict):
        raise ValueError(f"{obj_name}.rate_limit must be an object")
    if not isinstance(payload.get("cache"), dict):
        raise ValueError(f"{obj_name}.cache must be an object")
    if not isinstance(payload.get("features"), dict):
        raise ValueError(f"{obj_name}.features must be an object")

    _validate_timeout_block(payload["timeouts_ms"], f"{obj_name}.timeouts_ms")
    _validate_rate_limit_block(payload["rate_limit"], f"{obj_name}.rate_limit")
    _validate_cache_block(payload["cache"], f"{obj_name}.cache")


def _validate_static_provider(name: str, payload: dict[str, Any]) -> None:
    obj_name = f"providers.{name}"
    _require_keys(payload, {"enabled", "mode", "features"}, obj_name)
    if not isinstance(payload.get("enabled"), bool):
        raise ValueError(f"{obj_name}.enabled must be boolean")
    mode = payload.get("mode")
    if mode not in KNOWN_STATIC_MODES:
        raise ValueError(f"{obj_name}.mode must be one of: {', '.join(sorted(KNOWN_STATIC_MODES))}")
    if "version" in payload and payload.get("version") is not None and not isinstance(payload.get("version"), str):
        raise ValueError(f"{obj_name}.version must be string or null")
    if not isinstance(payload.get("features"), dict):
        raise ValueError(f"{obj_name}.features must be an object")


def validate_provider_config(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("provider_config must be an object")
    _require_keys(payload, {"schema_version", "provider_priority", "providers"}, "provider_config")

    if payload.get("schema_version") != "1.0":
        raise ValueError("provider_config.schema_version must be '1.0'")

    provider_priority = payload.get("provider_priority")
    if not isinstance(provider_priority, dict):
        raise ValueError("provider_config.provider_priority must be an object")
    for operation, providers in provider_priority.items():
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("provider_config.provider_priority keys must be non-empty strings")
        if not isinstance(providers, list) or not providers:
            raise ValueError(f"provider_config.provider_priority.{operation} must be a non-empty list")
        for provider_id in providers:
            if provider_id not in KNOWN_PROVIDER_IDS:
                raise ValueError(f"provider_config.provider_priority.{operation} contains unknown provider: {provider_id}")

    providers = payload.get("providers")
    if not isinstance(providers, dict):
        raise ValueError("provider_config.providers must be an object")

    missing_providers = sorted(KNOWN_PROVIDER_IDS - set(providers.keys()))
    if missing_providers:
        raise ValueError("provider_config.providers missing: " + ", ".join(missing_providers))

    for provider_id, config in providers.items():
        if provider_id not in KNOWN_PROVIDER_IDS:
            raise ValueError(f"provider_config.providers contains unsupported provider: {provider_id}")
        if not isinstance(config, dict):
            raise ValueError(f"provider_config.providers.{provider_id} must be an object")
        if provider_id == "edsy":
            _validate_static_provider(provider_id, config)
        else:
            _validate_http_provider(provider_id, config)


def load_provider_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path is not None else DEFAULT_PROVIDER_CONFIG_PATH
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    validate_provider_config(payload)
    return payload


def load_runtime_provider_config(
    path: str | Path | None = None,
    secrets_path: str | Path | None = None,
    codec: Any | None = None,
) -> dict[str, Any]:
    payload = deepcopy(load_provider_config(path))
    inara_secret = get_provider_secret_entry(
        "inara",
        secrets_path if secrets_path is not None else DEFAULT_PROVIDER_SECRETS_PATH,
        codec=codec,
    )
    if inara_secret:
        providers = payload.setdefault("providers", {})
        inara_cfg = providers.get("inara")
        if isinstance(inara_cfg, dict):
            auth = inara_cfg.setdefault("auth", {})
            if isinstance(auth, dict):
                for key in ("commander_name", "frontier_id", "app_key"):
                    value = inara_secret.get(key)
                    if value is not None:
                        auth[key] = value
    validate_provider_config(payload)
    return payload
