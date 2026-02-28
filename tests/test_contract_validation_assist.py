import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from validators import validate_assist_request, validate_intent_proposal


class AssistContractValidationTests(unittest.TestCase):
    def test_validate_assist_request_ok(self) -> None:
        payload = {
            "schema_version": "1.0",
            "request_id": "req-assist-001",
            "timestamp_utc": "2026-02-19T10:00:00Z",
            "mode": "game",
            "domain": "general",
            "urgency": "normal",
            "user_text": "press space",
            "stt_confidence": 0.95,
            "foreground_process": "EliteDangerous64.exe",
            "max_actions": 3,
            "context": {"from": "test"},
        }
        validate_assist_request(payload)

    def test_validate_assist_request_rejects_missing_user_text(self) -> None:
        payload = {
            "schema_version": "1.0",
            "request_id": "req-assist-002",
            "timestamp_utc": "2026-02-19T10:00:00Z",
            "mode": "game",
        }
        with self.assertRaises(ValueError):
            validate_assist_request(payload)

    def test_validate_intent_proposal_ok(self) -> None:
        proposal = {
            "schema_version": "1.0",
            "request_id": "req-proposal-001",
            "timestamp_utc": "2026-02-19T10:00:00Z",
            "mode": "game",
            "domain": "general",
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
                    "reason": "User asked to press space",
                    "confidence": 0.9,
                }
            ],
            "response_text": "Prepared one action.",
        }
        validate_intent_proposal(proposal)

    def test_validate_intent_proposal_rejects_bad_action(self) -> None:
        proposal = {
            "schema_version": "1.0",
            "request_id": "req-proposal-002",
            "timestamp_utc": "2026-02-19T10:00:00Z",
            "mode": "game",
            "domain": "general",
            "urgency": "normal",
            "user_text": "press space",
            "needs_tools": True,
            "needs_clarification": False,
            "proposed_actions": [
                {
                    "action_id": "a1",
                    "tool_name": "keypress",
                    "parameters": {"key": "space"},
                    "safety_level": "unsafe",
                    "timeout_ms": 1500,
                    "confidence": 0.9,
                }
            ],
            "response_text": "Prepared one action.",
        }
        with self.assertRaises(ValueError):
            validate_intent_proposal(proposal)


if __name__ == "__main__":
    unittest.main()

