from __future__ import annotations

import hashlib
import json
import sqlite3
import time
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
from provider_config import load_provider_config
from provider_health import HttpProviderHealthProbe, list_provider_health, upsert_provider_health


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


def query_provider_health(db_path: Path, config_path: str | Path | None = None) -> dict[str, Any]:
    config = load_provider_config(config_path)
    stored = get_provider_health_map(db_path)
    providers_cfg = config.get("providers", {})
    out: dict[str, Any] = {}
    for provider_id, cfg in providers_cfg.items():
        if not isinstance(cfg, dict):
            continue
        out[provider_id] = {
            "enabled": bool(cfg.get("enabled")),
            "base_url": str(cfg.get("base_url") or "").strip() or None,
            "features": cfg.get("features") if isinstance(cfg.get("features"), dict) else {},
            "health": stored.get(provider_id),
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


class ProviderQueryService:
    def __init__(
        self,
        *,
        db_path: Path,
        config_path: str | Path | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.db_path = Path(db_path)
        self.config_path = config_path
        self.config = load_provider_config(config_path)
        self.opener = opener
        self._spansh = self._build_spansh_adapter()
        self._edsm = self._build_edsm_adapter()
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

    def _build_probes(self) -> dict[str, HttpProviderHealthProbe]:
        probes: dict[str, HttpProviderHealthProbe] = {}
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
        return probes

    def _get_health(self, provider: ProviderId) -> ProviderHealth | None:
        raw = get_provider_health_map(self.db_path).get(provider.value)
        parsed = _as_provider_health(raw)
        if parsed is not None:
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
