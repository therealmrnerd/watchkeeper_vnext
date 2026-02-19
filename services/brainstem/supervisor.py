import ctypes
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
from db_service import BrainstemDB
from edparser_tool import EDParserTool


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
SUP_STATS_TXT_ENABLED = os.getenv("WKV_SUP_STATS_TXT_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}
SUP_STATS_DIR = Path(os.getenv("WKV_SUP_STATS_DIR", str(ROOT_DIR / "stats")))
SUP_STATS_LINE_SEC = max(0.0, float(os.getenv("WKV_SUP_STATS_LINE_SEC", "10")))
SUP_STATS_CPU_TEMP_FILE = os.getenv("WKV_SUP_STATS_CPU_TEMP_FILE", "cpu-temp.txt").strip() or "cpu-temp.txt"
SUP_STATS_CPU_USAGE_FILE = (
    os.getenv("WKV_SUP_STATS_CPU_USAGE_FILE", "cpu-usage.txt").strip() or "cpu-usage.txt"
)
SUP_STATS_GPU_TEMP_FILE = os.getenv("WKV_SUP_STATS_GPU_TEMP_FILE", "gpu-temp.txt").strip() or "gpu-temp.txt"
SUP_STATS_GPU_USAGE_FILE = (
    os.getenv("WKV_SUP_STATS_GPU_USAGE_FILE", "gpu-usage.txt").strip() or "gpu-usage.txt"
)
SUP_STATS_CPU_LINE_FILE = os.getenv("WKV_SUP_STATS_CPU_LINE_FILE", "cpu-line.txt").strip() or "cpu-line.txt"
SUP_STATS_GPU_LINE_FILE = os.getenv("WKV_SUP_STATS_GPU_LINE_FILE", "gpu-line.txt").strip() or "gpu-line.txt"

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
ED_STATUS_PATH = Path(
    os.getenv(
        "WKV_ED_STATUS_PATH",
        str(
            Path(os.getenv("USERPROFILE", "C:/Users/YourUser"))
            / "Saved Games"
            / "Frontier Developments"
            / "Elite Dangerous"
            / "Status.json"
        ),
    )
)
ED_JOURNAL_DIR = Path(
    os.getenv(
        "WKV_ED_JOURNAL_DIR",
        str(
            Path(os.getenv("USERPROFILE", "C:/Users/YourUser"))
            / "Saved Games"
            / "Frontier Developments"
            / "Elite Dangerous"
        ),
    )
)
ED_NAVROUTE_PATH = Path(
    os.getenv(
        "WKV_ED_NAVROUTE_PATH",
        str(
            Path(os.getenv("USERPROFILE", "C:/Users/YourUser"))
            / "Saved Games"
            / "Frontier Developments"
            / "Elite Dangerous"
            / "NavRoute.json"
        ),
    )
)
ED_ACTIVE_SEC = float(os.getenv("WKV_SUP_ED_ACTIVE_SEC", "0.35"))
ED_IDLE_SEC = float(os.getenv("WKV_SUP_ED_IDLE_SEC", "8"))

MUSIC_ACTIVE_SEC = float(os.getenv("WKV_SUP_MUSIC_ACTIVE_SEC", "2"))
MUSIC_IDLE_SEC = float(os.getenv("WKV_SUP_MUSIC_IDLE_SEC", "10"))
SUP_HARDWARE_REQUIRES_JINX = os.getenv("WKV_SUP_HARDWARE_REQUIRES_JINX", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}

LOOP_SLEEP_SEC = float(os.getenv("WKV_SUP_LOOP_SLEEP_SEC", "0.1"))
FORCE_WATCH_CONDITION = os.getenv("WKV_FORCE_WATCH_CONDITION", "").strip().upper()
EDPARSER_AUTORUN = os.getenv("WKV_SUP_EDPARSER_AUTORUN", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}
EDPARSER_TOOL = EDParserTool(db_service=None)

AUX_APPS_AUTORUN = os.getenv("WKV_SUP_AUX_APPS_AUTORUN", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}

SAMMI_ENABLED = os.getenv("WKV_SUP_SAMMI_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}
SAMMI_EXE = os.getenv("WKV_SUP_SAMMI_EXE", "").strip()
SAMMI_PROCESS_NAMES = [
    p.strip().lower()
    for p in os.getenv(
        "WKV_SUP_SAMMI_PROCESS_NAMES",
        "SAMMI Core.exe,SAMMI Deck.exe,SAMMI Panel.exe,SAMMI Voice.exe",
    ).split(",")
    if p.strip()
]

JINX_ENABLED = os.getenv("WKV_SUP_JINX_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}
JINX_EXE = os.getenv("WKV_SUP_JINX_EXE", "").strip()
JINX_ARGS_RAW = os.getenv("WKV_SUP_JINX_ARGS", "-m").strip()
try:
    JINX_LAUNCH_ARGS = shlex.split(JINX_ARGS_RAW, posix=False) if JINX_ARGS_RAW else []
except Exception:
    JINX_LAUNCH_ARGS = []
JINX_PROCESS_NAMES = [
    p.strip().lower()
    for p in os.getenv(
        "WKV_SUP_JINX_PROCESS_NAMES",
        "Hi-Jinx.exe,Hi-Jinx2.exe,Hi-Jinx 2.exe,Jinx.exe",
    ).split(",")
    if p.strip()
]
JINX_SYNC_ENABLED = os.getenv("WKV_SUP_JINX_SYNC_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}
JINX_SYNC_VAR_NAME = os.getenv("WKV_SUP_JINX_SYNC_VAR", "sync").strip() or "sync"
JINX_PYTHON = os.getenv("WKV_SUP_JINX_PYTHON", "python").strip() or "python"
JINX_SENDER_PATH = Path(
    os.getenv(
        "WKV_SUP_JINX_SENDER_PATH",
        str(ROOT_DIR / "tools" / "jinxsender.py"),
    )
)
JINX_ENV_MAP_PATH = Path(
    os.getenv(
        "WKV_SUP_JINX_ENV_MAP_PATH",
        str(ROOT_DIR / "config" / "jinx_envmap.json"),
    )
)
JINX_ARTNET_IP = os.getenv("WKV_SUP_JINX_ARTNET_IP", "127.0.0.1").strip() or "127.0.0.1"
JINX_ARTNET_UNIVERSE = int(os.getenv("WKV_SUP_JINX_ARTNET_UNIVERSE", "7"))
JINX_BRIGHTNESS = int(os.getenv("WKV_SUP_JINX_BRIGHTNESS", "200"))
JINX_OFF_EFFECT = os.getenv("WKV_SUP_JINX_OFF_EFFECT", "S1").strip() or "S1"

ED_AHK_ENABLED = os.getenv("WKV_SUP_ED_AHK_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}
ED_AHK_PATH = os.getenv("WKV_SUP_ED_AHK_PATH", "").strip()
AHK_EXE = os.getenv("WKV_SUP_AHK_EXE", "").strip()
ED_AHK_STOP_ON_EXIT = os.getenv("WKV_SUP_ED_AHK_STOP_ON_ED_EXIT", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}
ED_AHK_RESTART_BACKOFF_SEC = max(0.5, float(os.getenv("WKV_SUP_ED_AHK_RESTART_BACKOFF_SEC", "3")))
AHK_PROTECTED_SCRIPT_MARKERS = [
    marker.strip().lower()
    for marker in os.getenv(
        "WKV_SUP_AHK_PROTECTED_SCRIPTS",
        "stack_tray.ahk",
    ).split(",")
    if marker.strip()
]

SAMMI_API_ENABLED = os.getenv("WKV_SAMMI_API_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}
SAMMI_API_HOST = os.getenv("WKV_SAMMI_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
SAMMI_API_PORT = int(os.getenv("WKV_SAMMI_API_PORT", "9450"))
SAMMI_API_PASSWORD = os.getenv("WKV_SAMMI_API_PASSWORD", "").strip()
SAMMI_API_TIMEOUT_SEC = float(os.getenv("WKV_SAMMI_API_TIMEOUT_SEC", "0.6"))
SAMMI_API_BACKOFF_SEC = float(os.getenv("WKV_SAMMI_API_BACKOFF_SEC", "5"))
SAMMI_API_ERROR_LOG_SEC = float(os.getenv("WKV_SAMMI_API_ERROR_LOG_SEC", "5"))
SAMMI_API_MAX_UPDATES_PER_CYCLE = int(os.getenv("WKV_SAMMI_API_MAX_UPDATES_PER_CYCLE", "12"))
SAMMI_API_ONLY_WHEN_ED = os.getenv("WKV_SAMMI_API_ONLY_WHEN_ED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}
SAMMI_NEW_WRITE_VAR = os.getenv("WKV_SAMMI_NEW_WRITE_VAR", "ID116.new_write").strip() or "ID116.new_write"
_sammi_new_write_compat = os.getenv("WKV_SAMMI_NEW_WRITE_COMPAT_VAR", "").strip()
if _sammi_new_write_compat:
    SAMMI_NEW_WRITE_COMPAT_VAR = _sammi_new_write_compat
elif "." in SAMMI_NEW_WRITE_VAR:
    SAMMI_NEW_WRITE_COMPAT_VAR = SAMMI_NEW_WRITE_VAR.replace(".", "_")
else:
    SAMMI_NEW_WRITE_COMPAT_VAR = ""
SAMMI_NEW_WRITE_IGNORE_VARS = {
    name.strip()
    for name in os.getenv("WKV_SAMMI_NEW_WRITE_IGNORE_VARS", "Heartbeat,timestamp").split(",")
    if name.strip()
}

_sammi_backoff_until = 0.0
_sammi_last_error_at = 0.0
_sammi_last_sent: dict[str, Any] = {}
_sammi_heartbeat = 0
_ed_ahk_last_launch_attempt = 0.0
_journal_cache: dict[str, Any] = {"path": None, "size": 0, "mtime": 0.0, "values": {}}
_jinx_env_map_cache: dict[str, Any] = {"mtime": None, "values": {}}
_jinx_sync_state = "off"
_jinx_last_environment: str | None = None
_jinx_last_effect_key: str | None = None
_jinx_last_effect_code: str | None = None
_jinx_last_manual_request: str | None = None
_stats_last_line_write_monotonic = 0.0
SAMMI_PRIORITY_VARS = [
    "lights",
    "nightvision",
    "cargoscoop",
    "landing_gear",
    "landed",
    "shields_up",
    "hardpoints",
    "supercruise",
    "docked",
    "flightstatus",
    "gui_focus",
    "target_set",
    "current_system",
    "System",
    "Body",
    "destination",
    "Destination",
    "nav_route",
    "nav_route_destination",
    "nav_route_origin",
]
LEGACY_SAMMI_VARIABLES = [
    "Balance",
    "Body",
    "Cargo",
    "Destination",
    "FireGroup",
    "Flags",
    "Flags2",
    "Fuel",
    "GuiFocus",
    "Heartbeat",
    "LegalState",
    "Pips",
    "System",
    "aim_down_sight",
    "altitude",
    "balance",
    "balance_raw",
    "being_interdicted",
    "breathable_atmosphere",
    "cargo",
    "cargoscoop",
    "cold",
    "current_location",
    "current_system",
    "destination",
    "docked",
    "event",
    "fa",
    "fire_group",
    "flags_text",
    "flightstatus",
    "fsd_charging",
    "fsd_cooldown",
    "fsd_hyperdrive_charging",
    "fsd_jump",
    "fsd_mass_locked",
    "fuel_main",
    "fuel_reservoir",
    "glide_mode",
    "gui_focus_raw",
    "hardpoints",
    "has_lat_long",
    "heading",
    "health",
    "health_raw",
    "hot",
    "hud_analysis_mode",
    "in_fighter",
    "in_main_ship",
    "in_multicrew",
    "in_srv",
    "in_taxi",
    "in_wing",
    "is_in_danger",
    "landed",
    "landing_gear",
    "latitude",
    "latitude_raw",
    "legal_state",
    "lights",
    "longitude",
    "longitude_raw",
    "low_fuel",
    "low_health",
    "low_oxygen",
    "nav_route",
    "nav_route_destination",
    "nav_route_origin",
    "nightvision",
    "on_foot",
    "on_foot_exterior",
    "on_foot_in_hangar",
    "on_foot_in_station",
    "on_foot_on_planet",
    "on_foot_social_space",
    "overheating",
    "oxygen",
    "oxygen_raw",
    "physical_multicrew",
    "pips_eng",
    "pips_sys",
    "pips_wea",
    "scooping_fuel",
    "selected_weapon",
    "selected_weapon_localised",
    "shields_up",
    "ship_id",
    "ship_model",
    "ship_name",
    "silent_running",
    "srv_drive_assist",
    "srv_handbrake",
    "srv_high_beam",
    "srv_turret_retracted",
    "srv_turret_view",
    "supercruise",
    "sync",
    "target_set",
    "telepresence_multicrew",
    "temperature",
    "temperature_raw",
    "timestamp",
    "very_cold",
    "very_hot",
]


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


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except Exception:
            return None
    return None


def _nested_value(payload: dict[str, Any], key_path: str) -> Any:
    cursor: Any = payload
    for part in key_path.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(part)
    return cursor


def _probe_float(payload: dict[str, Any], *candidates: str) -> float | None:
    for key_path in candidates:
        value = _safe_float(_nested_value(payload, key_path))
        if value is not None:
            return value
    return None


def _normalize_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 1.0 and value <= 100.0:
        return value / 100.0
    return value


def _write_text_file(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except Exception:
        return


def _write_hardware_stats_txt(values: dict[str, Any]) -> None:
    global _stats_last_line_write_monotonic
    if not SUP_STATS_TXT_ENABLED:
        return

    cpu_temp = _safe_float(values.get("hardware.cpu_temp_c"))
    cpu_usage = _safe_float(values.get("hardware.cpu_percent"))
    gpu_temp = _safe_float(values.get("hardware.gpu_temp_c"))
    gpu_usage = _safe_float(values.get("hardware.gpu_percent"))

    if cpu_temp is not None:
        _write_text_file(SUP_STATS_DIR / SUP_STATS_CPU_TEMP_FILE, f"CPU{round(cpu_temp)}C")
    if cpu_usage is not None:
        _write_text_file(SUP_STATS_DIR / SUP_STATS_CPU_USAGE_FILE, f"CPU{round(cpu_usage)}%")
    if gpu_temp is not None:
        _write_text_file(SUP_STATS_DIR / SUP_STATS_GPU_TEMP_FILE, f"GPU{round(gpu_temp)}C")
    if gpu_usage is not None:
        _write_text_file(SUP_STATS_DIR / SUP_STATS_GPU_USAGE_FILE, f"GPU{round(gpu_usage)}%")

    now = time.monotonic()
    if SUP_STATS_LINE_SEC > 0 and (now - _stats_last_line_write_monotonic) < SUP_STATS_LINE_SEC:
        return

    cpu_temp_text = f"{round(cpu_temp)}C" if cpu_temp is not None else "??C"
    cpu_usage_text = f"{round(cpu_usage)}%" if cpu_usage is not None else "??%"
    gpu_temp_text = f"{round(gpu_temp)}C" if gpu_temp is not None else "??C"
    gpu_usage_text = f"{round(gpu_usage)}%" if gpu_usage is not None else "??%"
    _write_text_file(SUP_STATS_DIR / SUP_STATS_CPU_LINE_FILE, f"CPU {cpu_temp_text} | {cpu_usage_text}")
    _write_text_file(SUP_STATS_DIR / SUP_STATS_GPU_LINE_FILE, f"GPU {gpu_temp_text} | {gpu_usage_text}")
    _stats_last_line_write_monotonic = now


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


def _pid_running(pid: int | None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        out = result.stdout or ""
        if "No tasks are running" in out:
            return False
        for raw in out.splitlines():
            line = raw.strip()
            if line.startswith('"'):
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) > 1 and parts[1].strip() == str(pid):
                    return True
        return False
    except Exception:
        return False


def _terminate_pid(pid: int, force: bool = True) -> bool:
    if pid <= 0:
        return False
    cmd = ["taskkill", "/PID", str(pid), "/T"]
    if force:
        cmd.append("/F")
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception:
        return False
    return not _pid_running(pid)


def _path_or_none(value: str) -> Path | None:
    text = value.strip()
    if not text:
        return None
    path = Path(text)
    if path.exists():
        return path
    return None


def _process_running_by_names(
    process_names_snapshot: set[str],
    configured_names: list[str],
) -> bool:
    if not configured_names:
        return False
    if any(name in process_names_snapshot for name in configured_names):
        return True

    def _canon(value: str) -> str:
        text = value.strip().lower()
        if text.endswith(".exe"):
            text = text[:-4]
        return re.sub(r"[^a-z0-9]", "", text)

    process_canon = {_canon(name) for name in process_names_snapshot if name}
    configured_canon = [_canon(name) for name in configured_names if name]
    return any(name in process_canon for name in configured_canon)


def _launch_executable(
    exe_path: Path,
    args: list[str] | None = None,
    *,
    detached: bool = False,
) -> tuple[bool, int | None, str | None]:
    cmd = [str(exe_path)]
    if args:
        cmd.extend(args)
    creationflags = 0
    if detached:
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    else:
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
        return True, int(proc.pid), None
    except Exception as exc:
        return False, None, str(exc)


def _launch_executable_via_helper(exe_path: Path, args: list[str] | None = None) -> tuple[bool, int | None, str | None]:
    """Launch via a short-lived helper shell so target process is outside supervisor tree."""
    exe_quoted = str(exe_path).replace("'", "''")
    arg_list = args or []
    arg_literal = ", ".join(["'" + str(a).replace("'", "''") + "'" for a in arg_list])
    cmd = (
        f"$exe = '{exe_quoted}'; "
        f"$argList = @({arg_literal}); "
        "Start-Process -FilePath $exe -ArgumentList $argList | Out-Null"
    )
    argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode == 0:
            return True, None, None
        detail = (result.stderr or result.stdout or "").strip() or f"helper_exit_{result.returncode}"
        return False, None, detail
    except Exception as exc:
        return False, None, str(exc)


def _resolve_ahk_bin() -> str | None:
    explicit = _path_or_none(AHK_EXE)
    if explicit:
        return str(explicit)
    for name in ["AutoHotkey64.exe", "AutoHotkey.exe"]:
        found = shutil.which(name)
        if found:
            return found
    for candidate in [
        r"C:\Program Files\AutoHotkey\AutoHotkey64.exe",
        r"C:\Program Files\AutoHotkey\AutoHotkey.exe",
        r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe",
        r"C:\Program Files\AutoHotkey\v2\AutoHotkey.exe",
    ]:
        if Path(candidate).exists():
            return candidate
    return None


def _find_ahk_script_pids(script_path: Path) -> list[int]:
    if not script_path.exists():
        return []
    try:
        target = str(script_path.resolve()).lower().replace("'", "''")
        leaf = script_path.name.lower().replace("'", "''")
        cmd = (
            f"$target = '{target}'; "
            f"$leaf = '{leaf}'; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { "
            "$_.Name -like 'AutoHotkey*.exe' -and $_.CommandLine -and "
            "($_.CommandLine.ToLowerInvariant().Contains($target) -or $_.CommandLine.ToLowerInvariant().Contains($leaf)) "
            "} | "
            "Select-Object -ExpandProperty ProcessId"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        out = result.stdout or ""
        pids: list[int] = []
        for raw in out.splitlines():
            txt = raw.strip()
            if txt.isdigit():
                pids.append(int(txt))
        return pids
    except Exception:
        return []


def _process_command_line(pid: int | None) -> str:
    if not pid:
        return ""
    try:
        pid_int = int(pid)
        cmd = (
            f"$proc = Get-CimInstance Win32_Process -Filter \"ProcessId = {pid_int}\"; "
            "if ($proc -and $proc.CommandLine) { $proc.CommandLine }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _pid_matches_ahk_script(pid: int | None, script_path: Path | None) -> bool:
    if not pid or not script_path:
        return False
    line = _process_command_line(pid).lower()
    if not line:
        return False
    try:
        target = str(script_path.resolve()).lower()
    except Exception:
        target = str(script_path).lower()
    return target in line


def _is_protected_ahk_pid(pid: int | None) -> bool:
    if not pid or not AHK_PROTECTED_SCRIPT_MARKERS:
        return False
    line = _process_command_line(pid).lower()
    if not line:
        return False
    return any(marker in line for marker in AHK_PROTECTED_SCRIPT_MARKERS)


def _sammi_post(request_name: str, params: dict[str, Any]) -> tuple[bool, str | None]:
    global _sammi_backoff_until
    global _sammi_last_error_at

    if not SAMMI_API_ENABLED:
        return False, "sammi_api_disabled"

    now = time.monotonic()
    if now < _sammi_backoff_until:
        return False, "sammi_api_backoff"

    url = f"http://{SAMMI_API_HOST}:{SAMMI_API_PORT}/api"
    body = {"request": request_name}
    body.update(params)
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if SAMMI_API_PASSWORD:
        headers["Authorization"] = SAMMI_API_PASSWORD

    req = request.Request(url, data=raw, method="POST", headers=headers)
    try:
        with request.urlopen(req, timeout=SAMMI_API_TIMEOUT_SEC) as resp:
            _ = resp.read()
        _sammi_backoff_until = 0.0
        _sammi_last_error_at = 0.0
        return True, None
    except error.HTTPError as exc:
        detail = f"http_{exc.code}"
    except Exception as exc:
        detail = str(exc)

    if now - _sammi_last_error_at >= SAMMI_API_ERROR_LOG_SEC:
        print(f"[WARN] [sammi_bridge] request={request_name} failed: {detail}")
        _sammi_last_error_at = now
    _sammi_backoff_until = now + max(0.5, SAMMI_API_BACKOFF_SEC)
    return False, detail


def _sammi_get_variable(name: str) -> Any | None:
    if not SAMMI_API_ENABLED or not name:
        return None
    query = parse.urlencode({"request": "getVariable", "name": name})
    url = f"http://{SAMMI_API_HOST}:{SAMMI_API_PORT}/api?{query}"
    headers: dict[str, str] = {}
    if SAMMI_API_PASSWORD:
        headers["Authorization"] = SAMMI_API_PASSWORD
    req = request.Request(url, method="GET", headers=headers)
    try:
        with request.urlopen(req, timeout=SAMMI_API_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, dict):
        if "value" in data:
            return data.get("value")
        if "result" in data:
            return data.get("result")
        if "variable" in data:
            return data.get("variable")
    return data


def _normalize_jinx_effect(effect: Any) -> str | None:
    if effect is None:
        return None
    text = str(effect).strip().upper()
    if not text:
        return None
    if text.startswith("S") or text.startswith("C"):
        if len(text) > 1 and text[1:].isdigit():
            return f"{text[0]}{int(text[1:])}"
        return None
    if text.isdigit():
        return f"S{int(text)}"
    return None


def _load_jinx_env_map() -> dict[str, str]:
    global _jinx_env_map_cache

    fallback = {
        "Normal Space": "C7",
        "Supercruise": "C7",
        "Docked": "C14",
        "Planet Surface - SRV": "C7",
        "Planet Surface - Ship": "C7",
        "Planet Orbit": "C7",
        "Witch Space": "C7",
        "On Foot - Planet": "C7",
        "On Foot - Station": "C7",
    }
    if not JINX_ENV_MAP_PATH.exists():
        return fallback
    try:
        mtime = JINX_ENV_MAP_PATH.stat().st_mtime
        if _jinx_env_map_cache.get("mtime") == mtime:
            values = _jinx_env_map_cache.get("values")
            if isinstance(values, dict) and values:
                return values
        payload = json.loads(JINX_ENV_MAP_PATH.read_text(encoding="utf-8", errors="ignore"))
        if not isinstance(payload, dict):
            return fallback
        values: dict[str, str] = {}
        for key, value in payload.items():
            if not isinstance(key, str):
                continue
            normalized = _normalize_jinx_effect(value)
            if normalized:
                values[key] = normalized
        if not values:
            return fallback
        _jinx_env_map_cache = {"mtime": mtime, "values": values}
        return values
    except Exception:
        return fallback


def _trigger_jinx_effect(effect: str, reason: str) -> tuple[bool, str | None]:
    global _jinx_last_effect_key
    global _jinx_last_effect_code

    normalized = _normalize_jinx_effect(effect)
    if not normalized:
        return False, f"invalid_effect:{effect}"
    if not JINX_SENDER_PATH.exists():
        return False, f"missing_sender:{JINX_SENDER_PATH}"

    key = f"{JINX_ARTNET_IP}|{normalized}|{JINX_BRIGHTNESS}|{JINX_ARTNET_UNIVERSE}"
    if _jinx_last_effect_key == key:
        return True, None

    cmd = [
        JINX_PYTHON,
        str(JINX_SENDER_PATH),
        JINX_ARTNET_IP,
        normalized,
        str(int(JINX_BRIGHTNESS)),
        str(int(JINX_ARTNET_UNIVERSE)),
    ]
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        return False, str(exc)

    _jinx_last_effect_key = key
    _jinx_last_effect_code = normalized
    print(f"[INFO] [jinx_sync] effect={normalized} reason={reason}")
    return True, None


def process_jinx_sync(db: BrainstemDB, *, ed_running: bool, jinx_running: bool) -> None:
    global _jinx_sync_state
    global _jinx_last_environment
    global _jinx_last_manual_request

    if not JINX_ENABLED:
        return
    if not ed_running:
        return
    if not jinx_running:
        return

    sync_raw = _sammi_get_variable(JINX_SYNC_VAR_NAME)
    sync_now = _jinx_sync_state
    if sync_raw is not None:
        sync_now = "on" if str(sync_raw).strip().lower() == "on" else "off"

    manual_effect = None
    row_effect = db.get_state("jinx.effect")
    row_scene = db.get_state("jinx.scene")
    row_chase = db.get_state("jinx.chase")
    if row_effect and row_effect.get("state_value") not in (None, ""):
        manual_effect = _normalize_jinx_effect(row_effect.get("state_value"))
    elif row_scene and row_scene.get("state_value") not in (None, ""):
        scene = str(row_scene.get("state_value")).strip()
        if scene.isdigit():
            manual_effect = f"S{int(scene)}"
    elif row_chase and row_chase.get("state_value") not in (None, ""):
        chase = str(row_chase.get("state_value")).strip()
        if chase.isdigit():
            manual_effect = f"C{int(chase)}"

    current_environment = None
    selected_effect = None
    error_text: str | None = None

    if isinstance(manual_effect, str):
        if manual_effect != _jinx_last_manual_request:
            _jinx_last_manual_request = manual_effect
            selected_effect = manual_effect
    elif JINX_SYNC_ENABLED and sync_now == "on" and ed_running and jinx_running:
        status = _read_json_file(ED_STATUS_PATH)
        flags = _decode_flags(int(status.get("Flags"))) if isinstance(status.get("Flags"), int) else None
        flags2 = (
            _decode_flags2(int(status.get("Flags2"))) if isinstance(status.get("Flags2"), int) else None
        )
        current_environment = _map_environment(status, flags, flags2)
        if current_environment != _jinx_last_environment:
            env_map = _load_jinx_env_map()
            selected_effect = env_map.get(current_environment)
            _jinx_last_environment = current_environment

    if JINX_SYNC_ENABLED and sync_now != _jinx_sync_state:
        if sync_now == "off":
            selected_effect = JINX_OFF_EFFECT
        elif sync_now == "on" and not selected_effect and ed_running and jinx_running:
            status = _read_json_file(ED_STATUS_PATH)
            flags = _decode_flags(int(status.get("Flags"))) if isinstance(status.get("Flags"), int) else None
            flags2 = (
                _decode_flags2(int(status.get("Flags2"))) if isinstance(status.get("Flags2"), int) else None
            )
            current_environment = _map_environment(status, flags, flags2)
            env_map = _load_jinx_env_map()
            selected_effect = env_map.get(current_environment)
            _jinx_last_environment = current_environment

    if selected_effect and jinx_running:
        ok, err = _trigger_jinx_effect(selected_effect, reason=f"sync={sync_now}")
        if not ok:
            error_text = err or "trigger_failed"
    elif selected_effect and not jinx_running:
        error_text = "jinx_not_running"

    _jinx_sync_state = sync_now
    db.set_state(
        state_key="app.jinx.sync_enabled",
        state_value=JINX_SYNC_ENABLED,
        source="jinx_sync",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )
    db.set_state(
        state_key="app.jinx.sync_state",
        state_value=sync_now,
        source="jinx_sync",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )
    db.set_state(
        state_key="app.jinx.environment",
        state_value=current_environment,
        source="jinx_sync",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )
    db.set_state(
        state_key="app.jinx.current_effect",
        state_value=_jinx_last_effect_code,
        source="jinx_sync",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )
    db.set_state(
        state_key="app.jinx.sync_error",
        state_value=error_text,
        source="jinx_sync",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )


def _sammi_status_value(value: Any, max_chars: int = 250) -> Any:
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False)
        except Exception:
            text = str(value)
        if len(text) > max_chars:
            return text[:max_chars]
        return text
    return value


def _map_gui_focus(code: int) -> str:
    mapping = {
        0: "Normal Flight",
        1: "Management",
        2: "Navigation",
        3: "Comms",
        4: "Roles",
        5: "Station Services",
        6: "Galaxy",
        7: "System",
        8: "Orrery",
        9: "FSS",
        10: "SAA",
        11: "Codex",
    }
    return mapping.get(code, f"Unknown({code})")


def _decode_flags(flags_int: int) -> dict[str, bool]:
    bit = lambda n: (flags_int & (1 << n)) != 0
    return {
        "Docked": bit(0),
        "Landed": bit(1),
        "LandingGearDown": bit(2),
        "ShieldsUp": bit(3),
        "Supercruise": bit(4),
        "FlightAssistOff": bit(5),
        "HardpointsDeployed": bit(6),
        "InWing": bit(7),
        "LightsOn": bit(8),
        "CargoScoopDeployed": bit(9),
        "SilentRunning": bit(10),
        "ScoopingFuel": bit(11),
        "SrvHandbrake": bit(12),
        "SrvTurret": bit(13),
        "SrvTurretRetracted": bit(14),
        "SrvDriveAssist": bit(15),
        "FsdMassLocked": bit(16),
        "FsdCharging": bit(17),
        "FsdCooldown": bit(18),
        "LowFuel": bit(19),
        "Overheating": bit(20),
        "HasLatLong": bit(21),
        "IsInDanger": bit(22),
        "BeingInterdicted": bit(23),
        "InMainShip": bit(24),
        "InFighter": bit(25),
        "InSRV": bit(26),
        "HudAnalysisMode": bit(27),
        "NightVision": bit(28),
        "AltitudeFromAverageRadius": bit(29),
        "FsdJump": bit(30),
        "SrvHighBeam": bit(31),
    }


def _decode_flags2(flags2_int: int) -> dict[str, bool]:
    bit = lambda n: (flags2_int & (1 << n)) != 0
    return {
        "OnFoot": bit(0),
        "InTaxi": bit(1),
        "InMulticrew": bit(2),
        "OnFootInStation": bit(3),
        "OnFootOnPlanet": bit(4),
        "AimDownSight": bit(5),
        "LowOxygen": bit(6),
        "LowHealth": bit(7),
        "Cold": bit(8),
        "Hot": bit(9),
        "VeryCold": bit(10),
        "VeryHot": bit(11),
        "GlideMode": bit(12),
        "OnFootInHangar": bit(13),
        "OnFootSocialSpace": bit(14),
        "OnFootExterior": bit(15),
        "BreathableAtmosphere": bit(16),
        "TelepresenceMulticrew": bit(17),
        "PhysicalMulticrew": bit(18),
        "FsdHyperdriveCharging": bit(19),
    }


def _flags_to_summary(flags: dict[str, bool]) -> str:
    active: list[str] = []
    if flags.get("Docked"):
        active.append("Docked")
    if flags.get("Landed"):
        active.append("Landed")
    if flags.get("LandingGearDown"):
        active.append("Gear Down")
    if flags.get("ShieldsUp"):
        active.append("Shields Up")
    if flags.get("Supercruise"):
        active.append("Supercruise")
    if flags.get("FlightAssistOff"):
        active.append("FA Off")
    if flags.get("HardpointsDeployed"):
        active.append("Hardpoints")
    if flags.get("InWing"):
        active.append("Wing")
    if flags.get("LightsOn"):
        active.append("Lights On")
    if flags.get("CargoScoopDeployed"):
        active.append("Scoop")
    if flags.get("SilentRunning"):
        active.append("Silent Running")
    if flags.get("ScoopingFuel"):
        active.append("Scooping Fuel")
    if flags.get("SrvHandbrake"):
        active.append("SRV Handbrake")
    if flags.get("SrvDriveAssist"):
        active.append("SRV DriveAssist")
    if flags.get("FsdMassLocked"):
        active.append("Mass Locked")
    if flags.get("FsdCharging"):
        active.append("FSD Charging")
    if flags.get("FsdCooldown"):
        active.append("FSD Cooldown")
    if flags.get("LowFuel"):
        active.append("Low Fuel")
    if flags.get("Overheating"):
        active.append("Overheating")
    if flags.get("HasLatLong"):
        active.append("Has Lat/Long")
    if flags.get("IsInDanger"):
        active.append("In Danger")
    if flags.get("BeingInterdicted"):
        active.append("Interdiction")
    if flags.get("InMainShip"):
        active.append("Main Ship")
    if flags.get("InFighter"):
        active.append("Fighter")
    if flags.get("InSRV"):
        active.append("SRV")
    return ", ".join(active) if active else "None"


def _map_environment(
    status: dict[str, Any], flags: dict[str, bool] | None, flags2: dict[str, bool] | None
) -> str:
    if flags2 and flags2.get("OnFoot"):
        if flags2.get("OnFootInStation"):
            return "On Foot - Station"
        if flags2.get("OnFootOnPlanet"):
            return "On Foot - Planet"
        return "On Foot"

    in_srv = bool(flags and flags.get("InSRV"))
    docked = bool(flags and flags.get("Docked"))
    landed = bool(flags and flags.get("Landed"))
    supercruise = bool(flags and flags.get("Supercruise"))
    fsd_jump = bool(flags and flags.get("FsdCharging"))
    has_lat_long = bool(flags and flags.get("HasLatLong"))

    if in_srv:
        return "Planet Surface - SRV"
    if docked:
        return "Docked"
    if landed:
        return "Planet Surface - Ship"
    if fsd_jump:
        return "Witch Space"
    if supercruise:
        return "Supercruise"
    if has_lat_long and not landed and not in_srv and not docked:
        return "Planet Orbit"
    return "Normal Space"


def _latest_journal_context() -> dict[str, Any]:
    global _journal_cache

    if not ED_JOURNAL_DIR.exists():
        return {}
    latest: Path | None = None
    latest_mtime = 0.0
    for p in ED_JOURNAL_DIR.glob("Journal.*.log"):
        try:
            mtime = p.stat().st_mtime
        except Exception:
            continue
        if mtime > latest_mtime:
            latest = p
            latest_mtime = mtime
    if latest is None:
        return {}

    try:
        stat = latest.stat()
    except Exception:
        return {}

    if (
        _journal_cache.get("path") == str(latest)
        and _journal_cache.get("size") == stat.st_size
        and _journal_cache.get("mtime") == stat.st_mtime
    ):
        values = _journal_cache.get("values")
        return values if isinstance(values, dict) else {}

    values: dict[str, Any] = {}
    try:
        with latest.open("rb") as f:
            tail_size = min(max(stat.st_size, 0), 2_000_000)
            if tail_size > 0:
                f.seek(-tail_size, 2)
            blob = f.read().decode("utf-8", errors="ignore")
        lines = [ln.strip() for ln in blob.splitlines() if ln.strip()]
        for line in reversed(lines):
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if not isinstance(ev, dict):
                continue
            event_name = str(ev.get("event") or "")
            if event_name == "LoadGame":
                if "ship_name" not in values and isinstance(ev.get("ShipName"), str):
                    values["ship_name"] = ev.get("ShipName")
                if "ship_model" not in values and isinstance(ev.get("Ship"), str):
                    values["ship_model"] = ev.get("Ship")
                if "ship_id" not in values and ev.get("ShipID") is not None:
                    values["ship_id"] = str(ev.get("ShipID"))
            if event_name in {"Location", "FSDJump"}:
                if "System" not in values:
                    star = ev.get("StarSystem") or ev.get("System")
                    if isinstance(star, str):
                        values["System"] = star
                if "Body" not in values:
                    body = ev.get("Body") or ev.get("BodyName")
                    if isinstance(body, str):
                        values["Body"] = body
            if event_name == "FSDTarget" and "destination" not in values:
                for candidate in [ev.get("Name"), ev.get("System"), ev.get("StarSystem")]:
                    if isinstance(candidate, str) and candidate.strip():
                        values["destination"] = candidate.strip()
                        break
            if (
                "ship_name" in values
                and "ship_model" in values
                and "ship_id" in values
                and "System" in values
                and "Body" in values
                and "destination" in values
            ):
                break
    except Exception:
        pass

    _journal_cache = {
        "path": str(latest),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "values": values,
    }
    return values


def _read_nav_route_vars() -> dict[str, str]:
    if not ED_NAVROUTE_PATH.exists():
        return {
            "nav_route": "",
            "nav_route_origin": "",
            "nav_route_destination": "",
        }
    parsed = _read_json_file(ED_NAVROUTE_PATH)
    route = parsed.get("Route")
    if not isinstance(route, list):
        return {
            "nav_route": "",
            "nav_route_origin": "",
            "nav_route_destination": "",
        }
    systems = [
        step.get("StarSystem")
        for step in route
        if isinstance(step, dict) and isinstance(step.get("StarSystem"), str)
    ]
    systems = [s for s in systems if s]
    text = ""
    origin = ""
    dest = ""
    if len(systems) == 1:
        origin = systems[0]
        dest = systems[0]
        text = f"Course set for {dest}"
    elif len(systems) == 2:
        origin = systems[0]
        dest = systems[1]
        text = f"Course set for {dest} from {origin}"
    elif len(systems) > 2:
        origin = systems[0]
        dest = systems[-1]
        via = ", ".join(systems[1:-1])
        text = f"Course set for {dest} from {origin} via {via}"
    return {
        "nav_route": text,
        "nav_route_origin": origin,
        "nav_route_destination": dest,
    }


def _build_sammi_variable_map(db: BrainstemDB, *, ed_running: bool) -> dict[str, Any]:
    global _sammi_heartbeat

    def read_state(key: str) -> Any:
        row = db.get_state(key)
        if not row:
            return None
        return row.get("state_value")

    var_map: dict[str, Any] = {}
    status = _read_json_file(ED_STATUS_PATH) if ed_running else {}
    flags: dict[str, bool] | None = None
    flags2: dict[str, bool] | None = None

    if isinstance(status, dict) and status:
        for key, raw in status.items():
            var_map[str(key)] = _sammi_status_value(raw)

        if isinstance(status.get("GuiFocus"), int):
            var_map["gui_focus"] = _map_gui_focus(int(status.get("GuiFocus")))

        if isinstance(status.get("Fuel"), dict):
            fuel = status.get("Fuel", {})
            var_map["Fuel"] = _sammi_status_value(fuel)
            if isinstance(fuel.get("FuelMain"), (int, float)):
                var_map["FuelMain"] = fuel.get("FuelMain")
                var_map["fuel_main"] = fuel.get("FuelMain")
            if isinstance(fuel.get("FuelReservoir"), (int, float)):
                var_map["FuelReservoir"] = fuel.get("FuelReservoir")
                var_map["fuel_reservoir"] = fuel.get("FuelReservoir")

        if isinstance(status.get("Flags"), int):
            flags = _decode_flags(int(status.get("Flags")))
            var_map["Flags"] = int(status.get("Flags"))
            var_map["docked"] = "Docked" if flags["Docked"] else "Not Docked"
            var_map["landed"] = "Landed" if flags["Landed"] else "Not Landed"
            var_map["landing_gear"] = "Deployed" if flags["LandingGearDown"] else "Retracted"
            var_map["shields_up"] = "Up" if flags["ShieldsUp"] else "Down"
            var_map["supercruise"] = "Engaged" if flags["Supercruise"] else "Disengaged"
            var_map["fa"] = "Off" if flags["FlightAssistOff"] else "On"
            var_map["hardpoints"] = "Deployed" if flags["HardpointsDeployed"] else "Retracted"
            var_map["in_wing"] = "True" if flags["InWing"] else "False"
            var_map["lights"] = "On" if flags["LightsOn"] else "Off"
            var_map["cargoscoop"] = "Deployed" if flags["CargoScoopDeployed"] else "Retracted"
            var_map["silent_running"] = "True" if flags["SilentRunning"] else "False"
            var_map["scooping_fuel"] = "True" if flags["ScoopingFuel"] else "False"
            var_map["srv_handbrake"] = "True" if flags["SrvHandbrake"] else "False"
            var_map["srv_turret_view"] = "True" if flags["SrvTurret"] else "False"
            var_map["srv_turret_retracted"] = "True" if flags["SrvTurretRetracted"] else "False"
            var_map["srv_drive_assist"] = "True" if flags["SrvDriveAssist"] else "False"
            var_map["fsd_mass_locked"] = "True" if flags["FsdMassLocked"] else "False"
            var_map["fsd_charging"] = "True" if flags["FsdCharging"] else "False"
            var_map["fsd_cooldown"] = "True" if flags["FsdCooldown"] else "False"
            var_map["low_fuel"] = "True" if flags["LowFuel"] else "False"
            var_map["overheating"] = "True" if flags["Overheating"] else "False"
            var_map["has_lat_long"] = "True" if flags["HasLatLong"] else "False"
            var_map["is_in_danger"] = "True" if flags["IsInDanger"] else "False"
            var_map["being_interdicted"] = "True" if flags["BeingInterdicted"] else "False"
            var_map["in_main_ship"] = "True" if flags["InMainShip"] else "False"
            var_map["in_fighter"] = "True" if flags["InFighter"] else "False"
            var_map["in_srv"] = "True" if flags["InSRV"] else "False"
            var_map["hud_analysis_mode"] = "True" if flags["HudAnalysisMode"] else "False"
            var_map["nightvision"] = "On" if flags["NightVision"] else "Off"
            var_map["fsd_jump"] = "Jump" if flags["FsdJump"] else "Idle"
            var_map["srv_high_beam"] = "On" if flags["SrvHighBeam"] else "Off"
            var_map["flags_text"] = _flags_to_summary(flags)

        if isinstance(status.get("Flags2"), int):
            flags2 = _decode_flags2(int(status.get("Flags2")))
            var_map["Flags2"] = int(status.get("Flags2"))
            var_map["on_foot"] = "True" if flags2["OnFoot"] else "False"
            var_map["in_taxi"] = "True" if flags2["InTaxi"] else "False"
            var_map["in_multicrew"] = "True" if flags2["InMulticrew"] else "False"
            var_map["on_foot_in_station"] = "True" if flags2["OnFootInStation"] else "False"
            var_map["on_foot_on_planet"] = "True" if flags2["OnFootOnPlanet"] else "False"
            var_map["aim_down_sight"] = "True" if flags2["AimDownSight"] else "False"
            var_map["low_oxygen"] = "True" if flags2["LowOxygen"] else "False"
            var_map["low_health"] = "True" if flags2["LowHealth"] else "False"
            var_map["cold"] = "True" if flags2["Cold"] else "False"
            var_map["hot"] = "True" if flags2["Hot"] else "False"
            var_map["very_cold"] = "True" if flags2["VeryCold"] else "False"
            var_map["very_hot"] = "True" if flags2["VeryHot"] else "False"
            var_map["glide_mode"] = "True" if flags2["GlideMode"] else "False"
            var_map["on_foot_in_hangar"] = "True" if flags2["OnFootInHangar"] else "False"
            var_map["on_foot_social_space"] = "True" if flags2["OnFootSocialSpace"] else "False"
            var_map["on_foot_exterior"] = "True" if flags2["OnFootExterior"] else "False"
            var_map["breathable_atmosphere"] = "True" if flags2["BreathableAtmosphere"] else "False"
            var_map["telepresence_multicrew"] = (
                "True" if flags2["TelepresenceMulticrew"] else "False"
            )
            var_map["physical_multicrew"] = "True" if flags2["PhysicalMulticrew"] else "False"
            var_map["fsd_hyperdrive_charging"] = (
                "True" if flags2["FsdHyperdriveCharging"] else "False"
            )

        env = _map_environment(status, flags, flags2)
        var_map["flightstatus"] = env
        var_map["environment"] = env

        if isinstance(status.get("Cargo"), (int, float)):
            var_map["cargo"] = status.get("Cargo")
            var_map["Cargo"] = status.get("Cargo")
        if isinstance(status.get("Balance"), (int, float)):
            var_map["balance"] = status.get("Balance")
            var_map["balance_raw"] = status.get("Balance")
            var_map["Balance"] = status.get("Balance")
        if isinstance(status.get("LegalState"), str):
            var_map["legal_state"] = status.get("LegalState")
            var_map["LegalState"] = status.get("LegalState")
        if isinstance(status.get("Pips"), list):
            var_map["Pips"] = _sammi_status_value(status.get("Pips"))
            pips = status.get("Pips")
            if len(pips) >= 3:
                var_map["pips_sys"] = str(pips[0])
                var_map["pips_eng"] = str(pips[1])
                var_map["pips_wea"] = str(pips[2])
        if isinstance(status.get("FireGroup"), int):
            var_map["FireGroup"] = status.get("FireGroup")
            var_map["fire_group"] = status.get("FireGroup")
        if isinstance(status.get("GuiFocus"), int):
            var_map["GuiFocus"] = status.get("GuiFocus")
            var_map["gui_focus_raw"] = status.get("GuiFocus")
        if status.get("Latitude") is not None:
            var_map["latitude_raw"] = status.get("Latitude")
            var_map["latitude"] = str(status.get("Latitude"))
        if status.get("Longitude") is not None:
            var_map["longitude_raw"] = status.get("Longitude")
            var_map["longitude"] = str(status.get("Longitude"))
        if status.get("Altitude") is not None:
            var_map["altitude"] = str(status.get("Altitude"))
        if status.get("Heading") is not None:
            var_map["heading"] = str(status.get("Heading"))
        if status.get("Oxygen") is not None:
            var_map["oxygen_raw"] = status.get("Oxygen")
            var_map["oxygen"] = str(status.get("Oxygen"))
        if status.get("Health") is not None:
            var_map["health_raw"] = status.get("Health")
            var_map["health"] = str(status.get("Health"))
        if status.get("Temperature") is not None:
            var_map["temperature_raw"] = status.get("Temperature")
            var_map["temperature"] = str(status.get("Temperature"))
        if isinstance(status.get("SelectedWeapon"), str):
            var_map["selected_weapon"] = status.get("SelectedWeapon")
        if isinstance(status.get("SelectedWeapon_Localised"), str):
            var_map["selected_weapon_localised"] = status.get("SelectedWeapon_Localised")
        if isinstance(status.get("System"), str):
            var_map["System"] = status.get("System")
            var_map["current_system"] = status.get("System")
        if isinstance(status.get("Body"), str):
            var_map["Body"] = status.get("Body")
            var_map["current_location"] = status.get("Body")
        elif isinstance(status.get("BodyName"), str):
            var_map["Body"] = status.get("BodyName")
            var_map["current_location"] = status.get("BodyName")

        destination = status.get("Destination")
        has_destination = isinstance(destination, dict) and bool(destination)
        var_map["target_set"] = "true" if has_destination else "false"
        if has_destination:
            var_map["Destination"] = _sammi_status_value(destination)
            dest_name = ""
            for candidate in [
                destination.get("Name"),
                destination.get("Body"),
                destination.get("SystemName"),
                destination.get("StarSystem"),
                destination.get("System"),
            ]:
                if isinstance(candidate, str) and candidate.strip() and not candidate.strip().isdigit():
                    dest_name = candidate.strip()
                    break
            var_map["destination"] = dest_name
        else:
            var_map["Destination"] = ""
            var_map["destination"] = ""

        if isinstance(status.get("timestamp"), str):
            var_map["timestamp"] = status.get("timestamp")
        if isinstance(status.get("event"), str):
            var_map["event"] = status.get("event")

    journal_ctx = _latest_journal_context()
    for name in ["ship_name", "ship_model", "ship_id"]:
        if name not in var_map and journal_ctx.get(name) is not None:
            var_map[name] = journal_ctx.get(name)
    if "System" not in var_map and isinstance(journal_ctx.get("System"), str):
        var_map["System"] = journal_ctx.get("System")
        var_map["current_system"] = journal_ctx.get("System")
    if "Body" not in var_map and isinstance(journal_ctx.get("Body"), str):
        var_map["Body"] = journal_ctx.get("Body")
        var_map["current_location"] = journal_ctx.get("Body")
    if (not var_map.get("destination")) and isinstance(journal_ctx.get("destination"), str):
        var_map["destination"] = journal_ctx.get("destination")

    var_map.update(_read_nav_route_vars())

    hull_raw = read_state("ed.telemetry.hull_percent")
    if isinstance(hull_raw, (int, float)):
        var_map["hull_percent"] = round(float(hull_raw) * 100.0, 2)

    title = str(read_state("music.track.title") or "").strip()
    artist = str(read_state("music.track.artist") or "").strip()
    now_playing = " - ".join([part for part in [title, artist] if part]).strip()
    var_map["YTM_Title"] = title
    var_map["YTM_Artist"] = artist
    var_map["YTM_NowPlaying"] = now_playing

    if ed_running:
        _sammi_heartbeat += 1
        var_map["Heartbeat"] = _sammi_heartbeat

    for name in LEGACY_SAMMI_VARIABLES:
        if name not in var_map:
            var_map[name] = ""

    return var_map


def process_sammi_bridge(db: BrainstemDB, *, ed_running: bool) -> None:
    if not SAMMI_API_ENABLED:
        return
    if SAMMI_API_ONLY_WHEN_ED and not ed_running:
        return

    var_map = _build_sammi_variable_map(db, ed_running=ed_running)
    if "sync" not in _sammi_last_sent:
        var_map["sync"] = "off"
    changed = 0
    deferred = 0
    t0 = time.perf_counter()
    error_text: str | None = None
    sent_count = 0
    max_per_cycle = max(1, int(SAMMI_API_MAX_UPDATES_PER_CYCLE))
    pulse_var_names = [SAMMI_NEW_WRITE_VAR]
    if SAMMI_NEW_WRITE_COMPAT_VAR and SAMMI_NEW_WRITE_COMPAT_VAR not in pulse_var_names:
        pulse_var_names.append(SAMMI_NEW_WRITE_COMPAT_VAR)

    def _set_pulse_var(name: str, value: str, *, force_send: bool = False) -> bool:
        nonlocal changed, deferred, error_text, sent_count
        if not name:
            return False
        if not force_send and _sammi_last_sent.get(name) == value:
            return True
        if sent_count >= max_per_cycle:
            deferred += 1
            return False
        ok, err = _sammi_post("setVariable", {"name": name, "value": value})
        if not ok:
            if not error_text:
                error_text = err or "sammi_request_failed"
            return False
        _sammi_last_sent[name] = value
        changed += 1
        sent_count += 1
        return True

    changed_items: list[tuple[str, Any]] = []
    for name, value in var_map.items():
        if name in pulse_var_names:
            continue
        if _sammi_last_sent.get(name) != value:
            changed_items.append((name, value))
    priority_rank = {name: idx for idx, name in enumerate(SAMMI_PRIORITY_VARS)}
    changed_items.sort(key=lambda item: priority_rank.get(item[0], 9999))

    pulse_trigger = any(
        name not in SAMMI_NEW_WRITE_IGNORE_VARS and name not in pulse_var_names
        for name, _value in changed_items
    )

    if pulse_trigger:
        for pulse_name in pulse_var_names:
            _set_pulse_var(pulse_name, "yes", force_send=True)

    for idx, (name, value) in enumerate(changed_items):
        if sent_count >= max_per_cycle:
            deferred += 1
            continue
        ok, err = _sammi_post("setVariable", {"name": name, "value": value})
        if not ok:
            error_text = err or "sammi_request_failed"
            deferred += max(0, len(changed_items) - idx - 1)
            break
        _sammi_last_sent[name] = value
        changed += 1
        sent_count += 1

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    db.set_state(
        state_key="app.sammi.api.enabled",
        state_value=SAMMI_API_ENABLED,
        source="sammi_bridge",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )
    db.set_state(
        state_key="app.sammi.api.endpoint",
        state_value=f"http://{SAMMI_API_HOST}:{SAMMI_API_PORT}/api",
        source="sammi_bridge",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )
    db.set_state(
        state_key="app.sammi.api.last_push_count",
        state_value=changed,
        source="sammi_bridge",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )
    db.set_state(
        state_key="app.sammi.api.deferred_count",
        state_value=deferred,
        source="sammi_bridge",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )
    db.set_state(
        state_key="app.sammi.api.last_cycle_ms",
        state_value=elapsed_ms,
        source="sammi_bridge",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )
    db.set_state(
        state_key="app.sammi.api.last_error",
        state_value=error_text,
        source="sammi_bridge",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )


def collect_hardware_state() -> dict[str, Any]:
    probe = _read_json_file(HARDWARE_PROBE_JSON)
    if probe:
        cpu_percent = _probe_float(
            probe,
            "cpu_percent",
            "cpu.usagePercent",
            "cpu.usage",
            "cpu.loadPct",
        )
        cpu_temp_c = _probe_float(
            probe,
            "cpu_temp_c",
            "cpu.temp_c",
            "cpu.tempC",
        )
        gpu_temp_c = _probe_float(
            probe,
            "gpu_temp_c",
            "gpu.temp_c",
            "gpu.tempC",
        )
        gpu_percent = _probe_float(
            probe,
            "gpu_percent",
            "gpu_usage_percent",
            "gpu.usagePercent",
            "gpu.usage",
            "gpu.loadPct",
        )
        memory_used_pct = _normalize_ratio(
            _probe_float(
                probe,
                "memory_used_percent",
                "memory.used_percent",
                "memory.usedPct",
                "memory.loadPct",
            )
        )
        return {
            "hardware.cpu_percent": cpu_percent,
            "hardware.cpu_temp_c": cpu_temp_c,
            "hardware.gpu_temp_c": gpu_temp_c,
            "hardware.gpu_percent": gpu_percent,
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
        "hardware.cpu_temp_c": None,
        "hardware.gpu_temp_c": None,
        "hardware.gpu_percent": None,
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
        "ed.telemetry.landed": telemetry.get("landed"),
        "ed.telemetry.shield_up": telemetry.get("shield_up"),
        "ed.telemetry.lights_on": telemetry.get("lights_on"),
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
    _write_hardware_stats_txt(values)
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


def process_edparser(
    db: BrainstemDB,
    ed_running: bool,
    previous_running: bool | None,
    previous_error: str | None,
) -> tuple[bool, str | None]:
    correlation_id = str(uuid.uuid4())

    status = EDPARSER_TOOL.status()
    action = "status"
    if EDPARSER_AUTORUN:
        if ed_running and not bool(status.get("running")):
            status = EDPARSER_TOOL.start(reason="supervisor_ed_running")
            action = "start"
        elif not ed_running and bool(status.get("running")):
            status = EDPARSER_TOOL.stop(reason="supervisor_ed_stopped")
            action = "stop"
    running = bool(status.get("running"))
    current_error = status.get("last_error")
    if current_error is not None:
        current_error = str(current_error)

    values = {
        "capability.edparser.available": bool(status.get("enabled", False))
        and bool(status.get("script_exists", False)),
        "ed.parser.autorun": EDPARSER_AUTORUN,
        "ed.parser.enabled": bool(status.get("enabled", False)),
        "ed.parser.running": running,
        "ed.parser.pid": status.get("pid"),
        "ed.parser.managed_by": status.get("managed_by"),
        "ed.parser.last_error": current_error,
        "ed.parser.last_exit_code": status.get("last_exit_code"),
    }
    items = make_state_items(
        values=values,
        source="edparser_supervisor",
        correlation_id=correlation_id,
        mode="game" if ed_running else "standby",
    )
    db.batch_set_state(items=items, emit_events=True)

    if previous_running is not None and previous_running != running:
        db.append_event(
            event_id=str(uuid.uuid4()),
            timestamp_utc=utc_now_iso(),
            event_type="EDPARSER_STARTED" if running else "EDPARSER_STOPPED",
            source="edparser_supervisor",
            payload={
                "running": running,
                "pid": status.get("pid"),
                "managed_by": status.get("managed_by"),
                "autorun": EDPARSER_AUTORUN,
                "action": action,
            },
            profile=PROFILE,
            session_id=SESSION_ID,
            correlation_id=correlation_id,
            mode="game" if ed_running else "standby",
            severity="info",
            tags=["edparser", "tool"],
        )

    if current_error and current_error != previous_error:
        db.append_event(
            event_id=str(uuid.uuid4()),
            timestamp_utc=utc_now_iso(),
            event_type="EDPARSER_ERROR",
            source="edparser_supervisor",
            payload={
                "error": current_error,
                "running": running,
                "action": action,
                "enabled": bool(status.get("enabled", False)),
                "script_path": status.get("script_path"),
            },
            profile=PROFILE,
            session_id=SESSION_ID,
            correlation_id=correlation_id,
            mode="game" if ed_running else "standby",
            severity="warn",
            tags=["edparser", "tool", "error"],
        )
    elif previous_error and not current_error:
        db.append_event(
            event_id=str(uuid.uuid4()),
            timestamp_utc=utc_now_iso(),
            event_type="EDPARSER_RECOVERED",
            source="edparser_supervisor",
            payload={
                "running": running,
                "pid": status.get("pid"),
                "action": action,
            },
            profile=PROFILE,
            session_id=SESSION_ID,
            correlation_id=correlation_id,
            mode="game" if ed_running else "standby",
            severity="info",
            tags=["edparser", "tool"],
        )

    return running, current_error


def process_aux_apps(
    db: BrainstemDB,
    *,
    ed_running: bool,
    previous_running: dict[str, bool] | None,
    managed_ed_ahk_pid: int | None,
) -> tuple[dict[str, bool], int | None]:
    global _ed_ahk_last_launch_attempt

    correlation_id = str(uuid.uuid4())
    now = utc_now_iso()
    process_names = _list_process_names()

    sammi_path = _path_or_none(SAMMI_EXE)
    jinx_path = _path_or_none(JINX_EXE)
    ed_ahk_path = _path_or_none(ED_AHK_PATH)

    sammi_running = _process_running_by_names(process_names, SAMMI_PROCESS_NAMES)
    jinx_running = _process_running_by_names(process_names, JINX_PROCESS_NAMES)

    if isinstance(managed_ed_ahk_pid, int) and managed_ed_ahk_pid > 0 and not _pid_running(managed_ed_ahk_pid):
        managed_ed_ahk_pid = None

    ed_ahk_running = False
    ed_ahk_pids: list[int] = []
    if _pid_running(managed_ed_ahk_pid):
        ed_ahk_running = True
    elif ed_ahk_path:
        ed_ahk_pids = _find_ahk_script_pids(ed_ahk_path)
        ed_ahk_running = bool(ed_ahk_pids)

    sammi_error: str | None = None
    jinx_error: str | None = None
    ed_ahk_error: str | None = None

    if AUX_APPS_AUTORUN and ed_running:
        if SAMMI_ENABLED and sammi_path and not sammi_running:
            ok, _pid, err = _launch_executable(sammi_path)
            if ok:
                sammi_running = True
            else:
                sammi_error = err or "failed to launch"

        if JINX_ENABLED and jinx_path and not jinx_running:
            ok, _pid, err = _launch_executable_via_helper(jinx_path, JINX_LAUNCH_ARGS)
            if ok:
                jinx_running = True
            else:
                jinx_error = err or "failed to launch"

        can_restart_ahk = (time.monotonic() - _ed_ahk_last_launch_attempt) >= ED_AHK_RESTART_BACKOFF_SEC
        if ED_AHK_ENABLED and ed_ahk_path and not ed_ahk_running and can_restart_ahk:
            _ed_ahk_last_launch_attempt = time.monotonic()
            if ed_ahk_path.suffix.lower() == ".ahk":
                ahk_bin = _resolve_ahk_bin()
                if not ahk_bin:
                    ed_ahk_error = "AutoHotkey executable not found"
                else:
                    ok, pid, err = _launch_executable(Path(ahk_bin), [str(ed_ahk_path)])
                    if ok:
                        managed_ed_ahk_pid = pid
                        ed_ahk_running = True
                    else:
                        ed_ahk_error = err or "failed to launch ed.ahk"
            else:
                ok, pid, err = _launch_executable(ed_ahk_path)
                if ok:
                    managed_ed_ahk_pid = pid
                    ed_ahk_running = True
                else:
                    ed_ahk_error = err or "failed to launch ed.ahk executable"
        elif ED_AHK_ENABLED and ed_ahk_path and not ed_ahk_running and ed_ahk_error is None:
            ed_ahk_error = f"ed.ahk restart backoff active ({ED_AHK_RESTART_BACKOFF_SEC:.1f}s)"

    if AUX_APPS_AUTORUN and not ed_running and ED_AHK_ENABLED and ED_AHK_STOP_ON_EXIT:
        stopped = False
        if _pid_running(managed_ed_ahk_pid):
            if not _pid_matches_ahk_script(managed_ed_ahk_pid, ed_ahk_path):
                managed_ed_ahk_pid = None
            elif _is_protected_ahk_pid(managed_ed_ahk_pid):
                pass
            else:
                stopped = _terminate_pid(int(managed_ed_ahk_pid), force=True)
                managed_ed_ahk_pid = None
        if ed_ahk_path:
            for pid in _find_ahk_script_pids(ed_ahk_path):
                if _is_protected_ahk_pid(pid):
                    continue
                if _terminate_pid(pid, force=True):
                    stopped = True
        if stopped:
            ed_ahk_running = False
        elif ed_ahk_running:
            ed_ahk_error = "ed.ahk stop requested but process still running"
    if not ed_running:
        managed_ed_ahk_pid = None

    values = {
        "app.aux.autorun": AUX_APPS_AUTORUN,
        "app.sammi.enabled": SAMMI_ENABLED,
        "app.sammi.path": str(sammi_path) if sammi_path else SAMMI_EXE or None,
        "app.sammi.running": sammi_running,
        "app.sammi.last_error": sammi_error,
        "app.jinx.enabled": JINX_ENABLED,
        "app.jinx.path": str(jinx_path) if jinx_path else JINX_EXE or None,
        "app.jinx.running": jinx_running,
        "app.jinx.last_error": jinx_error,
        "app.ed_ahk.enabled": ED_AHK_ENABLED,
        "app.ed_ahk.path": str(ed_ahk_path) if ed_ahk_path else ED_AHK_PATH or None,
        "app.ed_ahk.running": ed_ahk_running,
        "app.ed_ahk.last_error": ed_ahk_error,
        "app.ed_ahk.pid": managed_ed_ahk_pid,
    }
    items = make_state_items(
        values=values,
        source="aux_app_supervisor",
        correlation_id=correlation_id,
        mode="game" if ed_running else "standby",
    )
    db.batch_set_state(items=items, emit_events=True)

    current = {
        "sammi": sammi_running,
        "jinx": jinx_running,
        "ed_ahk": ed_ahk_running,
    }
    if previous_running:
        for app_key, running in current.items():
            previous = previous_running.get(app_key)
            if previous == running:
                continue
            db.append_event(
                event_id=str(uuid.uuid4()),
                timestamp_utc=now,
                event_type="AUX_APP_STARTED" if running else "AUX_APP_STOPPED",
                source="aux_app_supervisor",
                payload={
                    "app": app_key,
                    "running": running,
                    "ed_running": ed_running,
                    "autorun": AUX_APPS_AUTORUN,
                },
                profile=PROFILE,
                session_id=SESSION_ID,
                correlation_id=correlation_id,
                mode="game" if ed_running else "standby",
                severity="info",
                tags=["aux_app"],
            )

    for app_key, error_value in [
        ("sammi", sammi_error),
        ("jinx", jinx_error),
        ("ed_ahk", ed_ahk_error),
    ]:
        if not error_value:
            continue
        db.append_event(
            event_id=str(uuid.uuid4()),
            timestamp_utc=now,
            event_type="AUX_APP_ERROR",
            source="aux_app_supervisor",
            payload={
                "app": app_key,
                "error": error_value,
                "ed_running": ed_running,
                "autorun": AUX_APPS_AUTORUN,
            },
            profile=PROFILE,
            session_id=SESSION_ID,
            correlation_id=correlation_id,
            mode="game" if ed_running else "standby",
            severity="warn",
            tags=["aux_app", "error"],
        )

    return current, managed_ed_ahk_pid


def process_music(
    db: BrainstemDB,
    previous_playing: bool | None,
    previous_track: tuple[str, str] | None,
) -> tuple[bool, tuple[str, str]]:
    correlation_id = str(uuid.uuid4())
    music_playing_row = db.get_state("music.playing")
    music_title_row = db.get_state("music.track.title")
    music_artist_row = db.get_state("music.track.artist")
    music_now_playing_row = db.get_state("music.now_playing")

    playing_raw = music_playing_row.get("state_value") if music_playing_row else None
    if isinstance(playing_raw, bool):
        playing = playing_raw
    elif isinstance(playing_raw, (int, float)):
        playing = bool(playing_raw)
    elif isinstance(playing_raw, str):
        playing = playing_raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        playing = False

    title = str((music_title_row or {}).get("state_value") or "").strip()
    artist = str((music_artist_row or {}).get("state_value") or "").strip()
    now_playing_obj = (music_now_playing_row or {}).get("state_value")
    if isinstance(now_playing_obj, dict):
        if not title:
            title = str(now_playing_obj.get("title") or "").strip()
        if not artist:
            artist = str(now_playing_obj.get("artist") or "").strip()
        if (not title or not artist) and isinstance(now_playing_obj.get("now_playing"), str):
            combined = str(now_playing_obj.get("now_playing") or "").strip()
            if combined and " - " in combined:
                parts = [part.strip() for part in combined.split(" - ", 1)]
                if len(parts) == 2:
                    if not title:
                        title = parts[0]
                    if not artist:
                        artist = parts[1]

    if not playing and (title or artist):
        playing = True
    track = (title, artist)

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


def determine_watch_condition(db: BrainstemDB, ed_running: bool) -> str:
    if FORCE_WATCH_CONDITION:
        return FORCE_WATCH_CONDITION

    degraded = db.get_state("system.degraded")
    restricted = db.get_state("system.restricted_mode")
    if degraded and bool(degraded.get("state_value")):
        return "DEGRADED"
    if restricted and bool(restricted.get("state_value")):
        return "RESTRICTED"
    if ed_running:
        return "GAME"
    return "STANDBY"


def handover_snapshot(db: BrainstemDB) -> dict[str, Any]:
    hardware_mem = db.get_state("hardware.memory_used_percent")
    ed_running = db.get_state("ed.running")
    ed_system = db.get_state("ed.telemetry.system_name")
    music_playing = db.get_state("music.playing")
    music_title = db.get_state("music.track.title")
    music_artist = db.get_state("music.track.artist")
    ai_local = db.get_state("ai.local.available")
    ai_cloud = db.get_state("ai.cloud.available")
    ai_degraded = db.get_state("ai.degraded")
    ed_parser_running = db.get_state("ed.parser.running")
    ed_parser_error = db.get_state("ed.parser.last_error")
    sammi_running = db.get_state("app.sammi.running")
    jinx_running = db.get_state("app.jinx.running")
    ed_ahk_running = db.get_state("app.ed_ahk.running")

    alarms: list[str] = []
    mem_value = hardware_mem.get("state_value") if hardware_mem else None
    if isinstance(mem_value, (int, float)) and mem_value >= HARDWARE_MEMORY_THRESHOLD:
        alarms.append("hardware.memory_used_percent_high")

    ai_status = "unknown"
    if ai_degraded and bool(ai_degraded.get("state_value")):
        ai_status = "degraded"
    else:
        local_on = bool(ai_local and ai_local.get("state_value"))
        cloud_on = bool(ai_cloud and ai_cloud.get("state_value"))
        if local_on and cloud_on:
            ai_status = "local+cloud"
        elif local_on:
            ai_status = "local_only"
        elif cloud_on:
            ai_status = "cloud_only"

    return {
        "equipment": {
            "hardware_probe": bool(hardware_mem),
            "ed_probe": bool(ed_running),
            "music_probe": bool(music_playing),
        },
        "current_alarms": alarms,
        "ed_status": {
            "running": ed_running.get("state_value") if ed_running else None,
            "system_name": ed_system.get("state_value") if ed_system else None,
            "parser_running": ed_parser_running.get("state_value") if ed_parser_running else None,
            "parser_error": ed_parser_error.get("state_value") if ed_parser_error else None,
            "aux_apps": {
                "sammi_running": sammi_running.get("state_value") if sammi_running else None,
                "jinx_running": jinx_running.get("state_value") if jinx_running else None,
                "ed_ahk_running": ed_ahk_running.get("state_value") if ed_ahk_running else None,
            },
        },
        "music_status": {
            "playing": music_playing.get("state_value") if music_playing else None,
            "title": music_title.get("state_value") if music_title else None,
            "artist": music_artist.get("state_value") if music_artist else None,
        },
        "ai_status": ai_status,
    }


def process_watch_condition(
    db: BrainstemDB,
    previous_condition: str | None,
    ed_running: bool,
) -> str:
    condition = determine_watch_condition(db, ed_running)
    now = utc_now_iso()
    db.set_state(
        state_key="system.watch_condition",
        state_value=condition,
        source="watch_condition_supervisor",
        observed_at_utc=now,
        confidence=1.0,
        emit_event=True,
        event_meta={
            "event_id": str(uuid.uuid4()),
            "timestamp_utc": now,
            "event_type": "STATE_UPDATED",
            "event_source": "watch_condition_supervisor",
            "profile": PROFILE,
            "session_id": SESSION_ID,
            "mode": condition.lower() if condition.lower() in {"game", "work", "standby", "tutor"} else "standby",
            "payload": {"state_key": "system.watch_condition", "value": condition},
            "tags": ["watch_condition"],
        },
    )

    if previous_condition == condition:
        return condition

    correlation_id = str(uuid.uuid4())
    db.append_event(
        event_id=str(uuid.uuid4()),
        timestamp_utc=now,
        event_type="WATCH_CONDITION_CHANGED",
        source="watch_condition_supervisor",
        payload={"from": previous_condition, "to": condition},
        profile=PROFILE,
        session_id=SESSION_ID,
        correlation_id=correlation_id,
        mode=condition.lower() if condition.lower() in {"game", "work", "standby", "tutor"} else "standby",
        severity="info",
        tags=["watch_condition", "handover"],
    )
    db.append_event(
        event_id=str(uuid.uuid4()),
        timestamp_utc=now,
        event_type="HANDOVER_NOTE",
        source="watch_condition_supervisor",
        payload=handover_snapshot(db),
        profile=PROFILE,
        session_id=SESSION_ID,
        correlation_id=correlation_id,
        mode=condition.lower() if condition.lower() in {"game", "work", "standby", "tutor"} else "standby",
        severity="info",
        tags=["handover"],
    )

    return condition


def run_supervisor_loop() -> None:
    db = BrainstemDB(DB_PATH, SCHEMA_PATH)
    db.ensure_schema()
    print(f"Supervisor started. DB: {DB_PATH}")

    previous_ed_running: bool | None = None
    previous_edparser_running: bool | None = None
    previous_edparser_error: str | None = None
    previous_music_playing: bool | None = None
    previous_track: tuple[str, str] | None = None
    previous_watch_condition: str | None = None
    previous_aux_running: dict[str, bool] | None = None
    managed_ed_ahk_pid: int | None = None

    now = time.monotonic()
    next_hardware = now
    next_ed = now
    next_music = now

    while True:
        now = time.monotonic()

        if now >= next_hardware:
            jinx_running_for_stats = bool((previous_aux_running or {}).get("jinx"))
            if previous_aux_running is None:
                jinx_running_for_stats = _process_running_by_names(
                    _list_process_names(),
                    JINX_PROCESS_NAMES,
                )
            if (not SUP_HARDWARE_REQUIRES_JINX) or jinx_running_for_stats:
                process_hardware(db)
            next_hardware = now + HARDWARE_LOOP_SEC

        if now >= next_ed:
            previous_ed_running = process_ed(db, previous_ed_running)
            previous_edparser_running, previous_edparser_error = process_edparser(
                db=db,
                ed_running=previous_ed_running,
                previous_running=previous_edparser_running,
                previous_error=previous_edparser_error,
            )
            previous_aux_running, managed_ed_ahk_pid = process_aux_apps(
                db,
                ed_running=bool(previous_ed_running),
                previous_running=previous_aux_running,
                managed_ed_ahk_pid=managed_ed_ahk_pid,
            )
            process_jinx_sync(
                db,
                ed_running=bool(previous_ed_running),
                jinx_running=bool((previous_aux_running or {}).get("jinx")),
            )
            if previous_ed_running:
                process_sammi_bridge(db, ed_running=True)
            next_ed = now + (ED_ACTIVE_SEC if previous_ed_running else ED_IDLE_SEC)

        if now >= next_music:
            previous_music_playing, previous_track = process_music(
                db,
                previous_music_playing,
                previous_track,
            )
            if previous_ed_running:
                process_sammi_bridge(db, ed_running=True)
            next_music = now + (MUSIC_ACTIVE_SEC if previous_music_playing else MUSIC_IDLE_SEC)

        if previous_ed_running is not None:
            previous_watch_condition = process_watch_condition(
                db,
                previous_watch_condition,
                previous_ed_running,
            )

        next_due = min(next_hardware, next_ed, next_music)
        sleep_for = max(0.05, min(LOOP_SLEEP_SEC, next_due - time.monotonic()))
        time.sleep(sleep_for)


def run_supervisor_once() -> None:
    db = BrainstemDB(DB_PATH, SCHEMA_PATH)
    db.ensure_schema()
    ed_running = process_ed(db, previous_running=None)
    process_edparser(
        db,
        ed_running=ed_running,
        previous_running=None,
        previous_error=None,
    )
    aux_running, _ = process_aux_apps(
        db,
        ed_running=ed_running,
        previous_running=None,
        managed_ed_ahk_pid=None,
    )
    process_jinx_sync(
        db,
        ed_running=ed_running,
        jinx_running=bool((aux_running or {}).get("jinx")),
    )
    if (not SUP_HARDWARE_REQUIRES_JINX) or bool((aux_running or {}).get("jinx")):
        process_hardware(db)
    if ed_running:
        process_sammi_bridge(db, ed_running=True)
    process_music(db, previous_playing=None, previous_track=None)
    process_watch_condition(db, previous_condition=None, ed_running=ed_running)


def main() -> None:
    run_supervisor_loop()


if __name__ == "__main__":
    main()
