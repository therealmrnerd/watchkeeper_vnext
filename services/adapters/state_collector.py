import ctypes
import hashlib
import json
import os
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


def collect_ed_state() -> dict[str, Any]:
    running_name = ""
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


def collect_music_state() -> dict[str, Any]:
    title = _read_text(NOW_PLAYING_DIR / "ytm-title.txt")
    artist = _read_text(NOW_PLAYING_DIR / "ytm-artist.txt")
    album = _read_text(NOW_PLAYING_DIR / "ytm-album.txt")
    now_playing = _read_text(NOW_PLAYING_DIR / "ytm-nowplaying.txt")
    artwork = NOW_PLAYING_DIR / "album.jpg"
    artwork_exists = artwork.exists()

    playing = any([title, artist, now_playing])
    return {
        "music.playing": playing,
        "music.now_playing": {
            "title": title,
            "artist": artist,
            "album": album,
            "now_playing": now_playing,
            "artwork_path": str(artwork) if artwork_exists else None,
        },
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

        if now >= next_ed:
            ed_state = collect_ed_state()
            pending_items.extend(_build_changed_items(ed_state, last_sent_hashes, "ed_probe"))
            ed_running = bool(ed_state.get("ed.running"))
            next_ed = now + (ED_ACTIVE_INTERVAL_SEC if ed_running else ED_IDLE_INTERVAL_SEC)

        if now >= next_music:
            music_state = collect_music_state()
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
