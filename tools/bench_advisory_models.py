from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
ADVISORY_DIR = ROOT_DIR / "services" / "advisory"
for p in (ROOT_DIR, ADVISORY_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from llm_client import LLMClient
from local_runtime import OpenVinoLocalRuntime
from retrieval import RetrievalPackBuilder
from router import build_assist_prompt, build_fallback_proposal, select_expert_profile


MODEL_CANDIDATES = {
    "phi3-mini-4k": ROOT_DIR / "models" / "llm" / "phi3-mini-4k-int4-ov",
    "phi3-mini-128k": ROOT_DIR / "models" / "llm" / "phi3-mini-128k-int4-ov",
    "qwen2.5-7b": ROOT_DIR / "models" / "llm" / "qwen2.5-7b-instruct-ov-8bit",
    "qwen2.5-3b-int4": ROOT_DIR / "models" / "llm" / "qwen2.5-3b-instruct-int4-ov",
    "phi-4-mini-int4": ROOT_DIR / "models" / "llm" / "phi-4-mini-int4-ov",
}

PYTHON_CANDIDATES = (
    Path(r"C:\Users\chief\openvino_env\Scripts\python.exe"),
    Path(r"C:\ai\openvino_env\Scripts\python.exe"),
)

REQUEST_FIXTURES = [
    {
        "request_id": "bench-001",
        "mode": "standby",
        "domain": "general",
        "urgency": "normal",
        "user_text": "Reply with a short acknowledgement that Watchkeeper is online.",
        "max_actions": 1,
    },
    {
        "request_id": "bench-002",
        "mode": "game",
        "domain": "gameplay",
        "urgency": "normal",
        "user_text": "Press space for me.",
        "max_actions": 1,
    },
    {
        "request_id": "bench-003",
        "mode": "game",
        "domain": "system",
        "urgency": "normal",
        "user_text": "What do we know about the current system?",
        "max_actions": 1,
    },
]


def _build_request_payload(raw: dict[str, Any], index: int) -> dict[str, Any]:
    payload = dict(raw)
    payload.setdefault("schema_version", "1.0")
    payload.setdefault("timestamp_utc", "2026-03-02T00:00:00Z")
    payload["request_id"] = f"{payload['request_id']}-{index:02d}"
    return payload


def _run_worker(model_name: str, device: str, local_output_mode: str) -> dict[str, Any]:
    env = dict(os.environ)
    env["WKV_ADVISORY_LOCAL_OUTPUT_MODE"] = local_output_mode
    env.setdefault("WKV_ADVISORY_MAX_NEW_TOKENS", "96")
    env.setdefault("WKV_ADVISORY_TEMPERATURE", "0.0")
    python_env = os.getenv("WKV_ADVISORY_PYTHON", "").strip()
    python_exe = Path(python_env).expanduser() if python_env else Path()
    if not python_env or not python_exe.exists():
        python_exe = next((candidate for candidate in PYTHON_CANDIDATES if candidate.exists()), Path(sys.executable))
    command = [
        str(python_exe),
        str(Path(__file__).resolve()),
        "--worker",
        "--model",
        model_name,
        "--device",
        device,
        "--local-output-mode",
        local_output_mode,
    ]
    started = time.perf_counter()
    try:
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=300)
    except subprocess.TimeoutExpired as exc:
        return {
            "model": model_name,
            "status": "worker_timeout",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "stdout": (exc.stdout or "")[-4000:],
            "stderr": (exc.stderr or "")[-4000:],
        }
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if result.returncode != 0:
        return {
            "model": model_name,
            "status": "worker_failed",
            "returncode": result.returncode,
            "elapsed_ms": elapsed_ms,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }
    try:
        payload = json.loads(result.stdout.strip())
        if isinstance(payload, dict):
            payload.setdefault("elapsed_ms", elapsed_ms)
            return payload
    except Exception as exc:
        return {
            "model": model_name,
            "status": "worker_invalid_output",
            "elapsed_ms": elapsed_ms,
            "error": str(exc),
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }
    return {
        "model": model_name,
        "status": "worker_empty_output",
        "elapsed_ms": elapsed_ms,
    }


def _worker(model_name: str, device: str) -> int:
    model_dir = MODEL_CANDIDATES.get(model_name)
    if model_dir is None:
        print(json.dumps({"model": model_name, "status": "unknown_model"}))
        return 0
    if not model_dir.exists():
        print(json.dumps({"model": model_name, "path": str(model_dir), "status": "missing"}))
        return 0

    runtime = OpenVinoLocalRuntime(model_dir=model_dir, device=device)
    client = LLMClient(mode="openvino_local", local_runtime=runtime)
    local_output_mode = os.getenv("WKV_ADVISORY_LOCAL_OUTPUT_MODE", "intent_sketch").strip().lower() or "intent_sketch"
    client.local_output_mode = local_output_mode
    client._openai_fallback_enabled = lambda: False  # type: ignore[attr-defined]
    retrieval_builder = RetrievalPackBuilder()

    engage_started = time.perf_counter()
    runtime.engage()
    engage_ms = int((time.perf_counter() - engage_started) * 1000)

    cases: list[dict[str, Any]] = []
    latencies: list[int] = []
    ok_cases = 0
    safe_fallback_cases = 0

    try:
        for idx, raw_fixture in enumerate(REQUEST_FIXTURES, start=1):
            request_payload = _build_request_payload(raw_fixture, idx)
            expert_profile = select_expert_profile(request_payload)
            context_pack = retrieval_builder.build(
                request_id=request_payload["request_id"],
                user_text=request_payload["user_text"],
                mode=request_payload["mode"],
                domain=request_payload["domain"],
                retrieval_domains=list(expert_profile.get("retrieval_domains", [])),
            )
            fallback_proposal = build_fallback_proposal(request_payload, context_pack, expert_profile)
            proposal_prompt = build_assist_prompt(
                request_payload,
                context_pack,
                expert_profile,
                output_contract="intent_proposal",
            )
            local_prompt = build_assist_prompt(
                request_payload,
                context_pack,
                expert_profile,
                output_contract="intent_sketch",
            )
            case_started = time.perf_counter()
            proposal, meta = client.generate_intent_proposal(
                prompt=proposal_prompt,
                local_prompt=local_prompt,
                fallback_proposal=fallback_proposal,
            )
            case_latency_ms = int((time.perf_counter() - case_started) * 1000)
            latencies.append(case_latency_ms)

            validation = str(meta.get("validation") or "")
            if validation == "ok":
                ok_cases += 1
            if validation == "safe_fallback":
                safe_fallback_cases += 1

            cases.append(
                {
                    "request_id": request_payload["request_id"],
                    "validation": validation,
                    "provider": meta.get("provider"),
                    "parse_mode": meta.get("parse_mode"),
                    "output_contract": meta.get("output_contract"),
                    "latency_ms": case_latency_ms,
                    "needs_tools": proposal.get("needs_tools"),
                    "needs_clarification": proposal.get("needs_clarification"),
                    "action_count": len(proposal.get("proposed_actions", [])),
                }
            )
    finally:
        runtime.disengage()

    print(
        json.dumps(
            {
                "model": model_name,
                "path": str(model_dir),
                "status": "ok",
                "device": device,
                "local_output_mode": local_output_mode,
                "engage_ms": engage_ms,
                "average_case_latency_ms": int(sum(latencies) / len(latencies)) if latencies else None,
                "ok_cases": ok_cases,
                "safe_fallback_cases": safe_fallback_cases,
                "total_cases": len(cases),
                "cases": cases,
            }
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark local advisory models against IntentSketch generation.")
    parser.add_argument("--device", default="GPU", help="OpenVINO device, default GPU")
    parser.add_argument(
        "--local-output-mode",
        default="intent_sketch",
        choices=["intent_sketch", "intent_proposal"],
        help="intent_sketch uses GenAI structured decoding, intent_proposal keeps the existing prompt-only path",
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=list(MODEL_CANDIDATES.keys()),
        help="Model short names to benchmark",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--model", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        return _worker(args.model, args.device)

    results = [_run_worker(model_name, args.device, args.local_output_mode) for model_name in args.models]
    print(json.dumps({"ok": True, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
