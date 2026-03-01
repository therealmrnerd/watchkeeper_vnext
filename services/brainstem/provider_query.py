from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from core.ed_provider_types import (
    ProviderCacheMeta,
    ProviderDenyReason,
    ProviderHealth,
    ProviderHealthStatus,
    ProviderId,
    ProviderOperationId,
    ProviderProvenance,
    ProviderQuery,
    ProviderRateLimitState,
    ProviderResult,
)
from provider_config import load_runtime_provider_config
from provider_health import (
    HttpProviderHealthProbe,
    InaraHealthProbe,
    list_provider_health,
    upsert_provider_health,
)
from settings_store import apply_runtime_settings_overrides, load_runtime_settings


FRONTIER_HEALTH_URL = os.getenv("WKV_FRONTIER_HEALTH_URL", "https://auth.frontierstore.net/").strip()
FRONTIER_STATUS_SITE_URL = os.getenv(
    "WKV_FRONTIER_STATUS_SITE_URL",
    "https://customersupport.frontier.co.uk",
).strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _iso_after(seconds: int) -> str:
    return (_utc_now() + timedelta(seconds=max(0, int(seconds)))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _cache_key(request: ProviderQuery) -> str:
    payload = {
        "provider": request.provider.value,
        "operation": request.operation.value,
        "params": request.params,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{request.provider.value}:{request.operation.value}:{digest}"


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def _provider_activity_summary(db_path: Path, provider_id: str, health: dict[str, Any] | None) -> dict[str, Any]:
    summary = {
        "last_success_at": None,
        "last_failure_at": None,
    }
    with _connect(db_path) as con:
        write_success_row = con.execute(
            """
            SELECT timestamp_utc
            FROM event_log
            WHERE source='provider_query'
              AND event_type='PROVIDER_WRITE_EXECUTED'
              AND json_extract(payload_json, '$.provider')=?
            ORDER BY timestamp_utc DESC
            LIMIT 1
            """,
            (provider_id,),
        ).fetchone()
        write_failure_row = con.execute(
            """
            SELECT timestamp_utc
            FROM event_log
            WHERE source='provider_query'
              AND event_type IN ('PROVIDER_WRITE_FAILED', 'PROVIDER_WRITE_DENIED')
              AND json_extract(payload_json, '$.provider')=?
            ORDER BY timestamp_utc DESC
            LIMIT 1
            """,
            (provider_id,),
        ).fetchone()
        cache_success_row = con.execute(
            """
            SELECT stored_at
            FROM provider_cache
            WHERE provider=?
            ORDER BY stored_at DESC
            LIMIT 1
            """,
            (provider_id,),
        ).fetchone()

    if cache_success_row:
        summary["last_success_at"] = str(cache_success_row["stored_at"])
    if write_success_row:
        write_success_at = str(write_success_row["timestamp_utc"])
        if summary["last_success_at"] is None or write_success_at > str(summary["last_success_at"]):
            summary["last_success_at"] = write_success_at
    if write_failure_row:
        summary["last_failure_at"] = str(write_failure_row["timestamp_utc"])

    if isinstance(health, dict):
        checked_at = str(health.get("checked_at") or "").strip() or None
        status = str(health.get("status") or "").strip().lower()
        if checked_at:
            if status in {"ok", "degraded"}:
                if summary["last_success_at"] is None or checked_at > str(summary["last_success_at"]):
                    summary["last_success_at"] = checked_at
            elif status in {"down", "throttled", "misconfigured"}:
                if summary["last_failure_at"] is None or checked_at > str(summary["last_failure_at"]):
                    summary["last_failure_at"] = checked_at
    return summary


def _as_provider_health(raw: dict[str, Any] | None) -> ProviderHealth | None:
    if not raw or not isinstance(raw, dict):
        return None
    try:
        http_obj = raw.get("http") if isinstance(raw.get("http"), dict) else {}
        rate_limit = raw.get("rate_limit") if isinstance(raw.get("rate_limit"), dict) else {}
        capabilities = raw.get("capabilities") if isinstance(raw.get("capabilities"), dict) else {}
        return ProviderHealth(
            provider=ProviderId(str(raw.get("provider") or "").strip().lower()),
            status=ProviderHealthStatus(str(raw.get("status") or "").strip().lower()),
            checked_at=str(raw.get("checked_at") or ""),
            latency_ms=raw.get("latency_ms"),
            http_code=http_obj.get("code"),
            rate_limit_state=ProviderRateLimitState(str(rate_limit.get("state") or "unknown")),
            retry_after_s=rate_limit.get("retry_after_s"),
            tool_calls_allowed=bool(capabilities.get("tool_calls_allowed")),
            degraded_readonly=bool(capabilities.get("degraded_readonly")),
            message=str(raw.get("message") or ""),
        )
    except Exception:
        return None


def get_provider_health_map(db_path: Path) -> dict[str, dict[str, Any]]:
    try:
        return list_provider_health(db_path)
    except sqlite3.Error:
        return {}


def query_provider_health(
    db_path: Path,
    config_path: str | Path | None = None,
    secrets_path: str | Path | None = None,
) -> dict[str, Any]:
    settings = load_runtime_settings(db_path)
    config = apply_runtime_settings_overrides(
        load_runtime_provider_config(config_path, secrets_path),
        settings,
    )
    stored = get_provider_health_map(db_path)
    providers_cfg = config.get("providers", {})
    out: dict[str, Any] = {}
    for provider_id, cfg in providers_cfg.items():
        if not isinstance(cfg, dict):
            continue
        auth = cfg.get("auth") if isinstance(cfg.get("auth"), dict) else {}
        sync_cfg = cfg.get("sync") if isinstance(cfg.get("sync"), dict) else {}
        auth_summary = None
        if auth:
            mode = str(auth.get("mode") or "").strip() or None
            commander_name_present = bool(str(auth.get("commander_name") or "").strip())
            app_name_present = bool(str(auth.get("app_name") or "").strip())
            api_key_present = bool(str(auth.get("api_key") or "").strip())
            app_key_present = bool(str(auth.get("app_key") or "").strip())
            frontier_id_present = bool(str(auth.get("frontier_id") or "").strip())
            configured = False
            if provider_id == "inara":
                configured = app_name_present and app_key_present and commander_name_present
            elif provider_id == "edsm":
                configured = commander_name_present and api_key_present
            auth_summary = {
                "mode": mode,
                "configured": configured,
                "commander_name_present": commander_name_present,
                "app_name_present": app_name_present,
                "api_key_present": api_key_present,
                "app_key_present": app_key_present,
                "frontier_id_present": frontier_id_present,
            }
        out[provider_id] = {
            "enabled": bool(cfg.get("enabled")),
            "base_url": str(cfg.get("base_url") or "").strip() or None,
            "features": cfg.get("features") if isinstance(cfg.get("features"), dict) else {},
            "auth_summary": auth_summary,
            "sync": sync_cfg,
            "settings": (
                settings.get("providers", {}).get(provider_id)
                if isinstance(settings.get("providers"), dict)
                else None
            ),
            "health": stored.get(provider_id),
            "activity_summary": _provider_activity_summary(db_path, provider_id, stored.get(provider_id)),
        }
    out[ProviderId.FRONTIER.value] = {
        "enabled": True,
        "base_url": FRONTIER_STATUS_SITE_URL or FRONTIER_HEALTH_URL or None,
        "features": {
            "service_health": True,
            "read_only": True,
        },
        "auth_summary": None,
        "sync": {},
        "settings": {
            "enabled": True,
            "live_applied": True,
            "label": "Frontier Services",
            "system_managed": True,
        },
        "health": stored.get(ProviderId.FRONTIER.value),
        "activity_summary": _provider_activity_summary(
            db_path,
            ProviderId.FRONTIER.value,
            stored.get(ProviderId.FRONTIER.value),
        ),
    }
    return {"ok": True, "providers": out}


@dataclass
class SpanshSystemLookupAdapter:
    base_url: str
    timeout_sec: float
    opener: Callable[..., Any] = urllib.request.urlopen

    def _get_json(self, url: str) -> tuple[Any, int]:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "watchkeeper-vnext"})
        with self.opener(req, timeout=self.timeout_sec) as resp:
            status = int(getattr(resp, "status", 200))
            body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else None, status

    def _search_systems(self, system_name: str) -> tuple[list[dict[str, Any]], int]:
        query = urllib.parse.urlencode({"q": system_name})
        payload, status = self._get_json(f"{self.base_url}/api/search/systems?{query}")
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            return payload["results"], status
        if isinstance(payload, list):
            return [{"name": item} for item in payload], status
        return [], status

    @staticmethod
    def _pick_system_id(system_name: str, search_results: list[dict[str, Any]]) -> int | None:
        wanted = str(system_name or "").strip().casefold()
        if not wanted:
            return None
        for item in search_results:
            if str(item.get("name") or "").strip().casefold() == wanted:
                raw_id = item.get("id64")
                if isinstance(raw_id, int):
                    return raw_id
                try:
                    return int(str(raw_id))
                except Exception:
                    return None
        return None

    @staticmethod
    def _normalize_record(record: dict[str, Any], fetched_at: str) -> dict[str, Any]:
        bodies = record.get("bodies") if isinstance(record.get("bodies"), list) else []
        stations = record.get("stations") if isinstance(record.get("stations"), list) else []
        return {
            "system_address": int(record["id64"]),
            "name": str(record.get("name") or ""),
            "coords": {
                "x": record.get("x"),
                "y": record.get("y"),
                "z": record.get("z"),
            },
            "allegiance": record.get("allegiance"),
            "government": record.get("government"),
            "security": record.get("security"),
            "primary_economy": record.get("primary_economy"),
            "secondary_economy": record.get("secondary_economy"),
            "population": record.get("population"),
            "body_count": int(record.get("body_count") or len(bodies) or 0),
            "station_count": int(len(stations)),
            "provider_updated_at": record.get("updated_at"),
            "region": record.get("region"),
            "known_permit": record.get("known_permit"),
            "needs_permit": record.get("needs_permit"),
            "fetched_at": fetched_at,
        }

    @staticmethod
    def _normalize_bodies(record: dict[str, Any], fetched_at: str) -> dict[str, Any]:
        bodies_raw = record.get("bodies") if isinstance(record.get("bodies"), list) else []
        items: list[dict[str, Any]] = []
        system_address = int(record["id64"])
        system_name = str(record.get("name") or "")
        for raw in bodies_raw:
            if not isinstance(raw, dict):
                continue
            extras = {
                "estimated_mapping_value": raw.get("estimated_mapping_value"),
                "estimated_scan_value": raw.get("estimated_scan_value"),
                "is_main_star": raw.get("is_main_star"),
                "parents": raw.get("parents"),
                "signals": raw.get("signals"),
                "volcanism_type": raw.get("volcanism_type"),
            }
            items.append(
                {
                    "body_id64": raw.get("id64"),
                    "system_address": system_address,
                    "system_name": system_name,
                    "name": str(raw.get("name") or ""),
                    "body_type": raw.get("type"),
                    "subtype": raw.get("subtype"),
                    "distance_to_arrival_ls": raw.get("distance_to_arrival"),
                    "terraform_state": raw.get("terraforming_state"),
                    "atmosphere": raw.get("atmosphere_type"),
                    "gravity": raw.get("gravity"),
                    "radius": raw.get("radius"),
                    "mass": raw.get("solar_mass") if raw.get("solar_mass") is not None else raw.get("earth_mass"),
                    "extras": extras,
                }
            )
        return {
            "system_address": system_address,
            "system_name": system_name,
            "body_count": len(items),
            "items": items,
            "fetched_at": fetched_at,
        }

    @staticmethod
    def _normalize_stations(record: dict[str, Any], fetched_at: str) -> dict[str, Any]:
        stations_raw = record.get("stations") if isinstance(record.get("stations"), list) else []
        items: list[dict[str, Any]] = []
        system_address = int(record["id64"])
        system_name = str(record.get("name") or "")
        for raw in stations_raw:
            if not isinstance(raw, dict):
                continue
            services = raw.get("services") if isinstance(raw.get("services"), list) else []
            items.append(
                {
                    "market_id": raw.get("market_id"),
                    "station_id64": raw.get("id"),
                    "system_address": system_address,
                    "system_name": system_name,
                    "name": str(raw.get("name") or ""),
                    "station_type": raw.get("type"),
                    "distance_to_arrival_ls": raw.get("distance_to_arrival"),
                    "has_docking": bool(
                        raw.get("has_market")
                        or raw.get("has_shipyard")
                        or raw.get("has_outfitting")
                        or raw.get("large_pads")
                        or raw.get("medium_pads")
                        or raw.get("small_pads")
                    ),
                    "services": services,
                }
            )
        return {
            "system_address": system_address,
            "system_name": system_name,
            "station_count": len(items),
            "items": items,
            "fetched_at": fetched_at,
        }

    def _resolve_record(self, request: ProviderQuery) -> tuple[dict[str, Any], dict[str, Any]]:
        system_address_raw = request.params.get("system_address")
        system_name = str(request.params.get("system_name") or "").strip()
        endpoint_url: str
        status_code: int
        if system_address_raw is not None:
            try:
                system_address = int(system_address_raw)
            except Exception as exc:
                raise ValueError("params.system_address must be an integer") from exc
        elif system_name:
            results, _ = self._search_systems(system_name)
            system_address = self._pick_system_id(system_name, results) or 0
            if not system_address:
                raise LookupError(f"spansh system not found: {system_name}")
        else:
            raise ValueError("params.system_name or params.system_address is required")

        endpoint_url = f"{self.base_url}/api/system/{system_address}"
        payload, status_code = self._get_json(endpoint_url)
        record = payload.get("record") if isinstance(payload, dict) else None
        if not isinstance(record, dict):
            raise LookupError("spansh returned no system record")
        fetched_at = _utc_now_iso()
        return record, {
            "endpoint": endpoint_url,
            "http_code": status_code,
            "raw": payload,
            "fetched_at": fetched_at,
        }

    def lookup(self, request: ProviderQuery) -> tuple[dict[str, Any], dict[str, Any]]:
        record, meta = self._resolve_record(request)
        fetched_at = str(meta.get("fetched_at") or _utc_now_iso())
        if request.operation == ProviderOperationId.SYSTEM_LOOKUP:
            normalized = self._normalize_record(record, fetched_at)
        elif request.operation == ProviderOperationId.BODIES_LOOKUP:
            normalized = self._normalize_bodies(record, fetched_at)
        elif request.operation == ProviderOperationId.STATIONS_LOOKUP:
            normalized = self._normalize_stations(record, fetched_at)
        else:
            raise ValueError(f"spansh does not implement {request.operation.value}")
        return normalized, meta


@dataclass
class EdsmSystemLookupAdapter:
    base_url: str
    timeout_sec: float
    opener: Callable[..., Any] = urllib.request.urlopen

    def _get_json(self, url: str) -> tuple[Any, int]:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "watchkeeper-vnext"})
        with self.opener(req, timeout=self.timeout_sec) as resp:
            status = int(getattr(resp, "status", 200))
            body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else None, status

    @staticmethod
    def _normalize_record(record: dict[str, Any], fetched_at: str) -> dict[str, Any]:
        info = record.get("information") if isinstance(record.get("information"), dict) else {}
        coords = record.get("coords") if isinstance(record.get("coords"), dict) else {}
        require_permit = record.get("requirePermit")
        return {
            "system_address": int(record["id64"]) if record.get("id64") is not None else None,
            "name": str(record.get("name") or ""),
            "coords": {
                "x": coords.get("x"),
                "y": coords.get("y"),
                "z": coords.get("z"),
            },
            "allegiance": info.get("allegiance"),
            "government": info.get("government"),
            "security": info.get("security"),
            "primary_economy": info.get("economy"),
            "secondary_economy": info.get("secondEconomy"),
            "population": info.get("population"),
            "body_count": None,
            "station_count": None,
            "provider_updated_at": None,
            "region": None,
            "known_permit": record.get("permitName"),
            "needs_permit": bool(require_permit) if require_permit is not None else None,
            "fetched_at": fetched_at,
        }

    def lookup(self, request: ProviderQuery) -> tuple[dict[str, Any], dict[str, Any]]:
        if request.operation != ProviderOperationId.SYSTEM_LOOKUP:
            raise ValueError(f"edsm does not implement {request.operation.value}")
        system_name = str(request.params.get("system_name") or "").strip()
        if not system_name:
            raise ValueError("params.system_name is required for edsm system_lookup")
        query = urllib.parse.urlencode(
            {
                "systemName": system_name,
                "showCoordinates": 1,
                "showInformation": 1,
                "showPermit": 1,
                "showId": 1,
            }
        )
        endpoint_url = f"{self.base_url}/api-v1/system?{query}"
        payload, status_code = self._get_json(endpoint_url)
        if not isinstance(payload, dict) or not str(payload.get("name") or "").strip():
            raise LookupError(f"edsm system not found: {system_name}")
        fetched_at = _utc_now_iso()
        return self._normalize_record(payload, fetched_at), {
            "endpoint": endpoint_url,
            "http_code": status_code,
            "raw": payload,
            "fetched_at": fetched_at,
        }


@dataclass
class InaraLocationSyncAdapter:
    base_url: str
    timeout_sec: float
    app_name: str
    app_key: str
    commander_name: str
    frontier_id: str | None
    opener: Callable[..., Any] = urllib.request.urlopen

    def _endpoint_url(self) -> str:
        return f"{str(self.base_url or '').rstrip('/')}/inapi/v1/"

    def sync_location(self, request: ProviderQuery) -> tuple[dict[str, Any], dict[str, Any]]:
        system_name = str(request.params.get("system_name") or "").strip()
        if not system_name:
            raise ValueError("params.system_name is required for inara commander_location_push")

        header = {
            "appName": self.app_name,
            "appVersion": "watchkeeper-vnext",
            "APIkey": self.app_key,
            "commanderName": self.commander_name,
        }
        if str(self.frontier_id or "").strip():
            header["commanderFrontierID"] = str(self.frontier_id).strip()

        event_data: dict[str, Any] = {"starsystemName": system_name}
        if request.params.get("system_address") is not None:
            try:
                event_data["systemAddress"] = int(request.params.get("system_address"))
            except Exception:
                pass
        if str(request.params.get("station_name") or "").strip():
            event_data["stationName"] = str(request.params.get("station_name")).strip()

        payload = {
            "header": header,
            "events": [
                {
                    "eventName": "setCommanderTravelLocation",
                    "eventTimestamp": _utc_now_iso(),
                    "eventData": event_data,
                }
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint_url = self._endpoint_url()
        req = urllib.request.Request(
            endpoint_url,
            method="POST",
            data=raw,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "watchkeeper-vnext",
            },
        )
        with self.opener(req, timeout=self.timeout_sec) as resp:
            status = int(getattr(resp, "status", 200))
            body = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(body) if body else {}
        event_status = None
        event_status_text = ""
        if isinstance(parsed, dict):
            events = parsed.get("events")
            if isinstance(events, list) and events and isinstance(events[0], dict):
                event_status = events[0].get("eventStatus")
                event_status_text = str(events[0].get("eventStatusText") or "")
        if event_status is not None:
            try:
                event_code = int(event_status)
            except Exception as exc:
                raise RuntimeError("inara returned invalid eventStatus") from exc
            if event_code < 200 or event_code >= 300:
                raise RuntimeError(event_status_text or f"inara eventStatus={event_code}")
        fetched_at = _utc_now_iso()
        normalized = {
            "commander_name": self.commander_name,
            "frontier_id": self.frontier_id,
            "system_name": system_name,
            "system_address": request.params.get("system_address"),
            "station_name": request.params.get("station_name"),
            "sync_skipped": False,
            "synced_at": fetched_at,
        }
        return normalized, {
            "endpoint": endpoint_url,
            "http_code": status,
            "raw": parsed,
            "fetched_at": fetched_at,
        }


class ProviderQueryService:
    def __init__(
        self,
        *,
        db_path: Path,
        config_path: str | Path | None = None,
        secrets_path: str | Path | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.db_path = Path(db_path)
        self.config_path = config_path
        self.secrets_path = secrets_path
        self.opener = opener
        self.reload_config()

    def reload_config(self) -> None:
        self.settings = load_runtime_settings(self.db_path)
        self.config = apply_runtime_settings_overrides(
            load_runtime_provider_config(self.config_path, self.secrets_path),
            self.settings,
        )
        self._spansh = self._build_spansh_adapter()
        self._edsm = self._build_edsm_adapter()
        self._inara = self._build_inara_adapter()
        self._probes = self._build_probes()

    def _build_spansh_adapter(self) -> SpanshSystemLookupAdapter | None:
        cfg = self.config.get("providers", {}).get("spansh")
        if not isinstance(cfg, dict) or not bool(cfg.get("enabled")):
            return None
        timeout_ms = cfg.get("timeouts_ms", {}).get("read", 4000)
        try:
            timeout_sec = max(0.1, float(timeout_ms) / 1000.0)
        except Exception:
            timeout_sec = 4.0
        return SpanshSystemLookupAdapter(
            base_url=str(cfg.get("base_url") or "").strip().rstrip("/"),
            timeout_sec=timeout_sec,
            opener=self.opener,
        )

    def _build_edsm_adapter(self) -> EdsmSystemLookupAdapter | None:
        cfg = self.config.get("providers", {}).get("edsm")
        if not isinstance(cfg, dict) or not bool(cfg.get("enabled")):
            return None
        timeout_ms = cfg.get("timeouts_ms", {}).get("read", 4000)
        try:
            timeout_sec = max(0.1, float(timeout_ms) / 1000.0)
        except Exception:
            timeout_sec = 4.0
        return EdsmSystemLookupAdapter(
            base_url=str(cfg.get("base_url") or "").strip().rstrip("/"),
            timeout_sec=timeout_sec,
            opener=self.opener,
        )

    def _build_inara_adapter(self) -> InaraLocationSyncAdapter | None:
        cfg = self.config.get("providers", {}).get("inara")
        if not isinstance(cfg, dict) or not bool(cfg.get("enabled")):
            return None
        timeout_ms = cfg.get("timeouts_ms", {}).get("read", 5000)
        try:
            timeout_sec = max(0.1, float(timeout_ms) / 1000.0)
        except Exception:
            timeout_sec = 5.0
        auth = cfg.get("auth", {}) if isinstance(cfg.get("auth"), dict) else {}
        return InaraLocationSyncAdapter(
            base_url=str(cfg.get("base_url") or "").strip(),
            timeout_sec=timeout_sec,
            app_name=str(auth.get("app_name") or "").strip(),
            app_key=str(auth.get("app_key") or "").strip(),
            commander_name=str(auth.get("commander_name") or "").strip(),
            frontier_id=(str(auth.get("frontier_id")).strip() if auth.get("frontier_id") is not None else None),
            opener=self.opener,
        )

    def _build_probes(self) -> dict[str, Any]:
        probes: dict[str, Any] = {}
        providers = self.config.get("providers", {})
        for provider_name in ("spansh", "edsm"):
            cfg = providers.get(provider_name)
            if not isinstance(cfg, dict) or not bool(cfg.get("enabled")):
                continue
            timeout_ms = cfg.get("timeouts_ms", {}).get("read", 4000)
            try:
                timeout_sec = max(0.1, float(timeout_ms) / 1000.0)
            except Exception:
                timeout_sec = 4.0
            probes[provider_name] = HttpProviderHealthProbe(
                provider_id=ProviderId(provider_name),
                base_url=str(cfg.get("base_url") or "").strip(),
                timeout_sec=timeout_sec,
                read_only=bool(cfg.get("features", {}).get("read_only", True)),
                opener=self.opener,
            )
        inara_cfg = providers.get("inara")
        if isinstance(inara_cfg, dict) and bool(inara_cfg.get("enabled")):
            timeout_ms = inara_cfg.get("timeouts_ms", {}).get("read", 5000)
            try:
                timeout_sec = max(0.1, float(timeout_ms) / 1000.0)
            except Exception:
                timeout_sec = 5.0
            auth = inara_cfg.get("auth", {}) if isinstance(inara_cfg.get("auth"), dict) else {}
            probes["inara"] = InaraHealthProbe(
                provider_id=ProviderId.INARA,
                base_url=str(inara_cfg.get("base_url") or "").strip(),
                timeout_sec=timeout_sec,
                app_name=str(auth.get("app_name") or "").strip(),
                app_key=str(auth.get("app_key") or "").strip(),
                commander_name=str(auth.get("commander_name") or "").strip(),
                opener=self.opener,
            )
        return probes

    def _append_provider_event(self, *, event_type: str, severity: str, payload: dict[str, Any]) -> None:
        with _connect(self.db_path) as con:
            con.execute(
                """
                INSERT INTO event_log(
                    event_id,timestamp_utc,event_type,source,profile,session_id,correlation_id,
                    mode,severity,payload_json,tags_json
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()),
                    _utc_now_iso(),
                    event_type,
                    "provider_query",
                    "watchkeeper",
                    None,
                    payload.get("incident_id"),
                    "game",
                    severity,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(["providers", str(payload.get("provider") or ""), str(payload.get("operation") or "")]),
                ),
            )
            con.commit()

    def _recent_write_count(self, *, provider: ProviderId, operation: ProviderOperationId, window_s: int) -> int:
        cutoff = (_utc_now() - timedelta(seconds=max(1, int(window_s)))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        count = 0
        with _connect(self.db_path) as con:
            rows = con.execute(
                """
                SELECT payload_json
                FROM event_log
                WHERE source='provider_query'
                  AND event_type='PROVIDER_WRITE_EXECUTED'
                  AND timestamp_utc>=?
                ORDER BY id DESC
                """,
                (cutoff,),
            ).fetchall()
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except Exception:
                continue
            if payload.get("provider") == provider.value and payload.get("operation") == operation.value:
                count += 1
        return count

    def _last_successful_write(
        self,
        *,
        provider: ProviderId,
        operation: ProviderOperationId,
    ) -> dict[str, Any] | None:
        with _connect(self.db_path) as con:
            rows = con.execute(
                """
                SELECT payload_json
                FROM event_log
                WHERE source='provider_query'
                  AND event_type='PROVIDER_WRITE_EXECUTED'
                ORDER BY id DESC
                LIMIT 20
                """
            ).fetchall()
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except Exception:
                continue
            if payload.get("provider") == provider.value and payload.get("operation") == operation.value:
                return payload
        return None

    def _handle_inara_write(self, request: ProviderQuery, provider_cfg: dict[str, Any]) -> ProviderResult:
        health = self._get_health(request.provider)
        if health and health.status in {
            ProviderHealthStatus.DOWN,
            ProviderHealthStatus.MISCONFIGURED,
            ProviderHealthStatus.THROTTLED,
        }:
            deny_reason = ProviderDenyReason.PROVIDER_DOWN
            if health.status == ProviderHealthStatus.MISCONFIGURED:
                deny_reason = ProviderDenyReason.MISCONFIGURED
            elif health.status == ProviderHealthStatus.THROTTLED:
                deny_reason = ProviderDenyReason.RATE_LIMITED
            self._append_provider_event(
                event_type="PROVIDER_WRITE_DENIED",
                severity="warn",
                payload={
                    "provider": request.provider.value,
                    "operation": request.operation.value,
                    "incident_id": request.incident_id,
                    "reason": request.reason,
                    "system_name": request.params.get("system_name"),
                    "system_address": request.params.get("system_address"),
                    "deny_reason": deny_reason.value,
                    "message": health.message if health else "",
                },
            )
            return ProviderResult(
                ok=False,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(),
                health_observed=health,
                data=None,
                provenance=ProviderProvenance(endpoint=None, http_code=None),
                error=health.message if health else "provider unavailable",
                deny_reason=deny_reason,
            )

        if self._inara is None:
            return ProviderResult(
                ok=False,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(),
                health_observed=health,
                data=None,
                provenance=ProviderProvenance(endpoint=None, http_code=None),
                error="inara adapter is not configured",
                deny_reason=ProviderDenyReason.MISCONFIGURED,
            )

        sync_cfg = provider_cfg.get("sync", {}) if isinstance(provider_cfg.get("sync"), dict) else {}
        debounce_s = max(0, int(sync_cfg.get("location_debounce_s", 300)))
        last_success = self._last_successful_write(
            provider=request.provider,
            operation=request.operation,
        )
        if debounce_s > 0 and isinstance(last_success, dict):
            same_system = (
                last_success.get("system_name") == request.params.get("system_name")
                and last_success.get("system_address") == request.params.get("system_address")
            )
            last_timestamp = _parse_iso8601(last_success.get("timestamp_utc"))
            if same_system and last_timestamp is not None:
                age_s = int((_utc_now() - last_timestamp).total_seconds())
                if age_s < debounce_s:
                    payload = {
                        "provider": request.provider.value,
                        "operation": request.operation.value,
                        "incident_id": request.incident_id,
                        "reason": request.reason,
                        "system_name": request.params.get("system_name"),
                        "system_address": request.params.get("system_address"),
                        "timestamp_utc": _utc_now_iso(),
                        "skip_reason": "debounced",
                        "debounce_s": debounce_s,
                        "age_s": age_s,
                    }
                    self._append_provider_event(
                        event_type="PROVIDER_WRITE_SKIPPED",
                        severity="info",
                        payload=payload,
                    )
                    return ProviderResult(
                        ok=True,
                        provider=request.provider,
                        operation=request.operation,
                        fetched_at=payload["timestamp_utc"],
                        cache=ProviderCacheMeta(),
                        health_observed=health,
                        data={
                            "sync_skipped": True,
                            "sync_reason": "debounced",
                            "system_name": request.params.get("system_name"),
                            "system_address": request.params.get("system_address"),
                            "debounce_s": debounce_s,
                            "age_s": age_s,
                        },
                        provenance=ProviderProvenance(endpoint=None, http_code=None),
                        error=None,
                        deny_reason=None,
                    )

        rpm_limit = int(provider_cfg.get("rate_limit", {}).get("rpm", 0) or 0)
        if rpm_limit > 0:
            recent_count = self._recent_write_count(
                provider=request.provider,
                operation=request.operation,
                window_s=60,
            )
            if recent_count >= rpm_limit:
                observed = ProviderHealth(
                    provider=request.provider,
                    status=ProviderHealthStatus.THROTTLED,
                    checked_at=_utc_now_iso(),
                    latency_ms=None,
                    http_code=429,
                    rate_limit_state=ProviderRateLimitState.THROTTLED,
                    retry_after_s=60,
                    tool_calls_allowed=False,
                    degraded_readonly=False,
                    message="client_rpm_limit",
                )
                upsert_provider_health(self.db_path, observed)
                self._append_provider_event(
                    event_type="PROVIDER_WRITE_DENIED",
                    severity="warn",
                    payload={
                        "provider": request.provider.value,
                        "operation": request.operation.value,
                        "incident_id": request.incident_id,
                        "reason": request.reason,
                        "system_name": request.params.get("system_name"),
                        "system_address": request.params.get("system_address"),
                        "deny_reason": ProviderDenyReason.RATE_LIMITED.value,
                        "message": "client_rpm_limit",
                        "recent_count": recent_count,
                        "rpm_limit": rpm_limit,
                    },
                )
                return ProviderResult(
                    ok=False,
                    provider=request.provider,
                    operation=request.operation,
                    fetched_at=_utc_now_iso(),
                    cache=ProviderCacheMeta(),
                    health_observed=observed,
                    data=None,
                    provenance=ProviderProvenance(endpoint=None, http_code=429),
                    error="client_rpm_limit",
                    deny_reason=ProviderDenyReason.RATE_LIMITED,
                )

        started = time.time()
        try:
            normalized, meta = self._inara.sync_location(request)
            observed = ProviderHealth(
                provider=request.provider,
                status=ProviderHealthStatus.OK,
                checked_at=_utc_now_iso(),
                latency_ms=int((time.time() - started) * 1000),
                http_code=int(meta.get("http_code") or 200),
                rate_limit_state=ProviderRateLimitState.OK,
                retry_after_s=None,
                tool_calls_allowed=True,
                degraded_readonly=False,
                message="healthy",
            )
            upsert_provider_health(self.db_path, observed)
            self._append_provider_event(
                event_type="PROVIDER_WRITE_EXECUTED",
                severity="info",
                payload={
                    "provider": request.provider.value,
                    "operation": request.operation.value,
                    "incident_id": request.incident_id,
                    "reason": request.reason,
                    "timestamp_utc": str(meta.get("fetched_at") or _utc_now_iso()),
                    "system_name": normalized.get("system_name"),
                    "system_address": normalized.get("system_address"),
                    "station_name": normalized.get("station_name"),
                },
            )
            return ProviderResult(
                ok=True,
                provider=request.provider,
                operation=request.operation,
                fetched_at=str(meta.get("fetched_at") or _utc_now_iso()),
                cache=ProviderCacheMeta(),
                health_observed=observed,
                data=normalized,
                provenance=ProviderProvenance(
                    endpoint=str(meta.get("endpoint") or ""),
                    http_code=int(meta.get("http_code") or 200),
                ),
                error=None,
                deny_reason=None,
            )
        except urllib.error.HTTPError as exc:
            observed = ProviderHealth(
                provider=request.provider,
                status=ProviderHealthStatus.THROTTLED if int(exc.code) == 429 else ProviderHealthStatus.DOWN,
                checked_at=_utc_now_iso(),
                latency_ms=int((time.time() - started) * 1000),
                http_code=int(exc.code),
                rate_limit_state=(
                    ProviderRateLimitState.THROTTLED if int(exc.code) == 429 else ProviderRateLimitState.UNKNOWN
                ),
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=False,
                message=f"http_{int(exc.code)}",
            )
            upsert_provider_health(self.db_path, observed)
            self._append_provider_event(
                event_type="PROVIDER_WRITE_FAILED",
                severity="warn",
                payload={
                    "provider": request.provider.value,
                    "operation": request.operation.value,
                    "incident_id": request.incident_id,
                    "reason": request.reason,
                    "system_name": request.params.get("system_name"),
                    "system_address": request.params.get("system_address"),
                    "message": f"http_{int(exc.code)}",
                },
            )
            return ProviderResult(
                ok=False,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(),
                health_observed=observed,
                data=None,
                provenance=ProviderProvenance(endpoint=None, http_code=int(exc.code)),
                error=f"provider HTTP {int(exc.code)}",
                deny_reason=ProviderDenyReason.RATE_LIMITED if int(exc.code) == 429 else ProviderDenyReason.PROVIDER_DOWN,
            )
        except Exception as exc:
            observed = ProviderHealth(
                provider=request.provider,
                status=ProviderHealthStatus.DOWN,
                checked_at=_utc_now_iso(),
                latency_ms=None,
                http_code=None,
                rate_limit_state=ProviderRateLimitState.UNKNOWN,
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=False,
                message=str(exc),
            )
            upsert_provider_health(self.db_path, observed)
            self._append_provider_event(
                event_type="PROVIDER_WRITE_FAILED",
                severity="warn",
                payload={
                    "provider": request.provider.value,
                    "operation": request.operation.value,
                    "incident_id": request.incident_id,
                    "reason": request.reason,
                    "system_name": request.params.get("system_name"),
                    "system_address": request.params.get("system_address"),
                    "message": str(exc),
                },
            )
            return ProviderResult(
                ok=False,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(),
                health_observed=observed,
                data=None,
                provenance=ProviderProvenance(endpoint=None, http_code=None),
                error=str(exc),
                deny_reason=ProviderDenyReason.PROVIDER_DOWN,
            )

    def _get_health(self, provider: ProviderId) -> ProviderHealth | None:
        raw = get_provider_health_map(self.db_path).get(provider.value)
        parsed = _as_provider_health(raw)
        if parsed is not None:
            if (
                parsed.status == ProviderHealthStatus.THROTTLED
                and isinstance(parsed.retry_after_s, int)
                and parsed.retry_after_s >= 0
            ):
                checked_at = _parse_iso8601(parsed.checked_at)
                if checked_at is not None:
                    age_s = int((_utc_now() - checked_at).total_seconds())
                    if age_s < parsed.retry_after_s:
                        return parsed
                # retry window elapsed: re-probe instead of leaving the provider stuck throttled
            else:
                return parsed
        probe = self._probes.get(provider.value)
        if probe is None:
            return None
        health = probe.probe()
        upsert_provider_health(self.db_path, health)
        return health

    def _read_cache(self, cache_key: str) -> tuple[sqlite3.Row | None, bool, int | None]:
        with _connect(self.db_path) as con:
            row = con.execute(
                """
                SELECT cache_key,stored_at,expires_at,normalized_json,raw_json
                FROM provider_cache
                WHERE cache_key=?
                LIMIT 1
                """,
                (cache_key,),
            ).fetchone()
            if row:
                con.execute(
                    "UPDATE provider_cache SET last_accessed_at_utc=? WHERE cache_key=?",
                    (_utc_now_iso(), cache_key),
                )
                con.commit()
        if not row:
            return None, False, None
        expires_at = _parse_iso8601(str(row["expires_at"]))
        stored_at = _parse_iso8601(str(row["stored_at"]))
        now = _utc_now()
        expired = True
        age_s = None
        if expires_at is not None:
            expired = now >= expires_at
        if stored_at is not None:
            age_s = max(0, int((now - stored_at).total_seconds()))
        return row, expired, age_s

    def _write_cache(
        self,
        *,
        cache_key: str,
        provider: ProviderId,
        operation: ProviderOperationId,
        expires_at: str,
        normalized: dict[str, Any],
        raw_payload: Any,
    ) -> None:
        stored_at = _utc_now_iso()
        with _connect(self.db_path) as con:
            con.execute(
                """
                INSERT INTO provider_cache(
                    cache_key,provider,operation,stored_at,expires_at,normalized_json,raw_json,last_accessed_at_utc,updated_at_utc
                )
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    stored_at=excluded.stored_at,
                    expires_at=excluded.expires_at,
                    normalized_json=excluded.normalized_json,
                    raw_json=excluded.raw_json,
                    last_accessed_at_utc=excluded.last_accessed_at_utc,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (
                    cache_key,
                    provider.value,
                    operation.value,
                    stored_at,
                    expires_at,
                    json.dumps(normalized, ensure_ascii=False),
                    json.dumps(raw_payload, ensure_ascii=False),
                    stored_at,
                    stored_at,
                ),
            )
            con.commit()

    def _persist_system(self, normalized: dict[str, Any], provider: ProviderId, ttl_s: int) -> None:
        if normalized.get("system_address") is None:
            return
        coords = normalized.get("coords") if isinstance(normalized.get("coords"), dict) else {}
        extras = {
            "body_count": normalized.get("body_count"),
            "station_count": normalized.get("station_count"),
            "provider_updated_at": normalized.get("provider_updated_at"),
            "region": normalized.get("region"),
            "known_permit": normalized.get("known_permit"),
            "needs_permit": normalized.get("needs_permit"),
            "secondary_economy": normalized.get("secondary_economy"),
        }
        fetched_at = str(normalized.get("fetched_at") or _utc_now_iso())
        expires_at = _iso_after(ttl_s)
        with _connect(self.db_path) as con:
            con.execute(
                """
                INSERT INTO ed_systems(
                    system_address,name,coords_x,coords_y,coords_z,
                    allegiance,government,security,economy,population,extras_json,
                    last_refreshed_at,expires_at,primary_source,source_confidence,updated_at_utc
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(system_address) DO UPDATE SET
                    name=excluded.name,
                    coords_x=excluded.coords_x,
                    coords_y=excluded.coords_y,
                    coords_z=excluded.coords_z,
                    allegiance=excluded.allegiance,
                    government=excluded.government,
                    security=excluded.security,
                    economy=excluded.economy,
                    population=excluded.population,
                    extras_json=excluded.extras_json,
                    last_refreshed_at=excluded.last_refreshed_at,
                    expires_at=excluded.expires_at,
                    primary_source=excluded.primary_source,
                    source_confidence=excluded.source_confidence,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (
                    int(normalized["system_address"]),
                    str(normalized.get("name") or ""),
                    coords.get("x"),
                    coords.get("y"),
                    coords.get("z"),
                    normalized.get("allegiance"),
                    normalized.get("government"),
                    normalized.get("security"),
                    normalized.get("primary_economy"),
                    normalized.get("population"),
                    json.dumps(extras, ensure_ascii=False),
                    fetched_at,
                    expires_at,
                    provider.value,
                    100,
                    _utc_now_iso(),
                ),
            )
            con.commit()

    def _ensure_parent_system(self, normalized: dict[str, Any], provider: ProviderId, ttl_s: int) -> None:
        system_address = normalized.get("system_address")
        if system_address is None:
            return
        minimal = {
            "system_address": system_address,
            "name": str(normalized.get("system_name") or normalized.get("name") or ""),
            "coords": {},
            "allegiance": None,
            "government": None,
            "security": None,
            "primary_economy": None,
            "secondary_economy": None,
            "population": None,
            "body_count": normalized.get("body_count"),
            "station_count": normalized.get("station_count"),
            "provider_updated_at": None,
            "region": None,
            "known_permit": None,
            "needs_permit": None,
            "fetched_at": normalized.get("fetched_at") or _utc_now_iso(),
        }
        if minimal["name"]:
            self._persist_system(minimal, provider, ttl_s)

    def _persist_bodies(self, normalized: dict[str, Any], provider: ProviderId, ttl_s: int) -> None:
        system_address = normalized.get("system_address")
        items = normalized.get("items")
        if system_address is None or not isinstance(items, list):
            return
        fetched_at = str(normalized.get("fetched_at") or _utc_now_iso())
        expires_at = _iso_after(ttl_s)
        with _connect(self.db_path) as con:
            for item in items:
                if not isinstance(item, dict):
                    continue
                body_id64 = item.get("body_id64")
                body_id64_value = None
                if body_id64 not in (None, ""):
                    try:
                        body_id64_value = int(body_id64)
                    except Exception:
                        body_id64_value = None
                extras = item.get("extras") if isinstance(item.get("extras"), dict) else {}
                con.execute(
                    """
                    INSERT INTO ed_bodies(
                        body_id64,system_address,name,body_type,subtype,distance_to_arrival_ls,
                        terraform_state,atmosphere,gravity,radius,mass,mapped_fields_json,
                        last_refreshed_at,expires_at,source,updated_at_utc
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(system_address, name) DO UPDATE SET
                        body_id64=excluded.body_id64,
                        body_type=excluded.body_type,
                        subtype=excluded.subtype,
                        distance_to_arrival_ls=excluded.distance_to_arrival_ls,
                        terraform_state=excluded.terraform_state,
                        atmosphere=excluded.atmosphere,
                        gravity=excluded.gravity,
                        radius=excluded.radius,
                        mass=excluded.mass,
                        mapped_fields_json=excluded.mapped_fields_json,
                        last_refreshed_at=excluded.last_refreshed_at,
                        expires_at=excluded.expires_at,
                        source=excluded.source,
                        updated_at_utc=excluded.updated_at_utc
                    """,
                    (
                        body_id64_value,
                        int(system_address),
                        str(item.get("name") or ""),
                        item.get("body_type"),
                        item.get("subtype"),
                        item.get("distance_to_arrival_ls"),
                        item.get("terraform_state"),
                        item.get("atmosphere"),
                        item.get("gravity"),
                        item.get("radius"),
                        item.get("mass"),
                        json.dumps(extras, ensure_ascii=False),
                        fetched_at,
                        expires_at,
                        provider.value,
                        _utc_now_iso(),
                    ),
                )
            con.commit()

    def _persist_stations(self, normalized: dict[str, Any], provider: ProviderId, ttl_s: int) -> None:
        system_address = normalized.get("system_address")
        items = normalized.get("items")
        if system_address is None or not isinstance(items, list):
            return
        fetched_at = str(normalized.get("fetched_at") or _utc_now_iso())
        expires_at = _iso_after(ttl_s)
        with _connect(self.db_path) as con:
            for item in items:
                if not isinstance(item, dict):
                    continue
                market_id = item.get("market_id")
                station_id64 = item.get("station_id64")
                market_id_value = None
                station_id64_value = None
                if market_id not in (None, ""):
                    try:
                        market_id_value = int(market_id)
                    except Exception:
                        market_id_value = None
                if station_id64 not in (None, ""):
                    try:
                        station_id64_value = int(station_id64)
                    except Exception:
                        station_id64_value = None
                services = item.get("services") if isinstance(item.get("services"), list) else []
                con.execute(
                    """
                    INSERT INTO ed_stations(
                        market_id,station_id64,system_address,name,station_type,distance_to_arrival_ls,
                        has_docking,services_json,last_refreshed_at,expires_at,source,updated_at_utc
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(system_address, name) DO UPDATE SET
                        market_id=excluded.market_id,
                        station_id64=excluded.station_id64,
                        station_type=excluded.station_type,
                        distance_to_arrival_ls=excluded.distance_to_arrival_ls,
                        has_docking=excluded.has_docking,
                        services_json=excluded.services_json,
                        last_refreshed_at=excluded.last_refreshed_at,
                        expires_at=excluded.expires_at,
                        source=excluded.source,
                        updated_at_utc=excluded.updated_at_utc
                    """,
                    (
                        market_id_value,
                        station_id64_value,
                        int(system_address),
                        str(item.get("name") or ""),
                        item.get("station_type"),
                        item.get("distance_to_arrival_ls"),
                        1 if bool(item.get("has_docking")) else 0,
                        json.dumps(services, ensure_ascii=False),
                        fetched_at,
                        expires_at,
                        provider.value,
                        _utc_now_iso(),
                    ),
                )
            con.commit()

    def _supports_operation(self, provider_cfg: dict[str, Any], operation: ProviderOperationId) -> bool:
        features = provider_cfg.get("features")
        if not isinstance(features, dict):
            return False
        return bool(features.get(operation.value))

    def _provider_priority_for(self, operation: ProviderOperationId) -> list[ProviderId]:
        raw = self.config.get("provider_priority", {}).get(operation.value, [])
        out: list[ProviderId] = []
        if isinstance(raw, list):
            for item in raw:
                try:
                    out.append(ProviderId(str(item).strip().lower()))
                except Exception:
                    continue
        return out

    def _stale_from_cache(
        self,
        *,
        request: ProviderQuery,
        cache_row: sqlite3.Row,
        age_s: int | None,
        ttl_s: int | None,
        health: ProviderHealth | None,
    ) -> ProviderResult:
        data = json.loads(str(cache_row["normalized_json"]))
        return ProviderResult(
            ok=True,
            provider=request.provider,
            operation=request.operation,
            fetched_at=_utc_now_iso(),
            cache=ProviderCacheMeta(hit=True, age_s=age_s, ttl_s=ttl_s, stale_served=True),
            health_observed=health,
            data=data,
            provenance=ProviderProvenance(endpoint=None, http_code=None),
            error=None,
            deny_reason=None,
        )

    def _execute_single_provider(self, request: ProviderQuery) -> ProviderResult:
        provider_cfg = self.config.get("providers", {}).get(request.provider.value)
        if not isinstance(provider_cfg, dict):
            return ProviderResult(
                ok=False,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(),
                health_observed=None,
                data=None,
                provenance=ProviderProvenance(endpoint=None, http_code=None),
                error=f"provider not configured: {request.provider.value}",
                deny_reason=ProviderDenyReason.MISCONFIGURED,
            )
        if not bool(provider_cfg.get("enabled")):
            return ProviderResult(
                ok=False,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(),
                health_observed=self._get_health(request.provider),
                data=None,
                provenance=ProviderProvenance(endpoint=None, http_code=None),
                error=f"provider disabled: {request.provider.value}",
                deny_reason=ProviderDenyReason.MISCONFIGURED,
            )
        if not self._supports_operation(provider_cfg, request.operation):
            return ProviderResult(
                ok=False,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(),
                health_observed=self._get_health(request.provider),
                data=None,
                provenance=ProviderProvenance(endpoint=None, http_code=None),
                error=f"{request.provider.value} does not support {request.operation.value}",
                deny_reason=ProviderDenyReason.NO_INTENT,
            )
        if request.provider == ProviderId.EDSM and request.operation != ProviderOperationId.SYSTEM_LOOKUP:
            return ProviderResult(
                ok=False,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(),
                health_observed=self._get_health(request.provider),
                data=None,
                provenance=ProviderProvenance(endpoint=None, http_code=None),
                error=f"{request.provider.value} adapter does not implement {request.operation.value}",
                deny_reason=ProviderDenyReason.NO_INTENT,
            )
        if request.provider == ProviderId.INARA and request.operation == ProviderOperationId.COMMANDER_LOCATION_PUSH:
            return self._handle_inara_write(request, provider_cfg)

        cache_cfg = provider_cfg.get("cache", {})
        ttl_s = int(cache_cfg.get("default_ttl_s", 86400))
        stale_window_s = int(cache_cfg.get("stale_if_error_s", 0)) if request.allow_stale_if_error else 0
        cache_key = _cache_key(request)
        cache_row, expired, age_s = self._read_cache(cache_key)
        age_expired = False
        if age_s is not None and request.max_age_s >= 0:
            age_expired = age_s > request.max_age_s
        if cache_row and not expired and not age_expired:
            health = self._get_health(request.provider)
            data = json.loads(str(cache_row["normalized_json"]))
            return ProviderResult(
                ok=True,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(hit=True, age_s=age_s, ttl_s=ttl_s, stale_served=False),
                health_observed=health,
                data=data,
                provenance=ProviderProvenance(endpoint=None, http_code=None),
                error=None,
                deny_reason=None,
            )

        health = self._get_health(request.provider)
        if health and health.status in {
            ProviderHealthStatus.DOWN,
            ProviderHealthStatus.MISCONFIGURED,
            ProviderHealthStatus.THROTTLED,
        }:
            if cache_row and stale_window_s > 0 and (age_s is None or age_s <= stale_window_s):
                return self._stale_from_cache(
                    request=request,
                    cache_row=cache_row,
                    age_s=age_s,
                    ttl_s=ttl_s,
                    health=health,
                )
            deny_reason = ProviderDenyReason.PROVIDER_DOWN
            if health.status == ProviderHealthStatus.MISCONFIGURED:
                deny_reason = ProviderDenyReason.MISCONFIGURED
            elif health.status == ProviderHealthStatus.THROTTLED:
                deny_reason = ProviderDenyReason.RATE_LIMITED
            return ProviderResult(
                ok=False,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(hit=bool(cache_row), age_s=age_s, ttl_s=ttl_s, stale_served=False),
                health_observed=health,
                data=None,
                provenance=ProviderProvenance(endpoint=None, http_code=None),
                error=health.message or f"{request.provider.value} unavailable",
                deny_reason=deny_reason,
            )

        started = time.time()
        try:
            if request.provider == ProviderId.SPANSH:
                if self._spansh is None:
                    raise ValueError("spansh adapter is not configured")
                normalized, meta = self._spansh.lookup(request)
            elif request.provider == ProviderId.EDSM:
                if self._edsm is None:
                    raise ValueError("edsm adapter is not configured")
                normalized, meta = self._edsm.lookup(request)
            else:
                raise ValueError(f"{request.provider.value} adapter is not implemented")
            latency_ms = int((time.time() - started) * 1000)
            observed = ProviderHealth(
                provider=request.provider,
                status=ProviderHealthStatus.OK,
                checked_at=_utc_now_iso(),
                latency_ms=latency_ms,
                http_code=int(meta.get("http_code") or 200),
                rate_limit_state=ProviderRateLimitState.OK,
                retry_after_s=None,
                tool_calls_allowed=True,
                degraded_readonly=True,
                message="healthy",
            )
            upsert_provider_health(self.db_path, observed)
            if request.operation == ProviderOperationId.SYSTEM_LOOKUP:
                self._persist_system(normalized, request.provider, ttl_s)
            elif request.operation == ProviderOperationId.BODIES_LOOKUP:
                self._ensure_parent_system(normalized, request.provider, ttl_s)
                self._persist_bodies(normalized, request.provider, ttl_s)
            elif request.operation == ProviderOperationId.STATIONS_LOOKUP:
                self._ensure_parent_system(normalized, request.provider, ttl_s)
                self._persist_stations(normalized, request.provider, ttl_s)
            self._write_cache(
                cache_key=cache_key,
                provider=request.provider,
                operation=request.operation,
                expires_at=_iso_after(ttl_s),
                normalized=normalized,
                raw_payload=meta.get("raw"),
            )
            return ProviderResult(
                ok=True,
                provider=request.provider,
                operation=request.operation,
                fetched_at=str(meta.get("fetched_at") or _utc_now_iso()),
                cache=ProviderCacheMeta(hit=False, age_s=0, ttl_s=ttl_s, stale_served=False),
                health_observed=observed,
                data=normalized,
                provenance=ProviderProvenance(
                    endpoint=str(meta.get("endpoint") or ""),
                    http_code=int(meta.get("http_code") or 200),
                ),
                error=None,
                deny_reason=None,
            )
        except LookupError as exc:
            return ProviderResult(
                ok=False,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(hit=bool(cache_row), age_s=age_s, ttl_s=ttl_s, stale_served=False),
                health_observed=health,
                data=None,
                provenance=ProviderProvenance(endpoint=None, http_code=None),
                error=str(exc),
                deny_reason=None,
            )
        except urllib.error.HTTPError as exc:
            status = ProviderHealthStatus.THROTTLED if int(exc.code) == 429 else ProviderHealthStatus.DOWN
            observed = ProviderHealth(
                provider=request.provider,
                status=status,
                checked_at=_utc_now_iso(),
                latency_ms=int((time.time() - started) * 1000),
                http_code=int(exc.code),
                rate_limit_state=(
                    ProviderRateLimitState.THROTTLED if int(exc.code) == 429 else ProviderRateLimitState.UNKNOWN
                ),
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=True,
                message=f"http_{int(exc.code)}",
            )
            upsert_provider_health(self.db_path, observed)
            if cache_row and stale_window_s > 0 and (age_s is None or age_s <= stale_window_s):
                return self._stale_from_cache(
                    request=request,
                    cache_row=cache_row,
                    age_s=age_s,
                    ttl_s=ttl_s,
                    health=observed,
                )
            return ProviderResult(
                ok=False,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(hit=bool(cache_row), age_s=age_s, ttl_s=ttl_s, stale_served=False),
                health_observed=observed,
                data=None,
                provenance=ProviderProvenance(endpoint=None, http_code=int(exc.code)),
                error=f"provider HTTP {int(exc.code)}",
                deny_reason=(
                    ProviderDenyReason.RATE_LIMITED if int(exc.code) == 429 else ProviderDenyReason.PROVIDER_DOWN
                ),
            )
        except Exception as exc:
            observed = ProviderHealth(
                provider=request.provider,
                status=ProviderHealthStatus.DOWN,
                checked_at=_utc_now_iso(),
                latency_ms=None,
                http_code=None,
                rate_limit_state=ProviderRateLimitState.UNKNOWN,
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=True,
                message=str(exc),
            )
            upsert_provider_health(self.db_path, observed)
            if cache_row and stale_window_s > 0 and (age_s is None or age_s <= stale_window_s):
                return self._stale_from_cache(
                    request=request,
                    cache_row=cache_row,
                    age_s=age_s,
                    ttl_s=ttl_s,
                    health=observed,
                )
            return ProviderResult(
                ok=False,
                provider=request.provider,
                operation=request.operation,
                fetched_at=_utc_now_iso(),
                cache=ProviderCacheMeta(hit=bool(cache_row), age_s=age_s, ttl_s=ttl_s, stale_served=False),
                health_observed=observed,
                data=None,
                provenance=ProviderProvenance(endpoint=None, http_code=None),
                error=str(exc),
                deny_reason=ProviderDenyReason.PROVIDER_DOWN,
            )

    def execute(self, request: ProviderQuery) -> ProviderResult:
        return self._execute_single_provider(request)

    def execute_priority(
        self,
        *,
        operation: ProviderOperationId,
        params: dict[str, Any],
        max_age_s: int,
        allow_stale_if_error: bool,
        incident_id: str | None = None,
        reason: str = "",
    ) -> ProviderResult:
        last_result: ProviderResult | None = None
        for provider_id in self._provider_priority_for(operation):
            request = ProviderQuery(
                provider=provider_id,
                operation=operation,
                params=dict(params),
                max_age_s=max_age_s,
                allow_stale_if_error=allow_stale_if_error,
                incident_id=incident_id,
                reason=reason,
            )
            result = self._execute_single_provider(request)
            if result.ok:
                return result
            last_result = result
        if last_result is not None:
            return last_result
        return ProviderResult(
            ok=False,
            provider=ProviderId.SPANSH,
            operation=operation,
            fetched_at=_utc_now_iso(),
            cache=ProviderCacheMeta(),
            health_observed=None,
            data=None,
            provenance=ProviderProvenance(endpoint=None, http_code=None),
            error=f"no provider priority configured for {operation.value}",
            deny_reason=ProviderDenyReason.MISCONFIGURED,
        )
