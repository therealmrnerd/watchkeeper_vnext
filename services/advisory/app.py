import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ROOT_DIR = Path(__file__).resolve().parents[2]
for p in (THIS_DIR, ROOT_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from llm_client import LLMClient
from retrieval import RetrievalPackBuilder
from router import (
    apply_expert_action_permissions,
    build_assist_prompt,
    build_fallback_proposal,
    select_expert_profile,
)


HOST = os.getenv("WKV_ADVISORY_HOST", "127.0.0.1")
PORT = int(os.getenv("WKV_ADVISORY_PORT", "8790"))
RETRIEVAL_BUILDER = RetrievalPackBuilder()
LLM_CLIENT = LLMClient()


class AdvisoryHandler(BaseHTTPRequestHandler):
    server_version = "WatchkeeperAdvisory/0.1"

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("request body is required")
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(parsed, dict):
            raise ValueError("JSON body must be an object")
        return parsed

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "advisory",
                    "mode": "stub",
                },
            )
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/assist":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        try:
            body = self._read_json_body()
            expert_profile = select_expert_profile(body)
            context_pack = RETRIEVAL_BUILDER.build(
                request_id=str(body.get("request_id") or ""),
                user_text=str(body.get("user_text") or ""),
                mode=str(body.get("mode") or "standby"),
                domain=str(body.get("domain") or "general"),
                retrieval_domains=list(expert_profile.get("retrieval_domains", [])),
            )
            fallback_proposal = build_fallback_proposal(body, context_pack, expert_profile)
            prompt = build_assist_prompt(body, context_pack, expert_profile)
            proposal, llm_meta = LLM_CLIENT.generate_intent_proposal(
                prompt=prompt,
                fallback_proposal=fallback_proposal,
            )
            proposal, dropped_count = apply_expert_action_permissions(proposal, expert_profile)

            retrieval = proposal.get("retrieval")
            if not isinstance(retrieval, dict):
                retrieval = {}
            retrieval.setdefault("citation_ids", list(context_pack.get("citations", [])))
            retrieval.setdefault("confidence", 0.4)
            retrieval["expert_id"] = expert_profile.get("expert_id")
            retrieval["allow_actions"] = bool(expert_profile.get("allow_actions", True))
            retrieval["retrieval_domains"] = list(expert_profile.get("retrieval_domains", []))
            retrieval["context_pack_metadata"] = context_pack.get("metadata", {})
            retrieval["dropped_actions_by_expert"] = dropped_count
            proposal["retrieval"] = retrieval

            self._send_json(
                200,
                {
                    "ok": True,
                    "provider": llm_meta.get("provider", "stub_local"),
                    "proposal": proposal,
                    "meta": {
                        "expert": expert_profile,
                        "llm": llm_meta,
                        "context_pack": context_pack.get("metadata", {}),
                        "prompt_chars": len(prompt),
                    },
                },
            )
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), AdvisoryHandler)
    print(f"Advisory API listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
