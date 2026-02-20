import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
import time
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
from core.policy.twitch_policy import TwitchPolicyEngine
from core.tool_router import ToolRouter
from db.logbook import Logbook
from db.twitch_repo import TwitchRepository
from sammi_client import SammiClient
from twitch_ingest import TwitchIngestService


DB_PATH = Path(os.getenv("WKV_DB_PATH", ROOT_DIR / "data" / "watchkeeper_vnext.db"))
SCHEMA_PATH = Path(
    os.getenv("WKV_SCHEMA_PATH", ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
)
HOST = os.getenv("WKV_HOST", "127.0.0.1")
PORT = int(os.getenv("WKV_PORT", "8787"))
START_TS = time.time()
VERSION = os.getenv("WKV_VERSION", "vnext-dev").strip() or "vnext-dev"
COMMIT = os.getenv("WKV_COMMIT", "").strip() or "unknown"
UI_DIR = Path(os.getenv("WKV_UI_DIR", THIS_DIR / "ui"))
LOG_DIR = Path(os.getenv("WKV_LOG_DIR", ROOT_DIR / "logs"))
SNAPSHOT_DIR = Path(os.getenv("WKV_SNAPSHOT_DIR", ROOT_DIR / "snapshots"))
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

ASSIST_REQUEST_ALLOWED_KEYS = {
    "schema_version",
    "request_id",
    "session_id",
    "timestamp_utc",
    "mode",
    "domain",
    "urgency",
    "watch_condition",
    "incident_id",
    "user_text",
    "stt_confidence",
    "foreground_process",
    "max_actions",
    "context",
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
    "confirm_token",
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
WATCH_CONDITION_SET = {"STANDBY", "GAME", "WORK", "TUTOR", "RESTRICTED", "DEGRADED"}

ADVISORY_ENABLED = os.getenv("WKV_ADVISORY_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
ADVISORY_URL = os.getenv("WKV_ADVISORY_URL", "http://127.0.0.1:8790/assist").strip()
ADVISORY_TIMEOUT_SEC = float(os.getenv("WKV_ADVISORY_TIMEOUT_SEC", "8"))
ADVISORY_HEALTH_URL = os.getenv("WKV_ADVISORY_HEALTH_URL", "http://127.0.0.1:8790/health").strip()
KNOWLEDGE_HEALTH_URL = os.getenv("WKV_KNOWLEDGE_HEALTH_URL", "http://127.0.0.1:8791/health").strip()
QDRANT_HEALTH_URL = os.getenv("WKV_QDRANT_HEALTH_URL", "http://127.0.0.1:6333/healthz").strip()
SAMMI_API_ENABLED = os.getenv("WKV_SAMMI_API_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
SAMMI_API_HOST = os.getenv("WKV_SAMMI_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
SAMMI_API_PORT = int(os.getenv("WKV_SAMMI_API_PORT", "9450"))
SAMMI_API_PASSWORD = os.getenv("WKV_SAMMI_API_PASSWORD", "").strip()
SAMMI_API_TIMEOUT_SEC = float(os.getenv("WKV_SAMMI_API_TIMEOUT_SEC", "0.8"))
TWITCH_UDP_ENABLED = os.getenv("WKV_TWITCH_UDP_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
TWITCH_UDP_HOST = os.getenv("WKV_TWITCH_UDP_HOST", "127.0.0.1").strip() or "127.0.0.1"
TWITCH_UDP_PORT = int(os.getenv("WKV_TWITCH_UDP_PORT", "9765"))
TWITCH_CHAT_DEBOUNCE_MS = int(os.getenv("WKV_TWITCH_CHAT_DEBOUNCE_MS", "250"))
TWITCH_REDEEM_DEBOUNCE_MS = int(os.getenv("WKV_TWITCH_REDEEM_DEBOUNCE_MS", "0"))
TWITCH_BITS_DEBOUNCE_MS = int(os.getenv("WKV_TWITCH_BITS_DEBOUNCE_MS", "0"))
TWITCH_FOLLOW_DEBOUNCE_MS = int(os.getenv("WKV_TWITCH_FOLLOW_DEBOUNCE_MS", "0"))
TWITCH_SUB_DEBOUNCE_MS = int(os.getenv("WKV_TWITCH_SUB_DEBOUNCE_MS", "0"))
TWITCH_RAID_DEBOUNCE_MS = int(os.getenv("WKV_TWITCH_RAID_DEBOUNCE_MS", "0"))
TWITCH_HYPE_TRAIN_DEBOUNCE_MS = int(os.getenv("WKV_TWITCH_HYPE_TRAIN_DEBOUNCE_MS", "0"))
TWITCH_POLL_DEBOUNCE_MS = int(os.getenv("WKV_TWITCH_POLL_DEBOUNCE_MS", "0"))
TWITCH_PREDICTION_DEBOUNCE_MS = int(os.getenv("WKV_TWITCH_PREDICTION_DEBOUNCE_MS", "0"))
TWITCH_SHOUTOUT_DEBOUNCE_MS = int(os.getenv("WKV_TWITCH_SHOUTOUT_DEBOUNCE_MS", "0"))
TWITCH_POWER_UPS_DEBOUNCE_MS = int(os.getenv("WKV_TWITCH_POWER_UPS_DEBOUNCE_MS", "0"))
TWITCH_HYPE_DEBOUNCE_MS = int(os.getenv("WKV_TWITCH_HYPE_DEBOUNCE_MS", "0"))
TWITCH_DEBOUNCE_MS_BY_EVENT = {
    "CHAT": TWITCH_CHAT_DEBOUNCE_MS,
    "REDEEM": TWITCH_REDEEM_DEBOUNCE_MS,
    "BITS": TWITCH_BITS_DEBOUNCE_MS,
    "FOLLOW": TWITCH_FOLLOW_DEBOUNCE_MS,
    "SUB": TWITCH_SUB_DEBOUNCE_MS,
    "RAID": TWITCH_RAID_DEBOUNCE_MS,
    "HYPE_TRAIN": TWITCH_HYPE_TRAIN_DEBOUNCE_MS,
    "POLL": TWITCH_POLL_DEBOUNCE_MS,
    "PREDICTION": TWITCH_PREDICTION_DEBOUNCE_MS,
    "SHOUTOUT": TWITCH_SHOUTOUT_DEBOUNCE_MS,
    "POWER_UPS": TWITCH_POWER_UPS_DEBOUNCE_MS,
    "HYPE": TWITCH_HYPE_DEBOUNCE_MS,
}
TWITCH_CHAT_SEND_VAR = os.getenv("WKV_TWITCH_CHAT_SEND_VAR", "Twitch_Chat.wk_chat").strip() or "Twitch_Chat.wk_chat"
TWITCH_CHAT_SEND_BUTTON = os.getenv("WKV_TWITCH_CHAT_SEND_BUTTON", "Twitch_Chat").strip() or "Twitch_Chat"
TWITCH_CHAT_STRICT_CONFIRM = os.getenv("WKV_TWITCH_CHAT_STRICT_CONFIRM", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}
TWITCH_VARIABLE_INDEX_PATH = Path(
    os.getenv("WKV_TWITCH_VARIABLE_INDEX_PATH", ROOT_DIR / "config" / "sammi_variable_index.json")
)
TWITCH_UDP_ACK_ONLY = os.getenv("WKV_TWITCH_UDP_ACK_ONLY", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}
TWITCH_DEV_INGEST_ENABLED = os.getenv("WKV_TWITCH_DEV_INGEST_ENABLED", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}

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


TWITCH_REPO = TwitchRepository(DB_SERVICE)
TWITCH_POLICY_ENGINE = TwitchPolicyEngine()
SAMMI_CLIENT = SammiClient(
    enabled=SAMMI_API_ENABLED,
    host=SAMMI_API_HOST,
    port=SAMMI_API_PORT,
    password=SAMMI_API_PASSWORD,
    timeout_sec=SAMMI_API_TIMEOUT_SEC,
)
TWITCH_INGEST_SERVICE = TwitchIngestService(
    db_service=DB_SERVICE,
    repo=TWITCH_REPO,
    sammi_client=SAMMI_CLIENT,
    source="twitch_ingest",
    chat_debounce_ms=TWITCH_CHAT_DEBOUNCE_MS,
    debounce_ms_by_event=TWITCH_DEBOUNCE_MS_BY_EVENT,
    ack_only=TWITCH_UDP_ACK_ONLY,
    variable_index_path=TWITCH_VARIABLE_INDEX_PATH,
)
