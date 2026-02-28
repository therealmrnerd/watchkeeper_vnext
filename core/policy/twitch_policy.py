from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TwitchPolicyDecision:
    decision: str
    reason: str
    suggested_question: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "suggested_question": self.suggested_question,
        }


class TwitchPolicyEngine:
    def __init__(
        self,
        *,
        usual_prompt_cooldown_sec: int = 600,
        max_auto_replies_per_minute: int = 6,
    ) -> None:
        self.usual_prompt_cooldown_sec = max(30, int(usual_prompt_cooldown_sec))
        self.max_auto_replies_per_minute = max(1, int(max_auto_replies_per_minute))

    def evaluate(self, context: dict[str, Any], proposed_action: dict[str, Any]) -> dict[str, Any]:
        action_type = str(proposed_action.get("type") or "").strip().lower()
        if not action_type:
            return TwitchPolicyDecision("deny", "missing_action_type").as_dict()

        if bool(proposed_action.get("store_full_chat")):
            return TwitchPolicyDecision("deny", "full_chat_storage_disallowed").as_dict()

        if bool(proposed_action.get("infer_sensitive_traits")):
            return TwitchPolicyDecision("deny", "sensitive_trait_inference_disallowed").as_dict()

        if bool(context.get("chat_storm")):
            if action_type in {"chat.reply", "chat.prompt", "chat.announce"}:
                return TwitchPolicyDecision("ask", "chat_storm_reduce_chatter").as_dict()

        replies_last_min = int(context.get("auto_replies_last_min", 0) or 0)
        if replies_last_min >= self.max_auto_replies_per_minute:
            return TwitchPolicyDecision("deny", "auto_reply_rate_limited").as_dict()

        if action_type in {"redeem.trigger", "chat.announce", "chat.mass_reply"}:
            return TwitchPolicyDecision(
                "ask",
                "costly_or_disruptive_action",
                suggested_question="Confirm Twitch action now?",
            ).as_dict()

        if action_type == "chat.usual_prompt":
            last_prompt_age_sec = int(context.get("usual_prompt_age_sec", 10**9) or 0)
            if last_prompt_age_sec < self.usual_prompt_cooldown_sec:
                return TwitchPolicyDecision("deny", "usual_prompt_cooldown").as_dict()
            return TwitchPolicyDecision(
                "ask",
                "usual_prompt_requires_consent",
                suggested_question="Offer the usual redeem for this user?",
            ).as_dict()

        return TwitchPolicyDecision("allow", "policy_allow").as_dict()
