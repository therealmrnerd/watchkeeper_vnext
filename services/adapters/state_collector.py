import ctypes
import hashlib
import json
import os
import re
import sqlite3
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
DB_PATH = Path(os.getenv("WKV_DB_PATH", str(ROOT_DIR / "data" / "watchkeeper_vnext.db")))
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
        (
            "YouTube Music Desktop App.exe,YouTubeMusicDesktopApp.exe,"
            "youtube-music-desktop-app.exe,YouTube Music.exe,ytmdesktop.exe"
        ),
    ).split(",")
    if p.strip()
]
_ytmd_next_allowed_at = 0.0
_ytmd_cached_payload: dict[str, Any] | None = None
_ytmd_cached_at = 0.0
ED_PROCESS_NAMES = [
    p.strip()
    for p in os.getenv(
        "WKV_ED_PROCESS_NAMES",
        "EliteDangerous64.exe,EliteDangerous.exe",
    ).split(",")
    if p.strip()
]
ED_DEFAULT_JOURNAL_DIR = Path(
    os.getenv(
        "WKV_ED_JOURNAL_DIR",
        str(Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous"),
    )
)
ED_STATUS_PATH = Path(os.getenv("WKV_ED_STATUS_PATH", str(ED_DEFAULT_JOURNAL_DIR / "Status.json")))
ED_JOURNAL_DIR = Path(os.getenv("WKV_ED_JOURNAL_DIR", str(ED_DEFAULT_JOURNAL_DIR)))
ED_MODULES_PATH = Path(os.getenv("WKV_ED_MODULES_PATH", str(ED_DEFAULT_JOURNAL_DIR / "ModulesInfo.json")))
ED_CARGO_PATH = Path(os.getenv("WKV_ED_CARGO_PATH", str(ED_DEFAULT_JOURNAL_DIR / "Cargo.json")))
ED_POWER_CAPACITY_MW_RAW = os.getenv("WKV_ED_POWER_CAPACITY_MW", "").strip()
LOOP_SLEEP_SEC = float(os.getenv("WKV_COLLECTOR_LOOP_SLEEP_SEC", "0.5"))
SYSTEM_INTERVAL_SEC = float(os.getenv("WKV_SYSTEM_INTERVAL_SEC", "15"))
ED_ACTIVE_INTERVAL_SEC = float(os.getenv("WKV_ED_ACTIVE_INTERVAL_SEC", "2"))
ED_IDLE_INTERVAL_SEC = float(os.getenv("WKV_ED_IDLE_INTERVAL_SEC", "8"))
MUSIC_ACTIVE_INTERVAL_SEC = float(os.getenv("WKV_MUSIC_ACTIVE_INTERVAL_SEC", "2"))
MUSIC_IDLE_INTERVAL_SEC = float(os.getenv("WKV_MUSIC_IDLE_INTERVAL_SEC", "12"))
YTMD_CACHE_MAX_SEC = float(os.getenv("WKV_YTMD_CACHE_MAX_SEC", "8"))
RUNTIME_SETTINGS_KEY = "runtime_settings"
ED_GAME_YEAR_OFFSET = int(os.getenv("WKV_ED_GAME_YEAR_OFFSET", "1286"))
_runtime_settings_cache: dict[str, Any] = {"loaded_at": 0.0, "syncs": None}
_RUNTIME_SETTINGS_CACHE_SEC = float(os.getenv("WKV_RUNTIME_SETTINGS_CACHE_SEC", "5"))


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


def _isoformat_ms(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds")


def _ed_game_datetime_from_utc(utc_dt: datetime) -> datetime:
    try:
        return utc_dt.replace(year=utc_dt.year + ED_GAME_YEAR_OFFSET)
    except ValueError:
        # 29 Feb has no equivalent in some target years; use 28 Feb rather than failing the collector.
        return utc_dt.replace(year=utc_dt.year + ED_GAME_YEAR_OFFSET, day=28)


def _clock_datetimes() -> tuple[datetime, datetime]:
    # Ask the OS for local time directly so Windows timezone/DST rules are applied.
    local_dt = datetime.now().astimezone()
    utc_dt = local_dt.astimezone(timezone.utc)
    return utc_dt, local_dt


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _flag_set(flags: int, bit: int) -> bool:
    return (int(flags or 0) & (1 << bit)) != 0


def _latest_journal_path(journal_dir: Path = ED_JOURNAL_DIR) -> Path | None:
    try:
        candidates = [p for p in journal_dir.glob("Journal.*.log") if p.is_file()]
    except Exception:
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda p: (p.stat().st_mtime, p.name))


def _last_json_line(path: Path) -> dict[str, Any] | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _last_journal_event(path: Path, event_name: str) -> dict[str, Any] | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None
    wanted = event_name.strip().lower()
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("event") or "").strip().lower() == wanted:
            return payload
    return None


def _latest_journal_location_context(path: Path) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return {}
    context: dict[str, Any] = {}
    key_pairs = {
        "system": ("StarSystem",),
        "system_address": ("SystemAddress",),
        "station": ("StationName",),
        "body": ("Body", "BodyName"),
    }
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        for output_key, source_keys in key_pairs.items():
            if output_key in context:
                continue
            for source_key in source_keys:
                value = payload.get(source_key)
                if value not in (None, ""):
                    context[output_key] = value
                    break
        if len(context) == len(key_pairs):
            break
    return context


def _latest_no_fire_zone_state(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "value": False,
            "event": None,
            "station": None,
            "timestamp": None,
            "source": None,
        }
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return {
            "value": False,
            "event": None,
            "station": None,
            "timestamp": None,
            "source": str(path),
        }

    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        event_name = str(payload.get("event") or "").strip()
        if event_name == "ReceiveText":
            message = str(payload.get("Message") or "")
            if "STATION_NoFireZone_entered" in message:
                return {
                    "value": True,
                    "event": "entered",
                    "station": payload.get("From") or None,
                    "timestamp": payload.get("timestamp"),
                    "source": str(path),
                }
            if "STATION_NoFireZone_exited" in message:
                return {
                    "value": False,
                    "event": "exited",
                    "station": payload.get("From") or None,
                    "timestamp": payload.get("timestamp"),
                    "source": str(path),
                }

        if event_name in {"Docked", "FSDJump", "SupercruiseEntry"}:
            return {
                "value": False,
                "event": event_name,
                "station": payload.get("StationName") or payload.get("Body") or None,
                "timestamp": payload.get("timestamp"),
                "source": str(path),
            }

    return {
        "value": False,
        "event": None,
        "station": None,
        "timestamp": None,
        "source": str(path),
    }


def _latest_docking_state(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "state": None,
            "event": None,
            "station": None,
            "station_type": None,
            "market_id": None,
            "landing_pad": None,
            "landing_pads": None,
            "reason": None,
            "timestamp": None,
            "source": None,
        }
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
            return {
                "state": None,
                "event": None,
                "station": None,
                "station_type": None,
                "market_id": None,
                "landing_pad": None,
                "landing_pads": None,
                "reason": None,
                "timestamp": None,
                "source": str(path),
            }

    event_states = {
        "DockingRequested": "requested",
        "DockingGranted": "granted",
        "DockingDenied": "denied",
        "DockingCancelled": "not_docking",
        "Docked": "docked",
        "Undocked": "not_docking",
        "FSDJump": "not_docking",
        "SupercruiseEntry": "not_docking",
    }
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        event_name = str(payload.get("event") or "").strip()
        if event_name in event_states:
            return {
                "state": event_states[event_name],
                "event": event_name,
                "station": payload.get("StationName") or payload.get("Body") or None,
                "station_type": payload.get("StationType"),
                "market_id": payload.get("MarketID"),
                "landing_pad": payload.get("LandingPad"),
                "landing_pads": payload.get("LandingPads"),
                "reason": payload.get("Reason"),
                "timestamp": payload.get("timestamp"),
                "source": str(path),
            }

    return {
        "state": None,
        "event": None,
        "station": None,
        "station_type": None,
        "market_id": None,
        "landing_pad": None,
        "landing_pads": None,
        "reason": None,
        "timestamp": None,
        "source": str(path),
    }


def _as_percent(value: Any) -> int | None:
    if value is None:
        return None
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if raw <= 1.0:
        raw *= 100.0
    return max(0, min(100, int(round(raw))))


def _latest_journal_operational_context(path: Path | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if path is None:
        return out
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return out

    target_done = False
    fighter_done = False
    srv_done = False
    suit_done = False
    system_done = False
    powerplay_done = False
    commander_power = None
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        event_name = str(payload.get("event") or "").strip()

        if not powerplay_done and event_name == "Powerplay":
            commander_power = payload.get("Power")
            out["ed.commander.power"] = commander_power
            powerplay_done = True

        if not target_done and event_name == "ShipTargeted":
            locked = bool(payload.get("TargetLocked"))
            out.update(
                {
                    "ed.target.locked": locked,
                    "ed.target.updated_at": payload.get("timestamp"),
                    "ed.target.scan_stage": payload.get("ScanStage"),
                    "ed.target.ship": payload.get("Ship"),
                    "ed.target.ship_localised": payload.get("Ship_Localised"),
                    "ed.target.pilot_name": payload.get("PilotName_Localised") or payload.get("PilotName"),
                    "ed.target.pilot_rank": payload.get("PilotRank"),
                    "ed.target.faction": payload.get("Faction"),
                    "ed.target.legal_status": payload.get("LegalStatus"),
                    "ed.target.power": payload.get("Power"),
                    "ed.target.shield_health_percent": _as_percent(payload.get("ShieldHealth")),
                    "ed.target.hull_health_percent": _as_percent(payload.get("HullHealth")),
                }
            )
            if not locked:
                out.update(
                    {
                        "ed.target.ship": None,
                        "ed.target.ship_localised": None,
                        "ed.target.pilot_name": None,
                        "ed.target.pilot_rank": None,
                        "ed.target.faction": None,
                        "ed.target.legal_status": None,
                        "ed.target.power": None,
                        "ed.target.hostility": None,
                        "ed.target.shield_health_percent": None,
                        "ed.target.hull_health_percent": None,
                    }
                )
            target_done = True

        if not fighter_done and event_name in {"LaunchFighter", "DockFighter", "FighterDestroyed"}:
            active = event_name == "LaunchFighter"
            out.update(
                {
                    "ed.fighter.active": active,
                    "ed.fighter.last_event": event_name,
                    "ed.fighter.updated_at": payload.get("timestamp"),
                    "ed.fighter.loadout": payload.get("Loadout"),
                    "ed.fighter.model": "taipan" if active else None,
                    "ed.fighter.model_localised": "Taipan" if active else None,
                    "ed.fighter.id": payload.get("ID"),
                    "ed.fighter.player_controlled": payload.get("PlayerControlled"),
                }
            )
            fighter_done = True

        if not srv_done and event_name in {"LaunchSRV", "DockSRV", "SRVDestroyed"}:
            active = event_name == "LaunchSRV"
            model = payload.get("SRVType") or ("testbuggy" if active else None)
            model_localised = payload.get("SRVType_Localised") or ("Scarab SRV" if active else None)
            out.update(
                {
                    "ed.srv.active": active,
                    "ed.srv.last_event": event_name,
                    "ed.srv.updated_at": payload.get("timestamp"),
                    "ed.srv.model": model,
                    "ed.srv.model_localised": model_localised,
                    "ed.srv.id": payload.get("ID"),
                }
            )
            srv_done = True

        if not suit_done and event_name in {"SuitLoadout", "Loadout"}:
            modules = payload.get("Modules")
            if not isinstance(modules, list):
                modules = []
            suit_modules = [
                item
                for item in modules
                if isinstance(item, dict)
                and (
                    str(item.get("SlotName") or "").strip()
                    or str(item.get("ModuleName") or "").strip()
                    or str(item.get("SuitModuleID") or "").strip()
                )
            ]
            if event_name == "SuitLoadout" or payload.get("SuitName") or suit_modules:
                out.update(
                    {
                        "ed.suit.updated_at": payload.get("timestamp"),
                        "ed.suit.id": payload.get("SuitID"),
                        "ed.suit.name": payload.get("SuitName"),
                        "ed.suit.name_localised": payload.get("SuitName_Localised"),
                        "ed.suit.loadout_id": payload.get("LoadoutID"),
                        "ed.suit.loadout_name": payload.get("LoadoutName"),
                        "ed.suit.modules": suit_modules,
                    }
                )
                suit_done = True

        if not system_done and event_name in {"Location", "FSDJump"}:
            system_faction = payload.get("SystemFaction")
            if not isinstance(system_faction, dict):
                system_faction = {}
            station_faction = payload.get("StationFaction")
            if not isinstance(station_faction, dict):
                station_faction = {}
            out.update(
                {
                    "ed.system.allegiance": payload.get("SystemAllegiance"),
                    "ed.system.government": payload.get("SystemGovernment_Localised")
                    or payload.get("SystemGovernment"),
                    "ed.system.security": payload.get("SystemSecurity_Localised")
                    or payload.get("SystemSecurity"),
                    "ed.system.economy": payload.get("SystemEconomy_Localised")
                    or payload.get("SystemEconomy"),
                    "ed.system.second_economy": payload.get("SystemSecondEconomy_Localised")
                    or payload.get("SystemSecondEconomy"),
                    "ed.system.population": payload.get("Population"),
                    "ed.system.star_class": payload.get("StarClass"),
                    "ed.system.faction": system_faction.get("Name"),
                    "ed.system.controlling_power": payload.get("ControllingPower"),
                    "ed.system.powerplay_state": payload.get("PowerplayState"),
                    "ed.system.powerplay_control_progress": payload.get("PowerplayStateControlProgress"),
                    "ed.system.powerplay_reinforcement": payload.get("PowerplayStateReinforcement"),
                    "ed.system.powerplay_undermining": payload.get("PowerplayStateUndermining"),
                    "ed.system.conflicts": [],
                    "ed.system.conflict_count": 0,
                    "ed.system.civil_war": False,
                    "ed.station.name": payload.get("StationName"),
                    "ed.station.type": payload.get("StationType"),
                    "ed.station.is_fleet_carrier": str(payload.get("StationType") or "").strip().lower() in {"fleetcarrier", "fleet carrier"},
                    "ed.station.faction": station_faction.get("Name"),
                    "ed.station.government": payload.get("StationGovernment_Localised")
                    or payload.get("StationGovernment"),
                    "ed.station.economy": payload.get("StationEconomy_Localised")
                    or payload.get("StationEconomy"),
                    "ed.station.market_id": payload.get("MarketID"),
                }
            )
            factions = payload.get("Factions")
            if isinstance(factions, list):
                controller_name = str(system_faction.get("Name") or "").strip()
                for faction in factions:
                    if not isinstance(faction, dict):
                        continue
                    if controller_name and str(faction.get("Name") or "").strip() != controller_name:
                        continue
                    out.update(
                        {
                            "ed.system.faction_state": faction.get("FactionState"),
                            "ed.system.faction_influence": faction.get("Influence"),
                            "ed.system.faction_happiness": faction.get("Happiness_Localised")
                            or faction.get("Happiness"),
                            "ed.system.faction_reputation": faction.get("MyReputation"),
                            "ed.system.squadron_faction": bool(faction.get("SquadronFaction")),
                        }
                    )
                    break
            conflicts = payload.get("Conflicts")
            if isinstance(conflicts, list):
                out["ed.system.conflicts"] = conflicts
                out["ed.system.conflict_count"] = len(conflicts)
                out["ed.system.civil_war"] = any(
                    _conflict_is_civil_war(conflict)
                    for conflict in conflicts
                    if isinstance(conflict, dict)
                )
            if str(out.get("ed.system.faction_state") or "").replace(" ", "").casefold() == "civilwar":
                out["ed.system.civil_war"] = True
            system_done = True

        if target_done and system_done and powerplay_done and fighter_done and srv_done and suit_done:
            break

    if "ed.target.locked" not in out:
        out["ed.target.locked"] = False
    target_power = out.get("ed.target.power")
    commander_power = out.get("ed.commander.power")
    if out.get("ed.target.locked") and target_power and commander_power:
        out["ed.target.hostility"] = (
            "friendly"
            if str(target_power).strip().lower() == str(commander_power).strip().lower()
            else "enemy"
        )
    return out


def _conflict_is_civil_war(conflict: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(conflict.get(key) or "")
        for key in ("WarType", "Status", "Faction1", "Faction2")
    ).replace("_", "").replace(" ", "").casefold()
    return "civilwar" in haystack


def _health_percent(value: Any) -> int | None:
    if value is None:
        return None
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if raw <= 1.0:
        raw *= 100.0
    return max(0, min(100, int(round(raw))))


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _module_metadata_by_slot(modules_info: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(modules_info, dict):
        return {}
    modules = modules_info.get("Modules")
    if not isinstance(modules, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in modules:
        if not isinstance(item, dict):
            continue
        slot = str(item.get("Slot") or "").strip()
        if slot:
            out[slot.lower()] = item
    return out


def _engineering_modifier_value(module: dict[str, Any], label: str) -> float | None:
    engineering = module.get("Engineering")
    if not isinstance(engineering, dict):
        return None
    modifiers = engineering.get("Modifiers")
    if not isinstance(modifiers, list):
        return None
    wanted = label.strip().lower()
    for modifier in modifiers:
        if not isinstance(modifier, dict):
            continue
        if str(modifier.get("Label") or "").strip().lower() != wanted:
            continue
        value = _as_float(modifier.get("Value"))
        if value is not None:
            return value
    return None


def _module_power_capacity_mw(modules: list[dict[str, Any]]) -> tuple[float | None, str | None]:
    override = _as_float(ED_POWER_CAPACITY_MW_RAW)
    if override and override > 0:
        return override, "env_override"

    for module in modules:
        if str(module.get("slot") or "").lower() != "powerplant":
            continue
        for label in ("PowerCapacity", "powercapacity"):
            capacity = _engineering_modifier_value(module, label)
            if capacity and capacity > 0:
                return capacity, "powerplant_engineering"

    powered = [
        _as_float(module.get("power"))
        for module in modules
        if module.get("on") is not False and _as_float(module.get("power")) is not None
    ]
    total_power = sum(value or 0.0 for value in powered)
    if total_power <= 0:
        return None, None
    # Elite's right-panel Modules view shows module draw as % of available output.
    # The journal exposes raw module draw but not the bottom-panel output/usage line,
    # so use the next 5 MW band as a stable rough display denominator.
    capacity = float(((int(total_power) // 5) + 1) * 5)
    return max(capacity, total_power), "estimated_next_5mw"


def _annotate_module_power_percent(
    modules: list[dict[str, Any]],
) -> tuple[float | None, int | None, str | None]:
    capacity, basis = _module_power_capacity_mw(modules)
    if not capacity or capacity <= 0:
        return None, None, basis
    total_power = 0.0
    for module in modules:
        power = _as_float(module.get("power"))
        if power is None:
            module["power_percent"] = None
            continue
        if module.get("on") is not False:
            total_power += max(0.0, power)
        module["power_percent"] = max(0, min(100, int(round((power / capacity) * 100.0))))
    usage_percent = max(0, min(999, int(round((total_power / capacity) * 100.0))))
    return capacity, usage_percent, basis


def _normalize_module_item(
    module: dict[str, Any],
    *,
    metadata_by_slot: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    slot = str(module.get("Slot") or "").strip()
    item = str(module.get("Item") or "").strip()
    if not slot and not item:
        return None
    metadata = metadata_by_slot.get(slot.lower(), {})
    health_percent = _health_percent(module.get("Health"))
    power = module.get("Power", metadata.get("Power"))
    return {
        "slot": slot or None,
        "item": item or None,
        "health_percent": health_percent,
        "health_raw": module.get("Health"),
        "on": module.get("On"),
        "priority": module.get("Priority", metadata.get("Priority")),
        "power": power,
        "power_percent": None,
        "ammo_in_clip": module.get("AmmoInClip"),
        "ammo_in_hopper": module.get("AmmoInHopper"),
        "value": module.get("Value"),
    }


def _collect_modules_state(
    *,
    latest_journal: Path | None,
    modules_path: Path,
) -> dict[str, Any]:
    modules_info = _read_json_file(modules_path)
    loadout = _last_journal_event(latest_journal, "Loadout") if latest_journal is not None else None
    metadata_by_slot = _module_metadata_by_slot(modules_info)

    source = None
    source_path = None
    updated_at = None
    modules_payload: list[Any] = []
    ship_payload: dict[str, Any] = {}
    if isinstance(loadout, dict) and isinstance(loadout.get("Modules"), list):
        source = "journal_loadout"
        source_path = str(latest_journal)
        updated_at = loadout.get("timestamp")
        modules_payload = loadout.get("Modules") or []
        ship_payload = loadout
    elif isinstance(modules_info, dict) and isinstance(modules_info.get("Modules"), list):
        source = "modules_info"
        source_path = str(modules_path)
        updated_at = modules_info.get("timestamp")
        modules_payload = modules_info.get("Modules") or []
        ship_payload = modules_info

    modules: list[dict[str, Any]] = []
    for module in modules_payload:
        if not isinstance(module, dict):
            continue
        normalized = _normalize_module_item(module, metadata_by_slot=metadata_by_slot)
        if normalized is not None:
            modules.append(normalized)

    power_capacity_mw, power_usage_percent, power_basis = _annotate_module_power_percent(modules)
    health_available = any(item.get("health_percent") is not None for item in modules)
    return {
        "ed.modules.available": bool(modules),
        "ed.modules.health_available": bool(health_available),
        "ed.modules.power_capacity_mw": power_capacity_mw,
        "ed.modules.power_usage_percent": power_usage_percent,
        "ed.modules.power_percent_basis": power_basis,
        "ed.modules.source": source,
        "ed.modules.source_path": source_path or str(modules_path),
        "ed.modules.updated_at": updated_at,
        "ed.modules.count": len(modules),
        "ed.modules.items": modules,
        "ed.modules.ship": ship_payload.get("Ship") if isinstance(ship_payload, dict) else None,
        "ed.modules.ship_id": ship_payload.get("ShipID") if isinstance(ship_payload, dict) else None,
        "ed.modules.ship_name": ship_payload.get("ShipName") if isinstance(ship_payload, dict) else None,
        "ed.modules.ship_ident": ship_payload.get("ShipIdent") if isinstance(ship_payload, dict) else None,
        "ed.modules.hull_health_percent": _health_percent(
            ship_payload.get("HullHealth") if isinstance(ship_payload, dict) else None
        ),
    }


def _normalize_cargo_item(item: dict[str, Any]) -> dict[str, Any] | None:
    name = str(item.get("Name") or "").strip()
    localised = str(item.get("Name_Localised") or "").strip()
    count = item.get("Count", 0)
    try:
        count = int(count)
    except Exception:
        count = 0
    if not name and not localised:
        return None
    return {
        "name": name or None,
        "name_localised": localised or None,
        "count": max(0, count),
        "stolen": item.get("Stolen"),
        "mission_id": item.get("MissionID"),
    }


def _collect_cargo_state(cargo_path: Path) -> dict[str, Any]:
    payload = _read_json_file(cargo_path)
    inventory_raw = payload.get("Inventory") if isinstance(payload, dict) else None
    inventory = []
    if isinstance(inventory_raw, list):
        for item in inventory_raw:
            if isinstance(item, dict):
                normalized = _normalize_cargo_item(item)
                if normalized is not None:
                    inventory.append(normalized)
    limpet_count = 0
    for item in inventory:
        text = f"{item.get('name') or ''} {item.get('name_localised') or ''}".lower()
        if "limpet" in text or "drone" in text:
            limpet_count += int(item.get("count") or 0)
    return {
        "ed.cargo.available": isinstance(payload, dict),
        "ed.cargo.source_path": str(cargo_path),
        "ed.cargo.updated_at": payload.get("timestamp") if isinstance(payload, dict) else None,
        "ed.cargo.vessel": payload.get("Vessel") if isinstance(payload, dict) else None,
        "ed.cargo.count": payload.get("Count") if isinstance(payload, dict) else None,
        "ed.cargo.items": inventory,
        "ed.cargo.limpet_count": limpet_count,
    }


def collect_ed_file_state(
    *,
    status_path: Path = ED_STATUS_PATH,
    journal_dir: Path = ED_JOURNAL_DIR,
    modules_path: Path = ED_MODULES_PATH,
    cargo_path: Path = ED_CARGO_PATH,
) -> dict[str, Any]:
    status = _read_json_file(status_path)
    latest_journal = _latest_journal_path(journal_dir)
    journal_event = _last_json_line(latest_journal) if latest_journal is not None else None
    journal_location = (
        _latest_journal_location_context(latest_journal) if latest_journal is not None else {}
    )
    no_fire_zone = _latest_no_fire_zone_state(latest_journal)
    docking_state = _latest_docking_state(latest_journal)
    journal_context = _latest_journal_operational_context(latest_journal)

    out: dict[str, Any] = {
        "ed.status.source_path": str(status_path),
        "ed.journal.dir": str(journal_dir),
        "ed.journal.latest_path": str(latest_journal) if latest_journal else None,
        "ed.station.no_fire_zone": bool(no_fire_zone.get("value")),
        "ed.station.no_fire_zone_event": no_fire_zone.get("event"),
        "ed.station.no_fire_zone_station": no_fire_zone.get("station"),
        "ed.station.no_fire_zone_updated_at": no_fire_zone.get("timestamp"),
        "ed.station.no_fire_zone_source_path": no_fire_zone.get("source"),
        "ed.station.docking_state": docking_state.get("state"),
        "ed.station.docking_state_event": docking_state.get("event"),
        "ed.station.docking_state_station": docking_state.get("station"),
        "ed.station.docking_state_station_type": docking_state.get("station_type"),
        "ed.station.docking_state_market_id": docking_state.get("market_id"),
        "ed.station.docking_state_landing_pad": docking_state.get("landing_pad"),
        "ed.station.docking_state_landing_pads": docking_state.get("landing_pads"),
        "ed.station.docking_state_reason": docking_state.get("reason"),
        "ed.station.docking_state_updated_at": docking_state.get("timestamp"),
        "ed.station.docking_state_source_path": docking_state.get("source"),
    }
    out.update(journal_context)
    out.update(_collect_modules_state(latest_journal=latest_journal, modules_path=modules_path))
    out.update(_collect_cargo_state(cargo_path))

    if status is not None:
        flags = int(status.get("Flags") or 0)
        flags2 = int(status.get("Flags2") or 0)
        fuel = status.get("Fuel") if isinstance(status.get("Fuel"), dict) else {}
        out.update(
            {
                "ed.status.available": True,
                "ed.status.flags": flags,
                "ed.status.flags2": flags2,
                "ed.status.gui_focus": status.get("GuiFocus"),
                "ed.status.pips": status.get("Pips") if isinstance(status.get("Pips"), list) else None,
                "ed.status.fuel": fuel,
                "ed.status.fuel_main": fuel.get("FuelMain"),
                "ed.status.fuel_reservoir": fuel.get("FuelReservoir"),
                "ed.status.cargo": status.get("Cargo"),
                "ed.status.legal_state": status.get("LegalState"),
                "ed.status.fire_group": status.get("FireGroup"),
                "ed.status.temperature": status.get("Temperature"),
                "ed.status.body_name": status.get("BodyName"),
                "ed.status.latitude": status.get("Latitude"),
                "ed.status.longitude": status.get("Longitude"),
                "ed.status.altitude": status.get("Altitude"),
                "ed.status.heading": status.get("Heading"),
                "ed.status.selected_weapon": status.get("SelectedWeapon"),
                "ed.status.selected_weapon_localised": status.get("SelectedWeapon_Localised"),
                "ed.status.docked": _flag_set(flags, 0),
                "ed.status.landed": _flag_set(flags, 1),
                "ed.status.landing_gear_down": _flag_set(flags, 2),
                "ed.status.shields_up": _flag_set(flags, 3),
                "ed.status.supercruise": _flag_set(flags, 4),
                "ed.status.flight_assist_off": _flag_set(flags, 5),
                "ed.status.hardpoints_deployed": _flag_set(flags, 6),
                "ed.status.lights_on": _flag_set(flags, 8),
                "ed.status.cargo_scoop_deployed": _flag_set(flags, 9),
                "ed.status.silent_running": _flag_set(flags, 10),
                "ed.status.scooping_fuel": _flag_set(flags, 11),
                "ed.status.fsd_mass_locked": _flag_set(flags, 16),
                "ed.status.fsd_charging": _flag_set(flags, 17),
                "ed.status.fsd_cooldown": _flag_set(flags, 18),
                "ed.status.low_fuel": _flag_set(flags, 19),
                "ed.status.overheating": _flag_set(flags, 20),
                "ed.status.has_lat_long": _flag_set(flags, 21),
                "ed.status.in_danger": _flag_set(flags, 22),
                "ed.status.being_interdicted": _flag_set(flags, 23),
                "ed.status.in_main_ship": _flag_set(flags, 24),
                "ed.status.in_fighter": _flag_set(flags, 25),
                "ed.status.in_srv": _flag_set(flags, 26),
                "ed.status.analysis_mode": _flag_set(flags, 27),
                "ed.status.night_vision": _flag_set(flags, 28),
                "ed.status.altitude_from_average_radius": _flag_set(flags, 29),
                "ed.status.in_hyperspace": _flag_set(flags, 30),
                "ed.status.on_foot": _flag_set(flags2, 0),
                "ed.status.in_taxi": _flag_set(flags2, 1),
                "ed.status.in_multicrew": _flag_set(flags2, 2),
                "ed.status.on_foot_in_station": _flag_set(flags2, 3),
                "ed.status.on_foot_on_planet": _flag_set(flags2, 4),
                "ed.status.aim_down_sight": _flag_set(flags2, 5),
                "ed.status.low_oxygen": _flag_set(flags2, 6),
                "ed.status.low_health": _flag_set(flags2, 7),
                "ed.status.cold": _flag_set(flags2, 8),
                "ed.status.hot": _flag_set(flags2, 9),
                "ed.status.very_cold": _flag_set(flags2, 10),
                "ed.status.very_hot": _flag_set(flags2, 11),
                "ed.status.glide_mode": _flag_set(flags2, 12),
                "ed.status.on_foot_in_hangar": _flag_set(flags2, 13),
                "ed.status.on_foot_social_space": _flag_set(flags2, 14),
                "ed.status.on_foot_exterior": _flag_set(flags2, 15),
                "ed.status.breathable_atmosphere": _flag_set(flags2, 16),
                "ed.status.fsd_hyperdrive_charging": _flag_set(flags2, 19),
            }
        )
    else:
        out["ed.status.available"] = False

    if journal_event is not None:
        event_name = str(journal_event.get("event") or "").strip()
        out.update(
            {
                "ed.journal.last_event": event_name,
                "ed.journal.last_timestamp": journal_event.get("timestamp"),
                "ed.location.system": journal_event.get("StarSystem") or journal_location.get("system"),
                "ed.location.system_address": journal_event.get("SystemAddress")
                or journal_location.get("system_address"),
                "ed.location.station": journal_event.get("StationName") or journal_location.get("station"),
                "ed.location.body": journal_event.get("Body")
                or journal_event.get("BodyName")
                or journal_location.get("body"),
            }
        )
    else:
        out["ed.journal.last_event"] = None

    return out


def _runtime_sync_enabled(sync_id: str, default: bool = True) -> bool:
    now = time.monotonic()
    cached_syncs = _runtime_settings_cache.get("syncs")
    if (
        isinstance(cached_syncs, dict)
        and (now - float(_runtime_settings_cache.get("loaded_at") or 0.0))
        <= max(0.0, _RUNTIME_SETTINGS_CACHE_SEC)
    ):
        item = cached_syncs.get(sync_id)
        if not isinstance(item, dict) or "enabled" not in item:
            return bool(default)
        return bool(item.get("enabled"))

    try:
        con = sqlite3.connect(DB_PATH, timeout=1.0)
        try:
            row = con.execute(
                "SELECT value_json FROM config WHERE key=? LIMIT 1",
                (RUNTIME_SETTINGS_KEY,),
            ).fetchone()
        finally:
            con.close()
    except Exception:
        return bool(default)
    if not row:
        _runtime_settings_cache.update({"loaded_at": now, "syncs": {}})
        return bool(default)
    try:
        payload = json.loads(str(row[0]))
    except Exception:
        return bool(default)
    syncs = payload.get("syncs")
    if not isinstance(syncs, dict):
        _runtime_settings_cache.update({"loaded_at": now, "syncs": {}})
        return bool(default)
    _runtime_settings_cache.update({"loaded_at": now, "syncs": syncs})
    item = syncs.get(sync_id)
    if not isinstance(item, dict) or "enabled" not in item:
        return bool(default)
    return bool(item.get("enabled"))


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
    global _ytmd_next_allowed_at, _ytmd_cached_payload, _ytmd_cached_at
    status = {
        "music.api_endpoint": f"http://{YTMD_HOST}:{YTMD_PORT}/api/v1/state",
        "music.api_reachable": False,
        "music.api_authorized": False,
    }
    if not YTMD_ENABLED:
        return None, status

    now = time.time()
    token = _read_ytmd_token()
    if now < _ytmd_next_allowed_at:
        if _ytmd_cached_payload and (now - _ytmd_cached_at) <= max(0.0, YTMD_CACHE_MAX_SEC):
            status["music.api_reachable"] = True
            status["music.api_authorized"] = True if token else status["music.api_authorized"]
            return dict(_ytmd_cached_payload), status
        return None, status

    if not _port_open(YTMD_HOST, YTMD_PORT, YTMD_TIMEOUT_SEC):
        _ytmd_next_allowed_at = now + max(1.0, YTMD_REST_POLL_MS / 1000.0)
        if _ytmd_cached_payload and (now - _ytmd_cached_at) <= max(0.0, YTMD_CACHE_MAX_SEC):
            return dict(_ytmd_cached_payload), status
        return None, status
    status["music.api_reachable"] = True

    headers: dict[str, str] = {}
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
        if _ytmd_cached_payload and (now - _ytmd_cached_at) <= max(0.0, YTMD_CACHE_MAX_SEC):
            return dict(_ytmd_cached_payload), status
        return None, status
    except Exception:
        _ytmd_next_allowed_at = now + max(1.0, YTMD_REST_POLL_MS / 1000.0)
        if _ytmd_cached_payload and (now - _ytmd_cached_at) <= max(0.0, YTMD_CACHE_MAX_SEC):
            return dict(_ytmd_cached_payload), status
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
        _ytmd_cached_payload = None
        _ytmd_cached_at = 0.0
        return None, status
    out = {
        "title": title,
        "artist": artist,
        "album": album,
        "now_playing": now_playing,
        "artwork_path": thumb_url or None,
    }
    _ytmd_cached_payload = dict(out)
    _ytmd_cached_at = now
    return out, status


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
    configured = {str(name or "").strip().lower() for name in configured_names if str(name or "").strip()}
    return any(name in process_names for name in configured)


def collect_ed_state(process_names: set[str] | None = None) -> dict[str, Any]:
    running_name = ""
    if process_names is None:
        process_names = _list_process_names()
    for candidate in ED_PROCESS_NAMES:
        if candidate.lower() in process_names:
            running_name = candidate
            break
    running = bool(running_name)
    state = {
        "ed.running": running,
        "ed.process_name": running_name if running else None,
    }
    state.update(collect_ed_file_state())
    return state


def collect_music_state(process_names: set[str] | None = None) -> dict[str, Any]:
    if process_names is None:
        process_names = _list_process_names()
    ytmd_running = _process_running_by_names(process_names, YTMD_PROCESS_NAMES)
    ytmd_ingest_enabled = _runtime_sync_enabled("ytmd_ingest", True)
    if not ytmd_running:
        return {
            "music.app_running": False,
            "music.ingest_enabled": ytmd_ingest_enabled,
            "music.playing": False,
            "music.track.title": "",
            "music.track.artist": "",
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

    if not ytmd_ingest_enabled:
        return {
            "music.app_running": True,
            "music.ingest_enabled": False,
            "music.playing": False,
            "music.track.title": "",
            "music.track.artist": "",
            "music.source_path": f"ytmd_api://{YTMD_HOST}:{YTMD_PORT}",
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
            "music.ingest_enabled": ytmd_ingest_enabled,
            "music.playing": True,
            "music.track.title": track_payload.get("title", ""),
            "music.track.artist": track_payload.get("artist", ""),
            "music.source_path": f"ytmd_api://{YTMD_HOST}:{YTMD_PORT}",
            **api_status,
            "music.now_playing": track_payload,
        }
    if api_status.get("music.api_reachable") and api_status.get("music.api_authorized"):
        # API path is healthy but no usable track payload (e.g. transient rate-limit window).
        # Keep prior now-playing state instead of overwriting with empty file values.
        return {
            "music.app_running": True,
            "music.ingest_enabled": ytmd_ingest_enabled,
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
        "music.ingest_enabled": ytmd_ingest_enabled,
        "music.playing": playing,
        "music.track.title": primary_payload.get("title", ""),
        "music.track.artist": primary_payload.get("artist", ""),
        "music.source_path": str(source_dir),
        **api_status,
        "music.now_playing": primary_payload,
    }


def collect_system_state() -> dict[str, Any]:
    memory = MEMORYSTATUSEX()
    memory.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))

    utc_dt, local_dt = _clock_datetimes()
    timezone_name = local_dt.tzname() or ""
    timezone_offset = local_dt.strftime("%z")
    if timezone_offset and len(timezone_offset) == 5:
        timezone_offset = f"{timezone_offset[:3]}:{timezone_offset[3:]}"
    ed_game_dt = _ed_game_datetime_from_utc(utc_dt)

    uptime_ms = ctypes.windll.kernel32.GetTickCount64()
    memory_total = int(memory.ullTotalPhys)
    memory_avail = int(memory.ullAvailPhys)
    memory_used = max(memory_total - memory_avail, 0)
    memory_pct = (memory_used / memory_total) if memory_total > 0 else 0.0

    return {
        "system.time.utc_iso": _isoformat_ms(utc_dt).replace("+00:00", "Z"),
        "system.time.local_iso": _isoformat_ms(local_dt),
        "system.time.local_date": local_dt.strftime("%Y-%m-%d"),
        "system.time.local_time": local_dt.strftime("%H:%M:%S"),
        "system.time.timezone": timezone_name,
        "system.time.utc_offset": timezone_offset,
        "system.time.unix_ts": int(utc_dt.timestamp()),
        "ed.game_time.utc_iso": _isoformat_ms(ed_game_dt).replace("+00:00", "Z"),
        "ed.game_time.date": ed_game_dt.strftime("%Y-%m-%d"),
        "ed.game_time.time": ed_game_dt.strftime("%H:%M:%S"),
        "ed.game_time.year_offset": ED_GAME_YEAR_OFFSET,
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
    force_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    observed_at = utc_now_iso()
    items: list[dict[str, Any]] = []
    force_keys = force_keys or set()
    for key, value in latest_values.items():
        value_hash = _state_hash(value)
        if key not in force_keys and last_sent_hashes.get(key) == value_hash:
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
            pending_items.extend(
                _build_changed_items(
                    ed_state,
                    last_sent_hashes,
                    "ed_probe",
                    force_keys={
                        "ed.status.available",
                        "ed.status.source_path",
                        "ed.status.in_main_ship",
                        "ed.status.in_fighter",
                        "ed.status.in_srv",
                        "ed.status.fsd_mass_locked",
                        "ed.status.fsd_charging",
                        "ed.status.fsd_cooldown",
                        "ed.status.in_hyperspace",
                        "ed.journal.latest_path",
                        "ed.fighter.active",
                        "ed.fighter.last_event",
                        "ed.fighter.updated_at",
                        "ed.fighter.loadout",
                        "ed.fighter.id",
                        "ed.fighter.model",
                        "ed.fighter.model_localised",
                        "ed.fighter.player_controlled",
                        "ed.srv.active",
                        "ed.srv.last_event",
                        "ed.srv.updated_at",
                        "ed.srv.id",
                        "ed.srv.model",
                        "ed.srv.model_localised",
                        "ed.suit.updated_at",
                        "ed.suit.id",
                        "ed.suit.name",
                        "ed.suit.name_localised",
                        "ed.suit.loadout_id",
                        "ed.suit.loadout_name",
                        "ed.suit.modules",
                        "ed.cargo.available",
                        "ed.cargo.count",
                        "ed.cargo.items",
                        "ed.cargo.limpet_count",
                        "ed.station.no_fire_zone",
                        "ed.station.no_fire_zone_event",
                        "ed.station.no_fire_zone_station",
                        "ed.station.no_fire_zone_updated_at",
                    },
                )
            )
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
