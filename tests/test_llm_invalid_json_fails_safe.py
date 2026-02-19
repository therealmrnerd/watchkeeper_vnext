import json
import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ADVISORY_DIR = ROOT_DIR / "services" / "advisory"
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
for p in (ADVISORY_DIR, BRAINSTEM_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from llm_client import LLMClient
from validators import validate_intent_proposal


def _fallback_proposal() -> dict:
    return {
        "schema_version": "1.0",
        "request_id": "req-llm-safe-001",
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
                "reason": "test",
                "confidence": 0.9,
            }
        ],
        "response_text": "Prepared one action.",
    }


class LLMInvalidJsonFailsSafeTests(unittest.TestCase):
    def test_invalid_json_returns_safe_no_action(self) -> None:
        client = LLMClient(raw_generator=lambda prompt: "this is not valid json")
        proposal, meta = client.generate_intent_proposal(
            prompt="test prompt",
            fallback_proposal=_fallback_proposal(),
        )
        validate_intent_proposal(proposal)
        self.assertFalse(proposal["needs_tools"])
        self.assertTrue(proposal["needs_clarification"])
        self.assertEqual(proposal["proposed_actions"], [])
        self.assertEqual(meta.get("validation"), "safe_fallback")

    def test_extracts_json_object_from_wrapped_text(self) -> None:
        payload = _fallback_proposal()
        wrapped = "Model output:\n```json\n" + json.dumps(payload) + "\n```"
        client = LLMClient(raw_generator=lambda prompt: wrapped)
        proposal, meta = client.generate_intent_proposal(
            prompt="test prompt",
            fallback_proposal=_fallback_proposal(),
        )
        validate_intent_proposal(proposal)
        self.assertEqual(proposal["request_id"], payload["request_id"])
        self.assertEqual(meta.get("validation"), "ok")


if __name__ == "__main__":
    unittest.main()

