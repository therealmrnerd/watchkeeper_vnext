import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ADVISORY_DIR = ROOT_DIR / "services" / "advisory"
if str(ADVISORY_DIR) not in sys.path:
    sys.path.insert(0, str(ADVISORY_DIR))

from router import build_assist_prompt, select_expert_profile


class RouterSelectsExpertTests(unittest.TestCase):
    def test_selects_lore_expert_for_lore_prompt(self) -> None:
        profile = select_expert_profile(
            {
                "mode": "game",
                "domain": "general",
                "user_text": "Tell me Thargoid lore and Galnet background",
            }
        )
        self.assertEqual(profile["expert_id"], "lore")
        self.assertFalse(profile["allow_actions"])

    def test_selects_coding_expert_for_code_prompt(self) -> None:
        profile = select_expert_profile(
            {
                "mode": "work",
                "domain": "general",
                "user_text": "Refactor this python function and add tests",
            }
        )
        self.assertEqual(profile["expert_id"], "coding")

    def test_selects_network_expert_for_network_prompt(self) -> None:
        profile = select_expert_profile(
            {
                "mode": "work",
                "domain": "general",
                "user_text": "Diagnose DNS latency and packet loss",
            }
        )
        self.assertEqual(profile["expert_id"], "network")

    def test_selects_gameplay_expert_for_gameplay_domain(self) -> None:
        profile = select_expert_profile(
            {
                "mode": "game",
                "domain": "gameplay",
                "user_text": "What should I do next?",
            }
        )
        self.assertEqual(profile["expert_id"], "ed_gameplay")

    def test_mfd_prompt_includes_local_only_url_guardrails(self) -> None:
        request = {
            "request_id": "req-mfd-prompt-001",
            "mode": "game",
            "domain": "gameplay",
            "urgency": "normal",
            "user_text": "Build a new Watchkeeper MFD display prompt",
        }
        profile = select_expert_profile(request)
        prompt = build_assist_prompt(
            request,
            {"sitrep": {"summary": "MFD standby"}, "chunks": [], "facts": []},
            profile,
        )

        self.assertIn("/mfd/state", prompt)
        self.assertIn("/mfd/stream", prompt)
        self.assertIn("Do not propose external URLs", prompt)
        self.assertIn("Never put URL strings in proposed_actions.parameters", prompt)
        self.assertIn("Never suggest external web assets", prompt)


if __name__ == "__main__":
    unittest.main()
