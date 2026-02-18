import json
import sqlite3
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

from actions import (
    execute_actions,
    ingest_state,
    record_confirmation,
    record_feedback,
    upsert_intent,
)
from queries import query_events, query_state
from runtime import EDPARSER_TOOL, STANDING_ORDERS_PATH, connect_db, utc_now_iso
from validators import (
    validate_confirm,
    validate_feedback,
    validate_intent,
    validate_state_ingest,
)


class BrainstemHandler(BaseHTTPRequestHandler):
    server_version = "WatchkeeperBrainstem/0.1"

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
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        try:
            if parsed.path == "/health":
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "service": "brainstem",
                        "ts": utc_now_iso(),
                        "standing_orders_path": str(STANDING_ORDERS_PATH),
                        "edparser": EDPARSER_TOOL.status(),
                    },
                )
                return

            if parsed.path == "/state":
                items = query_state(query)
                self._send_json(200, {"ok": True, "count": len(items), "items": items})
                return

            if parsed.path == "/events":
                items = query_events(query)
                self._send_json(200, {"ok": True, "count": len(items), "items": items})
                return

            self._send_json(404, {"ok": False, "error": "not_found"})
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        source = self.headers.get("X-Source", "brainstem_api")

        try:
            if parsed.path == "/state":
                body = self._read_json_body()
                validate_state_ingest(body)
                result = ingest_state(body, source=source)
                self._send_json(200, {"ok": True, **result})
                return

            if parsed.path == "/intent":
                body = self._read_json_body()
                validate_intent(body)
                with connect_db() as con:
                    action_count = upsert_intent(con, body, source=source)
                    con.commit()
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "request_id": body["request_id"],
                        "queued_actions": action_count,
                    },
                )
                return

            if parsed.path == "/execute":
                body = self._read_json_body()
                result = execute_actions(body, source=source)
                self._send_json(200, {"ok": True, **result})
                return

            if parsed.path == "/confirm":
                body = self._read_json_body()
                validate_confirm(body)
                result = record_confirmation(body, source=source)
                self._send_json(200, {"ok": True, **result})
                return

            if parsed.path == "/feedback":
                body = self._read_json_body()
                validate_feedback(body)
                result = record_feedback(body, source=source)
                self._send_json(200, {"ok": True, **result})
                return

            self._send_json(404, {"ok": False, "error": "not_found"})
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except sqlite3.IntegrityError as exc:
            self._send_json(409, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})
