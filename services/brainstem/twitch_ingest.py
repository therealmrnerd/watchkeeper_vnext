import json
import math
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from db.twitch_repo import TwitchRepository
from sammi_client import SammiClient
from twitch_variable_index import (
    DEFAULT_EVENT_COMMIT_KEYS,
    DEFAULT_EVENT_FIELD_MAP,
    load_twitch_variable_index,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _dt_to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _normalize_marker_ts(raw_value: str) -> str:
    text = str(raw_value or "").strip()
    if not text or not text.isdigit():
        return text
    try:
        marker_int = int(text)
    except Exception:
        return text
    if marker_int <= 0:
        return text
    try:
        if len(text) >= 13:
            return _dt_to_iso(datetime.fromtimestamp(float(marker_int) / 1000.0, tz=timezone.utc))
        if len(text) >= 10:
            return _dt_to_iso(datetime.fromtimestamp(float(marker_int), tz=timezone.utc))
        base_2020 = datetime(2020, 1, 1, tzinfo=timezone.utc)
        return _dt_to_iso(base_2020 + timedelta(seconds=marker_int))
    except Exception:
        return text


class TwitchEventType(str, Enum):
    CHAT = "CHAT"
    REDEEM = "REDEEM"
    BITS = "BITS"
    FOLLOW = "FOLLOW"
    SUB = "SUB"
    RAID = "RAID"
    HYPE_TRAIN = "HYPE_TRAIN"
    POLL = "POLL"
    PREDICTION = "PREDICTION"
    SHOUTOUT = "SHOUTOUT"
    POWER_UPS = "POWER_UPS"
    HYPE = "HYPE"


@dataclass
class TwitchSnapshot:
    event_type: TwitchEventType
    commit_ts: str
    payload: dict[str, Any]
    seq: int = 0
    source: str = "sammi"


class TwitchIngestService:
    def __init__(
        self,
        *,
        db_service: Any,
        repo: TwitchRepository,
        sammi_client: SammiClient,
        source: str = "twitch_ingest",
        chat_debounce_ms: int = 250,
        ack_only: bool = False,
        variable_index_path: str | Path | None = None,
    ) -> None:
        self.db_service = db_service
        self.repo = repo
        self.sammi = sammi_client
        self.source = source
        self.chat_debounce_ms = max(0, int(chat_debounce_ms))
        self.ack_only = bool(ack_only)
        self._lock = threading.Lock()
        self._pending_markers: dict[TwitchEventType, str] = {}
        self._debounce_timers: dict[TwitchEventType, threading.Timer] = {}
        self._last_doorbell_ts = 0.0
        self._last_doorbell_event = TwitchEventType.CHAT
        self._last_payload_signature: dict[TwitchEventType, str] = {}
        fields_by_event, commits_by_event = load_twitch_variable_index(variable_index_path)
        self.event_field_map: dict[TwitchEventType, dict[str, list[str]]] = {}
        self.event_commit_keys: dict[TwitchEventType, list[str]] = {}
        for event_type in TwitchEventType:
            default_fields = DEFAULT_EVENT_FIELD_MAP.get(event_type.value, {})
            default_commits = DEFAULT_EVENT_COMMIT_KEYS.get(event_type.value, [])
            self.event_field_map[event_type] = {
                field_name: list(var_names)
                for field_name, var_names in fields_by_event.get(event_type.value, default_fields).items()
            }
            self.event_commit_keys[event_type] = list(commits_by_event.get(event_type.value, default_commits))

    @staticmethod
    def parse_doorbell(payload_text: str) -> tuple[TwitchEventType, str, int]:
        raw_original = str(payload_text or "")
        raw = raw_original.strip().strip("\x00")
        if not raw:
            # Some SAMMI buffer modes can deliver boolean/null-byte payloads.
            # Route through ambiguous handling to detect which event payload changed.
            return TwitchEventType.CHAT, "__AUTO__", 0
        # Numeric-safe aliases for SAMMI setups where string payloads are unstable.
        # Keep 0/1 reserved for ambiguous/boolean behavior.
        numeric_aliases = {
            "101": "CHAT",
            "102": "REDEEM",
            "103": "BITS",
            "104": "FOLLOW",
            "105": "SUB",
            "106": "RAID",
            "107": "HYPE_TRAIN",
            "108": "POLL",
            "109": "PREDICTION",
            "110": "SHOUTOUT",
            "111": "POWER_UPS",
            "112": "HYPE",
        }

        # Packed numeric form: CCC<timestamp>, e.g. 104193735314 => FOLLOW|193735314.
        # This avoids string buffer types in SAMMI while preserving category + commit marker.
        if "|" not in raw and raw.isdigit() and len(raw) >= 4:
            if raw in {"0", "1"}:
                return TwitchEventType.CHAT, "__AUTO__", 0
            code = raw[:3]
            packed_ts = raw[3:].strip()
            normalized = numeric_aliases.get(code)
            if normalized and packed_ts:
                return TwitchEventType(normalized), packed_ts, 0
        parts = raw.split("|")
        raw_event_name = parts[0].strip().upper()
        event_aliases = {
            "CHAT": "CHAT",
            "REDEEM": "REDEEM",
            "BITS": "BITS",
            "BITDONATION": "BITS",
            "FOLLOW": "FOLLOW",
            "NEWFOLLOW": "FOLLOW",
            "SUB": "SUB",
            "SUBSCRIPTION": "SUB",
            "RAID": "RAID",
            "HYPETRAIN": "HYPE_TRAIN",
            "HYPE_TRAIN": "HYPE_TRAIN",
            "POLL": "POLL",
            "PREDICTION": "PREDICTION",
            "SHOUTOUT": "SHOUTOUT",
            "POWERUPS": "POWER_UPS",
            "POWER_UPS": "POWER_UPS",
            "HYPE": "HYPE",
            **numeric_aliases,
        }
        if raw_event_name in {"1", "TRUE", "FALSE", "0"}:
            return TwitchEventType.CHAT, "__AUTO__", 0
        normalized_event_name = event_aliases.get(raw_event_name, raw_event_name)
        if normalized_event_name == raw_event_name and raw_event_name not in event_aliases:
            return TwitchEventType.CHAT, "__AUTO__", 0
        event_type = TwitchEventType(normalized_event_name)
        marker = str(parts[1]).strip() if len(parts) > 1 else ""
        seq = 0
        if len(parts) > 2:
            try:
                seq = int(str(parts[2]).strip() or "0")
            except ValueError:
                seq = 0
        return event_type, marker, max(0, seq)

    @staticmethod
    def _looks_like_variable_name(value: str) -> bool:
        text = str(value or "").strip()
        if not text or "." not in text:
            return False
        if ":" in text or "-" in text or " " in text:
            return False
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._")
        return all(ch in allowed for ch in text)

    def _resolve_commit_marker(
        self,
        *,
        event_type: TwitchEventType,
        marker_hint: str | None,
    ) -> tuple[str, str]:
        marker = str(marker_hint or "").strip()
        default_keys = list(self.event_commit_keys.get(event_type, []))
        default_key = default_keys[0] if default_keys else "packet.timestamp"

        if marker:
            if self._looks_like_variable_name(marker):
                value = self.sammi.get_var(marker)
                resolved = str(value or "").strip()
                if resolved:
                    return _normalize_marker_ts(resolved), marker
                # Marker variable is unavailable; continue with packet marker fallback.
                if marker.isdigit() or marker.endswith("Z") or ("T" in marker and ":" in marker):
                    return _normalize_marker_ts(marker), marker
                return _utc_now_iso(), marker

            # Doorbell payload provided a marker value (for example numeric seconds).
            # Preferred flow is still to read the authoritative commit marker from SAMMI vars.
            for key in default_keys:
                value = self.sammi.get_var(key)
                resolved = str(value or "").strip()
                if resolved:
                    return resolved, key

            # Fallback only when commit marker vars are unavailable.
            return _normalize_marker_ts(marker), default_key

        for key in default_keys:
            value = self.sammi.get_var(key)
            resolved = str(value or "").strip()
            if resolved:
                return _normalize_marker_ts(resolved), key
        # No marker and no readable commit key from SAMMI. Use current UTC so ingest still proceeds.
        return _utc_now_iso(), default_key

    def record_packet_parse_error(self, payload_text: str, error_text: str) -> None:
        try:
            raw = str(payload_text or "")
            self.db_service.append_event(
                event_id=str(uuid.uuid4()),
                timestamp_utc=_utc_now_iso(),
                event_type="TWITCH_PACKET_PARSE_ERROR",
                source=self.source,
                payload={
                    "raw_payload": raw[:512],
                    "error": str(error_text or "")[:512],
                },
                severity="warn",
                tags=["twitch", "doorbell", "parse_error"],
            )
        except Exception:
            return

    @staticmethod
    def _snapshot_signature(payload: dict[str, Any]) -> str:
        core: dict[str, Any] = {}
        for key, value in (payload or {}).items():
            if key in {"commit_key", "commit_ts"}:
                continue
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            core[key] = value
        if not core:
            return ""
        try:
            return json.dumps(core, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            return str(core)

    @staticmethod
    def _snapshot_has_signal(payload: dict[str, Any]) -> bool:
        for key, value in (payload or {}).items():
            if key in {"commit_key", "commit_ts"}:
                continue
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return True
        return False

    def _coerce_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        text = str(value or "").strip().lower()
        return text in {"1", "true", "yes", "on"}

    def _parse_flags(self, payload: dict[str, Any]) -> dict[str, Any]:
        flags_raw = payload.get("flags_json")
        flags: dict[str, Any] = {}
        if isinstance(flags_raw, str) and flags_raw.strip():
            try:
                parsed = json.loads(flags_raw)
                if isinstance(parsed, dict):
                    flags.update(parsed)
            except Exception:
                pass
        for key in ("is_vip", "is_mod", "is_sub", "is_broadcaster"):
            if key in payload:
                flags[key] = self._coerce_bool(payload.get(key))
        return flags

    @staticmethod
    def _normalize_user_id(payload: dict[str, Any]) -> str:
        raw_user_id = payload.get("user_id")
        user_id = ""
        if isinstance(raw_user_id, bool):
            user_id = ""
        elif isinstance(raw_user_id, int):
            user_id = str(raw_user_id)
        elif isinstance(raw_user_id, float):
            if math.isfinite(raw_user_id) and raw_user_id.is_integer():
                user_id = str(int(raw_user_id))
            elif math.isfinite(raw_user_id):
                user_id = str(raw_user_id).strip()
        else:
            text = str(raw_user_id or "").strip()
            if text:
                try:
                    as_float = float(text)
                    if math.isfinite(as_float) and as_float.is_integer() and any(
                        token in text for token in (".", "e", "E")
                    ):
                        text = str(int(as_float))
                except Exception:
                    pass
            user_id = text
        if user_id:
            return user_id
        login = str(payload.get("login_name") or "").strip().lower()
        if login:
            return f"login:{login}"
        return "unknown"

    def read_sammi_snapshot(
        self,
        event_type: TwitchEventType,
        marker_hint: str | None = None,
    ) -> TwitchSnapshot | None:
        commit_ts, commit_key = self._resolve_commit_marker(
            event_type=event_type,
            marker_hint=marker_hint,
        )
        if not commit_ts:
            return None

        cursor = self.repo.get_cursor(event_type.value)
        if commit_ts <= str(cursor.get("last_commit_ts") or ""):
            return None

        key_map = self.event_field_map[event_type]
        all_var_names: list[str] = []
        for names in key_map.values():
            for var_name in names:
                if var_name not in all_var_names:
                    all_var_names.append(var_name)
        values = self.sammi.get_vars(all_var_names)
        payload: dict[str, Any] = {}
        for field_name, var_names in key_map.items():
            resolved = None
            for var_name in var_names:
                value = values.get(var_name)
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                resolved = value
                break
            payload[field_name] = resolved
        payload["commit_key"] = commit_key
        payload["commit_ts"] = commit_ts
        return TwitchSnapshot(event_type=event_type, commit_ts=commit_ts, payload=payload)

    def persist(self, snapshot: TwitchSnapshot) -> dict[str, Any]:
        payload = dict(snapshot.payload or {})
        event_type = snapshot.event_type
        commit_ts = str(snapshot.commit_ts or "").strip() or _utc_now_iso()
        seq = max(0, int(snapshot.seq or 0))
        chat_seen_count = 0
        is_first_chat = False

        cursor_result = self.repo.set_cursor(event_type.value, commit_ts, seq=seq)
        if not bool(cursor_result.get("updated")):
            return {
                "processed": False,
                "reason": "duplicate_or_old_commit",
                "event_type": event_type.value,
                "commit_ts": commit_ts,
            }

        user_id = self._normalize_user_id(payload)
        login_name = str(payload.get("login_name") or "").strip() or None
        display_name = str(payload.get("display_name") or "").strip() or None
        flags = self._parse_flags(payload)
        increment_messages = 1 if event_type == TwitchEventType.CHAT else 0

        self.repo.upsert_user(
            user_id=user_id,
            login_name=login_name,
            display_name=display_name,
            flags=flags,
            seen_ts_utc=commit_ts,
            increment_messages=increment_messages,
        )

        if event_type == TwitchEventType.CHAT:
            self.repo.insert_recent_message_and_prune(
                user_id=user_id,
                message_ts_utc=commit_ts,
                msg_id=str(payload.get("message_id") or "").strip() or None,
                text=str(payload.get("message_text") or "").strip(),
                keep_last=5,
            )
            chat_seen_count = self.repo.get_user_message_count(user_id)
            is_first_chat = chat_seen_count <= 1
        elif event_type == TwitchEventType.BITS:
            amount = int(payload.get("amount") or 0)
            self.repo.add_bits(user_id=user_id, amount=amount, ts_utc=commit_ts)
        elif event_type == TwitchEventType.FOLLOW:
            pass
        elif event_type == TwitchEventType.SUB:
            pass
        elif event_type == TwitchEventType.RAID:
            pass
        elif event_type == TwitchEventType.HYPE_TRAIN:
            pass
        elif event_type == TwitchEventType.POLL:
            pass
        elif event_type == TwitchEventType.PREDICTION:
            pass
        elif event_type == TwitchEventType.SHOUTOUT:
            pass
        elif event_type == TwitchEventType.POWER_UPS:
            pass
        elif event_type == TwitchEventType.REDEEM:
            reward_id = str(payload.get("reward_id") or "").strip() or "unknown_reward"
            reward_title = str(payload.get("reward_title") or "").strip()
            self.repo.add_redeem(
                user_id=user_id,
                reward_id=reward_id,
                title=reward_title,
                ts_utc=commit_ts,
            )
        elif event_type == TwitchEventType.HYPE:
            amount = int(payload.get("amount") or 0)
            self.repo.add_hype(user_id=user_id, amount=amount, ts_utc=commit_ts)

        recent_payload = {
            "event_type": event_type.value,
            "user_id": user_id,
            "login_name": login_name,
            "display_name": display_name,
            "payload": payload,
        }
        if event_type == TwitchEventType.CHAT:
            recent_payload["chat_seen_count"] = chat_seen_count
            recent_payload["is_first_chat"] = is_first_chat
        self.repo.record_recent_event(
            event_type=event_type.value,
            commit_ts=commit_ts,
            user_id=user_id,
            payload=recent_payload,
        )

        self.db_service.append_event(
            event_id=str(uuid.uuid4()),
            timestamp_utc=commit_ts,
            event_type=f"TWITCH_{event_type.value}_INGESTED",
            source=self.source,
            payload={
                "event_type": event_type.value,
                "commit_ts": commit_ts,
                "user_id": user_id,
                "seq": seq,
                "chat_seen_count": chat_seen_count if event_type == TwitchEventType.CHAT else None,
                "is_first_chat": is_first_chat if event_type == TwitchEventType.CHAT else None,
            },
            severity="info",
            tags=["twitch", event_type.value.lower(), "ingest"],
        )
        signature = self._snapshot_signature(payload)
        if signature:
            self._last_payload_signature[event_type] = signature
        return {
            "processed": True,
            "event_type": event_type.value,
            "commit_ts": commit_ts,
            "user_id": user_id,
            "chat_seen_count": chat_seen_count if event_type == TwitchEventType.CHAT else None,
            "is_first_chat": is_first_chat if event_type == TwitchEventType.CHAT else None,
        }

    def _ack_packet(
        self,
        *,
        event_type: TwitchEventType,
        marker: str,
        seq: int,
    ) -> dict[str, Any]:
        commit_ts = _normalize_marker_ts(str(marker or "").strip()) or _utc_now_iso()
        cursor_result = self.repo.set_cursor(event_type.value, commit_ts, seq=max(0, int(seq or 0)))
        if not bool(cursor_result.get("updated")):
            return {
                "accepted": True,
                "processed": False,
                "ack_only": True,
                "event_type": event_type.value,
                "commit_ts": commit_ts,
                "reason": "duplicate_or_old_commit",
            }
        self.db_service.append_event(
            event_id=str(uuid.uuid4()),
            timestamp_utc=commit_ts,
            event_type="TWITCH_PACKET_RECEIVED",
            source=self.source,
            payload={
                "event_type": event_type.value,
                "commit_ts": commit_ts,
                "seq": max(0, int(seq or 0)),
                "ack_only": True,
            },
            severity="info",
            tags=["twitch", "doorbell", "ack"],
        )
        return {
            "accepted": True,
            "processed": True,
            "ack_only": True,
            "event_type": event_type.value,
            "commit_ts": commit_ts,
        }

    def _flush_debounced(self, event_type: TwitchEventType) -> None:
        marker = ""
        with self._lock:
            marker = self._pending_markers.pop(event_type, "")
            self._debounce_timers.pop(event_type, None)
        if not marker:
            return
        snapshot = self.read_sammi_snapshot(event_type, marker_hint=marker)
        if snapshot is None:
            return
        self.persist(snapshot)

    def _handle_immediate(self, event_type: TwitchEventType, marker: str, seq: int) -> dict[str, Any]:
        snapshot = self.read_sammi_snapshot(event_type, marker_hint=marker)
        if snapshot is None:
            return {"accepted": True, "processed": False, "reason": "no_new_commit"}
        snapshot.seq = seq
        result = self.persist(snapshot)
        return {"accepted": True, **result}

    def _handle_ambiguous_ping(self, seq: int = 0) -> dict[str, Any]:
        event_priority = [
            TwitchEventType.CHAT,
            TwitchEventType.REDEEM,
            TwitchEventType.BITS,
            TwitchEventType.FOLLOW,
            TwitchEventType.SUB,
            TwitchEventType.RAID,
            TwitchEventType.HYPE_TRAIN,
            TwitchEventType.POLL,
            TwitchEventType.PREDICTION,
            TwitchEventType.SHOUTOUT,
            TwitchEventType.POWER_UPS,
            TwitchEventType.HYPE,
        ]
        for event_type in event_priority:
            snapshot = self.read_sammi_snapshot(event_type, marker_hint=None)
            if snapshot is None:
                continue
            if not self._snapshot_has_signal(snapshot.payload):
                continue
            signature = self._snapshot_signature(snapshot.payload)
            if signature and self._last_payload_signature.get(event_type) == signature:
                continue
            snapshot.seq = max(0, int(seq or 0))
            result = self.persist(snapshot)
            if result.get("processed"):
                return {
                    "accepted": True,
                    "ambiguous": True,
                    "guessed_event_type": event_type.value,
                    **result,
                }
        return {
            "accepted": True,
            "processed": False,
            "ambiguous": True,
            "reason": "no_changed_event_snapshot",
        }

    def handle_ping(self, payload_text: str) -> dict[str, Any]:
        event_type, marker, seq = self.parse_doorbell(payload_text)
        if marker == "__AUTO__":
            return self._handle_ambiguous_ping(seq=seq)
        now = time.monotonic()
        # Heuristic for SAMMI boolean/null payload follow-up packet behavior:
        # if we receive a generic CHAT fallback immediately after a non-CHAT event,
        # keep the previous event type.
        if (
            event_type == TwitchEventType.CHAT
            and marker
            and marker.endswith("Z")
            and (now - self._last_doorbell_ts) <= 0.4
            and self._last_doorbell_event != TwitchEventType.CHAT
        ):
            event_type = self._last_doorbell_event
        self._last_doorbell_ts = now
        self._last_doorbell_event = event_type
        if self.ack_only:
            return self._ack_packet(event_type=event_type, marker=marker, seq=seq)
        if event_type == TwitchEventType.CHAT and self.chat_debounce_ms > 0:
            with self._lock:
                self._pending_markers[event_type] = marker or _utc_now_iso()
                timer = self._debounce_timers.get(event_type)
                if timer is not None and timer.is_alive():
                    return {"accepted": True, "debounced": True, "event_type": event_type.value}
                new_timer = threading.Timer(
                    float(self.chat_debounce_ms) / 1000.0,
                    self._flush_debounced,
                    args=(event_type,),
                )
                new_timer.daemon = True
                self._debounce_timers[event_type] = new_timer
                new_timer.start()
            return {"accepted": True, "debounced": True, "event_type": event_type.value}
        return self._handle_immediate(event_type, marker, seq)

    def ingest_mock(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event_enum = TwitchEventType(str(event_type or "").strip().upper())
        commit_ts = str(payload.get("commit_ts") or "").strip() or _utc_now_iso()
        seq = int(payload.get("seq") or 0)
        snap = TwitchSnapshot(
            event_type=event_enum,
            commit_ts=commit_ts,
            payload=dict(payload),
            seq=max(0, seq),
            source="mock",
        )
        return self.persist(snap)


class TwitchDoorbellListener:
    def __init__(
        self,
        *,
        ingest_service: TwitchIngestService,
        host: str,
        port: int,
        enabled: bool = True,
        should_listen: Callable[[], bool] | None = None,
    ) -> None:
        self.ingest_service = ingest_service
        self.host = str(host or "127.0.0.1").strip() or "127.0.0.1"
        self.port = int(port)
        self.enabled = bool(enabled)
        self._should_listen = should_listen
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="twitch-udp-listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _wants_listen(self) -> bool:
        if not self.enabled:
            return False
        if self._should_listen is None:
            return True
        try:
            return bool(self._should_listen())
        except Exception:
            return False

    def _run(self) -> None:
        sock: socket.socket | None = None
        while not self._stop.is_set():
            wants_listen = self._wants_listen()
            if not wants_listen:
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass
                    sock = None
                    self._socket = None
                time.sleep(0.5)
                continue

            if sock is None:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.settimeout(0.5)
                    sock.bind((self.host, self.port))
                    self._socket = sock
                except Exception:
                    if sock is not None:
                        try:
                            sock.close()
                        except Exception:
                            pass
                    sock = None
                    self._socket = None
                    if self._stop.is_set():
                        break
                    time.sleep(1.0)
                    continue

            try:
                packet, _addr = sock.recvfrom(8192)
            except socket.timeout:
                continue
            except Exception:
                if self._stop.is_set():
                    break
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass
                sock = None
                self._socket = None
                time.sleep(0.2)
                continue
            try:
                text = packet.decode("utf-8", errors="replace")
                self.ingest_service.handle_ping(text)
            except Exception as exc:
                try:
                    self.ingest_service.record_packet_parse_error(
                        payload_text=text if "text" in locals() else repr(packet),
                        error_text=str(exc),
                    )
                except Exception:
                    pass
                continue

        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        self._socket = None
