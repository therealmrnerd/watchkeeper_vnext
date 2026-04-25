from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT_DIR / "models" / "llm"

PYTHON_CANDIDATES = (
    Path(r"C:\Users\chief\openvino_env\Scripts\python.exe"),
    Path(r"C:\ai\openvino_env\Scripts\python.exe"),
)

MODEL_ALIASES: dict[str, dict[str, str]] = {
    "phi3-mini-4k": {
        "path": str(MODELS_DIR / "phi3-mini-4k-int4-ov"),
    },
    "phi3-mini-128k": {
        "path": str(MODELS_DIR / "phi3-mini-128k-int4-ov"),
    },
    "qwen2.5-7b": {
        "path": str(MODELS_DIR / "qwen2.5-7b-instruct-ov-8bit"),
    },
    "qwen3-4b-int4": {
        "path": str(MODELS_DIR / "qwen3-4b-int4-ov"),
        "hf_model_id": "OpenVINO/Qwen3-4B-int4-ov",
    },
    "qwen3-1.7b-int4": {
        "path": str(MODELS_DIR / "qwen3-1.7b-int4-ov"),
        "hf_model_id": "OpenVINO/Qwen3-1.7B-int4-ov",
    },
}

PROMPTS = {
    "plain": "Reply with exactly: Watchkeeper online.",
    "regex": "Reply with exactly yes or no. Use yes.",
    "ebnf": "Reply with exactly yes or no. Use yes.",
    "json": "Return only a JSON object with a single field named intent. The intent must be ack.",
    "intent_sketch": (
        "Return only JSON for a minimal intent sketch. "
        "Use short values and prefer no actions unless needed."
    ),
}


def _pick_python() -> Path:
    python_env = os.getenv("WKV_ADVISORY_PYTHON", "").strip()
    python_exe = Path(python_env).expanduser() if python_env else None
    if python_exe and python_exe.exists():
        return python_exe
    for candidate in PYTHON_CANDIDATES:
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def _resolve_model(
    *,
    model: str,
    download_if_missing: bool,
    local_dir: str | None,
) -> tuple[Path, str | None]:
    alias = MODEL_ALIASES.get(model)
    if alias is not None:
        model_path = Path(local_dir or alias["path"]).expanduser().resolve()
        hf_model_id = alias.get("hf_model_id")
    else:
        model_path = Path(model).expanduser().resolve()
        hf_model_id = None

    if model_path.exists():
        return model_path, hf_model_id

    if not download_if_missing or not hf_model_id:
        raise FileNotFoundError(f"model directory not found: {model_path}")

    from huggingface_hub import snapshot_download  # type: ignore

    model_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=hf_model_id,
        local_dir=str(model_path),
        local_dir_use_symlinks=False,
        resume_download=True,
    )
    return model_path, hf_model_id


def _worker(
    *,
    model_path: Path,
    device: str,
    mode: str,
    iterations: int,
    max_new_tokens: int,
) -> int:
    import psutil  # type: ignore
    import openvino_genai as ovg  # type: ignore

    process = psutil.Process()
    rss_before = process.memory_info().rss

    load_started = time.perf_counter()
    pipeline = ovg.LLMPipeline(str(model_path), device)
    load_ms = int((time.perf_counter() - load_started) * 1000)
    rss_after_load = process.memory_info().rss

    config = ovg.GenerationConfig()
    config.max_new_tokens = int(max_new_tokens)
    config.do_sample = False

    structured = ovg.StructuredOutputConfig()
    if mode == "regex":
        structured.regex = r"(yes|no)"
        config.structured_output_config = structured
    elif mode == "ebnf":
        structured.grammar = 'root ::= "yes" | "no"'
        config.structured_output_config = structured
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
        config.structured_output_config = structured
    elif mode == "intent_sketch":
        structured.json_schema = json.dumps(
            {
                "type": "object",
                "properties": {
                    "reply_text": {"type": "string", "maxLength": 160},
                    "needs_tools": {"type": "boolean"},
                    "tool_name": {
                        "type": "string",
                        "enum": [
                            "",
                            "state.read",
                            "docs.read",
                            "vector.search",
                            "web.search",
                            "input.keypress",
                            "twitch.reply",
                        ],
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                },
                "required": ["reply_text", "needs_tools", "tool_name", "confidence"],
                "additionalProperties": False,
            },
            ensure_ascii=False,
        )
        config.structured_output_config = structured

    prompt = PROMPTS[mode]
    latencies: list[int] = []
    outputs: list[str] = []
    errors: list[str] = []
    json_valid_count = 0
    json_errors: list[str] = []

    for _ in range(iterations):
        started = time.perf_counter()
        try:
            text = str(pipeline.generate(prompt, config)).strip()
            latencies.append(int((time.perf_counter() - started) * 1000))
            outputs.append(text)
            if mode in {"json", "intent_sketch"}:
                try:
                    parsed = json.loads(text)
                    if mode == "json":
                        if not isinstance(parsed, dict) or parsed.get("intent") != "ack":
                            raise ValueError("json output did not match expected ack contract")
                    else:
                        required = {"reply_text", "needs_tools", "tool_name", "confidence"}
                        if not isinstance(parsed, dict) or not required.issubset(set(parsed.keys())):
                            raise ValueError("intent_sketch output missing required keys")
                    json_valid_count += 1
                except Exception as exc:
                    json_errors.append(str(exc))
        except Exception as exc:
            errors.append(str(exc))
            break

    rss_after_infer = process.memory_info().rss

    payload: dict[str, Any] = {
        "ok": not errors,
        "mode": mode,
        "device": device,
        "model": str(model_path),
        "load_ms": load_ms,
        "iterations": iterations,
        "rss_before_mb": round(rss_before / (1024 * 1024), 1),
        "rss_after_load_mb": round(rss_after_load / (1024 * 1024), 1),
        "rss_after_infer_mb": round(rss_after_infer / (1024 * 1024), 1),
        "samples": outputs[:3],
    }

    if latencies:
        payload.update(
            {
                "avg_infer_ms": round(sum(latencies) / len(latencies), 1),
                "min_infer_ms": min(latencies),
                "max_infer_ms": max(latencies),
                "median_infer_ms": statistics.median(latencies),
            }
        )
    if errors:
        payload["error"] = errors[0]
    if mode in {"json", "intent_sketch"}:
        payload["json_valid_count"] = json_valid_count
        payload["json_error"] = json_errors[0] if json_errors else None
        payload["structured_valid"] = json_valid_count == len(outputs) and not errors
        if not payload["structured_valid"]:
            payload["ok"] = False

    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _run_worker(
    *,
    model_path: Path,
    device: str,
    mode: str,
    iterations: int,
    max_new_tokens: int,
    timeout_s: int,
) -> dict[str, Any]:
    command = [
        str(_pick_python()),
        str(Path(__file__).resolve()),
        "--worker",
        "--model",
        str(model_path),
        "--device",
        device,
        "--mode",
        mode,
        "--iterations",
        str(iterations),
        "--max-new-tokens",
        str(max_new_tokens),
    ]
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "mode": mode,
            "status": "timeout",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "stdout": (exc.stdout or "")[-4000:],
            "stderr": (exc.stderr or "")[-4000:],
        }

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if result.returncode != 0:
        return {
            "ok": False,
            "mode": mode,
            "status": "worker_failed",
            "returncode": result.returncode,
            "elapsed_ms": elapsed_ms,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }

    try:
        payload = json.loads(result.stdout.strip())
    except Exception as exc:
        return {
            "ok": False,
            "mode": mode,
            "status": "invalid_json",
            "elapsed_ms": elapsed_ms,
            "error": str(exc),
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }

    if isinstance(payload, dict):
        payload.setdefault("elapsed_ms", elapsed_ms)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Generic OpenVINO model benchmark for A310 suitability checks.")
    parser.add_argument("--model", required=True, help="Model alias or local model path.")
    parser.add_argument("--device", default="GPU", help="OpenVINO device, default GPU.")
    parser.add_argument(
        "--modes",
        nargs="*",
        default=["plain", "intent_sketch"],
        choices=["plain", "regex", "ebnf", "json", "intent_sketch"],
        help="Generation modes to benchmark.",
    )
    parser.add_argument("--iterations", type=int, default=3, help="Inference iterations per mode.")
    parser.add_argument("--max-new-tokens", type=int, default=64, help="Max new tokens per generation.")
    parser.add_argument("--timeout-s", type=int, default=300, help="Worker timeout per mode.")
    parser.add_argument(
        "--download-if-missing",
        action="store_true",
        help="Download known alias from Hugging Face if the local path is missing.",
    )
    parser.add_argument(
        "--local-dir",
        default="",
        help="Override local download/storage directory for known aliases.",
    )
    parser.add_argument("--output", default="", help="Optional path to write JSON results.")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mode", default="plain", choices=["plain", "regex", "ebnf", "json", "intent_sketch"], help=argparse.SUPPRESS)
    args = parser.parse_args()

    model_path, hf_model_id = _resolve_model(
        model=args.model,
        download_if_missing=args.download_if_missing,
        local_dir=args.local_dir.strip() or None,
    )

    if args.worker:
        return _worker(
            model_path=model_path,
            device=args.device,
            mode=args.mode,  # type: ignore[attr-defined]
            iterations=args.iterations,
            max_new_tokens=args.max_new_tokens,
        )

    results = [
        _run_worker(
            model_path=model_path,
            device=args.device,
            mode=mode,
            iterations=args.iterations,
            max_new_tokens=args.max_new_tokens,
            timeout_s=args.timeout_s,
        )
        for mode in args.modes
    ]

    summary = {
        "ok": True,
        "model": args.model,
        "model_path": str(model_path),
        "hf_model_id": hf_model_id,
        "device": args.device,
        "results": results,
    }

    text = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
