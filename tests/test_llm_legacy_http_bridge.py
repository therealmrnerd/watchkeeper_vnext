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
        "request_id": "req-llm-legacy-001",
        "timestamp_utc": "2026-02-19T10:00:00Z",
        "mode": "game",
        "domain": "general",
        "urgency": "normal",
        "user_text": "What is my current ship status?",
        "needs_tools": False,
        "needs_clarification": False,
        "clarification_questions": [],
        "retrieval": {"citation_ids": [], "confidence": 0.5},
        "proposed_actions": [],
        "response_text": "Fallback answer.",
    }


class LLMLegacyHttpBridgeTests(unittest.TestCase):
    def test_legacy_http_maps_answer_into_valid_proposal(self) -> None:
        class _FakeResponse:
            def __init__(self, payload: dict) -> None:
                self._payload = payload

            def read(self) -> bytes:
                return json.dumps(self._payload).encode("utf-8")

            def __enter__(self) -> "_FakeResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        def _fake_opener(_req, timeout=0):
            return _FakeResponse(
                {
                    "answer": "Legacy local model says ship status is nominal.",
                    "reply": "Legacy local model says ship status is nominal.",
                    "used_model": "fast",
                    "meta": {"mode": "llm", "profile": "watchkeeper"},
                }
            )

        client = LLMClient(mode="legacy_http", http_opener=_fake_opener)
        proposal, meta = client.generate_intent_proposal(
            prompt="ignored by legacy bridge",
            fallback_proposal=_fallback_proposal(),
        )
        validate_intent_proposal(proposal)
        self.assertEqual(proposal["response_text"], "Legacy local model says ship status is nominal.")
        self.assertEqual(meta.get("provider"), "watchkeeper_local")
        self.assertEqual(meta.get("mode"), "legacy_http")


if __name__ == "__main__":
    unittest.main()
