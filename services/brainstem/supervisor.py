import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
from db_service import BrainstemDB


ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("WKV_DB_PATH", ROOT_DIR / "data" / "watchkeeper_vnext.db"))
SCHEMA_PATH = Path(
    os.getenv("WKV_SCHEMA_PATH", ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
)

PROFILE = os.getenv("WKV_PROFILE", "watchkeeper")
SESSION_ID = os.getenv("WKV_SUPERVISOR_SESSION", "supervisor-main")

HARDWARE_PROBE_JSON = Path(
    os.getenv("WKV_HARDWAREPROBE_JSON", str(ROOT_DIR / "data" / "hardware_probe.json"))
)
HARDWARE_MEMORY_THRESHOLD = float(os.getenv("WKV_HARDWARE_MEMORY_THRESHOLD", "0.90"))
HARDWARE_LOOP_SEC = float(os.getenv("WKV_SUP_HARDWARE_SEC", "10"))

ED_PROCESS_NAMES = [
    p.strip().lower()
    for p in os.getenv(
        "WKV_ED_PROCESS_NAMES",
        "EliteDangerous64.exe,EliteDangerous.exe",
    ).split(",")
    if p.strip()
]
ED_TELEMETRY_JSON = Path(
    os.getenv("WKV_ED_TELEMETRY_JSON", str(ROOT_DIR / "data" / "ed_telemetry.json"))
)
ED_ACTIVE_SEC = float(os.getenv("WKV_SUP_ED_ACTIVE_SEC", "2"))
ED_IDLE_SEC = float(os.getenv("WKV_SUP_ED_IDLE_SEC", "8"))

NOW_PLAYING_DIR = Path(
    os.getenv("WKV_NOW_PLAYING_DIR", str(Path("C:/ai/Watchkeeper/now-playing")))
)
MUSIC_ACTIVE_SEC = float(os.getenv("WKV_SUP_MUSIC_ACTIVE_SEC", "2"))
MUSIC_IDLE_SEC = float(os.getenv("WKV_SUP_MUSIC_IDLE_SEC", "10"))

LOOP_SLEEP_SEC = float(os.getenv("WKV_SUP_LOOP_SLEEP_SEC", "0.3"))


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


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}


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


def collect_hardware_state() -> dict[str, Any]:
    probe = _read_json_file(HARDWARE_PROBE_JSON)
    if probe:
        memory_used_pct = probe.get("memory_used_percent")
        return {
            "hardware.cpu_percent": probe.get("cpu_percent"),
            "hardware.gpu_temp_c": probe.get("gpu_temp_c"),
            "hardware.memory_used_percent": memory_used_pct,
            "hardware.source": "hardware_probe_json",
        }

    memory = MEMORYSTATUSEX()
    memory.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))
    total = int(memory.ullTotalPhys)
    avail = int(memory.ullAvailPhys)
    used = max(total - avail, 0)
    used_pct = (used / total) if total > 0 else 0.0
    uptime_sec = int(ctypes.windll.kernel32.GetTickCount64() // 1000)

    return {
        "hardware.cpu_percent": None,
        "hardware.gpu_temp_c": None,
        "hardware.memory_used_percent": used_pct,
        "hardware.memory_total_bytes": total,
        "hardware.memory_used_bytes": used,
        "hardware.uptime_sec": uptime_sec,
        "hardware.source": "windows_memory_api",
    }


def collect_ed_state() -> dict[str, Any]:
    process_names = _list_process_names()
    ed_running_name = ""
    for process_name in ED_PROCESS_NAMES:
        if process_name in process_names:
            ed_running_name = process_name
            break
    running = bool(ed_running_name)

    telemetry = _read_json_file(ED_TELEMETRY_JSON) if running else {}
    return {
        "ed.running": running,
        "ed.process_name": ed_running_name if running else None,
        "ed.telemetry.system_name": telemetry.get("system_name"),
        "ed.telemetry.hull_percent": telemetry.get("hull_percent"),
    }


def collect_music_state() -> dict[str, Any]:
    title = _read_text(NOW_PLAYING_DIR / "ytm-title.txt")
    artist = _read_text(NOW_PLAYING_DIR / "ytm-artist.txt")
    playing = bool(title or artist)
    return {
        "music.playing": playing,
        "music.track.title": title,
        "music.track.artist": artist,
    }


def make_state_items(
    *,
    values: dict[str, Any],
    source: str,
    correlation_id: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    now = utc_now_iso()
    items = []
    for state_key, state_value in values.items():
        items.append(
            {
                "state_key": state_key,
                "state_value": state_value,
                "source": source,
                "confidence": 1.0,
                "observed_at_utc": now,
                "event_id": str(uuid.uuid4()),
                "event_type": "STATE_UPDATED",
                "event_source": source,
                "profile": PROFILE,
                "session_id": SESSION_ID,
                "correlation_id": correlation_id,
                "mode": mode,
                "event_payload": {
                    "state_key": state_key,
                    "state_value": state_value,
                    "source": source,
                    "observed_at_utc": now,
                },
            }
        )
    return items


def process_hardware(db: BrainstemDB) -> None:
    correlation_id = str(uuid.uuid4())
    values = collect_hardware_state()
    items = make_state_items(
        values=values,
        source="hardware_probe",
        correlation_id=correlation_id,
        mode="standby",
    )
    result = db.batch_set_state(items=items, emit_events=True)

    threshold_value = values.get("hardware.memory_used_percent")
    if isinstance(threshold_value, (int, float)) and threshold_value >= HARDWARE_MEMORY_THRESHOLD:
        db.append_event(
            event_id=str(uuid.uuid4()),
            timestamp_utc=utc_now_iso(),
            event_type="HARDWARE_THRESHOLD",
            source="hardware_probe",
            payload={
                "metric": "hardware.memory_used_percent",
                "value": float(threshold_value),
                "threshold": HARDWARE_MEMORY_THRESHOLD,
                "state_changed": result["changed"],
            },
            profile=PROFILE,
            session_id=SESSION_ID,
            correlation_id=correlation_id,
            mode="standby",
            severity="warn",
            tags=["threshold", "hardware"],
        )


def process_ed(db: BrainstemDB, previous_running: bool | None) -> bool:
    correlation_id = str(uuid.uuid4())
    values = collect_ed_state()
    running = bool(values.get("ed.running"))
    items = make_state_items(
        values=values,
        source="ed_supervisor",
        correlation_id=correlation_id,
        mode="game" if running else "standby",
    )
    db.batch_set_state(items=items, emit_events=True)

    if previous_running is None:
        return running
    if previous_running != running:
        db.append_event(
            event_id=str(uuid.uuid4()),
            timestamp_utc=utc_now_iso(),
            event_type="ED_STARTED" if running else "ED_STOPPED",
            source="ed_supervisor",
            payload={
                "running": running,
                "process_name": values.get("ed.process_name"),
                "telemetry_system_name": values.get("ed.telemetry.system_name"),
                "telemetry_hull_percent": values.get("ed.telemetry.hull_percent"),
            },
            profile=PROFILE,
            session_id=SESSION_ID,
            correlation_id=correlation_id,
            mode="game" if running else "standby",
            severity="info",
            tags=["ed"],
        )
    return running


def process_music(
    db: BrainstemDB,
    previous_playing: bool | None,
    previous_track: tuple[str, str] | None,
) -> tuple[bool, tuple[str, str]]:
    correlation_id = str(uuid.uuid4())
    values = collect_music_state()
    playing = bool(values.get("music.playing"))
    track = (
        str(values.get("music.track.title") or ""),
        str(values.get("music.track.artist") or ""),
    )

    items = make_state_items(
        values=values,
        source="music_supervisor",
        correlation_id=correlation_id,
        mode="game" if playing else "standby",
    )
    db.batch_set_state(items=items, emit_events=True)

    if previous_playing is not None and previous_playing != playing:
        db.append_event(
            event_id=str(uuid.uuid4()),
            timestamp_utc=utc_now_iso(),
            event_type="MUSIC_STARTED" if playing else "MUSIC_STOPPED",
            source="music_supervisor",
            payload={"playing": playing, "track_title": track[0], "track_artist": track[1]},
            profile=PROFILE,
            session_id=SESSION_ID,
            correlation_id=correlation_id,
            mode="game" if playing else "standby",
            severity="info",
            tags=["music"],
        )

    if playing and previous_track is not None and track != previous_track:
        db.append_event(
            event_id=str(uuid.uuid4()),
            timestamp_utc=utc_now_iso(),
            event_type="TRACK_CHANGED",
            source="music_supervisor",
            payload={
                "previous_title": previous_track[0],
                "previous_artist": previous_track[1],
                "title": track[0],
                "artist": track[1],
            },
            profile=PROFILE,
            session_id=SESSION_ID,
            correlation_id=correlation_id,
            mode="game",
            severity="info",
            tags=["music", "track"],
        )

    return playing, track


def run_supervisor_loop() -> None:
    db = BrainstemDB(DB_PATH, SCHEMA_PATH)
    db.ensure_schema()
    print(f"Supervisor started. DB: {DB_PATH}")

    previous_ed_running: bool | None = None
    previous_music_playing: bool | None = None
    previous_track: tuple[str, str] | None = None

    next_hardware = 0.0
    next_ed = 0.0
    next_music = 0.0

    while True:
        now = time.monotonic()

        if now >= next_hardware:
            process_hardware(db)
            next_hardware = now + HARDWARE_LOOP_SEC

        if now >= next_ed:
            previous_ed_running = process_ed(db, previous_ed_running)
            next_ed = now + (ED_ACTIVE_SEC if previous_ed_running else ED_IDLE_SEC)

        if now >= next_music:
            previous_music_playing, previous_track = process_music(
                db,
                previous_music_playing,
                previous_track,
            )
            next_music = now + (MUSIC_ACTIVE_SEC if previous_music_playing else MUSIC_IDLE_SEC)

        time.sleep(max(0.05, LOOP_SLEEP_SEC))


def run_supervisor_once() -> None:
    db = BrainstemDB(DB_PATH, SCHEMA_PATH)
    db.ensure_schema()
    process_hardware(db)
    process_ed(db, previous_running=None)
    process_music(db, previous_playing=None, previous_track=None)


def main() -> None:
    run_supervisor_loop()


if __name__ == "__main__":
    main()
