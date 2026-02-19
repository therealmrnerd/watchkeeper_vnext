import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from urllib import error, request


ROOT_DIR = Path(__file__).resolve().parents[2]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from validators import validate_intent_proposal


class LLMClient:
    def __init__(
        self,
        *,
        mode: str | None = None,
        phi3_url: str | None = None,
        phi3_model: str | None = None,
        timeout_sec: float | None = None,
        raw_generator: Callable[[str], str] | None = None,
        schema_path: str | Path | None = None,
    ) -> None:
        self.mode = (mode or os.getenv("WKV_ADVISORY_LLM_MODE", "stub")).strip().lower()
        self.phi3_url = (phi3_url or os.getenv("WKV_PHI3_URL", "http://127.0.0.1:11434/api/generate")).strip()
        self.phi3_model = (phi3_model or os.getenv("WKV_PHI3_MODEL", "phi3:mini")).strip()
        self.timeout_sec = float(timeout_sec or os.getenv("WKV_PHI3_TIMEOUT_SEC", "25"))
        self.raw_generator = raw_generator
        self.schema_path = (
            Path(schema_path)
            if schema_path
            else (ROOT_DIR / "contracts" / "v1" / "intent_proposal.json")
        )
        self._contract = self._load_contract()

    def _load_contract(self) -> dict[str, Any]:
        try:
            return json.loads(self.schema_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _generate_raw(self, prompt: str, fallback_proposal: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if self.raw_generator is not None:
            return self.raw_generator(prompt), {"provider": "test_raw_generator", "mode": "custom"}

        if self.mode in {"stub", "disabled"}:
            return json.dumps(fallback_proposal, ensure_ascii=False), {
                "provider": "stub_local",
                "mode": self.mode,
            }

        if self.mode == "phi3":
            payload = {
                "model": self.phi3_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            }
            req = request.Request(
                self.phi3_url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with request.urlopen(req, timeout=self.timeout_sec) as resp:
                    raw_body = resp.read().decode("utf-8", errors="replace")
            except error.HTTPError as exc:
                message = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"phi3 HTTP {exc.code}: {message}") from exc
            except Exception as exc:
                raise RuntimeError(f"phi3 request failed: {exc}") from exc

            try:
                parsed = json.loads(raw_body)
                if isinstance(parsed, dict):
                    if isinstance(parsed.get("response"), str):
                        return parsed["response"], {
                            "provider": "phi3_local",
                            "mode": self.mode,
                            "model": self.phi3_model,
                        }
                    if isinstance(parsed.get("output"), str):
                        return parsed["output"], {
                            "provider": "phi3_local",
                            "mode": self.mode,
                            "model": self.phi3_model,
                        }
            except Exception:
                pass

            return raw_body, {"provider": "phi3_local", "mode": self.mode, "model": self.phi3_model}

        return json.dumps(fallback_proposal, ensure_ascii=False), {
            "provider": "stub_local",
            "mode": "fallback",
        }

    @staticmethod
    def _extract_json_object(raw_text: str) -> tuple[dict[str, Any] | None, str]:
        text = (raw_text or "").strip()
        if not text:
            return None, "empty"
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed, "full"
        except Exception:
            pass

        start = text.find("{")
        if start < 0:
            return None, "none"
        in_string = False
        escaped = False
        depth = 0
        for idx in range(start, len(text)):
            ch = text[idx]
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : idx + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            return parsed, "extracted"
                    except Exception:
                        return None, "invalid_extracted"
        return None, "invalid"

    def _validate_contract_shape(self, proposal: dict[str, Any]) -> None:
        if not isinstance(proposal, dict):
            raise ValueError("proposal must be object")
        properties = self._contract.get("properties", {})
        required = self._contract.get("required", [])
        if isinstance(required, list):
            for field in required:
                if field not in proposal:
                    raise ValueError(f"missing required field: {field}")
        if self._contract.get("additionalProperties") is False and isinstance(properties, dict):
            allowed = set(properties.keys())
            extra = sorted(set(proposal.keys()) - allowed)
            if extra:
                raise ValueError(f"unexpected fields: {', '.join(extra)}")

    def _safe_no_action(self, fallback_proposal: dict[str, Any], reason: str) -> dict[str, Any]:
        proposal = dict(fallback_proposal)
        proposal["needs_tools"] = False
        proposal["needs_clarification"] = True
        proposal["clarification_questions"] = ["Please confirm the exact action you want me to take."]
        proposal["proposed_actions"] = []
        proposal["response_text"] = "I need clarification before taking any action."
        retrieval = proposal.get("retrieval")
        if not isinstance(retrieval, dict):
            retrieval = {"citation_ids": [], "confidence": 0.0}
        retrieval["confidence"] = float(retrieval.get("confidence", 0.0))
        retrieval["llm_validation_error"] = reason[:300]
        proposal["retrieval"] = retrieval
        validate_intent_proposal(proposal)
        return proposal

    def generate_intent_proposal(
        self,
        *,
        prompt: str,
        fallback_proposal: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            raw_text, raw_meta = self._generate_raw(prompt, fallback_proposal)
        except Exception as exc:
            safe = self._safe_no_action(fallback_proposal, f"llm_request_error:{exc}")
            return safe, {
                "provider": "fail_safe",
                "mode": self.mode,
                "validation": "safe_fallback",
                "error": str(exc),
            }

        parsed, parse_mode = self._extract_json_object(raw_text)
        if parsed is None:
            safe = self._safe_no_action(fallback_proposal, "invalid_json")
            return safe, raw_meta | {"validation": "safe_fallback", "parse_mode": parse_mode}

        try:
            self._validate_contract_shape(parsed)
            validate_intent_proposal(parsed)
            return parsed, raw_meta | {"validation": "ok", "parse_mode": parse_mode}
        except Exception as exc:
            safe = self._safe_no_action(fallback_proposal, f"schema_validation_error:{exc}")
            return safe, raw_meta | {
                "validation": "safe_fallback",
                "parse_mode": parse_mode,
                "error": str(exc),
            }

