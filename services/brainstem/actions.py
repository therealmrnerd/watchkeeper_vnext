import ctypes
import json
import os
import runtime
import shlex
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from ctypes import windll
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import quote, urlparse

from runtime import (
    ADVISORY_ENABLED,
    ADVISORY_LLM_CONTROL_URL,
    ADVISORY_TIMEOUT_SEC,
    ADVISORY_URL,
    DB_PATH,
    DB_SERVICE,
    DEFAULT_WATCH_CONDITION,
    ED_PROVIDER_QUERY_SERVICE,
    EDPARSER_TOOL,
    ENABLE_ACTUATORS,
    ENABLE_KEYPRESS,
    KEYPRESS_ALLOWED_PROCESSES,
    KEYEVENTF_KEYUP,
    LIGHTS_WEBHOOK_TIMEOUT_SEC,
    LIGHTS_WEBHOOK_URL,
    LIGHTS_WEBHOOK_URL_TEMPLATE,
    LOGBOOK,
    PROVIDER_CONFIG_PATH,
    PROVIDER_HEALTH_ENABLED,
    PROVIDER_SECRETS_PATH,
    SAMMI_CLIENT,
    SPECIAL_VK_MAP,
    TOOL_ROUTER,
    TWITCH_DEV_INGEST_ENABLED,
    TWITCH_CHAT_SEND_BUTTON,
    TWITCH_CHAT_STRICT_CONFIRM,
    TWITCH_CHAT_SEND_VAR,
    TWITCH_INGEST_SERVICE,
    TWITCH_REPO,
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    connect_db,
    iso8601_utc_to_epoch,
    parse_iso8601_utc,
    parse_json,
    utc_now_iso,
)
from core.ed_provider_types import ProviderId, ProviderOperationId, ProviderQuery
from provider_health import build_provider_health_probes
from provider_secrets import clear_provider_secret_entry, save_edsm_secret_entry, save_inara_secret_entry, save_openai_secret_entry
from settings_store import load_runtime_settings, runtime_setting_enabled, save_runtime_settings
from mfd_layout_store import save_layout, save_outputs

NO_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ADVISORY_LLM_CONTROL_TIMEOUT_SEC = float(os.getenv("WKV_ADVISORY_LLM_CONTROL_TIMEOUT_SEC", "180"))
KEYPRESS_BACKEND = os.getenv("WKV_KEYPRESS_BACKEND", "win32").strip().lower() or "win32"
COCKPIT_CONTROL_BACKEND = os.getenv("WKV_COCKPIT_CONTROL_BACKEND", "ahk").strip().lower() or "ahk"
COCKPIT_MODE_KEY = os.getenv("WKV_COCKPIT_MODE_KEY", "m").strip() or "m"
FLIGHT_ASSIST_KEY = os.getenv("WKV_FLIGHT_ASSIST_KEY", "z").strip() or "z"
SUPERCRUISE_KEY = os.getenv("WKV_SUPERCRUISE_KEY", "j").strip() or "j"
HYPERSPACE_KEY = os.getenv("WKV_HYPERSPACE_KEY", "j").strip() or "j"
NIGHT_VISION_KEY = os.getenv("WKV_NIGHT_VISION_KEY", "alt+n").strip() or "alt+n"
AUTO_DOCK_TIMEOUT_SEC = float(os.getenv("WKV_AUTO_DOCK_TIMEOUT_SEC", "180"))
JINX_SYNC_VAR_NAME = os.getenv("WKV_SUP_JINX_SYNC_VAR", "sync").strip() or "sync"
JINX_PYTHON = os.getenv("WKV_SUP_JINX_PYTHON", "python").strip() or "python"
JINX_SENDER_PATH = Path(
    os.getenv("WKV_SUP_JINX_SENDER_PATH", str(runtime.ROOT_DIR / "tools" / "jinxsender.py"))
)
JINX_ARTNET_IP = os.getenv("WKV_SUP_JINX_ARTNET_IP", "127.0.0.1").strip() or "127.0.0.1"
JINX_ARTNET_UNIVERSE = int(os.getenv("WKV_SUP_JINX_ARTNET_UNIVERSE", "1"))
JINX_BRIGHTNESS = int(os.getenv("WKV_SUP_JINX_BRIGHTNESS", "200"))
JINX_LIGHT_SYNC_ON_EFFECT = os.getenv("WKV_MFD_LIGHT_SYNC_ON_EFFECT", "C7").strip() or "C7"
JINX_LIGHT_SYNC_OFF_EFFECT = os.getenv("WKV_SUP_JINX_OFF_EFFECT", "S1").strip() or "S1"
JINX_EXE = os.getenv("WKV_SUP_JINX_EXE", "").strip()
JINX_ARGS_RAW = os.getenv("WKV_SUP_JINX_ARGS", "-m").strip()
try:
    JINX_LAUNCH_ARGS = shlex.split(JINX_ARGS_RAW, posix=False) if JINX_ARGS_RAW else []
except Exception:
    JINX_LAUNCH_ARGS = []
JINX_PROCESS_NAMES = [
    name.strip()
    for name in os.getenv("WKV_SUP_JINX_PROCESS_NAMES", "Hi-Jinx.exe,Hi-Jinx 2.exe").split(",")
    if name.strip()
]
AHK_EXE_CANDIDATES = [
    os.getenv("WKV_SUP_AHK_EXE", "").strip(),
    r"C:\Program Files\AutoHotkey\AutoHotkey.exe",
    r"C:\Program Files\AutoHotkey\AutoHotkey64.exe",
    r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe",
    r"C:\Program Files\AutoHotkey\v2\AutoHotkey.exe",
]
REQUEST_DOCKING_SEQUENCE = [
    {"key": "1", "at_ms": 0, "hold_ms": 100},
    {"key": "e", "at_ms": 350, "hold_ms": 250},
    {"key": "e", "at_ms": 850, "hold_ms": 250},
    {"key": "a", "at_ms": 1350, "hold_ms": 200},
    {"key": "d", "at_ms": 1800, "hold_ms": 200},
    {"key": "space", "at_ms": 2250, "hold_ms": 200},
    {"key": "a", "at_ms": 2700, "hold_ms": 200},
    {"key": "q", "at_ms": 3150, "hold_ms": 200},
    {"key": "q", "at_ms": 3600, "hold_ms": 200},
    {"key": "1", "at_ms": 4050, "hold_ms": 100},
]
REPAIR_REFUEL_SEQUENCE = [
    {"key": "w", "at_ms": 2500, "hold_ms": 150},
    {"key": "space", "at_ms": 2800, "hold_ms": 150},
    {"key": "d", "at_ms": 3100, "hold_ms": 150},
    {"key": "space", "at_ms": 3400, "hold_ms": 150},
    {"key": "d", "at_ms": 3700, "hold_ms": 150},
    {"key": "space", "at_ms": 4000, "hold_ms": 150},
]
AUTO_LAUNCH_SEQUENCE = [
    {"key": "w", "at_ms": 0, "hold_ms": 150},
    {"key": "w", "at_ms": 200, "hold_ms": 150},
    {"key": "s", "at_ms": 400, "hold_ms": 150},
    {"key": "s", "at_ms": 600, "hold_ms": 150},
    {"key": "space", "at_ms": 800, "hold_ms": 150},
]


def _list_process_names() -> set[str]:
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=NO_WINDOW_FLAGS,
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


def _any_process_running(process_names: list[str]) -> bool:
    if not process_names:
        return True
    running = _list_process_names()
    return any(str(name or "").strip().lower() in running for name in process_names)


def _get_foreground_process_name() -> str | None:
    try:
        hwnd = windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_ulong(0)
        windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", f"PID eq {pid.value}"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=NO_WINDOW_FLAGS,
        )
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if line.startswith('"'):
                parts = [p.strip('"') for p in line.split('","')]
                if parts and parts[0]:
                    return parts[0]
        return None
    except Exception:
        return None


def _key_to_vk(key_name: str) -> int:
    key = key_name.strip().lower()
    if not key:
        raise ValueError("keypress key parameter is required")
    if key in SPECIAL_VK_MAP:
        return SPECIAL_VK_MAP[key]
    if len(key) == 1 and "a" <= key <= "z":
        return ord(key.upper())
    if len(key) == 1 and "0" <= key <= "9":
        return ord(key)
    raise ValueError(f"Unsupported keypress key: {key_name}")


def _send_virtual_key(vk_code: int) -> None:
    windll.user32.keybd_event(vk_code, 0, 0, 0)
    windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)


MODIFIER_VK_MAP = {
    "alt": 0x12,
    "ctrl": 0x11,
    "control": 0x11,
    "shift": 0x10,
}


def _send_key_combo(key_name: str) -> dict[str, Any]:
    parts = [part.strip().lower() for part in str(key_name or "").split("+") if part.strip()]
    if not parts:
        raise ValueError("keypress key parameter is required")
    main_key = parts[-1]
    modifiers = parts[:-1]
    modifier_vks: list[int] = []
    for modifier in modifiers:
        if modifier not in MODIFIER_VK_MAP:
            raise ValueError(f"Unsupported keypress modifier: {modifier}")
        modifier_vks.append(MODIFIER_VK_MAP[modifier])
    main_vk = _key_to_vk(main_key)
    for vk_code in modifier_vks:
        windll.user32.keybd_event(vk_code, 0, 0, 0)
    try:
        _send_virtual_key(main_vk)
    finally:
        for vk_code in reversed(modifier_vks):
            windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
    return {"key": key_name, "vk_code": main_vk, "modifier_vk_codes": modifier_vks}


def _resolve_ahk_exe() -> str:
    for raw in AHK_EXE_CANDIDATES:
        candidate = str(raw or "").strip()
        if candidate and os.path.exists(candidate):
            return candidate
    raise ValueError("AutoHotkey executable not found")


def _key_to_ahk_send(key_name: str) -> str:
    parts = [part.strip().lower() for part in str(key_name or "").split("+") if part.strip()]
    if not parts:
        raise ValueError("keypress key parameter is required")
    prefix = ""
    for modifier in parts[:-1]:
        if modifier == "alt":
            prefix += "!"
        elif modifier in {"ctrl", "control"}:
            prefix += "^"
        elif modifier == "shift":
            prefix += "+"
        else:
            raise ValueError(f"Unsupported keypress modifier: {modifier}")
    main = parts[-1]
    special = {
        "space": "{Space}",
        "enter": "{Enter}",
        "tab": "{Tab}",
        "esc": "{Esc}",
        "escape": "{Esc}",
        "up": "{Up}",
        "down": "{Down}",
        "left": "{Left}",
        "right": "{Right}",
    }
    if main in special:
        body = special[main]
    elif main.startswith("f") and main[1:].isdigit():
        body = "{" + main.upper() + "}"
    elif len(main) == 1 and (main.isalnum() or main in {"=", "-", "\\", "/", "."}):
        body = main
    else:
        raise ValueError(f"Unsupported AutoHotkey key: {main}")
    return prefix + body


def _send_key_combo_ahk(key_name: str) -> dict[str, Any]:
    ahk_exe = _resolve_ahk_exe()
    send_expr = _key_to_ahk_send(key_name)
    script = "\n".join(
        [
            "#NoEnv",
            "#NoTrayIcon",
            "SetTitleMatchMode, 2",
            "SetKeyDelay, 50, 50",
            "WinActivate, Elite - Dangerous (CLIENT)",
            "WinWaitActive, Elite - Dangerous (CLIENT),, 1",
            "if ErrorLevel",
            "  ExitApp, 2",
            f"Send, {send_expr}",
            "ExitApp, 0",
            "",
        ]
    )
    with tempfile.NamedTemporaryFile("w", suffix=".ahk", delete=False, encoding="utf-8") as handle:
        handle.write(script)
        script_path = handle.name
    try:
        result = subprocess.run(
            [ahk_exe, script_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
            creationflags=NO_WINDOW_FLAGS,
        )
    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"AutoHotkey send failed with code {result.returncode}: {detail}")
    return {
        "key": key_name,
        "backend": "ahk",
        "ahk_exe": ahk_exe,
        "send": send_expr,
    }


def _send_key_sequence_ahk(sequence: list[dict[str, Any]]) -> dict[str, Any]:
    if not sequence:
        raise ValueError("keypress sequence must contain at least one step")
    ahk_exe = _resolve_ahk_exe()
    lines = [
        "#NoEnv",
        "#NoTrayIcon",
        "SetTitleMatchMode, 2",
        "SetKeyDelay, 50, 50",
        "WinActivate, Elite - Dangerous (CLIENT)",
        "WinWaitActive, Elite - Dangerous (CLIENT),, 1",
        "if ErrorLevel",
        "  ExitApp, 2",
    ]
    last_at_ms = 0
    normalized: list[dict[str, Any]] = []
    for index, step in enumerate(sequence):
        if not isinstance(step, dict):
            raise ValueError(f"sequence[{index}] must be an object")
        key_name = str(step.get("key") or "").strip()
        send_expr = _key_to_ahk_send(key_name)
        at_ms = int(step.get("at_ms", last_at_ms))
        hold_ms = int(step.get("hold_ms", 100))
        if at_ms < last_at_ms:
            raise ValueError("keypress sequence at_ms values must be non-decreasing")
        if hold_ms < 0 or hold_ms > 5000:
            raise ValueError("keypress sequence hold_ms must be 0..5000")
        delay_ms = at_ms - last_at_ms
        if delay_ms:
            lines.append(f"Sleep, {delay_ms}")
        lines.append(f"Send, {send_expr}")
        normalized.append({"key": key_name, "send": send_expr, "at_ms": at_ms, "hold_ms": hold_ms})
        last_at_ms = at_ms + hold_ms
    lines.extend(["ExitApp, 0", ""])
    script = "\n".join(lines)
    with tempfile.NamedTemporaryFile("w", suffix=".ahk", delete=False, encoding="utf-8") as handle:
        handle.write(script)
        script_path = handle.name
    try:
        timeout_sec = max(3.0, (last_at_ms / 1000.0) + 3.0)
        result = subprocess.run(
            [ahk_exe, script_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_sec,
            creationflags=NO_WINDOW_FLAGS,
        )
    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"AutoHotkey sequence failed with code {result.returncode}: {detail}")
    return {
        "backend": "ahk",
        "ahk_exe": ahk_exe,
        "steps": normalized,
        "duration_ms": last_at_ms,
    }


def _send_key_combo_backend(key_name: str, backend: str | None = None) -> dict[str, Any]:
    selected = str(backend or KEYPRESS_BACKEND or "win32").strip().lower()
    if selected == "ahk":
        return _send_key_combo_ahk(key_name)
    if selected == "auto":
        try:
            return _send_key_combo_ahk(key_name) | {"backend": "ahk"}
        except Exception as exc:
            output = _send_key_combo(key_name)
            output["backend"] = "win32"
            output["fallback_reason"] = str(exc)
            return output
    output = _send_key_combo(key_name)
    output["backend"] = "win32"
    return output


def _build_lights_url(scene: str) -> str:
    if LIGHTS_WEBHOOK_URL_TEMPLATE:
        return LIGHTS_WEBHOOK_URL_TEMPLATE.replace("{scene}", quote(scene))
    if LIGHTS_WEBHOOK_URL:
        return LIGHTS_WEBHOOK_URL
    raise ValueError("set_lights is not configured (set WKV_LIGHTS_WEBHOOK_URL[_TEMPLATE])")


def _execute_set_lights(parameters: dict[str, Any], request_id: str, action_id: str) -> dict[str, Any]:
    scene = str(parameters.get("scene", "default")).strip() or "default"
    url = _build_lights_url(scene)
    payload = {
        "scene": scene,
        "request_id": request_id,
        "action_id": action_id,
        "timestamp_utc": utc_now_iso(),
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=raw,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=LIGHTS_WEBHOOK_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"set_lights webhook HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"set_lights webhook request failed: {exc}") from exc
    return {
        "scene": scene,
        "webhook_url": url,
        "http_status": status,
        "response_body": body[:500],
    }


def _execute_music(tool_name: str) -> dict[str, Any]:
    music_running_row = DB_SERVICE.get_state("music.app_running")
    raw_music_running = music_running_row.get("state_value") if music_running_row else None
    if isinstance(raw_music_running, bool):
        music_running = raw_music_running
    elif isinstance(raw_music_running, (int, float)):
        music_running = raw_music_running != 0
    elif isinstance(raw_music_running, str):
        music_running = raw_music_running.strip().lower() in {"1", "true", "yes", "on"}
    else:
        music_running = False
    if not music_running:
        raise ValueError("music control denied: YouTube Music Desktop is not running")
    if tool_name == "music_next":
        vk_code = VK_MEDIA_NEXT_TRACK
        vk_name = "VK_MEDIA_NEXT_TRACK"
    elif tool_name in {"music_pause", "music_resume"}:
        vk_code = VK_MEDIA_PLAY_PAUSE
        vk_name = "VK_MEDIA_PLAY_PAUSE"
    else:
        raise ValueError(f"Unsupported music tool: {tool_name}")
    _send_virtual_key(vk_code)
    return {"virtual_key": vk_name, "vk_code": vk_code}


def _execute_keypress(parameters: dict[str, Any]) -> dict[str, Any]:
    if not ENABLE_KEYPRESS:
        raise ValueError("keypress actuator is disabled (set WKV_ENABLE_KEYPRESS=1)")
    if not _any_process_running(KEYPRESS_ALLOWED_PROCESSES):
        raise ValueError("keypress denied: no allowed process is currently running")
    sequence = parameters.get("sequence")
    if isinstance(sequence, list):
        backend = str(parameters.get("backend") or KEYPRESS_BACKEND).strip().lower()
        if backend not in {"ahk", "auto"}:
            raise ValueError("keypress sequence requires AutoHotkey backend")
        return _send_key_sequence_ahk(sequence)
    key_name = str(parameters.get("key", "")).strip()
    backend = str(parameters.get("backend") or KEYPRESS_BACKEND).strip().lower()
    return _send_key_combo_backend(key_name, backend=backend)


def _state_bool(state_key: str) -> bool:
    row = DB_SERVICE.get_state(state_key)
    value = row.get("state_value") if row else None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "docked"}
    return False


def _state_int(state_key: str) -> int:
    row = DB_SERVICE.get_state(state_key)
    value = row.get("state_value") if row else None
    try:
        return int(value)
    except Exception:
        return 0


def _state_list(state_key: str) -> list[Any]:
    row = DB_SERVICE.get_state(state_key)
    value = row.get("state_value") if row else None
    return value if isinstance(value, list) else []


def _has_module_item(fragment: str) -> bool:
    needle = fragment.lower()
    for item in _state_list("ed.modules.items"):
        if isinstance(item, dict) and needle in str(item.get("item") or "").lower():
            return True
    return False


def _auto_launch_limpet_check() -> dict[str, Any]:
    has_limpet_controller = _has_module_item("dronecontrol")
    has_cargo_rack = _has_module_item("cargorack")
    limpet_count = _state_int("ed.cargo.limpet_count")
    needs_limpets = has_limpet_controller and has_cargo_rack and limpet_count <= 0
    return {
        "has_limpet_controller": has_limpet_controller,
        "has_cargo_rack": has_cargo_rack,
        "limpet_count": limpet_count,
        "needs_limpet_warning": needs_limpets,
    }


def _execute_cockpit_sequence(
    sequence: list[dict[str, Any]],
    *,
    dry_run: bool,
    label: str,
) -> dict[str, Any]:
    if dry_run:
        return {"status": "dry_run", "label": label, "steps": sequence}
    return _execute_keypress({"sequence": sequence, "backend": COCKPIT_CONTROL_BACKEND}) | {
        "label": label,
    }


def _auto_dock_worker(session_id: str, request_id: str) -> None:
    deadline = time.time() + max(1.0, AUTO_DOCK_TIMEOUT_SEC)
    _set_state_quick("ed.autodock.status", "waiting_for_docked")
    _set_state_quick("ed.autodock.request_id", request_id)
    while time.time() < deadline:
        if _state_bool("ed.status.docked") or _state_bool("ed.telemetry.dock_state"):
            try:
                result = _execute_cockpit_sequence(
                    REPAIR_REFUEL_SEQUENCE,
                    dry_run=False,
                    label="Post-dock Repair/Refuel",
                )
                _set_state_quick("ed.autodock.status", "serviced")
                _set_state_quick("ed.autodock.last_result", result)
                emit_event(
                    con=None,
                    event_type="AUTO_DOCK_SERVICE_EXECUTED",
                    source="cockpit_control",
                    payload={"request_id": request_id, "session_id": session_id, "result": result},
                    mode="game",
                    tags=["mfd", "auto_dock"],
                )
            except Exception as exc:
                _set_state_quick("ed.autodock.status", "service_failed")
                _set_state_quick("ed.autodock.last_error", str(exc))
            return
        time.sleep(1.0)
    _set_state_quick("ed.autodock.status", "timeout")


COCKPIT_CONTROL_ACTIONS: dict[str, dict[str, Any]] = {
    "landing_gear": {"label": "Landing Gear", "key": "l"},
    "cargo_scoop": {"label": "Cargo Scoop", "key": "f10"},
    "lights": {"label": "Lights", "key": "alt+t"},
    "night_vision": {"label": "Night Vision", "key": NIGHT_VISION_KEY},
    "hardpoints": {"label": "Hardpoints", "key": "u"},
    "flight_assist": {"label": "Flight Assist", "key": FLIGHT_ASSIST_KEY},
    "heatsink": {"label": "Heatsink", "key": "v"},
    "target_next": {"label": "Target Next", "key": "g"},
    "fsd": {"label": "FSD", "key": "j"},
    "supercruise": {"label": "Supercruise", "key": SUPERCRUISE_KEY},
    "hyperspace": {"label": "Hyperspace", "key": HYPERSPACE_KEY},
    "pips_sys": {"label": "Pips SYS", "key": "left"},
    "pips_eng": {"label": "Pips ENG", "key": "up"},
    "pips_wep": {"label": "Pips WEP", "key": "right"},
    "nav_panel": {"label": "Nav Panel", "key": "1"},
    "comms_panel": {"label": "Comms Panel", "key": "2"},
    "role_panel": {"label": "Role Panel", "key": "3"},
    "management_panel": {"label": "Management Panel", "key": "4"},
    "galaxy_map": {"label": "Galaxy Map", "key": "ctrl+g"},
    "system_map": {"label": "System Map", "key": "alt+s"},
    "fss": {"label": "FSS", "key": "f5"},
    "flight_control": {"label": "Flight Control", "key": "esc"},
    "cockpit_mode": {"label": "Combat/Analysis Mode", "key": COCKPIT_MODE_KEY},
    "request_docking": {"label": "Request Docking", "sequence": REQUEST_DOCKING_SEQUENCE},
    "repair_refuel": {"label": "Repair/Refuel", "sequence": REPAIR_REFUEL_SEQUENCE},
    "auto_dock": {"label": "Auto Dock", "sequence": REQUEST_DOCKING_SEQUENCE},
    "auto_launch": {"label": "Auto Launch", "sequence": AUTO_LAUNCH_SEQUENCE},
}


def cockpit_control_action(payload: dict[str, Any], source: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    action_name = str(payload.get("action") or "").strip().lower()
    if action_name not in COCKPIT_CONTROL_ACTIONS:
        raise ValueError(
            "action must be one of: " + ", ".join(sorted(COCKPIT_CONTROL_ACTIONS.keys()))
        )
    dry_run = payload.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be boolean")

    action_def = COCKPIT_CONTROL_ACTIONS[action_name]
    sequence = action_def.get("sequence")
    key_name = str(action_def.get("key") or "")
    request_id = f"req-mfd-{uuid.uuid4().hex[:12]}"
    action_id = f"mfd-{action_name}"
    incident_id = f"mfd-{action_name}-{uuid.uuid4().hex[:8]}"
    confirmed_at_utc = utc_now_iso()
    confirm_token = TOOL_ROUTER.build_confirmation_token(incident_id, "input.keypress")

    docked = _state_bool("ed.status.docked") or _state_bool("ed.telemetry.dock_state")
    no_fire_zone = _state_bool("ed.semantic.station.no_fire_zone") or _state_bool("ed.station.no_fire_zone")
    if action_name in {"request_docking", "auto_dock"} and not dry_run:
        if docked:
            raise ValueError("auto dock unavailable: already docked")
        if not no_fire_zone:
            raise ValueError("auto dock unavailable: not inside station no-fire zone")
    if action_name == "repair_refuel" and not dry_run and not docked:
        raise ValueError("repair/refuel unavailable: not docked")
    limpet_check = _auto_launch_limpet_check()
    if action_name == "auto_launch" and not dry_run:
        if not docked:
            raise ValueError("auto launch unavailable: not docked")
        warning_active = _state_bool("ed.autolaunch.limpet_warning_active")
        if limpet_check["needs_limpet_warning"] and not warning_active:
            _set_state_quick("ed.autolaunch.limpet_warning_active", True)
            _set_state_quick("ed.autolaunch.limpet_warning_at", utc_now_iso())
            message = "No limpets detected. Press Auto Launch again to launch anyway."
            return {
                "ok": True,
                "action": action_name,
                "label": action_def["label"],
                "dry_run": dry_run,
                "warning": {
                    "code": "missing_limpets",
                    "message": message,
                    **limpet_check,
                },
                "request_id": request_id,
                "incident_id": incident_id,
                "execute": {
                    "ok": True,
                    "results": [
                        {
                            "action_id": action_id,
                            "tool_name": "keypress",
                            "status": "warning",
                            "output": {"message": message, **limpet_check},
                        }
                    ],
                },
            }
        _set_state_quick("ed.autolaunch.limpet_warning_active", False)

    if isinstance(sequence, list):
        execute_result = _execute_cockpit_sequence(
            sequence,
            dry_run=dry_run,
            label=str(action_def["label"]),
        )
        background = None
        if action_name == "auto_dock" and not dry_run:
            worker = threading.Thread(
                target=_auto_dock_worker,
                args=(str(payload.get("session_id") or "mfd-display"), request_id),
                daemon=True,
            )
            worker.start()
            background = {
                "status": "waiting_for_docked",
                "timeout_sec": AUTO_DOCK_TIMEOUT_SEC,
            }
        return {
            "ok": True,
            "action": action_name,
            "label": action_def["label"],
            "sequence": execute_result,
            "dry_run": dry_run,
            "request_id": request_id,
            "incident_id": incident_id,
            "eligibility": {"docked": docked, "no_fire_zone": no_fire_zone},
            "background": background,
            "execute": {
                "ok": True,
                "results": [
                    {
                        "action_id": action_id,
                        "tool_name": "keypress",
                        "status": execute_result.get("status", "executed"),
                        "output": execute_result,
                    }
                ],
            },
        }

    key_sequence = [{"key": key_name, "at_ms": 0, "hold_ms": 100}]
    execute_result = _execute_cockpit_sequence(
        key_sequence,
        dry_run=dry_run,
        label=str(action_def["label"]),
    )
    return {
        "ok": True,
        "action": action_name,
        "label": action_def["label"],
        "key": key_name,
        "dry_run": dry_run,
        "request_id": request_id,
        "incident_id": incident_id,
        "execute": {
            "ok": True,
            "results": [
                {
                    "action_id": action_id,
                    "tool_name": "keypress",
                    "status": execute_result.get("status", "executed"),
                    "output": execute_result,
                }
            ],
        },
    }

    intent = {
        "schema_version": "1.0",
        "request_id": request_id,
        "timestamp_utc": confirmed_at_utc,
        "session_id": str(payload.get("session_id") or "mfd-display"),
        "mode": "game",
        "domain": "gameplay",
        "urgency": "normal",
        "user_text": f"MFD control: {action_def['label']}",
        "needs_tools": True,
        "needs_clarification": False,
        "clarification_questions": [],
        "retrieval": {},
        "proposed_actions": [
            {
                "action_id": action_id,
                "tool_name": "keypress",
                "parameters": {
                    "key": key_name,
                    "cockpit_action": action_name,
                    "backend": COCKPIT_CONTROL_BACKEND,
                },
                "safety_level": "high_risk",
                "mode_constraints": ["game"],
                "requires_confirmation": True,
                "timeout_ms": 1000,
                "reason": f"MFD control surface: {action_def['label']}",
                "confidence": 1.0,
            }
        ],
        "response_text": f"Queued MFD control: {action_def['label']}",
    }

    with connect_db() as con:
        upsert_intent(con, intent, source=source)
        con.commit()

    record_confirmation(
        {
            "incident_id": incident_id,
            "tool_name": "input.keypress",
            "confirm_token": confirm_token,
            "confirmed_at_utc": confirmed_at_utc,
            "request_id": request_id,
            "session_id": intent["session_id"],
            "mode": "game",
        },
        source=source,
    )

    executed = execute_actions(
        {
            "request_id": request_id,
            "action_ids": [action_id],
            "dry_run": dry_run,
            "allow_high_risk": True,
            "user_confirmed": True,
            "user_confirm_token": confirm_token,
            "confirmed_at_utc": confirmed_at_utc,
            "incident_id": incident_id,
            "watch_condition": "GAME",
            "stt_confidence": 1.0,
        },
        source=source,
    )
    return {
        "ok": True,
        "action": action_name,
        "label": action_def["label"],
        "key": key_name,
        "dry_run": dry_run,
        "request_id": request_id,
        "incident_id": incident_id,
        "execute": executed,
    }


def _execute_edparser(tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
    canonical = tool_name.strip().lower()
    reason = str(parameters.get("reason", "execute_tool")).strip() or "execute_tool"
    force = bool(parameters.get("force", False))
    force_restart = bool(parameters.get("force_restart", False))

    if canonical in {"edparser", "edparser.start", "edparser_start"}:
        return EDPARSER_TOOL.start(reason=reason, force_restart=force_restart)
    if canonical in {"edparser.stop", "edparser_stop"}:
        return EDPARSER_TOOL.stop(reason=reason, force=force)
    if canonical in {"edparser.status", "edparser_status"}:
        return EDPARSER_TOOL.status() | {"ok": True, "reason": reason}
    raise ValueError(f"Unsupported edparser tool: {tool_name}")


def _normalize_jinx_effect(effect: Any) -> str:
    text = str(effect or "").strip().upper()
    if not text:
        raise ValueError("jinx effect is required")
    if text.startswith("S") or text.startswith("C"):
        if len(text) <= 1 or not text[1:].isdigit():
            raise ValueError(f"Invalid jinx effect: {text}")
        return f"{text[0]}{int(text[1:])}"
    if text.isdigit():
        return f"S{int(text)}"
    raise ValueError(f"Invalid jinx effect: {text}")


def _set_state_quick(state_key: str, state_value: Any) -> None:
    DB_SERVICE.set_state(
        state_key=state_key,
        state_value=state_value,
        source="brainstem_execute",
        observed_at_utc=utc_now_iso(),
        confidence=1.0,
        emit_event=False,
    )


def _execute_jinx(tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
    canonical = tool_name.strip().lower()

    if canonical in {"jinx.set_effect", "jinx_set_effect", "jinx.effect"}:
        effect = _normalize_jinx_effect(parameters.get("effect") or parameters.get("mode"))
        _set_state_quick("jinx.effect", effect)
        _set_state_quick("jinx.scene", "")
        _set_state_quick("jinx.chase", "")
        return {"ok": True, "jinx.effect": effect}

    if canonical in {"jinx.set_scene", "jinx_set_scene", "jinx.scene"}:
        scene = str(parameters.get("scene", "")).strip()
        if not scene.isdigit():
            raise ValueError("jinx scene must be numeric")
        _set_state_quick("jinx.scene", int(scene))
        _set_state_quick("jinx.effect", "")
        _set_state_quick("jinx.chase", "")
        return {"ok": True, "jinx.scene": int(scene)}

    if canonical in {"jinx.set_chase", "jinx_set_chase", "jinx.chase"}:
        chase = str(parameters.get("chase", "")).strip()
        if not chase.isdigit():
            raise ValueError("jinx chase must be numeric")
        _set_state_quick("jinx.chase", int(chase))
        _set_state_quick("jinx.effect", "")
        _set_state_quick("jinx.scene", "")
        return {"ok": True, "jinx.chase": int(chase)}

    raise ValueError(f"Unsupported jinx tool: {tool_name}")


def execute_tool(
    *,
    tool_name: str,
    parameters: dict[str, Any],
    request_id: str,
    action_id: str,
    dry_run: bool,
) -> dict[str, Any]:
    if not ENABLE_ACTUATORS:
        return {
            "stub_execution": True,
            "dry_run": True,
            "tool_name": tool_name,
            "action_id": action_id,
            "parameters": parameters,
            "result": "Actuators disabled by configuration (WKV_ENABLE_ACTUATORS=0).",
        }

    if dry_run:
        return {
            "stub_execution": True,
            "dry_run": True,
            "tool_name": tool_name,
            "action_id": action_id,
            "parameters": parameters,
            "result": "Dry run only. No actuator call executed.",
        }

    if tool_name == "set_lights":
        output = _execute_set_lights(parameters, request_id=request_id, action_id=action_id)
    elif tool_name in {"music_next", "music_pause", "music_resume"}:
        output = _execute_music(tool_name)
    elif tool_name == "keypress":
        output = _execute_keypress(parameters)
    elif tool_name.startswith("edparser") or tool_name in {
        "edparser_start",
        "edparser_stop",
        "edparser_status",
    }:
        output = _execute_edparser(tool_name, parameters)
    elif tool_name.startswith("jinx"):
        output = _execute_jinx(tool_name, parameters)
    else:
        raise ValueError(f"Unsupported tool: {tool_name}")

    return {
        "stub_execution": False,
        "dry_run": False,
        "tool_name": tool_name,
        "action_id": action_id,
        "parameters": parameters,
        "result": "Actuator executed.",
        "details": output,
    }


def _mode_to_watch_condition(intent_mode: str) -> str:
    mapping = {
        "standby": "STANDBY",
        "game": "GAME",
        "work": "WORK",
        "tutor": "TUTOR",
    }
    return mapping.get(intent_mode.lower(), DEFAULT_WATCH_CONDITION)


def _resolve_watch_condition(requested: str | None, intent_mode: str) -> str:
    if requested:
        return requested.strip().upper()
    state = DB_SERVICE.get_state("policy.watch_condition") or DB_SERVICE.get_state(
        "system.watch_condition"
    )
    if state and isinstance(state.get("state_value"), str):
        return str(state["state_value"]).strip().upper()
    return _mode_to_watch_condition(intent_mode)


def emit_event(
    con: sqlite3.Connection | None,
    event_type: str,
    source: str,
    payload: dict[str, Any],
    profile: str | None = None,
    session_id: str | None = None,
    correlation_id: str | None = None,
    mode: str | None = None,
    severity: str = "info",
    tags: list[str] | None = None,
) -> str:
    event_id = str(uuid.uuid4())
    if con is not None:
        con.execute(
            """
            INSERT INTO event_log(
                event_id,timestamp_utc,event_type,source,profile,session_id,correlation_id,
                mode,severity,payload_json,tags_json
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                utc_now_iso(),
                event_type,
                source,
                profile,
                session_id,
                correlation_id,
                mode,
                severity,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(tags or [], ensure_ascii=False),
            ),
        )
    else:
        DB_SERVICE.append_event(
            event_id=event_id,
            timestamp_utc=utc_now_iso(),
            event_type=event_type,
            source=source,
            payload=payload,
            profile=profile,
            session_id=session_id,
            correlation_id=correlation_id,
            mode=mode,
            severity=severity,
            tags=tags or [],
        )
    return event_id


def upsert_intent(con: sqlite3.Connection, intent: dict[str, Any], source: str) -> int:
    questions = intent.get("clarification_questions", [])
    retrieval = intent.get("retrieval", {})
    actions = intent["proposed_actions"]

    con.execute(
        """
        INSERT OR REPLACE INTO intent_log(
            request_id,schema_version,timestamp_utc,session_id,mode,domain,urgency,user_text,
            needs_tools,needs_clarification,clarification_questions_json,retrieval_json,
            proposed_actions_json,response_text
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            intent["request_id"],
            intent["schema_version"],
            intent["timestamp_utc"],
            intent.get("session_id"),
            intent["mode"],
            intent["domain"],
            intent["urgency"],
            intent["user_text"],
            1 if intent["needs_tools"] else 0,
            1 if intent["needs_clarification"] else 0,
            json.dumps(questions, ensure_ascii=False),
            json.dumps(retrieval, ensure_ascii=False),
            json.dumps(actions, ensure_ascii=False),
            intent.get("response_text", ""),
        ),
    )

    count = 0
    for action in actions:
        params_for_log = {
            "parameters": action.get("parameters", {}),
            "mode_constraints": action.get("mode_constraints", []),
            "requires_confirmation": action.get("requires_confirmation", False),
            "timeout_ms": action.get("timeout_ms"),
            "confidence": action.get("confidence"),
        }
        con.execute(
            """
            INSERT OR REPLACE INTO action_log(
                request_id,action_id,tool_name,status,safety_level,mode_at_execution,reason,parameters_json
            )
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                intent["request_id"],
                action["action_id"],
                action["tool_name"],
                "queued",
                action["safety_level"],
                intent["mode"],
                action.get("reason"),
                json.dumps(params_for_log, ensure_ascii=False),
            ),
        )
        count += 1

    emit_event(
        con,
        event_type="INTENT_PROPOSED",
        source=source,
        payload={
            "request_id": intent["request_id"],
            "actions": [a["action_id"] for a in actions],
            "domain": intent["domain"],
            "urgency": intent["urgency"],
        },
        session_id=intent.get("session_id"),
        correlation_id=intent["request_id"],
        mode=intent["mode"],
    )

    return count


def ingest_state(payload: dict[str, Any], source: str) -> dict[str, Any]:
    items = payload["items"]
    emit_events = payload.get("emit_events", True)
    profile = payload.get("profile")
    session_id = payload.get("session_id")
    correlation_id = payload.get("correlation_id")
    prepared_items = []
    for item in items:
        state_key = item["state_key"].strip()
        state_value = item["state_value"]
        state_source = item["source"].strip()
        confidence = item.get("confidence")
        observed_at_utc = item.get("observed_at_utc") or utc_now_iso()

        prepared_items.append(
            {
                "state_key": state_key,
                "state_value": state_value,
                "source": state_source,
                "confidence": confidence,
                "observed_at_utc": observed_at_utc,
                "updated_at_utc": utc_now_iso(),
                "event_id": str(uuid.uuid4()),
                "event_type": "STATE_UPDATED",
                "event_source": source,
                "profile": profile,
                "session_id": session_id,
                "correlation_id": correlation_id,
                "event_payload": {
                    "state_key": state_key,
                    "source": state_source,
                    "confidence": confidence,
                    "observed_at_utc": observed_at_utc,
                },
            }
        )

    result = DB_SERVICE.batch_set_state(
        items=prepared_items,
        emit_events=emit_events,
    )
    return {
        "upserted": result["upserted"],
        "changed": result["changed"],
        "state_keys": [item["state_key"] for item in prepared_items],
    }


def record_feedback(payload: dict[str, Any], source: str) -> dict[str, Any]:
    request_id = payload["request_id"].strip()
    rating = payload["rating"]
    correction_text = payload.get("correction_text")
    reviewer = (payload.get("reviewer") or "user").strip()
    session_id = payload.get("session_id")
    mode = payload.get("mode")

    with connect_db() as con:
        intent = con.execute(
            "SELECT request_id,session_id,mode FROM intent_log WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if not intent:
            raise ValueError(f"request_id not found: {request_id}")

        effective_session = session_id or intent["session_id"]
        effective_mode = mode or intent["mode"]

        cur = con.execute(
            """
            INSERT INTO feedback_log(request_id,rating,correction_text,reviewer)
            VALUES(?,?,?,?)
            """,
            (request_id, rating, correction_text, reviewer),
        )
        feedback_id = cur.lastrowid

        emit_event(
            con,
            event_type="USER_FEEDBACK",
            source=source,
            payload={
                "request_id": request_id,
                "feedback_id": feedback_id,
                "rating": rating,
                "has_correction": bool(correction_text),
                "reviewer": reviewer,
            },
            session_id=effective_session,
            correlation_id=request_id,
            mode=effective_mode,
        )
        con.commit()

    return {"feedback_id": feedback_id, "request_id": request_id, "rating": rating}


def ingest_twitch_mock(payload: dict[str, Any], source: str) -> dict[str, Any]:
    if not TWITCH_DEV_INGEST_ENABLED:
        raise ValueError("twitch dev ingest endpoint is disabled")
    event_type = str(payload.get("event_type") or "").strip().upper()
    if not event_type:
        raise ValueError("event_type is required")
    event_payload = payload.get("payload")
    if not isinstance(event_payload, dict):
        event_payload = dict(payload)
        event_payload.pop("event_type", None)
    result = TWITCH_INGEST_SERVICE.ingest_mock(event_type, event_payload)
    emit_event(
        con=None,
        event_type="TWITCH_DEV_INGEST",
        source=source,
        payload={
            "event_type": event_type,
            "processed": bool(result.get("processed")),
            "user_id": result.get("user_id"),
            "commit_ts": result.get("commit_ts"),
        },
        tags=["twitch", "dev", "ingest"],
    )
    return result


def _state_value_text(key: str) -> str:
    row = DB_SERVICE.get_state(str(key or "").strip())
    if not row:
        return ""
    value = row.get("state_value")
    return str(value or "").strip()


def _state_value_bool(key: str) -> bool:
    row = DB_SERVICE.get_state(str(key or "").strip())
    if not row:
        return False
    value = row.get("state_value")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _looks_like_url(text: str) -> bool:
    clean = str(text or "").strip()
    parsed = urlparse(clean)
    if len(parsed.scheme) == 1 and len(clean) >= 3 and clean[1:3] in {":\\", ":/"}:
        return False
    return bool(parsed.scheme and (parsed.netloc or parsed.path))


def _looks_like_executable_target(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if normalized.lower().startswith("ytmd_api://"):
        return False
    if _looks_like_url(normalized):
        return False
    return any(
        normalized.lower().endswith(suffix)
        for suffix in (".exe", ".cmd", ".bat", ".lnk", ".ahk", ".ps1")
    ) or os.path.exists(normalized)


def _is_launchable_target(app_id: str, target: str) -> bool:
    text = str(target or "").strip()
    if not text:
        return False
    if app_id == "ytmd":
        return _looks_like_executable_target(text)
    if app_id == "elite":
        return _looks_like_url(text) or _looks_like_executable_target(text)
    return _looks_like_executable_target(text)


def _discover_process_executable(process_names: list[str]) -> str:
    if not process_names or os.name != "nt":
        return ""
    names = [name.strip() for name in process_names if name.strip()]
    if not names:
        return ""
    filter_names = ",".join(f"'{name}'" for name in names)
    command = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.Name -in @({filter_names}) -and $_.ExecutablePath }} | "
        "Select-Object -First 1 -ExpandProperty ExecutablePath"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
            creationflags=NO_WINDOW_FLAGS,
            timeout=10,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return str(result.stdout or "").strip()


def _normalize_app_open_target(app_id: str, target: str) -> str:
    text = str(target or "").strip()
    if not text:
        return ""
    if app_id == "ytmd" and text.lower().startswith("ytmd_api://"):
        return ""
    if app_id == "ytmd" and _looks_like_url(text):
        return ""
    return text


def open_external_app(payload: dict[str, Any], source: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")

    app_id = str(payload.get("app_id") or "").strip().lower()
    if app_id not in {"elite", "jinx", "sammi", "ytmd"}:
        raise ValueError("app_id must be one of: elite, jinx, sammi, ytmd")

    process_name_map: dict[str, list[str]] = {
        "elite": ["EliteDangerous64.exe", "EliteDangerous.exe"],
        "jinx": ["Hi-Jinx.exe", "Hi-Jinx 2.exe"],
        "sammi": ["SAMMI Core.exe"],
        "ytmd": [
            "youtube-music-desktop-app.exe",
            "YouTube Music Desktop App.exe",
            "YouTubeMusicDesktopApp.exe",
            "YouTube Music.exe",
            "ytmdesktop.exe",
        ],
    }
    target_map: dict[str, list[str]] = {
        "elite": ["app.ed.path", "app.elite.path", "app.ed_ahk.path"],
        "jinx": ["app.jinx.path"],
        "sammi": ["app.sammi.path"],
        "ytmd": ["app.ytmd.path", "music.app.path"],
    }
    target = ""
    for key in target_map.get(app_id, []):
        raw = _state_value_text(key)
        if not raw:
            continue
        normalized = _normalize_app_open_target(app_id, raw)
        if normalized and _is_launchable_target(app_id, normalized):
            target = normalized
            break

    if not target:
        discovered = _discover_process_executable(process_name_map.get(app_id, []))
        if discovered and _is_launchable_target(app_id, discovered):
            target = discovered
            if app_id == "ytmd":
                _set_state_quick("app.ytmd.path", discovered)

    if not target and app_id == "ytmd" and _state_value_bool("music.app_running"):
        emit_event(
            con=None,
            event_type="APP_OPEN_REQUESTED",
            source=source,
            payload={
                "app_id": app_id,
                "target": None,
                "launched": False,
                "already_running": True,
                "note": "YTMD is already running; no executable path configured.",
            },
            severity="info",
            tags=["ui", "app_open", app_id],
        )
        return {
            "app_id": app_id,
            "target": None,
            "launched": False,
            "already_running": True,
            "note": "YTMD is already running; no executable path configured.",
        }

    if not target:
        raise ValueError(f"no launch target configured for app_id={app_id}")

    if os.name != "nt":
        raise ValueError("app launching is only supported on Windows in this build")

    try:
        os.startfile(target)  # type: ignore[attr-defined]
    except Exception as exc:
        raise RuntimeError(f"failed to open target '{target}': {exc}") from exc

    emit_event(
        con=None,
        event_type="APP_OPEN_REQUESTED",
        source=source,
        payload={"app_id": app_id, "target": target},
        severity="info",
        tags=["ui", "app_open", app_id],
    )
    return {"app_id": app_id, "target": target, "launched": True}


def send_twitch_chat(payload: dict[str, Any], source: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")

    message = str(payload.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")
    if len(message) > 500:
        raise ValueError("message must be <= 500 characters")

    mode = str(payload.get("mode") or "standby").strip().lower() or "standby"
    watch_condition_input = payload.get("watch_condition")
    if watch_condition_input is not None and (
        not isinstance(watch_condition_input, str) or not watch_condition_input.strip()
    ):
        raise ValueError("watch_condition must be a non-empty string when supplied")
    watch_condition = _resolve_watch_condition(
        str(watch_condition_input or "").strip().upper() if watch_condition_input else None,
        mode,
    )

    incident_id = str(payload.get("incident_id") or "").strip() or f"twitch-chat-{uuid.uuid4().hex[:12]}"
    stt_confidence = payload.get("stt_confidence")
    if stt_confidence is not None:
        if not isinstance(stt_confidence, (int, float)) or stt_confidence < 0 or stt_confidence > 1:
            raise ValueError("stt_confidence must be number 0..1 when supplied")
        stt_confidence = float(stt_confidence)
    user_confirmed = bool(payload.get("user_confirmed", False))
    user_confirm_token = str(
        payload.get("user_confirm_token") or payload.get("confirm_token") or ""
    ).strip() or None
    confirmed_at_utc = payload.get("confirmed_at_utc")
    confirmed_at_epoch: float | None = None
    if confirmed_at_utc is not None:
        if not isinstance(confirmed_at_utc, str) or not confirmed_at_utc.strip():
            raise ValueError("confirmed_at_utc must be non-empty string when supplied")
        parse_iso8601_utc(confirmed_at_utc)
        confirmed_at_epoch = iso8601_utc_to_epoch(confirmed_at_utc)

    if TWITCH_CHAT_STRICT_CONFIRM and user_confirmed:
        raise ValueError(
            "strict confirm mode enabled: call /confirm first, then resend with incident_id + confirm_token"
        )
    settings = load_runtime_settings(Path(DB_PATH))
    if not runtime_setting_enabled(settings, "syncs", "sammi_bridge", True):
        raise ValueError("sammi bridge is disabled in runtime settings")

    routed = TOOL_ROUTER.evaluate_action(
        incident_id=incident_id,
        watch_condition=watch_condition,
        tool_name="twitch.send_chat",
        args={"message_len": len(message)},
        source=source,
        stt_confidence=stt_confidence,
        foreground_process=None,
        user_confirmed=False if TWITCH_CHAT_STRICT_CONFIRM else user_confirmed,
        user_confirm_token=user_confirm_token,
        action_requires_confirmation=False,
        now_ts=time.time(),
        confirmation_ts=confirmed_at_epoch,
        req_context={
            "mode": mode,
            "watch_condition": watch_condition,
            "message_len": len(message),
        },
    )
    decision = routed["decision"]
    if not decision.get("allowed"):
        emit_event(
            con=None,
            event_type="TWITCH_CHAT_SEND_DENIED",
            source=source,
            payload={
                "incident_id": incident_id,
                "watch_condition": watch_condition,
                "reason_code": decision.get("deny_reason_code"),
                "reason_text": decision.get("deny_reason_text"),
                "requires_confirmation": bool(decision.get("requires_confirmation")),
                "confirm_token": routed.get("confirm_token"),
            },
            mode=mode,
            severity="warn",
            tags=["twitch", "send_chat", "denied"],
        )
        return {
            "accepted": False,
            "sent": False,
            "incident_id": incident_id,
            "tool_name": "twitch.send_chat",
            "watch_condition": watch_condition,
            "policy": decision,
            "confirm_token": routed.get("confirm_token"),
        }

    ok_set, set_result = SAMMI_CLIENT.call(
        "setVariable",
        {"name": TWITCH_CHAT_SEND_VAR, "value": message},
    )
    if not ok_set:
        raise RuntimeError(f"setVariable failed for {TWITCH_CHAT_SEND_VAR}: {set_result}")

    ok_trigger, trigger_result = SAMMI_CLIENT.call(
        "triggerButton",
        {"buttonID": TWITCH_CHAT_SEND_BUTTON},
    )
    if not ok_trigger:
        raise RuntimeError(f"triggerButton failed for {TWITCH_CHAT_SEND_BUTTON}: {trigger_result}")

    emit_event(
        con=None,
        event_type="TWITCH_CHAT_SENT",
        source=source,
        payload={
            "incident_id": incident_id,
            "watch_condition": watch_condition,
            "message_len": len(message),
            "var_name": TWITCH_CHAT_SEND_VAR,
            "button_id": TWITCH_CHAT_SEND_BUTTON,
        },
        mode=mode,
        tags=["twitch", "send_chat"],
    )
    return {
        "accepted": True,
        "sent": True,
        "incident_id": incident_id,
        "tool_name": "twitch.send_chat",
        "watch_condition": watch_condition,
        "var_name": TWITCH_CHAT_SEND_VAR,
        "button_id": TWITCH_CHAT_SEND_BUTTON,
        "policy": decision,
        "sammi": {
            "set_variable": set_result,
            "trigger_button": trigger_result,
        },
    }


def save_inara_credentials(payload: dict[str, Any], source: str) -> dict[str, Any]:
    clear_requested = bool(payload.get("clear"))
    if clear_requested:
        clear_provider_secret_entry("inara", path=PROVIDER_SECRETS_PATH)
        entry: dict[str, Any] = {}
    else:
        entry = save_inara_secret_entry(
            commander_name=payload.get("commander_name"),
            frontier_id=payload.get("frontier_id"),
            app_key=payload.get("api_key"),
            path=PROVIDER_SECRETS_PATH,
        )

    if hasattr(ED_PROVIDER_QUERY_SERVICE, "reload_config"):
        ED_PROVIDER_QUERY_SERVICE.reload_config()
    if PROVIDER_HEALTH_ENABLED and hasattr(runtime, "ED_PROVIDER_HEALTH_SCHEDULER"):
        runtime.ED_PROVIDER_HEALTH_SCHEDULER.update_probes(
            build_provider_health_probes(PROVIDER_CONFIG_PATH, PROVIDER_SECRETS_PATH, DB_PATH)
        )

    emit_event(
        con=None,
        event_type="PROVIDER_CREDENTIALS_UPDATED",
        source=source,
        payload={
            "provider": "inara",
            "cleared": clear_requested,
            "commander_name_present": bool(str(entry.get("commander_name") or "").strip()),
            "frontier_id_present": bool(str(entry.get("frontier_id") or "").strip()),
            "app_key_present": bool(str(entry.get("app_key") or "").strip()),
            "storage_path": str(PROVIDER_SECRETS_PATH),
        },
        tags=["provider", "inara", "credentials"],
    )

    from queries import query_inara_credentials

    result = query_inara_credentials({})
    result["saved_securely"] = not clear_requested
    result["cleared_securely"] = clear_requested
    return result


def save_edsm_credentials(payload: dict[str, Any], source: str) -> dict[str, Any]:
    clear_requested = bool(payload.get("clear"))
    if clear_requested:
        clear_provider_secret_entry("edsm", path=PROVIDER_SECRETS_PATH)
        entry: dict[str, Any] = {}
    else:
        entry = save_edsm_secret_entry(
            commander_name=payload.get("commander_name"),
            api_key=payload.get("api_key"),
            path=PROVIDER_SECRETS_PATH,
        )

    if hasattr(ED_PROVIDER_QUERY_SERVICE, "reload_config"):
        ED_PROVIDER_QUERY_SERVICE.reload_config()
    if PROVIDER_HEALTH_ENABLED and hasattr(runtime, "ED_PROVIDER_HEALTH_SCHEDULER"):
        runtime.ED_PROVIDER_HEALTH_SCHEDULER.update_probes(
            build_provider_health_probes(PROVIDER_CONFIG_PATH, PROVIDER_SECRETS_PATH, DB_PATH)
        )

    emit_event(
        con=None,
        event_type="PROVIDER_CREDENTIALS_UPDATED",
        source=source,
        payload={
            "provider": "edsm",
            "cleared": clear_requested,
            "commander_name_present": bool(str(entry.get("commander_name") or "").strip()),
            "api_key_present": bool(str(entry.get("api_key") or "").strip()),
            "storage_path": str(PROVIDER_SECRETS_PATH),
        },
        tags=["provider", "edsm", "credentials"],
    )

    from queries import query_edsm_credentials

    result = query_edsm_credentials({})
    result["saved_securely"] = not clear_requested
    result["cleared_securely"] = clear_requested
    return result


def save_openai_credentials(payload: dict[str, Any], source: str) -> dict[str, Any]:
    clear_requested = bool(payload.get("clear"))
    if clear_requested:
        clear_provider_secret_entry("openai", path=PROVIDER_SECRETS_PATH)
        entry: dict[str, Any] = {}
    else:
        entry = save_openai_secret_entry(
            api_key=payload.get("api_key"),
            path=PROVIDER_SECRETS_PATH,
        )
    emit_event(
        con=None,
        event_type="PROVIDER_CREDENTIALS_UPDATED",
        source=source,
        payload={
            "provider": "openai",
            "cleared": clear_requested,
            "api_key_present": bool(str(entry.get("api_key") or "").strip()),
            "storage_path": str(PROVIDER_SECRETS_PATH),
        },
        tags=["provider", "openai", "credentials"],
    )

    from queries import query_openai_credentials

    result = query_openai_credentials({})
    result["saved_securely"] = not clear_requested
    result["cleared_securely"] = clear_requested
    return result


def save_runtime_settings_action(payload: dict[str, Any], source: str) -> dict[str, Any]:
    settings = save_runtime_settings(Path(DB_PATH), payload)
    if hasattr(ED_PROVIDER_QUERY_SERVICE, "reload_config"):
        ED_PROVIDER_QUERY_SERVICE.reload_config()
    if PROVIDER_HEALTH_ENABLED and hasattr(runtime, "ED_PROVIDER_HEALTH_SCHEDULER"):
        runtime.ED_PROVIDER_HEALTH_SCHEDULER.update_probes(
            build_provider_health_probes(PROVIDER_CONFIG_PATH, PROVIDER_SECRETS_PATH, DB_PATH)
        )
    emit_event(
        con=None,
        event_type="RUNTIME_SETTINGS_UPDATED",
        source=source,
        payload={
            "providers": payload.get("providers", {}),
            "syncs": payload.get("syncs", {}),
        },
        tags=["settings", "runtime"],
    )
    return {"ok": True, "settings": settings}


def save_mfd_layout_action(payload: dict[str, Any], source: str) -> dict[str, Any]:
    layout = save_layout(Path(DB_PATH), payload)
    DB_SERVICE.append_event(
        event_id=f"mfd-layout-{uuid.uuid4().hex[:12]}",
        timestamp_utc=utc_now_iso(),
        event_type="MFD_LAYOUT_SAVED",
        source=source,
        payload={"layout_id": layout["layout_id"], "name": layout["name"]},
        tags=["mfd", "layout"],
    )
    return {"ok": True, "layout": layout}


def save_mfd_outputs_action(payload: dict[str, Any], source: str) -> dict[str, Any]:
    outputs = save_outputs(Path(DB_PATH), payload)
    DB_SERVICE.append_event(
        event_id=f"mfd-outputs-{uuid.uuid4().hex[:12]}",
        timestamp_utc=utc_now_iso(),
        event_type="MFD_OUTPUTS_SAVED",
        source=source,
        payload={"outputs": [{"output_id": item["output_id"], "layout_id": item["layout_id"]} for item in outputs]},
        tags=["mfd", "layout", "outputs"],
    )
    return {"ok": True, "outputs": outputs}


def _normalize_jinx_mode_arg(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        raise ValueError("jinx mode is required")
    if text[0] in {"S", "C"} and text[1:].isdigit():
        return f"{text[0]}{int(text[1:])}"
    if text.isdigit():
        return f"S{int(text)}"
    raise ValueError(f"invalid jinx mode: {value}")


def _send_jinx_burst(effect: str) -> dict[str, Any]:
    mode = _normalize_jinx_mode_arg(effect)
    if not JINX_SENDER_PATH.exists():
        return {"ok": False, "error": f"missing_sender:{JINX_SENDER_PATH}", "effect": mode}
    cmd = [
        JINX_PYTHON,
        str(JINX_SENDER_PATH),
        JINX_ARTNET_IP,
        mode,
        str(int(JINX_BRIGHTNESS)),
        str(int(JINX_ARTNET_UNIVERSE)),
    ]
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW_FLAGS,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "effect": mode}
    return {
        "ok": True,
        "effect": mode,
        "ip": JINX_ARTNET_IP,
        "brightness": int(JINX_BRIGHTNESS),
        "universe": int(JINX_ARTNET_UNIVERSE),
    }


def _jinx_launch_target() -> tuple[str, list[str]]:
    candidates = [
        _state_value_text("app.jinx.path"),
        JINX_EXE,
        _discover_process_executable(JINX_PROCESS_NAMES),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text and Path(text).exists():
            return text, [c for c in candidates if c]
    return "", [c for c in candidates if c]


def _process_running_by_path(target: str) -> bool:
    text = str(target or "").strip()
    if not text or os.name != "nt":
        return False
    escaped = text.lower().replace("'", "''")
    command = (
        f"$target = '{escaped}'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.ExecutablePath -and $_.ExecutablePath.ToLowerInvariant() -eq $target } | "
        "Select-Object -First 1 -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
            creationflags=NO_WINDOW_FLAGS,
            timeout=10,
        )
    except Exception:
        return False
    return (result.stdout or "").strip().isdigit()


def _launch_jinx(target: str) -> dict[str, Any]:
    target_path = Path(target)
    escaped = str(target_path).replace("'", "''")
    arg_literal = ", ".join("'" + str(arg).replace("'", "''") + "'" for arg in JINX_LAUNCH_ARGS)
    command = (
        f"$exe = '{escaped}'; "
        f"$args = @({arg_literal}); "
        "Start-Process -FilePath $exe -ArgumentList $args | Out-Null"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
            creationflags=NO_WINDOW_FLAGS,
            timeout=10,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "target": target, "args": JINX_LAUNCH_ARGS}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or f"exit_{result.returncode}"
        return {"ok": False, "error": detail, "target": target, "args": JINX_LAUNCH_ARGS}
    _set_state_quick("app.jinx.path", target)
    return {"ok": True, "launched": True, "target": target, "args": JINX_LAUNCH_ARGS}


def _ensure_jinx_started() -> dict[str, Any]:
    if _any_process_running(JINX_PROCESS_NAMES):
        return {"ok": True, "already_running": True}
    target, checked = _jinx_launch_target()
    if target and _process_running_by_path(target):
        return {"ok": True, "already_running": True, "target": target}
    if not target:
        return {"ok": False, "error": "no_jinx_path", "checked": checked}
    return _launch_jinx(target)


def _force_close_jinx() -> dict[str, Any]:
    target, _checked = _jinx_launch_target()
    names = [name for name in JINX_PROCESS_NAMES if name]
    if not target and not names:
        return {"ok": False, "error": "no_jinx_process_target"}
    name_literal = ", ".join("'" + str(name).replace("'", "''") + "'" for name in names)
    target_filter = ""
    if target:
        escaped_target = str(Path(target)).lower().replace("'", "''")
        target_filter = f" -or ($_.ExecutablePath -and $_.ExecutablePath.ToLowerInvariant() -eq '{escaped_target}')"
    command = (
        f"$names = @({name_literal}); "
        "$targets = Get-CimInstance Win32_Process | "
        f"Where-Object {{ ($names -contains $_.Name){target_filter} }}; "
        "$ids = @($targets | ForEach-Object { $_.ProcessId }); "
        "foreach($id in $ids){ Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }; "
        "$ids -join ','"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
            creationflags=NO_WINDOW_FLAGS,
            timeout=10,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "target": target}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or f"exit_{result.returncode}"
        return {"ok": False, "error": detail, "target": target}
    killed = [pid for pid in (result.stdout or "").strip().split(",") if pid.strip()]
    _set_state_quick("app.jinx.running", False)
    return {"ok": True, "closed": bool(killed), "pids": killed, "target": target}


def set_mfd_light_sync(payload: dict[str, Any], source: str) -> dict[str, Any]:
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be boolean")

    settings = save_runtime_settings(
        Path(DB_PATH),
        {"schema_version": "1.0", "syncs": {"jinx_lighting": {"enabled": enabled}}},
    )
    sync_value = "on" if enabled else "off"
    effect = str(
        payload.get("effect")
        or (JINX_LIGHT_SYNC_ON_EFFECT if enabled else JINX_LIGHT_SYNC_OFF_EFFECT)
    )
    launch_result = _ensure_jinx_started() if enabled else {"ok": True, "skipped": True}
    if enabled and launch_result.get("launched"):
        time.sleep(0.8)
    jinx_result = _send_jinx_burst(effect)
    close_result = {"ok": True, "skipped": True}
    if not enabled:
        time.sleep(0.15)
        close_result = _force_close_jinx()
    emit_event(
        con=None,
        event_type="MFD_LIGHT_SYNC_UPDATED",
        source=source,
        payload={
            "enabled": enabled,
            "sync_var": JINX_SYNC_VAR_NAME,
            "sync_value": sync_value,
            "jinx_launch": launch_result,
            "jinx": jinx_result,
            "jinx_close": close_result,
        },
        tags=["mfd", "jinx", "settings"],
    )
    return {
        "ok": True,
        "enabled": enabled,
        "settings": settings,
        "sync_var": JINX_SYNC_VAR_NAME,
        "sync_value": sync_value,
        "jinx_launch": launch_result,
        "jinx": jinx_result,
        "jinx_close": close_result,
    }


def control_advisory_llm_action(payload: dict[str, Any], source: str) -> dict[str, Any]:
    action = str(payload.get("action") or "").strip().lower()
    req = request.Request(
        ADVISORY_LLM_CONTROL_URL,
        data=json.dumps({"action": action}, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=max(ADVISORY_TIMEOUT_SEC, ADVISORY_LLM_CONTROL_TIMEOUT_SEC)) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"llm control HTTP {exc.code}: {message}") from exc
    except Exception as exc:
        raise ValueError(f"llm control request failed: {exc}") from exc

    try:
        parsed = json.loads(raw_body) if raw_body else {}
    except Exception as exc:
        raise ValueError("llm control returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("llm control response must be a JSON object")
    emit_event(
        con=None,
        event_type="ADVISORY_LLM_CONTROL",
        source=source,
        payload={
            "action": action,
            "ok": bool(parsed.get("ok", False)),
            "mode": parsed.get("mode"),
            "llm": parsed.get("llm") if isinstance(parsed.get("llm"), dict) else {},
        },
        tags=["advisory", "llm", action],
    )
    return parsed


def _safe_twitch_context_pack(payload: dict[str, Any]) -> dict[str, Any]:
    context = payload.get("context")
    if not isinstance(context, dict):
        return {}
    user_id = str(context.get("twitch_user_id") or context.get("user_id") or "").strip()
    if not user_id:
        return {}

    try:
        user_ctx = TWITCH_REPO.get_user_context(user_id, redeem_limit=5)
    except Exception:
        return {}

    user = user_ctx.get("user") or {}
    stats = user_ctx.get("stats") or {}
    last_messages = user_ctx.get("last_messages") or []
    top_redeems = user_ctx.get("top_redeems") or []
    tags: list[str] = []

    redeem_total = int(stats.get("redeem_total") or 0)
    message_count = int(user.get("message_count") or 0)
    bits_total = int(stats.get("bits_total") or 0)
    if redeem_total >= 3:
        tags.append("usual_redeem_candidate")
    if message_count >= 20:
        tags.append("frequent_chatter")
    if bits_total > 0 and str(stats.get("last_bits_ts_utc") or "").strip():
        tags.append("recent_supporter")

    return {
        "user_id": user_id,
        "display_name": user.get("display_name"),
        "flags": user.get("flags") if isinstance(user.get("flags"), dict) else {},
        "last_messages": last_messages[:5] if isinstance(last_messages, list) else [],
        "top_redeems": top_redeems[:5] if isinstance(top_redeems, list) else [],
        "stats": stats if isinstance(stats, dict) else {},
        "heuristic_tags": tags,
    }


def _resolve_tool_from_assist_events(incident_id: str, confirm_token: str) -> str | None:
    token = confirm_token.strip()
    if not token:
        return None

    issued_events = DB_SERVICE.list_events(limit=500, event_type="ASSIST_CONFIRM_ISSUED")
    for row in issued_events:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if str(payload.get("incident_id") or "").strip() != incident_id:
            continue
        if str(payload.get("confirm_token") or "").strip() != token:
            continue
        tool_name = str(payload.get("tool_name") or "").strip()
        if tool_name:
            return TOOL_ROUTER.policy_engine.canonical_tool_name(tool_name)

    preview_events = DB_SERVICE.list_events(limit=500, event_type="ASSIST_POLICY_PREVIEW")
    for row in preview_events:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if str(payload.get("incident_id") or "").strip() != incident_id:
            continue
        actions = payload.get("actions")
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            if str(action.get("confirm_token") or "").strip() != token:
                continue
            tool_name = str(action.get("tool_name") or "").strip()
            if tool_name:
                return TOOL_ROUTER.policy_engine.canonical_tool_name(tool_name)
    return None


def _resolve_tool_name_for_confirmation(
    incident_id: str,
    tool_name: str,
    confirm_token: str,
) -> str:
    tool_text = tool_name.strip()
    if tool_text:
        return TOOL_ROUTER.policy_engine.canonical_tool_name(tool_text)

    from_events = _resolve_tool_from_assist_events(incident_id, confirm_token)
    if from_events:
        return from_events

    token = confirm_token.strip()
    if token.startswith("confirm-"):
        parts = token.split("-", 2)
        if len(parts) == 3 and parts[1] and parts[2]:
            return TOOL_ROUTER.policy_engine.canonical_tool_name(parts[2].replace("-", "."))

    raise ValueError("tool_name could not be resolved from confirm_token")


def record_confirmation(payload: dict[str, Any], source: str) -> dict[str, Any]:
    incident_id = payload["incident_id"].strip()
    confirm_token = (payload.get("confirm_token") or payload.get("user_confirm_token") or "").strip()
    tool_name = str(payload.get("tool_name") or "").strip()
    tool_key = _resolve_tool_name_for_confirmation(incident_id, tool_name, confirm_token)
    if not confirm_token:
        confirm_token = TOOL_ROUTER.build_confirmation_token(incident_id, tool_key)

    confirmed_at_utc = payload.get("confirmed_at_utc") or utc_now_iso()
    confirmed_at_epoch = iso8601_utc_to_epoch(confirmed_at_utc)
    TOOL_ROUTER.policy_engine.record_confirmation(
        incident_id=incident_id,
        tool_name=tool_key,
        token=confirm_token,
        ts=confirmed_at_epoch,
    )

    req_context = {
        "request_id": payload.get("request_id"),
        "session_id": payload.get("session_id"),
        "mode": payload.get("mode"),
        "incident_id": incident_id,
    }
    LOGBOOK.log_decision(
        incident_id=incident_id,
        tool_name=tool_key,
        decision={
            "allowed": True,
            "requires_confirmation": False,
            "deny_reason_code": "ALLOW",
            "deny_reason_text": None,
            "constraints": {
                "recorded_confirmation": True,
                "confirmed_at_utc": confirmed_at_utc,
            },
        },
        req_context=req_context,
    )
    emit_event(
        con=None,
        event_type="USER_CONFIRMATION_RECORDED",
        source=source,
        payload={
            "incident_id": incident_id,
            "tool_name": tool_key,
            "confirm_token": confirm_token,
            "confirmed_at_utc": confirmed_at_utc,
            "request_id": payload.get("request_id"),
        },
        session_id=payload.get("session_id"),
        correlation_id=payload.get("request_id") or incident_id,
        mode=payload.get("mode"),
    )
    emit_event(
        con=None,
        event_type="ASSIST_CONFIRM_ACCEPTED",
        source=source,
        payload={
            "incident_id": incident_id,
            "tool_name": tool_key,
            "confirm_token": confirm_token,
            "confirmed_at_utc": confirmed_at_utc,
            "request_id": payload.get("request_id"),
        },
        session_id=payload.get("session_id"),
        correlation_id=payload.get("request_id") or incident_id,
        mode=payload.get("mode"),
        tags=["assist", "confirm", "accepted"],
    )
    return {
        "incident_id": incident_id,
        "tool_name": tool_key,
        "confirm_token": confirm_token,
        "confirmed_at_utc": confirmed_at_utc,
    }


def execute_actions(payload: dict[str, Any], source: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("request_id is required and must be a non-empty string")

    action_ids = payload.get("action_ids")
    if action_ids is not None:
        if not isinstance(action_ids, list):
            raise ValueError("action_ids must be an array when supplied")
        for idx, action_id in enumerate(action_ids):
            if not isinstance(action_id, str) or not action_id:
                raise ValueError(f"action_ids[{idx}] must be a non-empty string")

    dry_run = payload.get("dry_run", True)
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be boolean")

    allow_high_risk = payload.get("allow_high_risk", False)
    if not isinstance(allow_high_risk, bool):
        raise ValueError("allow_high_risk must be boolean")

    user_confirmed = payload.get("user_confirmed", False)
    if not isinstance(user_confirmed, bool):
        raise ValueError("user_confirmed must be boolean")

    user_confirm_token = payload.get("user_confirm_token")
    if user_confirm_token is None:
        user_confirm_token = payload.get("confirm_token")
    if user_confirm_token is not None and (
        not isinstance(user_confirm_token, str) or not user_confirm_token.strip()
    ):
        raise ValueError("user_confirm_token must be a non-empty string when supplied")

    incident_id = payload.get("incident_id")
    if incident_id is not None and (not isinstance(incident_id, str) or not incident_id.strip()):
        raise ValueError("incident_id must be a non-empty string when supplied")

    watch_condition_input = payload.get("watch_condition")
    if watch_condition_input is not None and (
        not isinstance(watch_condition_input, str) or not watch_condition_input.strip()
    ):
        raise ValueError("watch_condition must be a non-empty string when supplied")

    stt_confidence = payload.get("stt_confidence")
    if stt_confidence is not None:
        if not isinstance(stt_confidence, (int, float)) or stt_confidence < 0 or stt_confidence > 1:
            raise ValueError("stt_confidence must be number 0..1 when supplied")
        stt_confidence = float(stt_confidence)

    confirmed_at_utc = payload.get("confirmed_at_utc")
    confirmed_at_epoch: float | None = None
    if confirmed_at_utc is not None:
        if not isinstance(confirmed_at_utc, str) or not confirmed_at_utc.strip():
            raise ValueError("confirmed_at_utc must be non-empty string when supplied")
        parse_iso8601_utc(confirmed_at_utc)
        confirmed_at_epoch = iso8601_utc_to_epoch(confirmed_at_utc)

    incident_id_value = (incident_id or "").strip()

    with connect_db() as con:
        intent = con.execute(
            "SELECT request_id,mode,session_id FROM intent_log WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if not intent:
            raise ValueError(f"request_id not found: {request_id}")
        watch_condition = _resolve_watch_condition(watch_condition_input, intent["mode"])

        sql = (
            "SELECT id,request_id,action_id,tool_name,status,safety_level,parameters_json,created_at_utc "
            "FROM action_log WHERE request_id=?"
        )
        args: list[Any] = [request_id]
        if action_ids:
            placeholders = ",".join("?" for _ in action_ids)
            sql += f" AND action_id IN ({placeholders})"
            args.extend(action_ids)
        sql += " ORDER BY id ASC"

        rows = con.execute(sql, args).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            status = row["status"]
            if status in {"success", "error", "timeout", "denied"}:
                results.append(
                    {
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "status": status,
                        "message": "already finalized",
                    }
                )
                continue

            action_meta = parse_json(row["parameters_json"], {})
            action_parameters = action_meta.get("parameters", {})
            mode_constraints = action_meta.get("mode_constraints") or []
            requires_confirmation = bool(action_meta.get("requires_confirmation", False))
            if not isinstance(action_parameters, dict):
                action_parameters = {}
            if not isinstance(mode_constraints, list):
                mode_constraints = []
            allowed_modes = [str(m) for m in mode_constraints if isinstance(m, str)]
            if allowed_modes and intent["mode"] not in allowed_modes:
                denied_reason = f"mode '{intent['mode']}' not in action mode_constraints"
                denied_reason_code = "DENY_MODE_CONSTRAINT"
                policy_decision = {
                    "allowed": False,
                    "requires_confirmation": False,
                    "deny_reason_code": denied_reason_code,
                    "deny_reason_text": denied_reason,
                    "constraints": {},
                }
            elif row["safety_level"] == "high_risk" and not allow_high_risk:
                denied_reason = "high_risk action requires allow_high_risk=true"
                denied_reason_code = "DENY_HIGH_RISK_NOT_ALLOWED"
                policy_decision = {
                    "allowed": False,
                    "requires_confirmation": False,
                    "deny_reason_code": denied_reason_code,
                    "deny_reason_text": denied_reason,
                    "constraints": {},
                }
            else:
                foreground_process = _get_foreground_process_name()
                routed = TOOL_ROUTER.evaluate_action(
                    incident_id=incident_id_value,
                    watch_condition=watch_condition,
                    tool_name=row["tool_name"],
                    args=action_parameters,
                    source=source,
                    stt_confidence=stt_confidence,
                    foreground_process=foreground_process,
                    user_confirmed=user_confirmed,
                    user_confirm_token=user_confirm_token,
                    action_requires_confirmation=requires_confirmation,
                    now_ts=time.time(),
                    confirmation_ts=confirmed_at_epoch,
                    req_context={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "session_id": intent["session_id"],
                        "mode": intent["mode"],
                    },
                )
                policy_decision = routed["decision"]
                denied_reason = policy_decision.get("deny_reason_text")
                denied_reason_code = policy_decision.get("deny_reason_code")
                if policy_decision.get("requires_confirmation", False):
                    confirm_event_type = "ACTION_CONFIRMATION_REQUIRED"
                    if denied_reason_code == "DENY_CONFIRMATION_EXPIRED":
                        confirm_event_type = "ACTION_CONFIRMATION_EXPIRED"
                    con.execute(
                        """
                        UPDATE action_log
                        SET status='queued', error_code=?, error_message=?, ended_at_utc=?
                        WHERE id=?
                        """,
                        (denied_reason_code, denied_reason, utc_now_iso(), row["id"]),
                    )
                    emit_event(
                        con,
                        event_type=confirm_event_type,
                        source=source,
                        payload={
                            "request_id": request_id,
                            "action_id": row["action_id"],
                            "tool_name": row["tool_name"],
                            "incident_id": incident_id,
                            "watch_condition": watch_condition,
                            "policy_decision": policy_decision,
                            "confirm_token": routed.get("confirm_token"),
                        },
                        session_id=intent["session_id"],
                        correlation_id=request_id,
                        mode=intent["mode"],
                        severity="warn",
                        tags=["assist", "confirm", "required"]
                        if confirm_event_type == "ACTION_CONFIRMATION_REQUIRED"
                        else ["assist", "confirm", "expired"],
                    )
                    results.append(
                        {
                            "action_id": row["action_id"],
                            "tool_name": row["tool_name"],
                            "status": "requires_confirmation",
                            "reason_code": denied_reason_code,
                            "reason": denied_reason,
                            "confirm_token": routed.get("confirm_token"),
                            "constraints": policy_decision.get("constraints", {}),
                            "incident_id": incident_id,
                            "watch_condition": watch_condition,
                        }
                    )
                    continue

            if denied_reason:
                con.execute(
                    """
                    UPDATE action_log
                    SET status='denied', error_code=?, error_message=?, ended_at_utc=?
                    WHERE id=?
                    """,
                    (denied_reason_code, denied_reason, utc_now_iso(), row["id"]),
                )
                emit_event(
                    con,
                    event_type="ACTION_DENIED",
                    source=source,
                    payload={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "reason": denied_reason,
                        "reason_code": denied_reason_code,
                        "incident_id": incident_id,
                        "watch_condition": watch_condition,
                        "policy_decision": policy_decision,
                    },
                    session_id=intent["session_id"],
                    correlation_id=request_id,
                    mode=intent["mode"],
                    severity="warn",
                )
                results.append(
                    {
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "status": "denied",
                        "reason_code": denied_reason_code,
                        "reason": denied_reason,
                    }
                )
                continue

            started_at = utc_now_iso()
            con.execute(
                """
                UPDATE action_log
                SET status='approved', started_at_utc=?
                WHERE id=?
                """,
                (started_at, row["id"]),
            )
            emit_event(
                con,
                event_type="ACTION_APPROVED",
                source=source,
                payload={
                    "request_id": request_id,
                    "action_id": row["action_id"],
                    "tool_name": row["tool_name"],
                    "incident_id": incident_id,
                    "watch_condition": watch_condition,
                    "policy_decision": policy_decision,
                },
                session_id=intent["session_id"],
                correlation_id=request_id,
                mode=intent["mode"],
            )

            try:
                output = execute_tool(
                    tool_name=row["tool_name"],
                    parameters=action_parameters,
                    request_id=request_id,
                    action_id=row["action_id"],
                    dry_run=dry_run,
                )
                status_after = "success"
                error_code = None
                error_message = None
            except Exception as exc:
                output = {}
                status_after = "error"
                error_code = "execution_error"
                error_message = str(exc)

            ended_at = utc_now_iso()
            con.execute(
                """
                UPDATE action_log
                SET status=?, output_json=?, error_code=?, error_message=?, ended_at_utc=?
                WHERE id=?
                """,
                (
                    status_after,
                    json.dumps(output, ensure_ascii=False),
                    error_code,
                    error_message,
                    ended_at,
                    row["id"],
                ),
            )
            if status_after == "success":
                emit_event(
                    con,
                    event_type="TOOL_EXECUTE_RESULT",
                    source=source,
                    payload={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "incident_id": incident_id,
                        "ok": True,
                        "result_or_error": output,
                    },
                    session_id=intent["session_id"],
                    correlation_id=request_id,
                    mode=intent["mode"],
                )
                emit_event(
                    con,
                    event_type="ACTION_EXECUTED",
                    source=source,
                    payload={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "dry_run": dry_run,
                        "incident_id": incident_id,
                        "watch_condition": watch_condition,
                        "stub_execution": bool(output.get("stub_execution")),
                        "result": output.get("result"),
                    },
                    session_id=intent["session_id"],
                    correlation_id=request_id,
                    mode=intent["mode"],
                )
            else:
                emit_event(
                    con,
                    event_type="TOOL_EXECUTE_RESULT",
                    source=source,
                    payload={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "incident_id": incident_id,
                        "ok": False,
                        "result_or_error": error_message,
                    },
                    session_id=intent["session_id"],
                    correlation_id=request_id,
                    mode=intent["mode"],
                    severity="error",
                )
                emit_event(
                    con,
                    event_type="ACTION_FAILED",
                    source=source,
                    payload={
                        "request_id": request_id,
                        "action_id": row["action_id"],
                        "tool_name": row["tool_name"],
                        "incident_id": incident_id,
                        "watch_condition": watch_condition,
                        "error_code": error_code,
                        "error_message": error_message,
                    },
                    session_id=intent["session_id"],
                    correlation_id=request_id,
                    mode=intent["mode"],
                    severity="error",
                )
            result_row = {
                "action_id": row["action_id"],
                "tool_name": row["tool_name"],
                "status": status_after,
            }
            if status_after == "success":
                result_row["output"] = output
            else:
                result_row["error"] = error_message
                result_row["error_code"] = error_code
            result_row["incident_id"] = incident_id
            result_row["watch_condition"] = watch_condition
            results.append(result_row)

        con.commit()

    return {
        "request_id": request_id,
        "incident_id": incident_id,
        "watch_condition": watch_condition,
        "dry_run": dry_run,
        "results": results,
    }


def _fetch_advisory_proposal(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not ADVISORY_ENABLED:
        raise ValueError("advisory service is disabled (WKV_ADVISORY_ENABLED=0)")
    if not ADVISORY_URL:
        raise ValueError("WKV_ADVISORY_URL is not configured")

    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        ADVISORY_URL,
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Source": "brainstem_assist",
        },
    )
    try:
        with request.urlopen(req, timeout=ADVISORY_TIMEOUT_SEC) as resp:
            status = int(getattr(resp, "status", 200))
            body = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"advisory HTTP {exc.code}: {message}") from exc
    except Exception as exc:
        raise ValueError(f"advisory request failed: {exc}") from exc

    try:
        parsed = json.loads(body) if body else {}
    except Exception as exc:
        raise ValueError("advisory returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("advisory response must be a JSON object")

    proposal = parsed.get("proposal")
    if not isinstance(proposal, dict):
        raise ValueError("advisory response missing proposal object")

    meta = {
        "status": status,
        "provider": parsed.get("provider"),
        "service_meta": parsed.get("meta") if isinstance(parsed.get("meta"), dict) else {},
    }
    return proposal, meta


def assist_with_advisory(payload: dict[str, Any], source: str) -> dict[str, Any]:
    payload_for_advisory = dict(payload)
    twitch_context_pack = _safe_twitch_context_pack(payload)
    if twitch_context_pack:
        context = payload.get("context")
        context_obj = dict(context) if isinstance(context, dict) else {}
        context_obj["twitch_context_pack"] = twitch_context_pack
        payload_for_advisory["context"] = context_obj

    request_id_hint = str(payload.get("request_id") or f"req-{uuid.uuid4().hex[:12]}")
    mode_hint = str(payload.get("mode") or "standby")
    emit_event(
        con=None,
        event_type="ASSIST_REQUEST_SUMMARY",
        source=source,
        payload={
            "request_id": request_id_hint,
            "mode": mode_hint,
            "domain": payload.get("domain"),
            "urgency": payload.get("urgency"),
            "watch_condition": payload.get("watch_condition"),
            "max_actions": payload.get("max_actions"),
            "user_text_chars": len(str(payload.get("user_text") or "")),
            "has_context": isinstance(payload_for_advisory.get("context"), dict),
            "has_twitch_context_pack": bool(twitch_context_pack),
        },
        session_id=payload.get("session_id"),
        correlation_id=request_id_hint,
        mode=mode_hint,
        tags=["assist", "request"],
    )

    proposal, advisory_meta = _fetch_advisory_proposal(payload_for_advisory)
    request_id = proposal["request_id"]
    incident_id = (payload.get("incident_id") or f"inc-{request_id}").strip()
    emit_event(
        con=None,
        event_type="ASSIST_PROPOSAL_RECEIVED",
        source=source,
        payload={
            "request_id": request_id,
            "incident_id": incident_id,
            "provider": advisory_meta.get("provider"),
            "advisory_status": advisory_meta.get("status"),
            "service_meta": advisory_meta.get("service_meta", {}),
            "actions_count": len(proposal.get("proposed_actions", []))
            if isinstance(proposal.get("proposed_actions"), list)
            else 0,
        },
        session_id=proposal.get("session_id"),
        correlation_id=request_id,
        mode=proposal.get("mode"),
        tags=["assist", "proposal", "received"],
    )

    from validators import validate_intent_proposal

    try:
        validate_intent_proposal(proposal)
    except Exception as exc:
        emit_event(
            con=None,
            event_type="ASSIST_PROPOSAL_INVALID",
            source=source,
            payload={
                "request_id": request_id,
                "incident_id": incident_id,
                "validation_error": str(exc),
                "provider": advisory_meta.get("provider"),
            },
            session_id=proposal.get("session_id"),
            correlation_id=request_id,
            mode=proposal.get("mode"),
            severity="warn",
            tags=["assist", "proposal", "invalid"],
        )
        raise

    stt_confidence = payload.get("stt_confidence")
    if not isinstance(stt_confidence, (int, float)):
        stt_confidence = None
    else:
        stt_confidence = float(stt_confidence)
    foreground_process = payload.get("foreground_process")
    if not isinstance(foreground_process, str) or not foreground_process.strip():
        foreground_process = None

    watch_condition = _resolve_watch_condition(payload.get("watch_condition"), proposal["mode"])
    retrieval = proposal.get("retrieval")
    if not isinstance(retrieval, dict):
        retrieval = {}
    emit_event(
        con=None,
        event_type="ASSIST_PROPOSAL_VALIDATED",
        source=source,
        payload={
            "request_id": request_id,
            "incident_id": incident_id,
            "watch_condition": watch_condition,
            "actions_count": len(proposal.get("proposed_actions", [])),
            "needs_clarification": bool(proposal.get("needs_clarification", False)),
            "retrieval_context_meta": retrieval.get("context_pack_metadata", {}),
        },
        session_id=proposal.get("session_id"),
        correlation_id=request_id,
        mode=proposal.get("mode"),
        tags=["assist", "proposal", "validated"],
    )

    with connect_db() as con:
        queued_actions = upsert_intent(con, proposal, source=source)
        con.commit()

    policy_preview: list[dict[str, Any]] = []
    needs_confirmation = False
    gated_action_count = 0
    now_ts = time.time()

    for action in proposal.get("proposed_actions", []):
        action_id = str(action.get("action_id") or "")
        tool_name = str(action.get("tool_name") or "")
        params = action.get("parameters")
        if not isinstance(params, dict):
            params = {}
        routed = TOOL_ROUTER.evaluate_action(
            incident_id=incident_id,
            watch_condition=watch_condition,
            tool_name=tool_name,
            args=params,
            source=source,
            stt_confidence=stt_confidence,
            foreground_process=foreground_process,
            user_confirmed=False,
            user_confirm_token=None,
            action_requires_confirmation=bool(action.get("requires_confirmation", False)),
            now_ts=now_ts,
            req_context={
                "request_id": request_id,
                "action_id": action_id,
                "session_id": proposal.get("session_id"),
                "mode": proposal.get("mode"),
                "phase": "assist_proposal",
            },
        )
        decision = routed["decision"]
        if decision.get("requires_confirmation"):
            needs_confirmation = True
            emit_event(
                con=None,
                event_type="ASSIST_CONFIRM_ISSUED",
                source=source,
                payload={
                    "request_id": request_id,
                    "incident_id": incident_id,
                    "action_id": action_id,
                    "tool_name": tool_name,
                    "confirm_token": routed.get("confirm_token"),
                    "reason_code": decision.get("deny_reason_code"),
                    "constraints": decision.get("constraints", {}),
                },
                session_id=proposal.get("session_id"),
                correlation_id=request_id,
                mode=proposal.get("mode"),
                severity="warn",
                tags=["assist", "confirm", "issued"],
            )
        if not decision.get("allowed"):
            gated_action_count += 1
        policy_preview.append(
            {
                "action_id": action_id,
                "tool_name": tool_name,
                "decision": decision,
                "confirm_token": routed.get("confirm_token"),
            }
        )

    emit_event(
        con=None,
        event_type="ASSIST_POLICY_PREVIEW",
        source=source,
        payload={
            "request_id": request_id,
            "incident_id": incident_id,
            "watch_condition": watch_condition,
            "actions": policy_preview,
        },
        session_id=proposal.get("session_id"),
        correlation_id=request_id,
        mode=proposal.get("mode"),
        tags=["assist", "policy", "preview"],
    )

    emit_event(
        con=None,
        event_type="ASSIST_PROPOSAL",
        source=source,
        payload={
            "request_id": request_id,
            "incident_id": incident_id,
            "watch_condition": watch_condition,
            "queued_actions": queued_actions,
            "gated_action_count": gated_action_count,
            "needs_confirmation": needs_confirmation,
            "advisory": advisory_meta,
            "retrieval_context_meta": retrieval.get("context_pack_metadata", {}),
        },
        session_id=proposal.get("session_id"),
        correlation_id=request_id,
        mode=proposal.get("mode"),
        tags=["assist", "proposal"],
    )

    return {
        "request_id": request_id,
        "incident_id": incident_id,
        "watch_condition": watch_condition,
        "proposal": proposal,
        "queued_actions": queued_actions,
        "policy_preview": policy_preview,
        "needs_confirmation": needs_confirmation,
        "advisory": advisory_meta,
    }


def execute_provider_query(payload: dict[str, Any], source: str) -> dict[str, Any]:
    requirements = payload.get("requirements") if isinstance(payload.get("requirements"), dict) else {}
    trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
    request_obj = ProviderQuery(
        provider=ProviderId(str(payload.get("provider") or "").strip().lower()),
        operation=ProviderOperationId(str(payload.get("operation") or "").strip().lower()),
        params=dict(payload.get("params") or {}),
        max_age_s=int(requirements.get("max_age_s", 0)),
        allow_stale_if_error=bool(requirements.get("allow_stale_if_error", False)),
        incident_id=str(trace.get("incident_id") or "").strip() or None,
        reason=str(trace.get("reason") or "api_query").strip() or "api_query",
    )
    result = ED_PROVIDER_QUERY_SERVICE.execute(request_obj)
    emit_event(
        con=None,
        event_type="ED_PROVIDER_QUERY",
        source=source,
        payload={
            "provider": request_obj.provider.value,
            "operation": request_obj.operation.value,
            "incident_id": request_obj.incident_id,
            "reason": request_obj.reason,
            "ok": result.ok,
            "cache": {
                "hit": result.cache.hit,
                "age_s": result.cache.age_s,
                "ttl_s": result.cache.ttl_s,
                "stale_served": result.cache.stale_served,
            },
            "deny_reason": result.deny_reason.value if result.deny_reason else None,
            "error": result.error,
        },
        correlation_id=request_obj.incident_id,
        tags=["provider", request_obj.provider.value, request_obj.operation.value],
    )
    return {"ok": result.ok, **result.to_dict()}
