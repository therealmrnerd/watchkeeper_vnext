from dataclasses import dataclass, field
from typing import Any


REASON_ALLOW = "ALLOW"
REASON_DENY_NOT_ALLOWED_IN_CONDITION = "DENY_NOT_ALLOWED_IN_CONDITION"
REASON_DENY_EXPLICITLY_DENIED = "DENY_EXPLICITLY_DENIED"
REASON_DENY_NEEDS_CONFIRMATION = "DENY_NEEDS_CONFIRMATION"
REASON_DENY_CONFIRMATION_EXPIRED = "DENY_CONFIRMATION_EXPIRED"
REASON_DENY_LOW_STT_CONFIDENCE = "DENY_LOW_STT_CONFIDENCE"
REASON_DENY_FOREGROUND_MISMATCH = "DENY_FOREGROUND_MISMATCH"
REASON_DENY_RATE_LIMIT = "DENY_RATE_LIMIT"
REASON_DENY_POLICY_INVALID = "DENY_POLICY_INVALID"

KNOWN_REASON_CODES = {
    REASON_ALLOW,
    REASON_DENY_NOT_ALLOWED_IN_CONDITION,
    REASON_DENY_EXPLICITLY_DENIED,
    REASON_DENY_NEEDS_CONFIRMATION,
    REASON_DENY_CONFIRMATION_EXPIRED,
    REASON_DENY_LOW_STT_CONFIDENCE,
    REASON_DENY_FOREGROUND_MISMATCH,
    REASON_DENY_RATE_LIMIT,
    REASON_DENY_POLICY_INVALID,
}


@dataclass
class ActionRequest:
    incident_id: str
    watch_condition: str
    tool_name: str
    args: dict[str, Any]
    source: str
    stt_confidence: float | None
    foreground_process: str | None
    now_ts: float
    user_confirm_token: str | None = None


@dataclass
class Decision:
    allowed: bool
    requires_confirmation: bool = False
    deny_reason_code: str | None = None
    deny_reason_text: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_confirmation": self.requires_confirmation,
            "deny_reason_code": self.deny_reason_code,
            "deny_reason_text": self.deny_reason_text,
            "constraints": self.constraints,
        }
