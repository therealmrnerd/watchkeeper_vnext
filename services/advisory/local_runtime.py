from __future__ import annotations

import gc
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class OpenVinoLocalRuntime:
    def __init__(
        self,
        *,
        model_dir: str | Path | None = None,
        device: str | None = None,
        tokenizer_loader: Callable[..., Any] | None = None,
        model_loader: Callable[..., Any] | None = None,
        gc_hook: Callable[[], None] | None = None,
    ) -> None:
        self.model_dir = Path(model_dir or os.getenv("WK_PHI3_DIR", "")).expanduser()
        self.device = (device or os.getenv("WKV_ADVISORY_MODEL_DEVICE", "GPU")).strip() or "GPU"
        self.tokenizer_loader = tokenizer_loader
        self.model_loader = model_loader
        self.gc_hook = gc_hook or gc.collect
        self._lock = threading.RLock()
        self._infer_lock = threading.Lock()
        self._tokenizer: Any = None
        self._model: Any = None
        self._loaded = False
        self._loading = False
        self._last_loaded_at: str | None = None
        self._last_unloaded_at: str | None = None
        self._last_error: str | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "loaded": bool(self._loaded and self._model is not None and self._tokenizer is not None),
                "loading": bool(self._loading),
                "device": self.device,
                "model_dir": str(self.model_dir),
                "model_dir_exists": self.model_dir.exists(),
                "last_loaded_at": self._last_loaded_at,
                "last_unloaded_at": self._last_unloaded_at,
                "last_error": self._last_error,
            }

    def engage(self) -> dict[str, Any]:
        with self._lock:
            if self._loaded and self._model is not None and self._tokenizer is not None:
                return self.status()
            self._loading = True
            self._last_error = None
        try:
            tokenizer_loader = self.tokenizer_loader
            model_loader = self.model_loader
            if tokenizer_loader is None or model_loader is None:
                from transformers import AutoTokenizer
                from optimum.intel.openvino import OVModelForCausalLM

                tokenizer_loader = AutoTokenizer.from_pretrained
                model_loader = OVModelForCausalLM.from_pretrained

            tokenizer = tokenizer_loader(str(self.model_dir), trust_remote_code=True)
            model = model_loader(str(self.model_dir), device=self.device)
        except Exception as exc:
            with self._lock:
                self._tokenizer = None
                self._model = None
                self._loaded = False
                self._loading = False
                self._last_error = str(exc)
            raise RuntimeError(f"local model load failed: {exc}") from exc

        with self._lock:
            self._tokenizer = tokenizer
            self._model = model
            self._loaded = True
            self._loading = False
            self._last_loaded_at = _utc_now_iso()
            self._last_error = None
            return self.status()

    def disengage(self) -> dict[str, Any]:
        with self._lock:
            self._tokenizer = None
            self._model = None
            self._loaded = False
            self._loading = False
            self._last_unloaded_at = _utc_now_iso()
        try:
            self.gc_hook()
        except Exception:
            pass
        return self.status()

    def generate(
        self,
        *,
        prompt: str,
        max_new_tokens: int = 256,
        temperature: float = 0.2,
        top_p: float = 0.9,
    ) -> tuple[str, dict[str, Any]]:
        with self._lock:
            tokenizer = self._tokenizer
            model = self._model
            loaded = self._loaded
        if not loaded or tokenizer is None or model is None:
            raise RuntimeError("local model is not engaged")

        started = time.perf_counter()
        try:
            with self._infer_lock:
                inputs = tokenizer(prompt, return_tensors="pt")
                input_ids = inputs.get("input_ids")
                prompt_token_count = int(getattr(input_ids, "shape", [0, 0])[-1]) if input_ids is not None else 0
                pad_token_id = getattr(tokenizer, "pad_token_id", None) or getattr(tokenizer, "eos_token_id", None)
                do_sample = float(temperature) > 0.0
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=int(max_new_tokens),
                    temperature=float(temperature),
                    top_p=float(top_p),
                    do_sample=do_sample,
                    pad_token_id=pad_token_id,
                    eos_token_id=getattr(tokenizer, "eos_token_id", None),
                )
                sequence = outputs[0]
                generated_ids = sequence[prompt_token_count:] if prompt_token_count > 0 else sequence
                reply = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
                if reply.startswith(prompt):
                    reply = reply[len(prompt) :].strip()
                if not reply:
                    full_text = tokenizer.decode(sequence, skip_special_tokens=True)
                    reply = full_text[len(prompt) :].strip() if full_text.startswith(prompt) else full_text.strip()
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            raise RuntimeError(f"local generation failed: {exc}") from exc

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return reply, {"provider": "openvino_local", "latency_ms": elapsed_ms, "device": self.device}
