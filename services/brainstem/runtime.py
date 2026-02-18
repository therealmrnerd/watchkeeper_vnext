import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ROOT_DIR = Path(__file__).resolve().parents[2]
for p in (THIS_DIR, ROOT_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from db_service import BrainstemDB
from edparser_tool import EDParserTool
from core.policy_engine import PolicyEngine
from core.tool_router import ToolRouter
from db.logbook import Logbook


DB_PATH = Path(os.getenv("WKV_DB_PATH", ROOT_DIR / "data" / "watchkeeper_vnext.db"))
SCHEMA_PATH = Path(
    os.getenv("WKV_SCHEMA_PATH", ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
)
HOST = os.getenv("WKV_HOST", "127.0.0.1")
PORT = int(os.getenv("WKV_PORT", "8787"))
ENABLE_ACTUATORS = os.getenv("WKV_ENABLE_ACTUATORS", "1").strip().lower() in {"1", "true", "yes"}
ENABLE_KEYPRESS = os.getenv("WKV_ENABLE_KEYPRESS", "0").strip().lower() in {"1", "true", "yes"}
LIGHTS_WEBHOOK_URL = os.getenv("WKV_LIGHTS_WEBHOOK_URL", "").strip()
LIGHTS_WEBHOOK_URL_TEMPLATE = os.getenv("WKV_LIGHTS_WEBHOOK_URL_TEMPLATE", "").strip()
LIGHTS_WEBHOOK_TIMEOUT_SEC = float(os.getenv("WKV_LIGHTS_WEBHOOK_TIMEOUT_SEC", "5"))
KEYPRESS_ALLOWED_PROCESSES = [
    p.strip().lower()
    for p in os.getenv(
        "WKV_KEYPRESS_ALLOWED_PROCESSES",
        "EliteDangerous64.exe,EliteDangerous.exe",
    ).split(",")
    if p.strip()
]
STANDING_ORDERS_PATH = Path(
    os.getenv("WKV_STANDING_ORDERS_PATH", ROOT_DIR / "config" / "standing_orders.json")
)
DEFAULT_WATCH_CONDITION = os.getenv("WKV_DEFAULT_WATCH_CONDITION", "STANDBY").strip().upper()
DB_SERVICE = BrainstemDB(DB_PATH, SCHEMA_PATH)
EDPARSER_TOOL = EDParserTool(db_service=DB_SERVICE)
POLICY_ENGINE = PolicyEngine(STANDING_ORDERS_PATH)
LOGBOOK = Logbook(db_service=DB_SERVICE, source="brainstem_policy")
TOOL_ROUTER = ToolRouter(policy_engine=POLICY_ENGINE, logbook=LOGBOOK)

INTENT_ALLOWED_KEYS = {
    "schema_version",
    "request_id",
    "session_id",
    "timestamp_utc",
    "mode",
    "domain",
    "urgency",
    "user_text",
    "needs_tools",
    "needs_clarification",
    "clarification_questions",
    "retrieval",
    "proposed_actions",
    "response_text",
}

ACTION_ALLOWED_KEYS = {
    "action_id",
    "tool_name",
    "parameters",
    "safety_level",
    "mode_constraints",
    "requires_confirmation",
    "timeout_ms",
    "reason",
    "confidence",
}

STATE_ITEM_ALLOWED_KEYS = {
    "state_key",
    "state_value",
    "source",
    "confidence",
    "observed_at_utc",
}

STATE_INGEST_ALLOWED_KEYS = {
    "items",
    "emit_events",
    "profile",
    "session_id",
    "correlation_id",
}

FEEDBACK_ALLOWED_KEYS = {
    "request_id",
    "rating",
    "correction_text",
    "reviewer",
    "session_id",
    "mode",
}

CONFIRM_ALLOWED_KEYS = {
    "incident_id",
    "tool_name",
    "user_confirm_token",
    "confirmed_at_utc",
    "request_id",
    "session_id",
    "mode",
}

MODE_SET = {"game", "work", "standby", "tutor"}
DOMAIN_SET = {
    "gameplay",
    "lore",
    "astrophysics",
    "general_gaming",
    "coding",
    "networking",
    "system",
    "music",
    "speech",
    "general",
}
URGENCY_SET = {"low", "normal", "high"}
SAFETY_SET = {"read_only", "low_risk", "high_risk"}
MAX_ACTIONS = 10

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002

SPECIAL_VK_MAP = {
    "space": 0x20,
    "enter": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}
for i in range(1, 13):
    SPECIAL_VK_MAP[f"f{i}"] = 0x6F + i


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso8601_utc(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp_utc must be a non-empty string")
    normalized = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("timestamp_utc must be ISO-8601") from exc


def iso8601_utc_to_epoch(value: str) -> float:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).timestamp()


def connect_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def ensure_db() -> None:
    DB_SERVICE.ensure_schema()


def parse_json(raw: Any, fallback: Any) -> Any:
    if raw is None:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback
