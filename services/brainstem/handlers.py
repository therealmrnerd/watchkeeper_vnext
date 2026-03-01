import json
import mimetypes
import sqlite3
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from actions import (
    assist_with_advisory,
    execute_provider_query,
    execute_actions,
    ingest_state,
    ingest_twitch_mock,
    open_external_app,
    record_confirmation,
    record_feedback,
    save_inara_credentials,
    save_openai_credentials,
    save_runtime_settings_action,
    send_twitch_chat,
    upsert_intent,
)
from queries import (
    build_diag_bundle,
    query_current_system_bodies,
    query_events,
    query_log_files,
    query_log_tail,
    query_obs_status,
    query_current_system_provider,
    query_current_system_stations,
    query_inara_credentials,
    query_openai_credentials,
    query_providers_health,
    query_runtime_settings,
    query_sitrep,
    query_state,
    query_twitch_redeems_top,
    query_twitch_recent,
    query_twitch_user,
    resolve_diag_bundle,
)
from runtime import (
    EDPARSER_TOOL,
    STANDING_ORDERS_PATH,
    TWITCH_DEV_INGEST_ENABLED,
    TWITCH_UDP_ACK_ONLY,
    TWITCH_UDP_ENABLED,
    TWITCH_UDP_HOST,
    TWITCH_UDP_PORT,
    TWITCH_VARIABLE_INDEX_PATH,
    UI_DIR,
    connect_db,
    utc_now_iso,
)
from validators import (
    validate_assist_request,
    validate_confirm,
    validate_feedback,
    validate_inara_credentials_update,
    validate_intent,
    validate_openai_credentials_update,
    validate_provider_query,
    validate_runtime_settings_payload,
    validate_state_ingest,
)


class BrainstemHandler(BaseHTTPRequestHandler):
    server_version = "WatchkeeperBrainstem/0.2"

    def _send_bytes(
        self,
        status_code: int,
        body: bytes,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_text(
        self, status_code: int, text: str, content_type: str = "text/plain; charset=utf-8"
    ) -> None:
        self._send_bytes(status_code, text.encode("utf-8"), content_type)

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status_code, encoded, "application/json; charset=utf-8")

    def _send_file(self, file_path: Path, download_name: str | None = None) -> None:
        if not file_path.exists() or not file_path.is_file():
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        content = file_path.read_bytes()
        mime, _ = mimetypes.guess_type(str(file_path))
        if not mime:
            mime = "application/octet-stream"
        headers = {}
        if download_name:
            headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
        self._send_bytes(200, content, mime, headers)

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

    def _resolve_ui_path(self, path_value: str) -> Path | None:
        ui_root = Path(UI_DIR).resolve()
        if path_value in {"", "/"}:
            candidate = (ui_root / "index.html").resolve()
        elif path_value.startswith("/ui/"):
            rel = path_value[len("/ui/") :]
            candidate = (ui_root / rel).resolve()
        elif path_value.startswith("/") and "." in path_value.rsplit("/", 1)[-1]:
            rel = path_value.lstrip("/")
            candidate = (ui_root / rel).resolve()
        else:
            return None
        if not str(candidate).startswith(str(ui_root)):
            return None
        if not candidate.exists() or not candidate.is_file():
            return None
        return candidate

    def _stream_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        seen: set[str] = set()
        try:
            hello = {"ok": True, "ts": utc_now_iso(), "service": "brainstem"}
            self.wfile.write(f"event: hello\ndata: {json.dumps(hello, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()
            while True:
                events = query_events({"limit": ["40"]})
                to_send = []
                for item in reversed(events):
                    event_id = str(item.get("event_id") or "")
                    if not event_id:
                        continue
                    if event_id in seen:
                        continue
                    seen.add(event_id)
                    to_send.append(item)
                if len(seen) > 500:
                    seen = set(list(seen)[-250:])

                for event in to_send:
                    payload = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"event: event\ndata: {payload}\n\n".encode("utf-8"))
                self.wfile.write(f"event: ping\ndata: {json.dumps({'ts': utc_now_iso()})}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            return

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        try:
            is_root_asset = parsed.path.startswith("/") and "." in parsed.path.rsplit("/", 1)[-1]
            if parsed.path in {"/", "/ui", "/ui/"} or parsed.path.startswith("/ui/") or is_root_asset:
                ui_file = self._resolve_ui_path(parsed.path)
                if ui_file is None:
                    if parsed.path in {"/", "/ui", "/ui/"} or parsed.path.startswith("/ui/"):
                        self._send_json(404, {"ok": False, "error": "not_found"})
                        return
                else:
                    self._send_file(ui_file)
                    return

            if parsed.path == "/health":
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "service": "brainstem",
                        "ts": utc_now_iso(),
                        "standing_orders_path": str(STANDING_ORDERS_PATH),
                        "edparser": EDPARSER_TOOL.status(),
                        "twitch_udp": {
                            "enabled": TWITCH_UDP_ENABLED,
                            "host": TWITCH_UDP_HOST,
                            "port": TWITCH_UDP_PORT,
                            "ack_only": TWITCH_UDP_ACK_ONLY,
                            "variable_index_path": str(TWITCH_VARIABLE_INDEX_PATH),
                        },
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

            if parsed.path == "/events/stream":
                self._stream_events()
                return

            if parsed.path == "/sitrep":
                payload = query_sitrep(query)
                self._send_json(200, payload)
                return

            if parsed.path == "/providers/health":
                self._send_json(200, query_providers_health(query))
                return

            if parsed.path == "/providers/inara/credentials":
                self._send_json(200, query_inara_credentials(query))
                return

            if parsed.path == "/config/openai/credentials":
                self._send_json(200, query_openai_credentials(query))
                return

            if parsed.path == "/settings":
                self._send_json(200, query_runtime_settings(query))
                return

            if parsed.path == "/obs/status":
                self._send_json(200, query_obs_status(query))
                return

            if parsed.path == "/providers/current-system":
                self._send_json(200, query_current_system_provider(query))
                return

            if parsed.path == "/providers/current-system/bodies":
                self._send_json(200, query_current_system_bodies(query))
                return

            if parsed.path == "/providers/current-system/stations":
                self._send_json(200, query_current_system_stations(query))
                return

            if parsed.path == "/logs/files":
                self._send_json(200, query_log_files())
                return

            if parsed.path == "/logs/tail":
                self._send_json(200, query_log_tail(query))
                return

            if parsed.path == "/diag/bundle":
                payload = build_diag_bundle()
                self._send_json(200, payload)
                return

            if parsed.path.startswith("/twitch/user/"):
                suffix = parsed.path[len("/twitch/user/") :]
                if suffix.endswith("/redeems/top"):
                    user_id = unquote(suffix[: -len("/redeems/top")]).strip("/")
                    limit_raw = (query.get("limit", ["5"])[0] or "5").strip()
                    try:
                        limit = max(1, min(50, int(limit_raw)))
                    except ValueError:
                        raise ValueError("limit must be an integer")
                    self._send_json(200, query_twitch_redeems_top(user_id, limit=limit))
                    return
                user_id = unquote(suffix).strip("/")
                self._send_json(200, query_twitch_user(user_id, redeem_limit=5))
                return

            if parsed.path == "/twitch/recent":
                self._send_json(200, query_twitch_recent(query))
                return

            if parsed.path.startswith("/diag/bundle/"):
                bundle_name = parsed.path.split("/diag/bundle/", 1)[1]
                bundle_path = resolve_diag_bundle(bundle_name)
                self._send_file(bundle_path, download_name=bundle_path.name)
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

            if parsed.path == "/assist":
                body = self._read_json_body()
                validate_assist_request(body)
                result = assist_with_advisory(body, source=source)
                self._send_json(200, {"ok": True, **result})
                return

            if parsed.path == "/providers/query":
                body = self._read_json_body()
                validate_provider_query(body)
                result = execute_provider_query(body, source=source)
                self._send_json(200, result)
                return

            if parsed.path == "/providers/inara/credentials":
                body = self._read_json_body()
                validate_inara_credentials_update(body)
                result = save_inara_credentials(body, source=source)
                self._send_json(200, result)
                return

            if parsed.path == "/config/openai/credentials":
                body = self._read_json_body()
                validate_openai_credentials_update(body)
                result = save_openai_credentials(body, source=source)
                self._send_json(200, result)
                return

            if parsed.path == "/settings":
                body = self._read_json_body()
                validate_runtime_settings_payload(body)
                result = save_runtime_settings_action(body, source=source)
                self._send_json(200, result)
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

            if parsed.path == "/diag/bundle":
                payload = build_diag_bundle()
                self._send_json(200, payload)
                return

            if parsed.path == "/twitch/dev/ingest_mock":
                if not TWITCH_DEV_INGEST_ENABLED:
                    raise ValueError("twitch dev ingest endpoint is disabled")
                body = self._read_json_body()
                result = ingest_twitch_mock(body, source=source)
                self._send_json(200, {"ok": True, **result})
                return

            if parsed.path == "/twitch/send_chat":
                body = self._read_json_body()
                result = send_twitch_chat(body, source=source)
                self._send_json(200, {"ok": True, **result})
                return

            if parsed.path == "/app/open":
                body = self._read_json_body()
                result = open_external_app(body, source=source)
                self._send_json(200, {"ok": True, **result})
                return

            self._send_json(404, {"ok": False, "error": "not_found"})
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except sqlite3.IntegrityError as exc:
            self._send_json(409, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})
