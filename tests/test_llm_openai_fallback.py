import json
import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ADVISORY_DIR = ROOT_DIR / "services" / "advisory"
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
for p in (ROOT_DIR, ADVISORY_DIR, BRAINSTEM_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import llm_client as llm_client_module
from llm_client import LLMClient


def _fallback_proposal() -> dict:
    return {
        "schema_version": "1.0",
        "request_id": "req-openai-fallback-001",
        "timestamp_utc": "2026-02-19T10:00:00Z",
        "mode": "game",
        "domain": "general",
        "urgency": "normal",
        "user_text": "press space",
        "needs_tools": False,
        "needs_clarification": False,
        "clarification_questions": [],
        "retrieval": {"citation_ids": [], "confidence": 0.5},
        "proposed_actions": [],
        "response_text": "Prepared one action.",
    }


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class LLMOpenAiFallbackTests(unittest.TestCase):
    def test_invalid_local_json_uses_openai_structured_fallback(self) -> None:
        original_get_provider_secret_entry = llm_client_module.get_provider_secret_entry
        original_load_runtime_settings = llm_client_module.load_runtime_settings
        original_runtime_setting_enabled = llm_client_module.runtime_setting_enabled

        def fake_http_opener(req, timeout=0):
            del timeout
            self.assertEqual(req.full_url, "https://api.openai.com/v1/responses")
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body["text"]["format"]["type"], "json_schema")
            proposal = dict(_fallback_proposal())
            proposal["request_id"] = "req-openai-accepted"
            proposal["response_text"] = "Watchkeeper online."
            return _FakeResponse({"output_text": json.dumps(proposal)})

        try:
            llm_client_module.get_provider_secret_entry = lambda provider_id, path=None: {"api_key": "test-key"}
            llm_client_module.load_runtime_settings = lambda db_path: {"providers": {"openai": {"enabled": True}}}
            llm_client_module.runtime_setting_enabled = lambda settings, section, item_id, default: True

            client = LLMClient(
                raw_generator=lambda prompt: "not json",
                http_opener=fake_http_opener,
            )
            proposal, meta = client.generate_intent_proposal(
                prompt="test prompt",
                fallback_proposal=_fallback_proposal(),
            )
        finally:
            llm_client_module.get_provider_secret_entry = original_get_provider_secret_entry
            llm_client_module.load_runtime_settings = original_load_runtime_settings
            llm_client_module.runtime_setting_enabled = original_runtime_setting_enabled

        self.assertEqual(meta.get("provider"), "openai")
        self.assertEqual(meta.get("validation"), "ok")
        self.assertEqual(proposal.get("request_id"), "req-openai-accepted")
        self.assertEqual(proposal.get("response_text"), "Watchkeeper online.")


if __name__ == "__main__":
    unittest.main()
