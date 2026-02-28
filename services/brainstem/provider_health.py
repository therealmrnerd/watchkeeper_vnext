from __future__ import annotations

import random
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.ed_provider_types import (
    ProviderHealth,
    ProviderHealthStatus,
    ProviderId,
    ProviderRateLimitState,
)
from provider_config import load_provider_config


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def _as_provider_id(raw: str) -> ProviderId:
    return ProviderId(str(raw or "").strip().lower())


def upsert_provider_health(db_path: Path, health: ProviderHealth) -> dict[str, Any]:
    with _connect(db_path) as con:
        con.execute(
            """
            INSERT INTO provider_health(
                provider,status,checked_at,latency_ms,http_code,rate_limit_state,retry_after_s,
                tool_calls_allowed,degraded_readonly,message,updated_at_utc
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(provider) DO UPDATE SET
                status=excluded.status,
                checked_at=excluded.checked_at,
                latency_ms=excluded.latency_ms,
                http_code=excluded.http_code,
                rate_limit_state=excluded.rate_limit_state,
                retry_after_s=excluded.retry_after_s,
                tool_calls_allowed=excluded.tool_calls_allowed,
                degraded_readonly=excluded.degraded_readonly,
                message=excluded.message,
                updated_at_utc=excluded.updated_at_utc
            """,
            (
                health.provider.value,
                health.status.value,
                health.checked_at,
                health.latency_ms,
                health.http_code,
                health.rate_limit_state.value,
                health.retry_after_s,
                1 if health.tool_calls_allowed else 0,
                1 if health.degraded_readonly else 0,
                health.message,
                _utc_now_iso(),
            ),
        )
        con.commit()
    return health.to_dict()


def list_provider_health(db_path: Path) -> dict[str, dict[str, Any]]:
    with _connect(db_path) as con:
        rows = con.execute(
            """
            SELECT provider,status,checked_at,latency_ms,http_code,rate_limit_state,retry_after_s,
                   tool_calls_allowed,degraded_readonly,message
            FROM provider_health
            ORDER BY provider ASC
            """
        ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = ProviderHealth(
            provider=_as_provider_id(row["provider"]),
            status=ProviderHealthStatus(str(row["status"])),
            checked_at=str(row["checked_at"]),
            latency_ms=row["latency_ms"],
            http_code=row["http_code"],
            rate_limit_state=ProviderRateLimitState(str(row["rate_limit_state"])),
            retry_after_s=row["retry_after_s"],
            tool_calls_allowed=bool(row["tool_calls_allowed"]),
            degraded_readonly=bool(row["degraded_readonly"]),
            message=str(row["message"] or ""),
        )
        out[item.provider.value] = item.to_dict()
    return out


@dataclass
class HttpProviderHealthProbe:
    provider_id: ProviderId
    base_url: str
    timeout_sec: float
    read_only: bool = True
    opener: Callable[..., Any] = urllib.request.urlopen

    def probe(self) -> ProviderHealth:
        checked_at = _utc_now_iso()
        url = str(self.base_url or "").strip()
        if not url:
            return ProviderHealth(
                provider=self.provider_id,
                status=ProviderHealthStatus.MISCONFIGURED,
                checked_at=checked_at,
                latency_ms=None,
                http_code=None,
                rate_limit_state=ProviderRateLimitState.UNKNOWN,
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=self.read_only,
                message="base_url missing",
            )

        req = urllib.request.Request(url, method="GET")
        started = time.time()
        try:
            with self.opener(req, timeout=self.timeout_sec) as resp:
                code = int(getattr(resp, "status", 200))
                resp.read(1)
            latency_ms = int((time.time() - started) * 1000)
            status = ProviderHealthStatus.OK if code < 400 else ProviderHealthStatus.DEGRADED
            return ProviderHealth(
                provider=self.provider_id,
                status=status,
                checked_at=checked_at,
                latency_ms=latency_ms,
                http_code=code,
                rate_limit_state=ProviderRateLimitState.OK,
                retry_after_s=None,
                tool_calls_allowed=status in {ProviderHealthStatus.OK, ProviderHealthStatus.DEGRADED},
                degraded_readonly=self.read_only,
                message="healthy" if status == ProviderHealthStatus.OK else f"http_{code}",
            )
        except urllib.error.HTTPError as exc:
            code = int(exc.code)
            latency_ms = int((time.time() - started) * 1000)
            if code == 429:
                status = ProviderHealthStatus.THROTTLED
                rate_state = ProviderRateLimitState.THROTTLED
            elif 400 <= code < 500:
                status = ProviderHealthStatus.DEGRADED
                rate_state = ProviderRateLimitState.OK
            else:
                status = ProviderHealthStatus.DOWN
                rate_state = ProviderRateLimitState.UNKNOWN
            retry_after_raw = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
            try:
                retry_after_s = int(str(retry_after_raw or "").strip()) if retry_after_raw is not None else None
            except Exception:
                retry_after_s = None
            return ProviderHealth(
                provider=self.provider_id,
                status=status,
                checked_at=checked_at,
                latency_ms=latency_ms,
                http_code=code,
                rate_limit_state=rate_state,
                retry_after_s=retry_after_s,
                tool_calls_allowed=status in {ProviderHealthStatus.OK, ProviderHealthStatus.DEGRADED},
                degraded_readonly=self.read_only,
                message=f"http_{code}",
            )
        except Exception as exc:
            return ProviderHealth(
                provider=self.provider_id,
                status=ProviderHealthStatus.DOWN,
                checked_at=checked_at,
                latency_ms=None,
                http_code=None,
                rate_limit_state=ProviderRateLimitState.UNKNOWN,
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=self.read_only,
                message=str(exc),
            )


@dataclass
class InaraHealthProbe:
    provider_id: ProviderId
    base_url: str
    timeout_sec: float
    app_name: str
    app_key: str
    commander_name: str
    opener: Callable[..., Any] = urllib.request.urlopen

    def probe(self) -> ProviderHealth:
        checked_at = _utc_now_iso()
        if not str(self.base_url or "").strip():
            return ProviderHealth(
                provider=self.provider_id,
                status=ProviderHealthStatus.MISCONFIGURED,
                checked_at=checked_at,
                latency_ms=None,
                http_code=None,
                rate_limit_state=ProviderRateLimitState.UNKNOWN,
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=False,
                message="base_url missing",
            )
        if not str(self.app_name or "").strip():
            return ProviderHealth(
                provider=self.provider_id,
                status=ProviderHealthStatus.MISCONFIGURED,
                checked_at=checked_at,
                latency_ms=None,
                http_code=None,
                rate_limit_state=ProviderRateLimitState.UNKNOWN,
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=False,
                message="auth.app_name missing",
            )
        if not str(self.app_key or "").strip():
            return ProviderHealth(
                provider=self.provider_id,
                status=ProviderHealthStatus.MISCONFIGURED,
                checked_at=checked_at,
                latency_ms=None,
                http_code=None,
                rate_limit_state=ProviderRateLimitState.UNKNOWN,
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=False,
                message="auth.app_key missing",
            )
        if not str(self.commander_name or "").strip():
            return ProviderHealth(
                provider=self.provider_id,
                status=ProviderHealthStatus.MISCONFIGURED,
                checked_at=checked_at,
                latency_ms=None,
                http_code=None,
                rate_limit_state=ProviderRateLimitState.UNKNOWN,
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=False,
                message="auth.commander_name missing",
            )
        req = urllib.request.Request(str(self.base_url).strip(), method="GET")
        started = time.time()
        try:
            with self.opener(req, timeout=self.timeout_sec) as resp:
                code = int(getattr(resp, "status", 200))
                resp.read(1)
            latency_ms = int((time.time() - started) * 1000)
            status = ProviderHealthStatus.OK if code < 400 else ProviderHealthStatus.DEGRADED
            return ProviderHealth(
                provider=self.provider_id,
                status=status,
                checked_at=checked_at,
                latency_ms=latency_ms,
                http_code=code,
                rate_limit_state=ProviderRateLimitState.OK,
                retry_after_s=None,
                tool_calls_allowed=status in {ProviderHealthStatus.OK, ProviderHealthStatus.DEGRADED},
                degraded_readonly=False,
                message="healthy" if status == ProviderHealthStatus.OK else f"http_{code}",
            )
        except urllib.error.HTTPError as exc:
            code = int(exc.code)
            latency_ms = int((time.time() - started) * 1000)
            return ProviderHealth(
                provider=self.provider_id,
                status=ProviderHealthStatus.THROTTLED if code == 429 else ProviderHealthStatus.DOWN,
                checked_at=checked_at,
                latency_ms=latency_ms,
                http_code=code,
                rate_limit_state=(
                    ProviderRateLimitState.THROTTLED if code == 429 else ProviderRateLimitState.UNKNOWN
                ),
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=False,
                message=f"http_{code}",
            )
        except Exception as exc:
            return ProviderHealth(
                provider=self.provider_id,
                status=ProviderHealthStatus.DOWN,
                checked_at=checked_at,
                latency_ms=None,
                http_code=None,
                rate_limit_state=ProviderRateLimitState.UNKNOWN,
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=False,
                message=str(exc),
            )


def build_provider_health_probes(config_path: str | Path | None = None) -> list[Any]:
    config = load_provider_config(config_path)
    providers = config.get("providers", {})
    probes: list[HttpProviderHealthProbe] = []
    for provider_name in ("spansh", "edsm"):
        provider_cfg = providers.get(provider_name)
        if not isinstance(provider_cfg, dict):
            continue
        if not bool(provider_cfg.get("enabled")):
            continue
        timeout_ms = provider_cfg.get("timeouts_ms", {}).get("read", 4000)
        try:
            timeout_sec = max(0.1, float(timeout_ms) / 1000.0)
        except Exception:
            timeout_sec = 4.0
        features = provider_cfg.get("features", {})
        read_only = bool(features.get("read_only", True))
        probes.append(
            HttpProviderHealthProbe(
                provider_id=ProviderId(provider_name),
                base_url=str(provider_cfg.get("base_url") or "").strip(),
                timeout_sec=timeout_sec,
                read_only=read_only,
            )
        )
    inara_cfg = providers.get("inara")
    if isinstance(inara_cfg, dict) and bool(inara_cfg.get("enabled")):
        timeout_ms = inara_cfg.get("timeouts_ms", {}).get("read", 5000)
        try:
            timeout_sec = max(0.1, float(timeout_ms) / 1000.0)
        except Exception:
            timeout_sec = 5.0
        auth = inara_cfg.get("auth", {}) if isinstance(inara_cfg.get("auth"), dict) else {}
        probes.append(
            InaraHealthProbe(
                provider_id=ProviderId.INARA,
                base_url=str(inara_cfg.get("base_url") or "").strip(),
                timeout_sec=timeout_sec,
                app_name=str(auth.get("app_name") or "").strip(),
                app_key=str(auth.get("app_key") or "").strip(),
                commander_name=str(auth.get("commander_name") or "").strip(),
            )
        )
    return probes


class ProviderHealthScheduler:
    def __init__(
        self,
        *,
        db_path: Path,
        probes: list[HttpProviderHealthProbe],
        min_interval_sec: int = 1800,
        max_interval_sec: int = 3600,
        startup_probe: bool = True,
        rng: random.Random | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.probes = list(probes)
        self.min_interval_sec = max(1, int(min_interval_sec))
        self.max_interval_sec = max(self.min_interval_sec, int(max_interval_sec))
        self.startup_probe = bool(startup_probe)
        self._rng = rng or random.Random()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for probe in self.probes:
            health = probe.probe()
            results[health.provider.value] = upsert_provider_health(self.db_path, health)
        return results

    def _sleep_interval(self) -> float:
        if self.min_interval_sec >= self.max_interval_sec:
            return float(self.min_interval_sec)
        return float(self._rng.randint(self.min_interval_sec, self.max_interval_sec))

    def _run(self) -> None:
        if self.startup_probe:
            try:
                self.run_once()
            except Exception:
                pass
        while not self._stop.is_set():
            wait_sec = self._sleep_interval()
            if self._stop.wait(wait_sec):
                break
            try:
                self.run_once()
            except Exception:
                continue

    def start(self) -> None:
        if not self.probes:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="provider-health-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
