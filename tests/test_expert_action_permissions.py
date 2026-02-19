import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ADVISORY_DIR = ROOT_DIR / "services" / "advisory"
if str(ADVISORY_DIR) not in sys.path:
    sys.path.insert(0, str(ADVISORY_DIR))

from router import apply_expert_action_permissions, build_fallback_proposal, select_expert_profile


class ExpertActionPermissionsTests(unittest.TestCase):
    def test_lore_expert_does_not_emit_actions_in_fallback(self) -> None:
        expert = select_expert_profile(
            {
                "mode": "game",
                "domain": "lore",
                "user_text": "Press space and tell me Thargoid lore",
            }
        )
        proposal = build_fallback_proposal(
            {
                "schema_version": "1.0",
                "request_id": "req-lore-actions-001",
                "timestamp_utc": "2026-02-19T10:00:00Z",
                "mode": "game",
                "domain": "lore",
                "urgency": "normal",
                "user_text": "Press space and tell me Thargoid lore",
            },
            {"citations": [], "metadata": {}},
            expert,
        )
        self.assertEqual(expert["expert_id"], "lore")
        self.assertFalse(proposal["proposed_actions"])

    def test_lore_expert_filters_keypress_action(self) -> None:
        expert = {"expert_id": "lore", "allow_actions": True, "retrieval_domains": ["lore"]}
        proposal = {
            "schema_version": "1.0",
            "request_id": "req-lore-actions-002",
            "timestamp_utc": "2026-02-19T10:00:00Z",
            "mode": "game",
            "domain": "lore",
            "urgency": "normal",
            "user_text": "press space",
            "needs_tools": True,
            "needs_clarification": False,
            "clarification_questions": [],
            "retrieval": {"citation_ids": [], "confidence": 0.5},
            "proposed_actions": [
                {
                    "action_id": "a1",
                    "tool_name": "keypress",
                    "parameters": {"key": "space"},
                    "safety_level": "high_risk",
                    "mode_constraints": ["game"],
                    "requires_confirmation": True,
                    "timeout_ms": 1500,
                    "reason": "test",
                    "confidence": 0.9,
                }
            ],
            "response_text": "test",
        }
        filtered, removed = apply_expert_action_permissions(proposal, expert)
        self.assertEqual(removed, 1)
        self.assertFalse(filtered["proposed_actions"])
        self.assertFalse(filtered["needs_tools"])


if __name__ == "__main__":
    unittest.main()

