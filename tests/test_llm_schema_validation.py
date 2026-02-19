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


def _fallback_proposal() -> dict:
    return {
        "schema_version": "1.0",
        "request_id": "req-llm-schema-001",
        "timestamp_utc": "2026-02-19T10:00:00Z",
        "mode": "work",
        "domain": "coding",
        "urgency": "normal",
        "user_text": "help me refactor this",
        "needs_tools": False,
        "needs_clarification": False,
        "clarification_questions": [],
        "retrieval": {"citation_ids": [], "confidence": 0.5},
        "proposed_actions": [],
        "response_text": "No direct actions required.",
    }


class LLMSchemaValidationTests(unittest.TestCase):
    def test_schema_invalid_output_falls_back(self) -> None:
        bad_payload = {
            "schema_version": "1.0",
            "request_id": "req-bad-001",
            "timestamp_utc": "2026-02-19T10:00:00Z",
            "mode": "work",
            # domain missing on purpose
            "urgency": "normal",
            "user_text": "broken payload",
            "needs_tools": False,
            "needs_clarification": False,
            "proposed_actions": [],
            "response_text": "bad",
        }
        client = LLMClient(raw_generator=lambda prompt: json.dumps(bad_payload))
        proposal, meta = client.generate_intent_proposal(
            prompt="test prompt",
            fallback_proposal=_fallback_proposal(),
        )
        self.assertEqual(meta.get("validation"), "safe_fallback")
        self.assertTrue(proposal.get("needs_clarification"))
        self.assertEqual(proposal.get("proposed_actions"), [])

    def test_schema_valid_output_is_accepted(self) -> None:
        good_payload = dict(_fallback_proposal())
        good_payload["request_id"] = "req-good-001"
        client = LLMClient(raw_generator=lambda prompt: json.dumps(good_payload))
        proposal, meta = client.generate_intent_proposal(
            prompt="test prompt",
            fallback_proposal=_fallback_proposal(),
        )
        self.assertEqual(meta.get("validation"), "ok")
        self.assertEqual(proposal.get("request_id"), "req-good-001")
        self.assertFalse(proposal.get("needs_clarification"))


if __name__ == "__main__":
    unittest.main()

