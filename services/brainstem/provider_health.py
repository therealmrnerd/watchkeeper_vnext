from __future__ import annotations

import os
import random
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import json
import re
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
from provider_config import load_runtime_provider_config
from settings_store import apply_runtime_settings_overrides, load_runtime_settings


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def _as_provider_id(raw: str) -> ProviderId:
    return ProviderId(str(raw or "").strip().lower())


def _ed_checks_enabled(db_path: Path | None) -> bool:
    if db_path is None:
        return True
    try:
        with _connect(Path(db_path)) as con:
            rows = con.execute(
                """
                SELECT state_value_json
                FROM state_current
                WHERE state_key IN ('ed.running','ed.status.running','ed.process.running','app.ed.running')
                """
            ).fetchall()
    except Exception:
        return True
    for row in rows:
        if str(row["state_value_json"] or "").strip().lower() in {"true", "1"}:
            return True
    return False


FRONTIER_HEALTH_ENABLED = os.getenv("WKV_FRONTIER_HEALTH_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}
FRONTIER_HEALTH_URL = os.getenv("WKV_FRONTIER_HEALTH_URL", "https://auth.frontierstore.net/").strip()
FRONTIER_EXTERNAL_STATUS_URL = os.getenv("WKV_FRONTIER_EXTERNAL_STATUS_URL", "https://ed-server-status.orerve.net/").strip()
FRONTIER_HEALTH_SAMPLES = max(2, int(os.getenv("WKV_FRONTIER_HEALTH_SAMPLES", "4")))
FRONTIER_HEALTH_SAMPLE_PAUSE_SEC = max(0.0, float(os.getenv("WKV_FRONTIER_HEALTH_SAMPLE_PAUSE_SEC", "0.12")))


def _host_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    return str(parsed.hostname or "").strip()


def _parse_ping_output(output: str) -> int | None:
    text = str(output or "")
    match = re.search(r"Average = (\d+)ms", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"time[=<]\s*(\d+)ms", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"min/avg/max(?:/[a-z]+)? = [\d.]+/([\d.]+)/[\d.]+", text, re.IGNORECASE)
    if match:
        return int(round(float(match.group(1))))
    return None


def icmp_ping_host(host: str, timeout_sec: float) -> tuple[int | None, str | None]:
    target = str(host or "").strip()
    if not target:
        return None, "host_missing"
    try:
        timeout_ms = max(250, int(float(timeout_sec) * 1000))
    except Exception:
        timeout_ms = 1000
    if os.name == "nt":
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), target]
    else:
        timeout_s = max(1, int(round(timeout_ms / 1000.0)))
        cmd = ["ping", "-c", "1", "-W", str(timeout_s), target]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(2.0, float(timeout_sec) + 1.0),
            check=False,
        )
    except FileNotFoundError:
        return None, "ping_unavailable"
    except subprocess.TimeoutExpired:
        return None, "ping_timeout"
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    ping_ms = _parse_ping_output(output)
    if completed.returncode == 0 and ping_ms is not None:
        return ping_ms, None
    if completed.returncode == 0:
        return None, "ping_parse_failed"
    return None, "ping_failed"


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
    ping_probe: Callable[[str, float], tuple[int | None, str | None]] = icmp_ping_host

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

        host = _host_from_url(url)
        ping_ms, ping_error = self.ping_probe(host, self.timeout_sec)
        req = urllib.request.Request(url, method="GET")
        started = time.time()
        try:
            with self.opener(req, timeout=self.timeout_sec) as resp:
                code = int(getattr(resp, "status", 200))
                resp.read(1)
            request_latency_ms = int((time.time() - started) * 1000)
            if ping_ms is None:
                status = ProviderHealthStatus.DOWN
            else:
                status = ProviderHealthStatus.OK if code < 400 else ProviderHealthStatus.DEGRADED
            return ProviderHealth(
                provider=self.provider_id,
                status=status,
                checked_at=checked_at,
                latency_ms=request_latency_ms,
                http_code=code,
                rate_limit_state=ProviderRateLimitState.OK,
                retry_after_s=None,
                tool_calls_allowed=status in {ProviderHealthStatus.OK, ProviderHealthStatus.DEGRADED},
                degraded_readonly=self.read_only,
                message=json.dumps(
                    {
                        "kind": "provider_probe",
                        "host": host,
                        "ping_ms": ping_ms,
                        "ping_ok": ping_ms is not None,
                        "ping_error": ping_error,
                        "request_latency_ms": request_latency_ms,
                        "http_code": code,
                        "request_ok": code < 400,
                        "status_text": "healthy" if status == ProviderHealthStatus.OK else f"http_{code}",
                    },
                    separators=(",", ":"),
                ),
            )
        except urllib.error.HTTPError as exc:
            code = int(exc.code)
            request_latency_ms = int((time.time() - started) * 1000)
            if ping_ms is None:
                status = ProviderHealthStatus.DOWN
                rate_state = ProviderRateLimitState.UNKNOWN
            elif code == 429:
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
                latency_ms=request_latency_ms,
                http_code=code,
                rate_limit_state=rate_state,
                retry_after_s=retry_after_s,
                tool_calls_allowed=status in {ProviderHealthStatus.OK, ProviderHealthStatus.DEGRADED},
                degraded_readonly=self.read_only,
                message=json.dumps(
                    {
                        "kind": "provider_probe",
                        "host": host,
                        "ping_ms": ping_ms,
                        "ping_ok": ping_ms is not None,
                        "ping_error": ping_error,
                        "request_latency_ms": request_latency_ms,
                        "http_code": code,
                        "request_ok": False,
                        "request_error": f"http_{code}",
                        "status_text": f"http_{code}",
                    },
                    separators=(",", ":"),
                ),
            )
        except Exception as exc:
            request_error = str(exc)
            return ProviderHealth(
                provider=self.provider_id,
                status=ProviderHealthStatus.DOWN if ping_ms is None else ProviderHealthStatus.DEGRADED,
                checked_at=checked_at,
                latency_ms=None,
                http_code=None,
                rate_limit_state=ProviderRateLimitState.UNKNOWN,
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=self.read_only,
                message=json.dumps(
                    {
                        "kind": "provider_probe",
                        "host": host,
                        "ping_ms": ping_ms,
                        "ping_ok": ping_ms is not None,
                        "ping_error": ping_error,
                        "request_latency_ms": None,
                        "http_code": None,
                        "request_ok": False,
                        "request_error": request_error,
                        "status_text": request_error,
                    },
                    separators=(",", ":"),
                ),
            )


def _frontier_jitter_ms(samples: list[int]) -> int:
    if len(samples) < 2:
        return 0
    deltas = [abs(samples[idx] - samples[idx - 1]) for idx in range(1, len(samples))]
    return int(round(sum(deltas) / len(deltas)))


def _frontier_grade(
    *,
    status: ProviderHealthStatus,
    latency_ms: int | None,
    jitter_ms: int | None,
    loss_pct: float,
    http_code: int | None,
) -> str:
    if status in {ProviderHealthStatus.DOWN, ProviderHealthStatus.MISCONFIGURED}:
        return "F"
    if status == ProviderHealthStatus.THROTTLED:
        return "D"
    if http_code is not None and http_code >= 500:
        return "D"
    if loss_pct >= 50.0:
        return "F"
    if loss_pct >= 25.0:
        return "D"
    if latency_ms is None:
        return "F"
    jitter_value = jitter_ms or 0
    if latency_ms <= 90 and jitter_value <= 10 and loss_pct <= 0:
        return "A+"
    if latency_ms <= 120 and jitter_value <= 15 and loss_pct <= 0:
        return "A"
    if latency_ms <= 160 and jitter_value <= 25 and loss_pct <= 2:
        return "B"
    if latency_ms <= 220 and jitter_value <= 40 and loss_pct <= 5:
        return "C"
    if latency_ms <= 320 and jitter_value <= 80 and loss_pct <= 15:
        return "D"
    return "F"


@dataclass
class FrontierHealthProbe:
    provider_id: ProviderId
    base_url: str
    timeout_sec: float
    sample_count: int = FRONTIER_HEALTH_SAMPLES
    sample_pause_sec: float = FRONTIER_HEALTH_SAMPLE_PAUSE_SEC
    opener: Callable[..., Any] = urllib.request.urlopen
    external_status_url: str | None = FRONTIER_EXTERNAL_STATUS_URL

    def _fetch_external_status(self) -> dict[str, Any] | None:
        url = str(self.external_status_url or "").strip()
        if not url:
            return None
        req = urllib.request.Request(url, method="GET")
        try:
            with self.opener(req, timeout=self.timeout_sec) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                code = int(getattr(resp, "status", 200))
            payload = json.loads(body) if body else {}
            if isinstance(payload, dict):
                payload["_source"] = "orerve"
                payload["_verified"] = False
                payload["_http_code"] = code
                return payload
        except Exception as exc:
            return {
                "_source": "orerve",
                "_verified": False,
                "_http_code": None,
                "_error": str(exc),
            }
        return None

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
                degraded_readonly=True,
                message="base_url missing",
            )

        latencies: list[int] = []
        observed_codes: list[int] = []
        last_error: str | None = None
        throttled = False
        external_status = self._fetch_external_status()

        for index in range(max(2, int(self.sample_count))):
            req = urllib.request.Request(url, method="GET")
            started = time.perf_counter()
            try:
                with self.opener(req, timeout=self.timeout_sec) as resp:
                    code = int(getattr(resp, "status", 200))
                    resp.read(1)
                observed_codes.append(code)
                latencies.append(int((time.perf_counter() - started) * 1000))
            except urllib.error.HTTPError as exc:
                code = int(exc.code)
                observed_codes.append(code)
                throttled = throttled or code == 429
                last_error = f"http_{code}"
            except Exception as exc:
                last_error = str(exc)
            if index + 1 < max(2, int(self.sample_count)) and self.sample_pause_sec > 0:
                time.sleep(self.sample_pause_sec)

        total_samples = max(2, int(self.sample_count))
        success_count = len(latencies)
        loss_pct = round(((total_samples - success_count) / total_samples) * 100.0, 1)
        http_code = observed_codes[-1] if observed_codes else None

        if success_count <= 0:
            status = ProviderHealthStatus.THROTTLED if throttled else ProviderHealthStatus.DOWN
            return ProviderHealth(
                provider=self.provider_id,
                status=status,
                checked_at=checked_at,
                latency_ms=None,
                http_code=http_code,
                rate_limit_state=(
                    ProviderRateLimitState.THROTTLED if throttled else ProviderRateLimitState.UNKNOWN
                ),
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=True,
                message=json.dumps(
                    {
                        "kind": "frontier_connection",
                        "grade": _frontier_grade(
                            status=status,
                            latency_ms=None,
                            jitter_ms=None,
                            loss_pct=loss_pct,
                            http_code=http_code,
                        ),
                        "samples": total_samples,
                        "successful_samples": success_count,
                        "packet_loss_pct": loss_pct,
                        "error": last_error or "probe_failed",
                        "http_code": http_code,
                        "external_status": external_status,
                    },
                    separators=(",", ":"),
                ),
            )

        ping_ms = min(latencies)
        latency_ms = int(round(sum(latencies) / len(latencies)))
        jitter_ms = _frontier_jitter_ms(latencies)
        status = ProviderHealthStatus.OK
        if throttled:
            status = ProviderHealthStatus.THROTTLED
        elif loss_pct > 0 or latency_ms > 180 or jitter_ms > 30 or (http_code is not None and http_code >= 400):
            status = ProviderHealthStatus.DEGRADED

        details = {
            "kind": "frontier_connection",
            "grade": _frontier_grade(
                status=status,
                latency_ms=latency_ms,
                jitter_ms=jitter_ms,
                loss_pct=loss_pct,
                http_code=http_code,
            ),
            "samples": total_samples,
            "successful_samples": success_count,
            "packet_loss_pct": loss_pct,
            "ping_ms": ping_ms,
            "latency_ms": latency_ms,
            "jitter_ms": jitter_ms,
            "http_code": http_code,
            "status_text": "healthy" if status == ProviderHealthStatus.OK else (last_error or f"http_{http_code}"),
            "external_status": external_status,
        }
        return ProviderHealth(
            provider=self.provider_id,
            status=status,
            checked_at=checked_at,
            latency_ms=latency_ms,
            http_code=http_code,
            rate_limit_state=ProviderRateLimitState.THROTTLED if throttled else ProviderRateLimitState.OK,
            retry_after_s=None,
            tool_calls_allowed=status in {ProviderHealthStatus.OK, ProviderHealthStatus.DEGRADED},
            degraded_readonly=True,
            message=json.dumps(details, separators=(",", ":")),
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
    ping_probe: Callable[[str, float], tuple[int | None, str | None]] = icmp_ping_host

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
        host = _host_from_url(str(self.base_url).strip())
        ping_ms, ping_error = self.ping_probe(host, self.timeout_sec)
        req = urllib.request.Request(str(self.base_url).strip(), method="GET")
        started = time.time()
        try:
            with self.opener(req, timeout=self.timeout_sec) as resp:
                code = int(getattr(resp, "status", 200))
                resp.read(1)
            request_latency_ms = int((time.time() - started) * 1000)
            status = ProviderHealthStatus.OK if code < 400 and ping_ms is not None else ProviderHealthStatus.DEGRADED
            return ProviderHealth(
                provider=self.provider_id,
                status=status,
                checked_at=checked_at,
                latency_ms=request_latency_ms,
                http_code=code,
                rate_limit_state=ProviderRateLimitState.OK,
                retry_after_s=None,
                tool_calls_allowed=status in {ProviderHealthStatus.OK, ProviderHealthStatus.DEGRADED},
                degraded_readonly=False,
                message=json.dumps(
                    {
                        "kind": "provider_probe",
                        "host": host,
                        "ping_ms": ping_ms,
                        "ping_ok": ping_ms is not None,
                        "ping_error": ping_error,
                        "request_latency_ms": request_latency_ms,
                        "http_code": code,
                        "request_ok": code < 400,
                        "status_text": "healthy" if status == ProviderHealthStatus.OK else f"http_{code}",
                    },
                    separators=(",", ":"),
                ),
            )
        except urllib.error.HTTPError as exc:
            code = int(exc.code)
            request_latency_ms = int((time.time() - started) * 1000)
            return ProviderHealth(
                provider=self.provider_id,
                status=ProviderHealthStatus.THROTTLED if code == 429 else (ProviderHealthStatus.DOWN if ping_ms is None else ProviderHealthStatus.DEGRADED),
                checked_at=checked_at,
                latency_ms=request_latency_ms,
                http_code=code,
                rate_limit_state=(
                    ProviderRateLimitState.THROTTLED if code == 429 else ProviderRateLimitState.UNKNOWN
                ),
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=False,
                message=json.dumps(
                    {
                        "kind": "provider_probe",
                        "host": host,
                        "ping_ms": ping_ms,
                        "ping_ok": ping_ms is not None,
                        "ping_error": ping_error,
                        "request_latency_ms": request_latency_ms,
                        "http_code": code,
                        "request_ok": False,
                        "request_error": f"http_{code}",
                        "status_text": f"http_{code}",
                    },
                    separators=(",", ":"),
                ),
            )
        except Exception as exc:
            return ProviderHealth(
                provider=self.provider_id,
                status=ProviderHealthStatus.DOWN if ping_ms is None else ProviderHealthStatus.DEGRADED,
                checked_at=checked_at,
                latency_ms=None,
                http_code=None,
                rate_limit_state=ProviderRateLimitState.UNKNOWN,
                retry_after_s=None,
                tool_calls_allowed=False,
                degraded_readonly=False,
                message=json.dumps(
                    {
                        "kind": "provider_probe",
                        "host": host,
                        "ping_ms": ping_ms,
                        "ping_ok": ping_ms is not None,
                        "ping_error": ping_error,
                        "request_latency_ms": None,
                        "http_code": None,
                        "request_ok": False,
                        "request_error": str(exc),
                        "status_text": str(exc),
                    },
                    separators=(",", ":"),
                ),
            )


def build_provider_health_probes(
    config_path: str | Path | None = None,
    secrets_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> list[Any]:
    config = load_runtime_provider_config(config_path, secrets_path)
    if db_path is not None:
        config = apply_runtime_settings_overrides(config, load_runtime_settings(Path(db_path)))
    if not _ed_checks_enabled(Path(db_path) if db_path is not None else None):
        return []
    providers = config.get("providers", {})
    probes: list[Any] = []
    if FRONTIER_HEALTH_ENABLED and str(FRONTIER_HEALTH_URL or "").strip():
        probes.append(
            FrontierHealthProbe(
                provider_id=ProviderId.FRONTIER,
                base_url=str(FRONTIER_HEALTH_URL).strip(),
                timeout_sec=4.0,
            )
        )
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
        probe_factory: Callable[[], list[Any]] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.probes = list(probes)
        self.min_interval_sec = max(1, int(min_interval_sec))
        self.max_interval_sec = max(self.min_interval_sec, int(max_interval_sec))
        self.startup_probe = bool(startup_probe)
        self._rng = rng or random.Random()
        self._probe_factory = probe_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def run_once(self) -> dict[str, dict[str, Any]]:
        if self._probe_factory is not None:
            try:
                self.update_probes(self._probe_factory())
            except Exception:
                pass
        results: dict[str, dict[str, Any]] = {}
        with self._lock:
            probes = list(self.probes)
        for probe in probes:
            health = probe.probe()
            results[health.provider.value] = upsert_provider_health(self.db_path, health)
        return results

    def update_probes(self, probes: list[Any]) -> None:
        with self._lock:
            self.probes = list(probes)

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
        with self._lock:
            has_probes = bool(self.probes)
        if not has_probes:
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
