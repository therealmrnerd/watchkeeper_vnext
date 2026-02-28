from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Protocol


class ProviderId(str, Enum):
    SPANSH = "spansh"
    EDSM = "edsm"
    INARA = "inara"
    EDSY = "edsy"


class ProviderHealthStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    THROTTLED = "throttled"
    DOWN = "down"
    MISCONFIGURED = "misconfigured"


class ProviderRateLimitState(str, Enum):
    OK = "ok"
    UNKNOWN = "unknown"
    THROTTLED = "throttled"
    COOLDOWN = "cooldown"


class ProviderOperationId(str, Enum):
    SYSTEM_LOOKUP = "system_lookup"
    BODIES_LOOKUP = "bodies_lookup"
    STATIONS_LOOKUP = "stations_lookup"
    COMMANDER_PROFILE_LOOKUP = "commander_profile_lookup"
    COMMANDER_LOCATION_PUSH = "commander_location_push"
    SHIP_BUILD_REFERENCE = "ship_build_reference"


class ProviderDenyReason(str, Enum):
    PROVIDER_DOWN = "provider_down"
    MISCONFIGURED = "misconfigured"
    RATE_LIMITED = "rate_limited"
    NO_INTENT = "no_intent"
    WRITE_REQUIRES_CONFIRM = "write_requires_confirm"
    CALL_BUDGET_EXCEEDED = "call_budget_exceeded"


READ_ONLY_OPERATIONS = {
    ProviderOperationId.SYSTEM_LOOKUP,
    ProviderOperationId.BODIES_LOOKUP,
    ProviderOperationId.STATIONS_LOOKUP,
    ProviderOperationId.COMMANDER_PROFILE_LOOKUP,
    ProviderOperationId.SHIP_BUILD_REFERENCE,
}


@dataclass
class ProviderHealth:
    provider: ProviderId
    status: ProviderHealthStatus
    checked_at: str
    latency_ms: int | None
    http_code: int | None
    rate_limit_state: ProviderRateLimitState = ProviderRateLimitState.UNKNOWN
    retry_after_s: int | None = None
    tool_calls_allowed: bool = False
    degraded_readonly: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider.value,
            "status": self.status.value,
            "checked_at": self.checked_at,
            "latency_ms": self.latency_ms,
            "http": {"code": self.http_code},
            "rate_limit": {
                "state": self.rate_limit_state.value,
                "retry_after_s": self.retry_after_s,
            },
            "capabilities": {
                "tool_calls_allowed": self.tool_calls_allowed,
                "degraded_readonly": self.degraded_readonly,
            },
            "message": self.message,
        }


@dataclass
class ProviderQuery:
    provider: ProviderId
    operation: ProviderOperationId
    params: dict[str, Any]
    max_age_s: int
    allow_stale_if_error: bool
    incident_id: str | None = None
    reason: str = ""

    @property
    def read_only(self) -> bool:
        return self.operation in READ_ONLY_OPERATIONS


@dataclass
class ProviderCacheMeta:
    hit: bool = False
    age_s: int | None = None
    ttl_s: int | None = None
    stale_served: bool = False


@dataclass
class ProviderProvenance:
    endpoint: str | None = None
    http_code: int | None = None


@dataclass
class ProviderResult:
    ok: bool
    provider: ProviderId
    operation: ProviderOperationId
    fetched_at: str
    cache: ProviderCacheMeta = field(default_factory=ProviderCacheMeta)
    health_observed: ProviderHealth | None = None
    data: dict[str, Any] | None = None
    provenance: ProviderProvenance = field(default_factory=ProviderProvenance)
    error: str | None = None
    deny_reason: ProviderDenyReason | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider.value,
            "operation": self.operation.value,
            "fetched_at": self.fetched_at,
            "cache": asdict(self.cache),
            "health_observed": self.health_observed.to_dict() if self.health_observed else None,
            "data": self.data,
            "provenance": asdict(self.provenance),
            "error": self.error,
            "deny_reason": self.deny_reason.value if self.deny_reason else None,
        }


class ProviderAdapter(Protocol):
    provider_id: ProviderId

    def query(self, request: ProviderQuery) -> ProviderResult:
        ...


class HealthProbe(Protocol):
    provider_id: ProviderId

    def probe(self) -> ProviderHealth:
        ...


class ProviderQueryService(Protocol):
    def execute(self, request: ProviderQuery) -> ProviderResult:
        ...
