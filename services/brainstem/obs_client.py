from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import time
from typing import Any


OBS_HOST = os.getenv("WKV_OBS_HOST", "127.0.0.1").strip() or "127.0.0.1"
OBS_PORT = int(os.getenv("WKV_OBS_PORT", "4455"))
OBS_TIMEOUT_SEC = max(0.5, float(os.getenv("WKV_OBS_TIMEOUT_SEC", "2.5")))


class ObsWebsocketError(RuntimeError):
    pass


def _recv_until(sock: socket.socket, marker: bytes) -> bytes:
    data = b""
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ObsWebsocketError("socket closed before payload was complete")
        data += chunk
    return data


class ObsWebsocketClient:
    def __init__(self, host: str = OBS_HOST, port: int = OBS_PORT, timeout_sec: float = OBS_TIMEOUT_SEC) -> None:
        self.host = str(host or OBS_HOST).strip() or OBS_HOST
        self.port = int(port or OBS_PORT)
        self.timeout_sec = float(timeout_sec or OBS_TIMEOUT_SEC)
        self.sock: socket.socket | None = None

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout_sec)
        sock.settimeout(self.timeout_sec)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        sock.sendall(request)
        response = _recv_until(sock, b"\r\n\r\n")
        if b"101 Switching Protocols" not in response:
            raise ObsWebsocketError(f"websocket handshake failed: {response!r}")

        accept = None
        for line in response.decode("latin1", errors="replace").split("\r\n"):
            if line.lower().startswith("sec-websocket-accept:"):
                accept = line.split(":", 1)[1].strip()
                break
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if accept != expected:
            raise ObsWebsocketError("websocket handshake accept mismatch")
        self.sock = sock

    def close(self) -> None:
        sock = self.sock
        self.sock = None
        if sock is None:
            return
        try:
            self._send_json({"op": 8, "d": {}})
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass

    def _send_json(self, payload: dict[str, Any]) -> None:
        if self.sock is None:
            raise ObsWebsocketError("socket not connected")
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        frame = bytearray()
        frame.append(0x81)
        length = len(raw)
        if length < 126:
            frame.append(0x80 | length)
        elif length < (1 << 16):
            frame.append(0x80 | 126)
            frame.extend(struct.pack("!H", length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        frame.extend(mask)
        frame.extend(bytes(byte ^ mask[idx % 4] for idx, byte in enumerate(raw)))
        self.sock.sendall(bytes(frame))

    def _recv_json(self) -> dict[str, Any]:
        if self.sock is None:
            raise ObsWebsocketError("socket not connected")
        header = _recv_exact(self.sock, 2)
        b1, b2 = header[0], header[1]
        opcode = b1 & 0x0F
        masked = (b2 & 0x80) != 0
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", _recv_exact(self.sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _recv_exact(self.sock, 8))[0]
        mask = _recv_exact(self.sock, 4) if masked else b""
        payload = _recv_exact(self.sock, length)
        if masked:
            payload = bytes(byte ^ mask[idx % 4] for idx, byte in enumerate(payload))
        if opcode == 0x8:
            raise ObsWebsocketError("obs websocket closed the connection")
        if opcode != 0x1:
            raise ObsWebsocketError(f"unexpected websocket opcode {opcode}")
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise ObsWebsocketError(f"invalid websocket json payload: {exc}") from exc
        if not isinstance(decoded, dict):
            raise ObsWebsocketError("invalid websocket message shape")
        return decoded

    def identify(self) -> dict[str, Any]:
        hello = self._recv_json()
        if int(hello.get("op", -1)) != 0:
            raise ObsWebsocketError("did not receive OBS Hello frame")
        data = hello.get("d") if isinstance(hello.get("d"), dict) else {}
        identify_payload = {
            "op": 1,
            "d": {
                "rpcVersion": int(data.get("rpcVersion", 1) or 1),
            },
        }
        auth = data.get("authentication") if isinstance(data.get("authentication"), dict) else None
        if auth:
            raise ObsWebsocketError("obs websocket requires authentication")
        self._send_json(identify_payload)
        identified = self._recv_json()
        if int(identified.get("op", -1)) != 2:
            raise ObsWebsocketError("did not receive OBS Identified frame")
        return data

    def request(self, request_type: str, request_data: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = f"{request_type}-{int(time.time() * 1000)}"
        payload: dict[str, Any] = {
            "op": 6,
            "d": {
                "requestType": request_type,
                "requestId": request_id,
            },
        }
        if request_data:
            payload["d"]["requestData"] = request_data
        self._send_json(payload)
        while True:
            message = self._recv_json()
            if int(message.get("op", -1)) != 7:
                continue
            data = message.get("d") if isinstance(message.get("d"), dict) else {}
            if data.get("requestId") == request_id:
                return data


def fetch_obs_status(host: str = OBS_HOST, port: int = OBS_PORT, timeout_sec: float = OBS_TIMEOUT_SEC) -> dict[str, Any]:
    client = ObsWebsocketClient(host=host, port=port, timeout_sec=timeout_sec)
    started = time.time()
    try:
        client.connect()
        hello = client.identify()
        latency_ms = int((time.time() - started) * 1000)

        version = client.request("GetVersion")
        stats = client.request("GetStats")
        stream_status = client.request("GetStreamStatus")
        record_status = client.request("GetRecordStatus")
        studio_mode = client.request("GetStudioModeEnabled")
        program_scene = client.request("GetCurrentProgramScene")
        preview_scene = client.request("GetCurrentPreviewScene")

        version_data = version.get("responseData") if isinstance(version.get("responseData"), dict) else {}
        stats_data = stats.get("responseData") if isinstance(stats.get("responseData"), dict) else {}
        stream_data = stream_status.get("responseData") if isinstance(stream_status.get("responseData"), dict) else {}
        record_data = record_status.get("responseData") if isinstance(record_status.get("responseData"), dict) else {}
        studio_data = studio_mode.get("responseData") if isinstance(studio_mode.get("responseData"), dict) else {}
        program_data = program_scene.get("responseData") if isinstance(program_scene.get("responseData"), dict) else {}
        preview_ok = bool(preview_scene.get("requestStatus", {}).get("result"))
        preview_data = preview_scene.get("responseData") if isinstance(preview_scene.get("responseData"), dict) else {}

        return {
            "ok": True,
            "status": "up",
            "endpoint": {
                "host": host,
                "port": int(port),
                "latency_ms": latency_ms,
            },
            "versions": {
                "obs_studio": version_data.get("obsVersion") or hello.get("obsStudioVersion"),
                "obs_websocket": version_data.get("obsWebSocketVersion") or hello.get("obsWebSocketVersion"),
                "rpc_version": version_data.get("rpcVersion") or hello.get("rpcVersion"),
                "platform": version_data.get("platform"),
                "platform_description": version_data.get("platformDescription"),
            },
            "studio_mode_enabled": bool(studio_data.get("studioModeEnabled")),
            "scene": {
                "program": program_data.get("currentProgramSceneName") or program_data.get("sceneName"),
                "preview": (
                    preview_data.get("currentPreviewSceneName") or preview_data.get("sceneName")
                    if preview_ok
                    else None
                ),
            },
            "stream": {
                "active": bool(stream_data.get("outputActive")),
                "reconnecting": bool(stream_data.get("outputReconnecting")),
                "duration_ms": stream_data.get("outputDuration"),
                "congestion": stream_data.get("outputCongestion"),
                "skipped_frames": stream_data.get("outputSkippedFrames"),
                "total_frames": stream_data.get("outputTotalFrames"),
            },
            "record": {
                "active": bool(record_data.get("outputActive")),
                "paused": bool(record_data.get("outputPaused")),
                "duration_ms": record_data.get("outputDuration"),
            },
            "stats": {
                "active_fps": stats_data.get("activeFps"),
                "cpu_usage": stats_data.get("cpuUsage"),
                "memory_usage_mb": stats_data.get("memoryUsage"),
                "avg_frame_render_ms": stats_data.get("averageFrameRenderTime"),
                "render_skipped_frames": stats_data.get("renderSkippedFrames"),
                "render_total_frames": stats_data.get("renderTotalFrames"),
                "output_skipped_frames": stats_data.get("outputSkippedFrames"),
                "output_total_frames": stats_data.get("outputTotalFrames"),
                "disk_free_mb": stats_data.get("availableDiskSpace"),
            },
            "notes": [] if preview_ok else ["Preview scene unavailable because Studio Mode is off."],
        }
    except ObsWebsocketError as exc:
        return {
            "ok": False,
            "status": "needs_auth" if "authentication" in str(exc).lower() else "down",
            "endpoint": {"host": host, "port": int(port)},
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "down",
            "endpoint": {"host": host, "port": int(port)},
            "error": str(exc),
        }
    finally:
        client.close()
