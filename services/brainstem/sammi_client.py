import json
import time
from typing import Any
from urllib import parse, request


class SammiClient:
    def __init__(
        self,
        *,
        enabled: bool,
        host: str,
        port: int,
        password: str,
        timeout_sec: float = 0.8,
    ) -> None:
        self.enabled = bool(enabled)
        self.host = str(host or "127.0.0.1").strip() or "127.0.0.1"
        self.port = int(port)
        self.password = str(password or "").strip()
        self.timeout_sec = max(0.1, float(timeout_sec))

    def _headers(self, with_json: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {}
        if with_json:
            headers["Content-Type"] = "application/json"
        if self.password:
            headers["Authorization"] = self.password
        return headers

    @property
    def api_base(self) -> str:
        return f"http://{self.host}:{self.port}/api"

    def get_var(self, name: str) -> Any | None:
        if not self.enabled:
            return None
        key = str(name or "").strip()
        if not key:
            return None
        query = parse.urlencode({"request": "getVariable", "name": key})
        url = f"{self.api_base}?{query}"
        req = request.Request(url, method="GET", headers=self._headers(with_json=False))
        started = time.time()
        try:
            with request.urlopen(req, timeout=self.timeout_sec) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(text) if text else {}
            _latency_ms = int((time.time() - started) * 1000)
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                for field in ("value", "result", "variable"):
                    if field in data:
                        return data.get(field)
            return data
        except Exception:
            return None

    def get_vars(self, names: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if not self.enabled:
            return out
        for raw_name in names:
            name = str(raw_name or "").strip()
            if not name:
                continue
            out[name] = self.get_var(name)
        return out

    def call(self, request_name: str, params: dict[str, Any] | None = None) -> tuple[bool, Any]:
        if not self.enabled:
            return False, "sammi_disabled"
        req_name = str(request_name or "").strip()
        if not req_name:
            return False, "request_name_required"

        body = {"request": req_name}
        if isinstance(params, dict):
            body.update(params)
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.api_base,
            data=raw,
            method="POST",
            headers=self._headers(with_json=True),
        )
        started = time.time()
        try:
            with request.urlopen(req, timeout=self.timeout_sec) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(text) if text else {}
            latency_ms = int((time.time() - started) * 1000)
            return True, {"response": payload, "latency_ms": latency_ms}
        except Exception as exc:
            return False, str(exc)
