import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ADVISORY_DIR = ROOT_DIR / "services" / "advisory"
if str(ADVISORY_DIR) not in sys.path:
    sys.path.insert(0, str(ADVISORY_DIR))

from router import select_expert_profile


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


if __name__ == "__main__":
    unittest.main()

