import fnmatch
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from core.policy_types import (
        ActionRequest,
        Decision,
        REASON_ALLOW,
        REASON_DENY_CONFIRMATION_EXPIRED,
        REASON_DENY_EXPLICITLY_DENIED,
        REASON_DENY_FOREGROUND_MISMATCH,
        REASON_DENY_LOW_STT_CONFIDENCE,
        REASON_DENY_NEEDS_CONFIRMATION,
        REASON_DENY_NOT_ALLOWED_IN_CONDITION,
        REASON_DENY_POLICY_INVALID,
        REASON_DENY_RATE_LIMIT,
    )
except ModuleNotFoundError:
    # Allows direct execution from the core folder during local debugging.
    from policy_types import (  # type: ignore
        ActionRequest,
        Decision,
        REASON_ALLOW,
        REASON_DENY_CONFIRMATION_EXPIRED,
        REASON_DENY_EXPLICITLY_DENIED,
        REASON_DENY_FOREGROUND_MISMATCH,
        REASON_DENY_LOW_STT_CONFIDENCE,
        REASON_DENY_NEEDS_CONFIRMATION,
        REASON_DENY_NOT_ALLOWED_IN_CONDITION,
        REASON_DENY_POLICY_INVALID,
        REASON_DENY_RATE_LIMIT,
    )


@dataclass
class ConfirmationRecord:
    incident_id: str
    tool_name: str
    token: str
    ts: float


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_dict(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def _ensure_type(name: str, value: Any, expected_type: type) -> None:
    if not isinstance(value, expected_type):
        raise ValueError(f"{name} must be {expected_type.__name__}")


class PolicyEngine:
    def __init__(self, policy_path: str | Path) -> None:
        self.policy_path = Path(policy_path)
        self._policy: dict[str, Any] = {}
        self._mtime: float | None = None
        self._confirmations: list[ConfirmationRecord] = []
        self._rate_windows: dict[str, list[float]] = {}
        self.load_policy(self.policy_path)

    def load_policy(self, path: str | Path) -> dict[str, Any]:
        self.policy_path = Path(path)
        if not self.policy_path.exists():
            raise ValueError(f"Standing Orders invalid: file not found: {self.policy_path}")
        raw = json.loads(self.policy_path.read_text(encoding="utf-8"))
        self.validate_policy(raw)
        self._policy = raw
        self._mtime = self.policy_path.stat().st_mtime
        return raw

    # Keep camelCase alias for contract parity with future ports.
    def loadPolicy(self, path: str | Path) -> dict[str, Any]:  # noqa: N802
        return self.load_policy(path)

    def maybe_reload(self) -> None:
        if not self.policy_path.exists():
            return
        mtime = self.policy_path.stat().st_mtime
        if self._mtime is None or mtime != self._mtime:
            self.load_policy(self.policy_path)

    @staticmethod
    def validate_policy(policy: dict[str, Any]) -> None:
        _ensure_type("policy", policy, dict)
        for key in ("version", "defaults", "watch_conditions", "tool_policies"):
            if key not in policy:
                raise ValueError(f"Standing Orders invalid: missing key '{key}'")

        defaults = policy["defaults"]
        _ensure_type("defaults", defaults, dict)
        if "confirm_window_seconds" not in defaults or not isinstance(
            defaults["confirm_window_seconds"], (int, float)
        ):
            raise ValueError("Standing Orders invalid: defaults.confirm_window_seconds must be numeric")
        if "stt_min_confidence" not in defaults or not isinstance(
            defaults["stt_min_confidence"], (int, float)
        ):
            raise ValueError("Standing Orders invalid: defaults.stt_min_confidence must be numeric")
        if "ui_foreground_required_for_input" not in defaults or not isinstance(
            defaults["ui_foreground_required_for_input"], bool
        ):
            raise ValueError(
                "Standing Orders invalid: defaults.ui_foreground_required_for_input must be boolean"
            )
        if "log_all_denies" in defaults and not isinstance(defaults["log_all_denies"], bool):
            raise ValueError("Standing Orders invalid: defaults.log_all_denies must be boolean")
        if "log_all_executes" in defaults and not isinstance(defaults["log_all_executes"], bool):
            raise ValueError("Standing Orders invalid: defaults.log_all_executes must be boolean")
        if "require_incident_id" in defaults and not isinstance(defaults["require_incident_id"], bool):
            raise ValueError("Standing Orders invalid: defaults.require_incident_id must be boolean")

        conditions = policy["watch_conditions"]
        _ensure_type("watch_conditions", conditions, dict)
        required_conditions = {"STANDBY", "GAME", "WORK", "TUTOR", "RESTRICTED", "DEGRADED"}
        missing = sorted(required_conditions - set(conditions.keys()))
        if missing:
            raise ValueError(f"Standing Orders invalid: missing watch_conditions: {', '.join(missing)}")

        for name, conf in conditions.items():
            _ensure_type(f"watch_conditions.{name}", conf, dict)
            for arr_key in ("allowed_tools", "deny_tools"):
                if arr_key in conf and not isinstance(conf[arr_key], list):
                    raise ValueError(f"Standing Orders invalid: {name}.{arr_key} must be an array")
                if arr_key in conf:
                    for i, pattern in enumerate(conf[arr_key]):
                        if not isinstance(pattern, str):
                            raise ValueError(
                                f"Standing Orders invalid: {name}.{arr_key}[{i}] must be string"
                            )

            confirmation = conf.get("confirmation")
            if confirmation is not None:
                _ensure_type(f"watch_conditions.{name}.confirmation", confirmation, dict)
                for c_key in ("always", "when_low_confidence"):
                    if c_key in confirmation and not isinstance(confirmation[c_key], list):
                        raise ValueError(
                            f"Standing Orders invalid: {name}.confirmation.{c_key} must be array"
                        )
                    for i, pattern in enumerate(confirmation.get(c_key, [])):
                        if not isinstance(pattern, str):
                            raise ValueError(
                                f"Standing Orders invalid: {name}.confirmation.{c_key}[{i}] must be string"
                            )

            guardrails = conf.get("guardrails")
            if guardrails is not None:
                _ensure_type(f"watch_conditions.{name}.guardrails", guardrails, dict)
                if "foreground_process_must_be" in guardrails and not isinstance(
                    guardrails["foreground_process_must_be"], list
                ):
                    raise ValueError(
                        f"Standing Orders invalid: {name}.guardrails.foreground_process_must_be must be array"
                    )
                if "max_keypress_per_minute" in guardrails and not isinstance(
                    guardrails["max_keypress_per_minute"], int
                ):
                    raise ValueError(
                        f"Standing Orders invalid: {name}.guardrails.max_keypress_per_minute must be integer"
                    )
                if "stt_requires_confidence_for_input" in guardrails and not isinstance(
                    guardrails["stt_requires_confidence_for_input"], bool
                ):
                    raise ValueError(
                        f"Standing Orders invalid: {name}.guardrails.stt_requires_confidence_for_input must be boolean"
                    )
                if "require_confirmation_for_all_actions" in guardrails and not isinstance(
                    guardrails["require_confirmation_for_all_actions"], bool
                ):
                    raise ValueError(
                        "Standing Orders invalid: "
                        f"{name}.guardrails.require_confirmation_for_all_actions must be boolean"
                    )

            parent = conf.get("inherits")
            if parent is not None and not isinstance(parent, str):
                raise ValueError(f"Standing Orders invalid: {name}.inherits must be string")

        tool_policies = policy["tool_policies"]
        _ensure_type("tool_policies", tool_policies, dict)
        for pattern, conf in tool_policies.items():
            if not isinstance(pattern, str):
                raise ValueError("Standing Orders invalid: tool policy pattern must be string")
            _ensure_type(f"tool_policies.{pattern}", conf, dict)
            for arr_key in ("requires", "deny_if"):
                if arr_key in conf and not isinstance(conf[arr_key], list):
                    raise ValueError(
                        f"Standing Orders invalid: tool_policies.{pattern}.{arr_key} must be array"
                    )
            if "rate_limit_per_minute" in conf and not isinstance(conf["rate_limit_per_minute"], int):
                raise ValueError(
                    f"Standing Orders invalid: tool_policies.{pattern}.rate_limit_per_minute must be integer"
                )

    def _defaults(self) -> dict[str, Any]:
        return self._policy.get("defaults", {})

    def confirm_window_seconds(self) -> int:
        return int(self._defaults().get("confirm_window_seconds", 12))

    def _watch_conditions(self) -> dict[str, Any]:
        return self._policy.get("watch_conditions", {})

    def _tool_policies(self) -> dict[str, Any]:
        return self._policy.get("tool_policies", {})

    @staticmethod
    def canonical_tool_name(tool_name: str) -> str:
        mapping = {
            "keypress": "input.keypress",
            "set_lights": "sammi.set_lights",
            "music_next": "sammi.music_next",
            "music_pause": "sammi.music_pause",
            "music_resume": "sammi.music_resume",
            "edparser_start": "edparser.start",
            "edparser_stop": "edparser.stop",
            "edparser_status": "edparser.status",
        }
        return mapping.get(tool_name, tool_name)

    @staticmethod
    def _matches(pattern: str, value: str) -> bool:
        return fnmatch.fnmatchcase(value.lower(), pattern.lower())

    @classmethod
    def _any_match(cls, patterns: list[str], value: str) -> bool:
        return any(cls._matches(p, value) for p in patterns)

    def _resolve_condition(self, watch_condition: str) -> dict[str, Any] | None:
        conditions = self._watch_conditions()
        key = watch_condition.upper()
        conf = conditions.get(key)
        if conf is None:
            return None
        parent = conf.get("inherits")
        if not parent:
            return deepcopy(conf)
        parent_conf = self._resolve_condition(str(parent))
        if parent_conf is None:
            return deepcopy(conf)
        return _merge_dict(parent_conf, conf)

    def _find_tool_policy(self, tool_key: str) -> dict[str, Any]:
        for pattern, policy in self._tool_policies().items():
            if self._matches(pattern, tool_key):
                return deepcopy(policy)
        return {}

    def record_confirmation(self, incident_id: str, tool_name: str, token: str, ts: float) -> None:
        if not incident_id or not tool_name or not token:
            return
        tool_key = self.canonical_tool_name(tool_name)
        self._confirmations.append(
            ConfirmationRecord(
                incident_id=incident_id.strip(),
                tool_name=tool_key.strip(),
                token=token.strip(),
                ts=float(ts),
            )
        )
        cutoff = float(ts) - 3600
        self._confirmations = [c for c in self._confirmations if c.ts >= cutoff]

    def _get_confirmation(
        self,
        incident_id: str,
        tool_key: str,
        token: str | None,
    ) -> ConfirmationRecord | None:
        matches = [c for c in self._confirmations if c.incident_id == incident_id and c.tool_name == tool_key]
        if not matches:
            return None
        if token:
            matches = [c for c in matches if c.token == token]
            if not matches:
                return None
        matches.sort(key=lambda c: c.ts, reverse=True)
        return matches[0]

    def _rate_limit_check(self, bucket_key: str, now_ts: float, limit_per_minute: int) -> tuple[bool, int]:
        window = self._rate_windows.setdefault(bucket_key, [])
        cutoff = now_ts - 60.0
        window[:] = [t for t in window if t >= cutoff]
        if len(window) >= limit_per_minute:
            return False, 0
        window.append(now_ts)
        remaining = max(0, limit_per_minute - len(window))
        return True, remaining

    def evaluate(self, req: ActionRequest) -> Decision:
        self.maybe_reload()
        defaults = self._defaults()
        tool_key = self.canonical_tool_name(req.tool_name)
        now_ts = float(req.now_ts)
        constraints: dict[str, Any] = {}

        if not isinstance(req.watch_condition, str) or not req.watch_condition.strip():
            return Decision(
                allowed=False,
                deny_reason_code=REASON_DENY_POLICY_INVALID,
                deny_reason_text="watch_condition is required",
                constraints=constraints,
            )

        if bool(defaults.get("require_incident_id", True)) and not str(req.incident_id or "").strip():
            return Decision(
                allowed=False,
                deny_reason_code=REASON_DENY_POLICY_INVALID,
                deny_reason_text="incident_id is required by policy",
                constraints=constraints,
            )

        condition = self._resolve_condition(req.watch_condition)
        if condition is None:
            return Decision(
                allowed=False,
                deny_reason_code=REASON_DENY_POLICY_INVALID,
                deny_reason_text=f"unknown watch_condition: {req.watch_condition}",
                constraints=constraints,
            )

        deny_tools = list(condition.get("deny_tools", []))
        if self._any_match(deny_tools, tool_key):
            return Decision(
                allowed=False,
                deny_reason_code=REASON_DENY_EXPLICITLY_DENIED,
                deny_reason_text=f"{tool_key} denied in {req.watch_condition}",
                constraints=constraints,
            )

        allowed_tools = list(condition.get("allowed_tools", []))
        if allowed_tools and not self._any_match(allowed_tools, tool_key):
            return Decision(
                allowed=False,
                deny_reason_code=REASON_DENY_NOT_ALLOWED_IN_CONDITION,
                deny_reason_text=f"{tool_key} not allowed in {req.watch_condition}",
                constraints=constraints,
            )

        guardrails = condition.get("guardrails", {}) or {}
        confirmation = condition.get("confirmation", {}) or {}
        tool_policy = self._find_tool_policy(tool_key)

        stt_min = float(defaults.get("stt_min_confidence", 0.82))
        stt_conf = req.stt_confidence
        stt_low = stt_conf is not None and stt_conf < stt_min

        if bool(guardrails.get("stt_requires_confidence_for_input", False)):
            if tool_key == "input.keypress" and stt_low:
                return Decision(
                    allowed=False,
                    deny_reason_code=REASON_DENY_LOW_STT_CONFIDENCE,
                    deny_reason_text=f"stt_confidence {stt_conf} below threshold {stt_min}",
                    constraints=constraints,
                )

        deny_if = [str(x) for x in tool_policy.get("deny_if", [])]
        if "stt_confidence_low" in deny_if and stt_low:
            return Decision(
                allowed=False,
                deny_reason_code=REASON_DENY_LOW_STT_CONFIDENCE,
                deny_reason_text=f"tool policy deny_if stt_confidence_low ({stt_conf}<{stt_min})",
                constraints=constraints,
            )

        foreground_expected = [str(x).lower() for x in guardrails.get("foreground_process_must_be", [])]
        if foreground_expected and (tool_key == "input.keypress" or "foreground_ok" in tool_policy.get("requires", [])):
            if not req.foreground_process or req.foreground_process.lower() not in foreground_expected:
                return Decision(
                    allowed=False,
                    deny_reason_code=REASON_DENY_FOREGROUND_MISMATCH,
                    deny_reason_text=(
                        f"foreground '{req.foreground_process}' not in allowed "
                        f"{', '.join(foreground_expected)}"
                    ),
                    constraints=constraints,
                )

        if bool(defaults.get("ui_foreground_required_for_input", True)) and tool_key == "input.keypress":
            if not req.foreground_process:
                return Decision(
                    allowed=False,
                    deny_reason_code=REASON_DENY_FOREGROUND_MISMATCH,
                    deny_reason_text="foreground process required for input.keypress",
                    constraints=constraints,
                )

        max_kpm = guardrails.get("max_keypress_per_minute")
        if tool_key == "input.keypress" and isinstance(max_kpm, int) and max_kpm > 0:
            ok, remaining = self._rate_limit_check(
                bucket_key=f"{req.watch_condition}:{tool_key}:guardrail",
                now_ts=now_ts,
                limit_per_minute=max_kpm,
            )
            constraints["rate_limit_remaining"] = remaining
            if not ok:
                return Decision(
                    allowed=False,
                    deny_reason_code=REASON_DENY_RATE_LIMIT,
                    deny_reason_text=f"max_keypress_per_minute exceeded ({max_kpm}/min)",
                    constraints=constraints,
                )

        tool_rl = tool_policy.get("rate_limit_per_minute")
        if isinstance(tool_rl, int) and tool_rl > 0:
            ok, remaining = self._rate_limit_check(
                bucket_key=f"{req.watch_condition}:{tool_key}:tool_policy",
                now_ts=now_ts,
                limit_per_minute=tool_rl,
            )
            constraints["rate_limit_remaining"] = remaining
            if not ok:
                return Decision(
                    allowed=False,
                    deny_reason_code=REASON_DENY_RATE_LIMIT,
                    deny_reason_text=f"tool rate limit exceeded ({tool_rl}/min)",
                    constraints=constraints,
                )

        requires_confirmation = False
        always = [str(x) for x in confirmation.get("always", [])]
        low_conf = [str(x) for x in confirmation.get("when_low_confidence", [])]

        if self._any_match(always, tool_key):
            requires_confirmation = True
        if stt_low and self._any_match(low_conf, tool_key):
            requires_confirmation = True
        if bool(guardrails.get("require_confirmation_for_all_actions", False)):
            requires_confirmation = True
        requires_list = [str(x) for x in tool_policy.get("requires", [])]
        if "recent_user_confirm" in requires_list:
            requires_confirmation = True

        if requires_confirmation:
            confirm_window = self.confirm_window_seconds()
            confirm_by = now_ts + confirm_window
            constraints["confirm_by_ts"] = confirm_by
            record = self._get_confirmation(req.incident_id, tool_key, req.user_confirm_token)
            if record is None:
                return Decision(
                    allowed=False,
                    requires_confirmation=True,
                    deny_reason_code=REASON_DENY_NEEDS_CONFIRMATION,
                    deny_reason_text=f"{tool_key} requires user confirmation",
                    constraints=constraints,
                )
            age = now_ts - record.ts
            if age > confirm_window:
                return Decision(
                    allowed=False,
                    requires_confirmation=True,
                    deny_reason_code=REASON_DENY_CONFIRMATION_EXPIRED,
                    deny_reason_text=f"confirmation expired ({age:.1f}s > {confirm_window}s)",
                    constraints=constraints,
                )

        return Decision(
            allowed=True,
            requires_confirmation=False,
            deny_reason_code=REASON_ALLOW,
            deny_reason_text=None,
            constraints=constraints,
        )
