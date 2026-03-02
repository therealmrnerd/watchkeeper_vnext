from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def build_prompt(mode: str) -> str:
    if mode == "json":
        return (
            "Return only a JSON object with one field named intent. "
            "The intent must be ack."
        )
    if mode in {"regex", "ebnf"}:
        return "Reply with exactly yes or no. Use yes."
    return "Reply with exactly: Watchkeeper online."


def apply_constraint(mode: str, ovg: object, config: object) -> None:
    if mode == "plain":
        return

    structured = ovg.StructuredOutputConfig()
    if mode == "regex":
        structured.regex = r"(yes|no)"
    elif mode == "ebnf":
        structured.grammar = 'root ::= "yes" | "no"'
    elif mode == "json":
        structured.json_schema = json.dumps(
            {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": ["ack"],
                    }
                },
                "required": ["intent"],
                "additionalProperties": False,
            },
            ensure_ascii=False,
        )
    else:
        raise ValueError(f"unsupported mode: {mode}")
    config.structured_output_config = structured


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal OpenVINO GenAI structured decode repro.")
    parser.add_argument("--model", required=True, help="Path to OpenVINO model directory")
    parser.add_argument("--device", default="GPU", help="OpenVINO device, default GPU")
    parser.add_argument(
        "--mode",
        choices=("plain", "regex", "ebnf", "json"),
        required=True,
        help="Constraint mode to test",
    )
    parser.add_argument("--max-new-tokens", type=int, default=32)
    args = parser.parse_args()

    model_dir = Path(args.model).expanduser().resolve()
    if not model_dir.exists():
        raise SystemExit(f"model directory not found: {model_dir}")

    import openvino_genai as ovg  # type: ignore

    started = time.perf_counter()
    pipeline = ovg.LLMPipeline(str(model_dir), args.device)
    load_ms = int((time.perf_counter() - started) * 1000)

    config = ovg.GenerationConfig()
    config.max_new_tokens = int(args.max_new_tokens)
    config.do_sample = False
    apply_constraint(args.mode, ovg, config)

    prompt = build_prompt(args.mode)
    infer_started = time.perf_counter()
    text = str(pipeline.generate(prompt, config)).strip()
    infer_ms = int((time.perf_counter() - infer_started) * 1000)

    print(
        json.dumps(
            {
                "ok": True,
                "mode": args.mode,
                "device": args.device,
                "model": str(model_dir),
                "load_ms": load_ms,
                "infer_ms": infer_ms,
                "text": text,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
