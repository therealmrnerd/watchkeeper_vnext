import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from urllib import error, request


ROOT_DIR = Path(__file__).resolve().parents[2]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
for p in (ROOT_DIR, BRAINSTEM_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from provider_secrets import DEFAULT_PROVIDER_SECRETS_PATH, get_provider_secret_entry
from settings_store import load_runtime_settings, runtime_setting_enabled
from validators import validate_intent_proposal
from local_runtime import OpenVinoLocalRuntime


class LLMClient:
    def __init__(
        self,
        *,
        mode: str | None = None,
        phi3_url: str | None = None,
        phi3_model: str | None = None,
        timeout_sec: float | None = None,
        raw_generator: Callable[[str], str] | None = None,
        http_opener: Callable[..., Any] | None = None,
        schema_path: str | Path | None = None,
        intent_sketch_schema_path: str | Path | None = None,
        local_runtime: OpenVinoLocalRuntime | None = None,
    ) -> None:
        self.mode = (mode or os.getenv("WKV_ADVISORY_LLM_MODE", "openvino_local")).strip().lower()
        self.local_output_mode = (
            os.getenv("WKV_ADVISORY_LOCAL_OUTPUT_MODE", "intent_proposal").strip().lower() or "intent_proposal"
        )
        self.phi3_url = (phi3_url or os.getenv("WKV_PHI3_URL", "http://127.0.0.1:11434/api/generate")).strip()
        self.phi3_model = (phi3_model or os.getenv("WKV_PHI3_MODEL", "phi3:mini")).strip()
        self.timeout_sec = float(timeout_sec or os.getenv("WKV_PHI3_TIMEOUT_SEC", "25"))
        self.legacy_assist_url = os.getenv("WKV_LEGACY_ASSIST_URL", "http://127.0.0.1:8000/assist").strip()
        self.legacy_profile = os.getenv("WKV_LEGACY_PROFILE", "watchkeeper").strip() or "watchkeeper"
        self.legacy_max_new_tokens = int(os.getenv("WKV_LEGACY_MAX_NEW_TOKENS", "256"))
        self.legacy_temperature = float(os.getenv("WKV_LEGACY_TEMPERATURE", "0.3"))
        self.legacy_top_p = float(os.getenv("WKV_LEGACY_TOP_P", "0.9"))
        self.db_path = Path(os.getenv("WKV_DB_PATH", ROOT_DIR / "data" / "watchkeeper_vnext.db"))
        self.provider_secrets_path = Path(
            os.getenv("WKV_PROVIDER_SECRETS_PATH", str(DEFAULT_PROVIDER_SECRETS_PATH))
        )
        self.openai_url = os.getenv("WKV_OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses").strip()
        self.openai_model = os.getenv("WKV_OPENAI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
        self.openai_timeout_sec = float(os.getenv("WKV_OPENAI_TIMEOUT_SEC", "45"))
        self.raw_generator = raw_generator
        self.http_opener = http_opener or request.urlopen
        self.local_runtime = local_runtime or OpenVinoLocalRuntime()
        self.schema_path = (
            Path(schema_path)
            if schema_path
            else (ROOT_DIR / "contracts" / "v1" / "intent_proposal.json")
        )
        self.intent_sketch_schema_path = (
            Path(intent_sketch_schema_path)
            if intent_sketch_schema_path
            else (ROOT_DIR / "contracts" / "v1" / "intent_sketch.schema.json")
        )
        self._contract = self._load_contract(self.schema_path)
        self._intent_sketch_contract = self._load_contract(self.intent_sketch_schema_path)

    def _load_contract(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _generate_raw(
        self,
        prompt: str,
        fallback_proposal: dict[str, Any],
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if self.raw_generator is not None:
            return self.raw_generator(prompt), {"provider": "test_raw_generator", "mode": "custom"}

        if self.mode in {"stub", "disabled"}:
            return json.dumps(fallback_proposal, ensure_ascii=False), {
                "provider": "stub_local",
                "mode": self.mode,
            }

        if self.mode in {"openvino_local", "native", "phi3_openvino"}:
            reply, runtime_meta = self.local_runtime.generate(
                prompt=prompt,
                max_new_tokens=int(os.getenv("WKV_ADVISORY_MAX_NEW_TOKENS", "256")),
                temperature=float(os.getenv("WKV_ADVISORY_TEMPERATURE", "0.2")),
                top_p=float(os.getenv("WKV_ADVISORY_TOP_P", "0.9")),
                json_schema=json_schema,
            )
            return reply, {
                "provider": "openvino_local",
                "mode": self.mode,
                "runtime": runtime_meta,
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
                with self.http_opener(req, timeout=self.timeout_sec) as resp:
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

        if self.mode in {"legacy_http", "legacy_local", "original_http"}:
            request_payload = {
                "message": str(fallback_proposal.get("user_text") or "").strip(),
                "profile": self.legacy_profile,
                "tool_policy": "never",
                "memory_policy": "off",
                "max_new_tokens": self.legacy_max_new_tokens,
                "temperature": self.legacy_temperature,
                "top_p": self.legacy_top_p,
            }
            req = request.Request(
                self.legacy_assist_url,
                data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with self.http_opener(req, timeout=self.timeout_sec) as resp:
                    raw_body = resp.read().decode("utf-8", errors="replace")
            except error.HTTPError as exc:
                message = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"legacy_http HTTP {exc.code}: {message}") from exc
            except Exception as exc:
                raise RuntimeError(f"legacy_http request failed: {exc}") from exc

            try:
                parsed = json.loads(raw_body)
            except Exception as exc:
                raise RuntimeError(f"legacy_http returned non-JSON body: {exc}") from exc

            if not isinstance(parsed, dict):
                raise RuntimeError("legacy_http returned non-object response")

            answer = str(parsed.get("answer") or parsed.get("reply") or "").strip()
            if not answer:
                raise RuntimeError("legacy_http returned empty answer")

            proposal = dict(fallback_proposal)
            proposal["response_text"] = answer
            retrieval = proposal.get("retrieval")
            if not isinstance(retrieval, dict):
                retrieval = {"citation_ids": [], "confidence": 0.0}
            retrieval["legacy_backend"] = {
                "provider": "watchkeeper_local",
                "profile": self.legacy_profile,
                "mode": self.mode,
                "used_model": parsed.get("used_model"),
                "meta": parsed.get("meta") if isinstance(parsed.get("meta"), dict) else {},
            }
            proposal["retrieval"] = retrieval
            return json.dumps(proposal, ensure_ascii=False), {
                "provider": "watchkeeper_local",
                "mode": self.mode,
                "profile": self.legacy_profile,
                "source_url": self.legacy_assist_url,
            }

        return json.dumps(fallback_proposal, ensure_ascii=False), {
            "provider": "stub_local",
            "mode": "fallback",
        }

    def _openai_fallback_enabled(self) -> bool:
        try:
            settings = load_runtime_settings(self.db_path)
        except Exception:
            settings = {}
        if not runtime_setting_enabled(settings, "providers", "openai", False):
            return False
        try:
            entry = get_provider_secret_entry("openai", self.provider_secrets_path)
        except Exception:
            return False
        return bool(str(entry.get("api_key") or "").strip())

    def _generate_raw_openai(self, prompt: str) -> tuple[str, dict[str, Any]]:
        entry = get_provider_secret_entry("openai", self.provider_secrets_path)
        api_key = str(entry.get("api_key") or "").strip()
        if not api_key:
            raise RuntimeError("openai fallback key missing")

        schema = self._build_openai_intent_schema()

        payload = {
            "model": self.openai_model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "intent_proposal",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        req = request.Request(
            self.openai_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with self.http_opener(req, timeout=self.openai_timeout_sec) as resp:
                raw_body = resp.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"openai HTTP {exc.code}: {message}") from exc
        except Exception as exc:
            raise RuntimeError(f"openai request failed: {exc}") from exc

        try:
            parsed = json.loads(raw_body)
        except Exception as exc:
            raise RuntimeError(f"openai returned non-JSON body: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("openai returned non-object response")

        output_text = str(parsed.get("output_text") or "").strip()
        if not output_text:
            output = parsed.get("output")
            if isinstance(output, list):
                collected: list[str] = []
                for item in output:
                    if not isinstance(item, dict):
                        continue
                    content = item.get("content")
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        text_value = block.get("text")
                        if isinstance(text_value, str) and text_value.strip():
                            collected.append(text_value)
                output_text = "\n".join(collected).strip()
        if not output_text:
            raise RuntimeError("openai returned empty structured output")
        return output_text, {
            "provider": "openai",
            "mode": "responses_structured",
            "model": self.openai_model,
        }

    def _build_openai_intent_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "schema_version": {"type": "string", "enum": ["1.0"]},
                "request_id": {"type": "string"},
                "timestamp_utc": {"type": "string"},
                "mode": {"type": "string", "enum": ["game", "work", "standby", "tutor"]},
                "domain": {
                    "type": "string",
                    "enum": [
                        "gameplay",
                        "lore",
                        "astrophysics",
                        "general_gaming",
                        "coding",
                        "networking",
                        "system",
                        "music",
                        "speech",
                        "general",
                    ],
                },
                "urgency": {"type": "string", "enum": ["low", "normal", "high"]},
                "user_text": {"type": "string"},
                "needs_tools": {"type": "boolean"},
                "needs_clarification": {"type": "boolean"},
                "clarification_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "retrieval": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "citation_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "confidence": {"type": "number"},
                    },
                    "required": ["citation_ids", "confidence"],
                },
                "proposed_actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "action_id": {"type": "string"},
                            "tool_name": {"type": "string"},
                            "parameters": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {},
                                "required": [],
                            },
                            "safety_level": {
                                "type": "string",
                                "enum": ["read_only", "low_risk", "high_risk"],
                            },
                            "mode_constraints": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "requires_confirmation": {"type": "boolean"},
                            "timeout_ms": {"type": "integer"},
                            "reason": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                        "required": [
                            "action_id",
                            "tool_name",
                            "parameters",
                            "safety_level",
                            "mode_constraints",
                            "requires_confirmation",
                            "timeout_ms",
                            "reason",
                            "confidence",
                        ],
                    },
                },
                "response_text": {"type": "string"},
            },
            "required": [
                "schema_version",
                "request_id",
                "timestamp_utc",
                "mode",
                "domain",
                "urgency",
                "user_text",
                "needs_tools",
                "needs_clarification",
                "clarification_questions",
                "retrieval",
                "proposed_actions",
                "response_text",
            ],
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

    def _validate_intent_sketch_shape(self, sketch: dict[str, Any]) -> None:
        if not isinstance(sketch, dict):
            raise ValueError("intent sketch must be object")
        properties = self._intent_sketch_contract.get("properties", {})
        required = self._intent_sketch_contract.get("required", [])
        if isinstance(required, list):
            for field in required:
                if field not in sketch:
                    raise ValueError(f"intent sketch missing required field: {field}")
        if self._intent_sketch_contract.get("additionalProperties") is False and isinstance(properties, dict):
            allowed = set(properties.keys())
            extra = sorted(set(sketch.keys()) - allowed)
            if extra:
                raise ValueError(f"unexpected sketch fields: {', '.join(extra)}")

    def _repair_intent_sketch(self, sketch: dict[str, Any]) -> dict[str, Any]:
        repaired = dict(sketch) if isinstance(sketch, dict) else {}
        repaired["schema_version"] = "1.0"

        intent = str(repaired.get("intent") or "").strip().lower()
        if intent not in {"respond", "clarify", "tool_request"}:
            intent = "respond"
        repaired["intent"] = intent

        response_text = str(repaired.get("response_text") or "").strip()
        repaired["response_text"] = (response_text or "I can help with that.")[:480]

        tool_name = str(repaired.get("tool_name") or "").strip()
        if tool_name not in {"none", "keypress", "set_lights", "music_next"}:
            tool_name = "none"
        repaired["tool_name"] = tool_name
        repaired["tool_arg"] = str(repaired.get("tool_arg") or "").strip()[:64]

        confidence_band = str(repaired.get("confidence_band") or "").strip().lower()
        if confidence_band not in {"low", "medium", "high"}:
            confidence_band = "medium"
        repaired["confidence_band"] = confidence_band

        needs_clarification = bool(repaired.get("needs_clarification")) or intent == "clarify"
        repaired["needs_clarification"] = needs_clarification
        clarification_question = str(repaired.get("clarification_question") or "").strip()[:160]
        if needs_clarification and not clarification_question:
            clarification_question = "Please confirm the exact action you want me to take."
        repaired["clarification_question"] = clarification_question

        if repaired["needs_clarification"]:
            repaired["intent"] = "clarify"
            repaired["tool_name"] = "none"
            repaired["tool_arg"] = ""
        elif repaired["tool_name"] == "none":
            repaired["intent"] = "respond"
        else:
            repaired["intent"] = "tool_request"
        return repaired

    def _confidence_band_score(self, value: str) -> float:
        return {"low": 0.35, "medium": 0.65, "high": 0.9}.get(str(value).strip().lower(), 0.5)

    def _normalize_keypress_arg(self, value: str) -> str | None:
        key = str(value or "").strip().lower()
        if key in {"space", "enter", "tab", "esc", "up", "down", "left", "right"}:
            return key
        if key.startswith("f") and key[1:].isdigit():
            number = int(key[1:])
            if 1 <= number <= 12:
                return key
        return None

    def _map_intent_sketch_to_proposal(
        self,
        sketch: dict[str, Any],
        fallback_proposal: dict[str, Any],
    ) -> dict[str, Any]:
        repaired = self._repair_intent_sketch(sketch)
        proposal = dict(fallback_proposal)
        proposal["response_text"] = repaired["response_text"]
        proposal["needs_clarification"] = bool(repaired["needs_clarification"])
        proposal["clarification_questions"] = (
            [repaired["clarification_question"]] if repaired["needs_clarification"] else []
        )

        confidence = self._confidence_band_score(str(repaired.get("confidence_band") or "medium"))
        retrieval = proposal.get("retrieval")
        if not isinstance(retrieval, dict):
            retrieval = {"citation_ids": [], "confidence": confidence}
        retrieval["confidence"] = max(float(retrieval.get("confidence", 0.0)), confidence)
        proposal["retrieval"] = retrieval

        actions: list[dict[str, Any]] = []
        tool_name = str(repaired.get("tool_name") or "none")
        tool_arg = str(repaired.get("tool_arg") or "").strip()
        if not proposal["needs_clarification"] and tool_name != "none":
            if tool_name == "keypress":
                key = self._normalize_keypress_arg(tool_arg)
                if key:
                    actions.append(
                        {
                            "action_id": "a1",
                            "tool_name": "keypress",
                            "parameters": {"key": key},
                            "safety_level": "high_risk",
                            "mode_constraints": ["game"],
                            "requires_confirmation": True,
                            "timeout_ms": 1500,
                            "reason": f"User requested keypress '{key}'",
                            "confidence": confidence,
                        }
                    )
                else:
                    proposal["needs_clarification"] = True
                    proposal["clarification_questions"] = ["Which key should I press?"]
            elif tool_name == "set_lights":
                scene = tool_arg if tool_arg in {"default", "combat", "work", "standby"} else "default"
                actions.append(
                    {
                        "action_id": "a1",
                        "tool_name": "set_lights",
                        "parameters": {"scene": scene},
                        "safety_level": "low_risk",
                        "mode_constraints": ["game", "work", "standby", "tutor"],
                        "requires_confirmation": False,
                        "timeout_ms": 3000,
                        "reason": f"Set lights scene to '{scene}'",
                        "confidence": confidence,
                    }
                )
            elif tool_name == "music_next":
                actions.append(
                    {
                        "action_id": "a1",
                        "tool_name": "music_next",
                        "parameters": {},
                        "safety_level": "low_risk",
                        "mode_constraints": ["game", "work", "standby", "tutor"],
                        "requires_confirmation": False,
                        "timeout_ms": 1200,
                        "reason": "Advance music track",
                        "confidence": confidence,
                    }
                )
        proposal["proposed_actions"] = actions[:1]
        proposal["needs_tools"] = bool(proposal["proposed_actions"])
        if proposal["needs_clarification"]:
            proposal["proposed_actions"] = []
            proposal["needs_tools"] = False
        validate_intent_proposal(proposal)
        return proposal

    def _repair_proposal(self, proposal: dict[str, Any], fallback_proposal: dict[str, Any]) -> dict[str, Any]:
        repaired = dict(proposal) if isinstance(proposal, dict) else {}
        fallback = dict(fallback_proposal)

        scalar_fields = (
            "schema_version",
            "request_id",
            "timestamp_utc",
            "mode",
            "domain",
            "urgency",
            "user_text",
            "response_text",
            "session_id",
        )
        bool_fields = ("needs_tools", "needs_clarification")

        for field in scalar_fields:
            value = repaired.get(field)
            if not isinstance(value, str) or not value.strip():
                if field in fallback:
                    repaired[field] = fallback[field]
        for field in bool_fields:
            if not isinstance(repaired.get(field), bool):
                repaired[field] = bool(fallback.get(field, False))

        clarifications = repaired.get("clarification_questions")
        if not isinstance(clarifications, list):
            clarifications = list(fallback.get("clarification_questions", []))
        cleaned_questions = [str(q).strip() for q in clarifications if str(q).strip()][:3]
        repaired["clarification_questions"] = cleaned_questions

        retrieval = repaired.get("retrieval")
        if not isinstance(retrieval, dict):
            retrieval = dict(fallback.get("retrieval", {}))
        retrieval = {
            "citation_ids": list(retrieval.get("citation_ids", []))[:20]
            if isinstance(retrieval.get("citation_ids"), list)
            else list(fallback.get("retrieval", {}).get("citation_ids", [])),
            "confidence": float(retrieval.get("confidence", fallback.get("retrieval", {}).get("confidence", 0.4))),
        }
        if retrieval["confidence"] < 0:
            retrieval["confidence"] = 0.0
        if retrieval["confidence"] > 1:
            retrieval["confidence"] = 1.0
        repaired["retrieval"] = retrieval

        actions = repaired.get("proposed_actions")
        if not isinstance(actions, list):
            actions = list(fallback.get("proposed_actions", []))
        repaired["proposed_actions"] = [action for action in actions if isinstance(action, dict)][:10]

        allowed = set(self._contract.get("properties", {}).keys()) if isinstance(self._contract.get("properties"), dict) else set()
        if allowed:
            repaired = {key: value for key, value in repaired.items() if key in allowed}

        if not repaired.get("needs_tools"):
            repaired["proposed_actions"] = []
        if not repaired.get("needs_clarification"):
            repaired["clarification_questions"] = []
        return repaired

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

    def _safe_disengaged(self, fallback_proposal: dict[str, Any], reason: str) -> dict[str, Any]:
        proposal = dict(fallback_proposal)
        proposal["needs_tools"] = False
        proposal["needs_clarification"] = False
        proposal["clarification_questions"] = []
        proposal["proposed_actions"] = []
        proposal["response_text"] = "LLM is disengaged."
        retrieval = proposal.get("retrieval")
        if not isinstance(retrieval, dict):
            retrieval = {"citation_ids": [], "confidence": 0.0}
        retrieval["confidence"] = 0.0
        retrieval["llm_validation_error"] = reason[:300]
        proposal["retrieval"] = retrieval
        validate_intent_proposal(proposal)
        return proposal

    def _try_openai_fallback(
        self,
        *,
        prompt: str,
        fallback_proposal: dict[str, Any],
        prior_error: str,
        prior_meta: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not self._openai_fallback_enabled():
            return None, None
        try:
            raw_text, raw_meta = self._generate_raw_openai(prompt)
            parsed, parse_mode = self._extract_json_object(raw_text)
            if parsed is None:
                raise ValueError(f"openai_invalid_json:{parse_mode}")
            repaired = self._repair_proposal(parsed, fallback_proposal)
            self._validate_contract_shape(repaired)
            validate_intent_proposal(repaired)
            return repaired, {
                "provider": "openai",
                "mode": raw_meta.get("mode", "responses_structured"),
                "model": raw_meta.get("model"),
                "validation": "ok",
                "parse_mode": parse_mode,
                "fallback_from": prior_meta or {},
                "fallback_reason": prior_error,
            }
        except Exception as exc:
            return None, {
                "provider": "openai",
                "mode": "responses_structured",
                "validation": "fallback_failed",
                "error": str(exc),
                "fallback_reason": prior_error,
                "fallback_from": prior_meta or {},
            }

    def generate_intent_proposal(
        self,
        *,
        prompt: str,
        local_prompt: str | None = None,
        fallback_proposal: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        use_local_sketch = (
            self.raw_generator is None
            and self.mode in {"openvino_local", "native", "phi3_openvino"}
            and self.local_output_mode == "intent_sketch"
        )
        try:
            raw_text, raw_meta = self._generate_raw(
                local_prompt if use_local_sketch and local_prompt else prompt,
                fallback_proposal,
                json_schema=self._intent_sketch_contract if use_local_sketch else None,
            )
        except Exception as exc:
            if "not engaged" in str(exc).lower():
                safe = self._safe_disengaged(fallback_proposal, f"llm_disengaged:{exc}")
                return safe, {
                    "provider": "openvino_local",
                    "mode": self.mode,
                    "validation": "disengaged",
                    "error": str(exc),
                }
            proposal, meta = self._try_openai_fallback(
                prompt=prompt,
                fallback_proposal=fallback_proposal,
                prior_error=f"llm_request_error:{exc}",
                prior_meta={
                    "provider": "openvino_local",
                    "mode": self.mode,
                    "validation": "request_error",
                    "error": str(exc),
                },
            )
            if proposal is not None and meta is not None:
                return proposal, meta
            safe = self._safe_no_action(fallback_proposal, f"llm_request_error:{exc}")
            return safe, {
                "provider": "fail_safe",
                "mode": self.mode,
                "validation": "safe_fallback",
                "error": str(exc),
            }

        parsed, parse_mode = self._extract_json_object(raw_text)
        if parsed is None:
            proposal, meta = self._try_openai_fallback(
                prompt=prompt,
                fallback_proposal=fallback_proposal,
                prior_error="invalid_json",
                prior_meta=raw_meta | {"validation": "invalid_json", "parse_mode": parse_mode},
            )
            if proposal is not None and meta is not None:
                return proposal, meta
            safe = self._safe_no_action(fallback_proposal, "invalid_json")
            return safe, raw_meta | {"validation": "safe_fallback", "parse_mode": parse_mode}

        if use_local_sketch:
            try:
                self._validate_intent_sketch_shape(parsed)
                repaired_sketch = self._repair_intent_sketch(parsed)
                proposal = self._map_intent_sketch_to_proposal(repaired_sketch, fallback_proposal)
                return proposal, raw_meta | {
                    "validation": "ok",
                    "parse_mode": parse_mode,
                    "output_contract": "intent_sketch",
                }
            except Exception as exc:
                proposal, meta = self._try_openai_fallback(
                    prompt=prompt,
                    fallback_proposal=fallback_proposal,
                    prior_error=f"intent_sketch_error:{exc}",
                    prior_meta=raw_meta | {
                        "validation": "repair_failed",
                        "parse_mode": parse_mode,
                        "error": str(exc),
                        "output_contract": "intent_sketch",
                    },
                )
                if proposal is not None and meta is not None:
                    return proposal, meta
                safe = self._safe_no_action(fallback_proposal, f"intent_sketch_error:{exc}")
                return safe, raw_meta | {
                    "validation": "safe_fallback",
                    "parse_mode": parse_mode,
                    "error": str(exc),
                    "output_contract": "intent_sketch",
                }

        try:
            self._validate_contract_shape(parsed)
            validate_intent_proposal(parsed)
            return parsed, raw_meta | {"validation": "ok", "parse_mode": parse_mode}
        except Exception as exc:
            try:
                repaired = self._repair_proposal(parsed, fallback_proposal)
                self._validate_contract_shape(repaired)
                validate_intent_proposal(repaired)
                return repaired, raw_meta | {
                    "validation": "repaired",
                    "parse_mode": parse_mode,
                    "error": str(exc),
                }
            except Exception:
                proposal, meta = self._try_openai_fallback(
                    prompt=prompt,
                    fallback_proposal=fallback_proposal,
                    prior_error=f"schema_validation_error:{exc}",
                    prior_meta=raw_meta | {
                        "validation": "repair_failed",
                        "parse_mode": parse_mode,
                        "error": str(exc),
                    },
                )
                if proposal is not None and meta is not None:
                    return proposal, meta
                safe = self._safe_no_action(fallback_proposal, f"schema_validation_error:{exc}")
                return safe, raw_meta | {
                    "validation": "safe_fallback",
                    "parse_mode": parse_mode,
                    "error": str(exc),
                }
