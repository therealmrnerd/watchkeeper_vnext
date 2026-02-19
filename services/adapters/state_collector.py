import ctypes
import hashlib
import json
import os
import re
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


ROOT_DIR = Path(__file__).resolve().parents[2]
BRAINSTEM_BASE_URL = os.getenv("WKV_BRAINSTEM_URL", "http://127.0.0.1:8787").rstrip("/")
PROFILE = os.getenv("WKV_PROFILE", "watchkeeper")
SESSION_ID = os.getenv("WKV_COLLECTOR_SESSION", "collector-main")
NOW_PLAYING_DIR = Path(
    os.getenv("WKV_NOW_PLAYING_DIR", str(ROOT_DIR / "data" / "now-playing"))
)
NOW_PLAYING_FALLBACK_DIR_RAW = os.getenv("WKV_NOW_PLAYING_FALLBACK_DIR", "").strip()
NOW_PLAYING_FALLBACK_DIR = (
    Path(NOW_PLAYING_FALLBACK_DIR_RAW).expanduser() if NOW_PLAYING_FALLBACK_DIR_RAW else None
)
YTMD_ENABLED = os.getenv("WKV_YTMD_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
YTMD_HOST = os.getenv("WKV_YTMD_HOST", "127.0.0.1").strip() or "127.0.0.1"
YTMD_PORT = int(os.getenv("WKV_YTMD_PORT", "9863"))
YTMD_TIMEOUT_SEC = float(os.getenv("WKV_YTMD_TIMEOUT_SEC", "2.0"))
YTMD_REST_POLL_MS = int(os.getenv("WKV_YTMD_REST_POLL_MS", "5000"))
YTMD_TOKEN_FILE = Path(os.getenv("WKV_YTMD_TOKEN_FILE", str(ROOT_DIR / "ytm-token.json")))
YTMD_LEGACY_TOKEN_FILE = Path(
    os.getenv("WKV_YTMD_LEGACY_TOKEN_FILE", r"C:\ai\Watchkeeper\ytm-token.json")
)
YTMD_RATE_LIMIT_BACKOFF_SEC_DEFAULT = int(os.getenv("WKV_YTMD_BACKOFF_SEC", "30"))
YTMD_PROCESS_NAMES = [
    p.strip().lower()
    for p in os.getenv(
        "WKV_YTMD_PROCESS_NAMES",
        "YouTube Music Desktop App.exe,YouTubeMusicDesktopApp.exe,YouTube Music.exe,ytmdesktop.exe",
    ).split(",")
    if p.strip()
]
_ytmd_next_allowed_at = 0.0
ED_PROCESS_NAMES = [
    p.strip()
    for p in os.getenv(
        "WKV_ED_PROCESS_NAMES",
        "EliteDangerous64.exe,EliteDangerous.exe",
    ).split(",")
    if p.strip()
]
LOOP_SLEEP_SEC = float(os.getenv("WKV_COLLECTOR_LOOP_SLEEP_SEC", "0.5"))
SYSTEM_INTERVAL_SEC = float(os.getenv("WKV_SYSTEM_INTERVAL_SEC", "15"))
ED_ACTIVE_INTERVAL_SEC = float(os.getenv("WKV_ED_ACTIVE_INTERVAL_SEC", "2"))
ED_IDLE_INTERVAL_SEC = float(os.getenv("WKV_ED_IDLE_INTERVAL_SEC", "8"))
MUSIC_ACTIVE_INTERVAL_SEC = float(os.getenv("WKV_MUSIC_ACTIVE_INTERVAL_SEC", "2"))
MUSIC_IDLE_INTERVAL_SEC = float(os.getenv("WKV_MUSIC_IDLE_INTERVAL_SEC", "12"))


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _port_open(host: str, port: int, timeout_sec: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except Exception:
        return False


def _read_ytmd_token() -> str | None:
    for candidate in (YTMD_TOKEN_FILE, YTMD_LEGACY_TOKEN_FILE):
        if not candidate or not candidate.exists():
            continue
        raw = _read_text(candidate)
        if not raw:
            continue
        token = raw
        if token.startswith("{"):
            try:
                obj = json.loads(token)
                token = str(obj.get("token", "")).strip()
            except Exception:
                token = ""
        token = token.strip()
        if token:
            return token
    return None


def _fetch_ytmd_track() -> tuple[dict[str, Any] | None, dict[str, Any]]:
    global _ytmd_next_allowed_at
    status = {
        "music.api_endpoint": f"http://{YTMD_HOST}:{YTMD_PORT}/api/v1/state",
        "music.api_reachable": False,
        "music.api_authorized": False,
    }
    if not YTMD_ENABLED:
        return None, status

    now = time.time()
    if now < _ytmd_next_allowed_at:
        return None, status

    if not _port_open(YTMD_HOST, YTMD_PORT, YTMD_TIMEOUT_SEC):
        _ytmd_next_allowed_at = now + max(1.0, YTMD_REST_POLL_MS / 1000.0)
        return None, status
    status["music.api_reachable"] = True

    headers: dict[str, str] = {}
    token = _read_ytmd_token()
    if token:
        headers["Authorization"] = token

    req = request.Request(
        f"http://{YTMD_HOST}:{YTMD_PORT}/api/v1/state",
        method="GET",
        headers=headers,
    )
    try:
        with request.urlopen(req, timeout=YTMD_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            _ytmd_next_allowed_at = now + max(1.0, YTMD_REST_POLL_MS / 1000.0)
    except error.HTTPError as exc:
        backoff_sec = max(1.0, YTMD_REST_POLL_MS / 1000.0)
        if int(exc.code) == 429:
            retry_after = str(exc.headers.get("Retry-After", "")).strip()
            if retry_after.isdigit():
                backoff_sec = float(int(retry_after))
            else:
                body = exc.read().decode("utf-8", errors="replace")
                match = re.search(r"retry in\s+(\d+)\s+seconds", body, flags=re.IGNORECASE)
                if match:
                    backoff_sec = float(int(match.group(1)))
                else:
                    backoff_sec = float(YTMD_RATE_LIMIT_BACKOFF_SEC_DEFAULT)
        _ytmd_next_allowed_at = now + backoff_sec
        if int(exc.code) not in (401, 403):
            status["music.api_authorized"] = bool(token)
        return None, status
    except Exception:
        _ytmd_next_allowed_at = now + max(1.0, YTMD_REST_POLL_MS / 1000.0)
        return None, status

    status["music.api_authorized"] = True
    try:
        payload = json.loads(raw)
    except Exception:
        return None, status

    video = payload.get("video") if isinstance(payload, dict) else None
    if not isinstance(video, dict):
        return None, status

    title = str(video.get("title") or "").strip()
    artist = str(video.get("author") or "").strip()
    album = str(video.get("album") or "").strip()
    thumbs = video.get("thumbnails") if isinstance(video.get("thumbnails"), list) else []
    thumb_url = ""
    if thumbs and isinstance(thumbs[0], dict):
        thumb_url = str(thumbs[0].get("url") or "").strip()
    now_playing = " - ".join([part for part in (title, artist) if part]).strip()
    if not title and not artist:
        return None, status

    return (
        {
            "title": title,
            "artist": artist,
            "album": album,
            "now_playing": now_playing,
            "artwork_path": thumb_url or None,
        },
        status,
    )


def _list_process_names() -> set[str]:
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        names: set[str] = set()
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith('"'):
                parts = [p.strip('"') for p in line.split('","')]
                if parts:
                    names.add(parts[0].lower())
        return names
    except Exception:
        return set()


def _process_running_by_names(process_names: set[str], configured_names: list[str]) -> bool:
    if not configured_names:
        return False
    return any(name in process_names for name in configured_names)


def collect_ed_state(process_names: set[str] | None = None) -> dict[str, Any]:
    running_name = ""
    if process_names is None:
        process_names = _list_process_names()
    for candidate in ED_PROCESS_NAMES:
        if candidate.lower() in process_names:
            running_name = candidate
            break
    running = bool(running_name)
    return {
        "ed.running": running,
        "ed.process_name": running_name if running else None,
    }


def collect_music_state(process_names: set[str] | None = None) -> dict[str, Any]:
    if process_names is None:
        process_names = _list_process_names()
    ytmd_running = _process_running_by_names(process_names, YTMD_PROCESS_NAMES)
    if not ytmd_running:
        return {
            "music.app_running": False,
            "music.playing": False,
            "music.source_path": None,
            "music.api_endpoint": f"http://{YTMD_HOST}:{YTMD_PORT}/api/v1/state",
            "music.api_reachable": False,
            "music.api_authorized": False,
            "music.now_playing": {
                "title": "",
                "artist": "",
                "album": "",
                "now_playing": "",
                "artwork_path": None,
            },
        }

    track_payload, api_status = _fetch_ytmd_track()
    if track_payload:
        return {
            "music.app_running": True,
            "music.playing": True,
            "music.source_path": f"ytmd_api://{YTMD_HOST}:{YTMD_PORT}",
            **api_status,
            "music.now_playing": track_payload,
        }
    if api_status.get("music.api_reachable") and api_status.get("music.api_authorized"):
        # API path is healthy but no usable track payload (e.g. transient rate-limit window).
        # Keep prior now-playing state instead of overwriting with empty file values.
        return {
            "music.app_running": True,
            "music.source_path": f"ytmd_api://{YTMD_HOST}:{YTMD_PORT}",
            **api_status,
        }

    def _read_music_from_dir(base_dir: Path) -> dict[str, Any]:
        title = _read_text(base_dir / "ytm-title.txt")
        artist = _read_text(base_dir / "ytm-artist.txt")
        album = _read_text(base_dir / "ytm-album.txt")
        now_playing = _read_text(base_dir / "ytm-nowplaying.txt")
        artwork = base_dir / "album.jpg"
        return {
            "title": title,
            "artist": artist,
            "album": album,
            "now_playing": now_playing,
            "artwork_path": str(artwork) if artwork.exists() else None,
        }

    primary_payload = _read_music_from_dir(NOW_PLAYING_DIR)
    source_dir = NOW_PLAYING_DIR

    has_primary_music = any(
        [primary_payload["title"], primary_payload["artist"], primary_payload["now_playing"]]
    )
    if (
        not has_primary_music
        and NOW_PLAYING_FALLBACK_DIR is not None
        and NOW_PLAYING_FALLBACK_DIR != NOW_PLAYING_DIR
    ):
        fallback_payload = _read_music_from_dir(NOW_PLAYING_FALLBACK_DIR)
        has_fallback_music = any(
            [fallback_payload["title"], fallback_payload["artist"], fallback_payload["now_playing"]]
        )
        if has_fallback_music:
            primary_payload = fallback_payload
            source_dir = NOW_PLAYING_FALLBACK_DIR

    playing = any([primary_payload["title"], primary_payload["artist"], primary_payload["now_playing"]])
    return {
        "music.app_running": True,
        "music.playing": playing,
        "music.source_path": str(source_dir),
        **api_status,
        "music.now_playing": primary_payload,
    }


def collect_system_state() -> dict[str, Any]:
    memory = MEMORYSTATUSEX()
    memory.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))

    uptime_ms = ctypes.windll.kernel32.GetTickCount64()
    memory_total = int(memory.ullTotalPhys)
    memory_avail = int(memory.ullAvailPhys)
    memory_used = max(memory_total - memory_avail, 0)
    memory_pct = (memory_used / memory_total) if memory_total > 0 else 0.0

    return {
        "hw.cpu.logical_cores": os.cpu_count(),
        "hw.memory": {
            "total_bytes": memory_total,
            "available_bytes": memory_avail,
            "used_bytes": memory_used,
            "used_percent": memory_pct,
        },
        "hw.uptime_sec": int(uptime_ms // 1000),
    }


def _state_hash(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        payload = repr(value)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def _build_changed_items(
    latest_values: dict[str, Any],
    last_sent_hashes: dict[str, str],
    source: str,
) -> list[dict[str, Any]]:
    observed_at = utc_now_iso()
    items: list[dict[str, Any]] = []
    for key, value in latest_values.items():
        value_hash = _state_hash(value)
        if last_sent_hashes.get(key) == value_hash:
            continue
        items.append(
            {
                "state_key": key,
                "state_value": value,
                "source": source,
                "confidence": 1.0,
                "observed_at_utc": observed_at,
            }
        )
        last_sent_hashes[key] = value_hash
    return items


def post_state(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"ok": True, "upserted": 0}
    payload = {
        "items": items,
        "emit_events": True,
        "profile": PROFILE,
        "session_id": SESSION_ID,
        "correlation_id": str(uuid.uuid4()),
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{BRAINSTEM_BASE_URL}/state",
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Source": "state_collector",
        },
    )
    try:
        with request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body)
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"http_{exc.code}", "detail": message}
    except Exception as exc:
        return {"ok": False, "error": "network_error", "detail": str(exc)}


def run_loop() -> None:
    print(f"State collector started -> {BRAINSTEM_BASE_URL}/state")
    last_sent_hashes: dict[str, str] = {}
    next_ed = 0.0
    next_music = 0.0
    next_system = 0.0

    while True:
        now = time.monotonic()
        pending_items: list[dict[str, Any]] = []
        process_names: set[str] | None = None
        if now >= next_ed or now >= next_music:
            process_names = _list_process_names()

        if now >= next_ed:
            ed_state = collect_ed_state(process_names=process_names)
            pending_items.extend(_build_changed_items(ed_state, last_sent_hashes, "ed_probe"))
            ed_running = bool(ed_state.get("ed.running"))
            next_ed = now + (ED_ACTIVE_INTERVAL_SEC if ed_running else ED_IDLE_INTERVAL_SEC)

        if now >= next_music:
            music_state = collect_music_state(process_names=process_names)
            pending_items.extend(_build_changed_items(music_state, last_sent_hashes, "music_probe"))
            music_playing = bool(music_state.get("music.playing"))
            next_music = now + (
                MUSIC_ACTIVE_INTERVAL_SEC if music_playing else MUSIC_IDLE_INTERVAL_SEC
            )

        if now >= next_system:
            system_state = collect_system_state()
            pending_items.extend(_build_changed_items(system_state, last_sent_hashes, "system_probe"))
            next_system = now + SYSTEM_INTERVAL_SEC

        if pending_items:
            result = post_state(pending_items)
            if not result.get("ok"):
                print(f"[state_collector] post failed: {result}")

        time.sleep(max(LOOP_SLEEP_SEC, 0.1))


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()
