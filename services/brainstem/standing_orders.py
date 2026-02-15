import fnmatch
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_iso_to_epoch(value: str) -> float:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).timestamp()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return value != 0
    return False


class StandingOrders:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._mtime: float | None = None
        self._config: dict[str, Any] = {}
        self._rate_buckets: dict[str, list[float]] = {}
        self.reload(force=True)

    def reload(self, force: bool = False) -> None:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Standing orders config not found: {self.config_path}")
        mtime = self.config_path.stat().st_mtime
        if not force and self._mtime is not None and mtime == self._mtime:
            return
        self._config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self._mtime = mtime

    def _defaults(self) -> dict[str, Any]:
        return self._config.get("defaults", {})

    def _watch_conditions(self) -> dict[str, Any]:
        return self._config.get("watch_conditions", {})

    def _tool_policies(self) -> dict[str, Any]:
        return self._config.get("tool_policies", {})

    @staticmethod
    def canonical_tool(tool_name: str) -> str:
        mapping = {
            "keypress": "input.keypress",
            "set_lights": "sammi.set_lights",
            "music_next": "sammi.music_next",
            "music_pause": "sammi.music_pause",
            "music_resume": "sammi.music_resume",
        }
        return mapping.get(tool_name, tool_name)

    @staticmethod
    def _match(patterns: list[str], value: str) -> bool:
        value_l = value.lower()
        for pattern in patterns:
            if fnmatch.fnmatchcase(value_l, pattern.lower()):
                return True
        return False

    def _resolve_condition(self, watch_condition: str) -> dict[str, Any]:
        conditions = self._watch_conditions()
        key = watch_condition.upper()
        if key not in conditions:
            raise ValueError(f"Unknown watch condition: {watch_condition}")
        raw = dict(conditions[key])
        parent = raw.get("inherits")
        if not parent:
            return raw
        base = self._resolve_condition(str(parent))
        merged = dict(base)
        for merge_key, merge_value in raw.items():
            if merge_key == "inherits":
                continue
            if isinstance(merge_value, dict) and isinstance(merged.get(merge_key), dict):
                temp = dict(merged.get(merge_key, {}))
                temp.update(merge_value)
                merged[merge_key] = temp
            else:
                merged[merge_key] = merge_value
        return merged

    def _tool_policy(self, tool_key: str) -> dict[str, Any]:
        for pattern, policy in self._tool_policies().items():
            if fnmatch.fnmatchcase(tool_key.lower(), pattern.lower()):
                return dict(policy or {})
        return {}

    def _recent_confirmation_ok(self, user_confirmed: bool, confirmed_at_utc: str | None) -> bool:
        defaults = self._defaults()
        window_sec = int(defaults.get("confirm_window_seconds", 12))
        if not user_confirmed:
            return False
        if not confirmed_at_utc:
            return True
        try:
            age = time.time() - _parse_iso_to_epoch(confirmed_at_utc)
        except Exception:
            return False
        return age <= window_sec

    def _rate_limit_ok(self, bucket_key: str, limit_per_minute: int) -> bool:
        now = time.time()
        arr = self._rate_buckets.setdefault(bucket_key, [])
        cutoff = now - 60
        arr[:] = [t for t in arr if t >= cutoff]
        if len(arr) >= limit_per_minute:
            return False
        arr.append(now)
        return True

    def evaluate(
        self,
        *,
        tool_name: str,
        watch_condition: str,
        incident_id: str | None,
        intent_mode: str,
        user_confirmed: bool,
        confirmed_at_utc: str | None,
        stt_confidence: float | None,
        foreground_process: str | None,
        action_meta: dict[str, Any],
    ) -> dict[str, Any]:
        self.reload(force=False)
        defaults = self._defaults()
        condition = self._resolve_condition(watch_condition)
        tool_key = self.canonical_tool(tool_name)

        reasons: list[str] = []

        if _as_bool(defaults.get("require_incident_id", True)) and not incident_id:
            reasons.append("incident_id is required by standing orders")

        deny_tools = list(condition.get("deny_tools", []))
        if self._match(deny_tools, tool_key):
            reasons.append(f"tool denied in {watch_condition}: {tool_key}")

        allowed_tools = list(condition.get("allowed_tools", []))
        if allowed_tools and not self._match(allowed_tools, tool_key):
            reasons.append(f"tool not allowed in {watch_condition}: {tool_key}")

        guardrails = condition.get("guardrails", {}) or {}
        confirmation = condition.get("confirmation", {}) or {}
        tool_policy = self._tool_policy(tool_key)

        mode_constraints = action_meta.get("mode_constraints") or []
        if isinstance(mode_constraints, list) and mode_constraints:
            if intent_mode not in [str(m) for m in mode_constraints]:
                reasons.append(f"mode '{intent_mode}' not in action mode_constraints")

        if _as_bool(guardrails.get("require_confirmation_for_all_actions", False)):
            if not self._recent_confirmation_ok(user_confirmed, confirmed_at_utc):
                reasons.append("confirmation required for all actions in this watch condition")

        stt_min = float(defaults.get("stt_min_confidence", 0.82))
        stt_low = (stt_confidence is not None) and (stt_confidence < stt_min)
        if _as_bool(guardrails.get("stt_requires_confidence_for_input", False)):
            if tool_key == "input.keypress" and stt_low:
                reasons.append("input denied due to low STT confidence")

        always_confirm = list(confirmation.get("always", []))
        if self._match(always_confirm, tool_key):
            if not self._recent_confirmation_ok(user_confirmed, confirmed_at_utc):
                reasons.append("tool requires recent confirmation")

        low_conf_confirm = list(confirmation.get("when_low_confidence", []))
        if stt_low and self._match(low_conf_confirm, tool_key):
            if not self._recent_confirmation_ok(user_confirmed, confirmed_at_utc):
                reasons.append("low-confidence request requires recent confirmation")

        requires = list(tool_policy.get("requires", []))
        deny_if = list(tool_policy.get("deny_if", []))

        if "stt_confidence_low" in deny_if and stt_low:
            reasons.append("tool policy deny_if: stt_confidence_low")

        if "recent_user_confirm" in requires:
            if not self._recent_confirmation_ok(user_confirmed, confirmed_at_utc):
                reasons.append("tool policy requires recent user confirmation")

        if "foreground_ok" in requires:
            allowed_fg = [str(x).lower() for x in guardrails.get("foreground_process_must_be", [])]
            if allowed_fg:
                if not foreground_process:
                    reasons.append("foreground process unavailable")
                elif foreground_process.lower() not in allowed_fg:
                    reasons.append(
                        f"foreground process '{foreground_process}' not allowed ({', '.join(allowed_fg)})"
                    )

        if _as_bool(defaults.get("ui_foreground_required_for_input", True)):
            if tool_key == "input.keypress" and not foreground_process:
                reasons.append("foreground process required for input.keypress")

        if tool_key == "input.keypress":
            kpm = guardrails.get("max_keypress_per_minute")
            if isinstance(kpm, int) and kpm > 0:
                if not self._rate_limit_ok(f"{watch_condition}:{tool_key}", kpm):
                    reasons.append("max_keypress_per_minute exceeded")

        rlpm = tool_policy.get("rate_limit_per_minute")
        if isinstance(rlpm, int) and rlpm > 0:
            if not self._rate_limit_ok(f"{watch_condition}:{tool_key}:policy", rlpm):
                reasons.append("tool policy rate_limit_per_minute exceeded")

        allowed = len(reasons) == 0
        return {
            "allowed": allowed,
            "reasons": reasons,
            "tool_key": tool_key,
            "watch_condition": watch_condition,
            "incident_id": incident_id,
            "evaluated_at_utc": _utc_now_iso(),
            "stt_confidence": stt_confidence,
            "foreground_process": foreground_process,
            "defaults": defaults,
            "tool_policy": tool_policy,
        }
