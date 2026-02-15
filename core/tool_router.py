import time
from typing import Any

from core.policy_engine import PolicyEngine
from core.policy_types import (
    ActionRequest,
    Decision,
    REASON_DENY_NEEDS_CONFIRMATION,
)
from db.logbook import Logbook


class ToolRouter:
    def __init__(self, policy_engine: PolicyEngine, logbook: Logbook | None = None) -> None:
        self.policy_engine = policy_engine
        self.logbook = logbook

    @staticmethod
    def build_confirmation_token(incident_id: str, tool_key: str) -> str:
        safe_tool = tool_key.replace(".", "-")
        return f"confirm-{incident_id[:12]}-{safe_tool}"

    @classmethod
    def _confirmation_token(cls, incident_id: str, tool_key: str) -> str:
        return cls.build_confirmation_token(incident_id, tool_key)

    def evaluate_action(
        self,
        *,
        incident_id: str,
        watch_condition: str,
        tool_name: str,
        args: dict[str, Any],
        source: str,
        stt_confidence: float | None,
        foreground_process: str | None,
        user_confirmed: bool,
        user_confirm_token: str | None,
        action_requires_confirmation: bool = False,
        now_ts: float | None = None,
        confirmation_ts: float | None = None,
        req_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        req_context = req_context or {}
        eval_ts = float(now_ts if now_ts is not None else time.time())
        tool_key = self.policy_engine.canonical_tool_name(tool_name)
        confirm_token = (user_confirm_token or "").strip() or self._confirmation_token(
            incident_id=incident_id,
            tool_key=tool_key,
        )

        if user_confirmed:
            self.policy_engine.record_confirmation(
                incident_id=incident_id,
                tool_name=tool_key,
                token=confirm_token,
                ts=float(confirmation_ts if confirmation_ts is not None else eval_ts),
            )

        req = ActionRequest(
            incident_id=incident_id,
            watch_condition=watch_condition,
            tool_name=tool_name,
            args=args,
            source=source,
            stt_confidence=stt_confidence,
            foreground_process=foreground_process,
            now_ts=eval_ts,
            user_confirm_token=confirm_token if user_confirmed or user_confirm_token else None,
        )

        decision = self.policy_engine.evaluate(req)
        if decision.allowed and action_requires_confirmation and not user_confirmed:
            confirm_window = self.policy_engine.confirm_window_seconds()
            decision = Decision(
                allowed=False,
                requires_confirmation=True,
                deny_reason_code=REASON_DENY_NEEDS_CONFIRMATION,
                deny_reason_text="action metadata requires user confirmation",
                constraints={
                    "confirm_by_ts": eval_ts + confirm_window,
                },
            )

        if decision.requires_confirmation:
            decision.constraints.setdefault("confirm_token", confirm_token)

        if self.logbook is not None:
            self.logbook.log_decision(
                incident_id=incident_id,
                tool_name=tool_key,
                decision=decision.to_dict(),
                req_context=req_context
                | {
                    "watch_condition": watch_condition,
                    "source": source,
                    "stt_confidence": stt_confidence,
                    "foreground_process": foreground_process,
                },
            )

        return {
            "decision": decision.to_dict(),
            "tool_key": tool_key,
            "confirm_token": confirm_token if decision.requires_confirmation else None,
        }
