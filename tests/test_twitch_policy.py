import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.policy.twitch_policy import TwitchPolicyEngine


class TwitchPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = TwitchPolicyEngine(usual_prompt_cooldown_sec=300, max_auto_replies_per_minute=3)

    def test_deny_full_chat_storage(self) -> None:
        decision = self.policy.evaluate({}, {"type": "chat.reply", "store_full_chat": True})
        self.assertEqual(decision["decision"], "deny")

    def test_ask_for_disruptive_action(self) -> None:
        decision = self.policy.evaluate({}, {"type": "chat.announce"})
        self.assertEqual(decision["decision"], "ask")
        self.assertTrue(str(decision.get("suggested_question") or "").strip())

    def test_allow_read_only_personalized_reply(self) -> None:
        decision = self.policy.evaluate(
            {"chat_storm": False, "auto_replies_last_min": 0},
            {"type": "chat.reply", "text": "Thanks for the support!"},
        )
        self.assertEqual(decision["decision"], "allow")

    def test_usual_prompt_cooldown(self) -> None:
        decision = self.policy.evaluate(
            {"usual_prompt_age_sec": 10},
            {"type": "chat.usual_prompt"},
        )
        self.assertEqual(decision["decision"], "deny")


if __name__ == "__main__":
    unittest.main()
