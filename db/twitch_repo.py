import json
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class TwitchRepository:
    def __init__(self, db_service: Any) -> None:
        self.db_service = db_service

    @staticmethod
    def _json_dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _json_load(raw: Any, fallback: Any) -> Any:
        if raw is None:
            return fallback
        try:
            return json.loads(raw)
        except Exception:
            return fallback

    @staticmethod
    def _normalize_ts(ts: str | None) -> str:
        text = str(ts or "").strip()
        return text if text else _utc_now_iso()

    @staticmethod
    def _parse_marker_value(marker: str) -> tuple[str, Any]:
        text = str(marker or "").strip()
        if not text:
            return ("empty", "")
        if text.lstrip("-").isdigit():
            try:
                return ("int", int(text))
            except Exception:
                pass
        normalized = text.replace("Z", "+00:00")
        try:
            return ("iso", datetime.fromisoformat(normalized).timestamp())
        except Exception:
            return ("str", text)

    @classmethod
    def _is_marker_newer(
        cls,
        *,
        new_marker: str,
        old_marker: str,
        new_seq: int,
        old_seq: int,
    ) -> bool:
        new_text = str(new_marker or "").strip()
        old_text = str(old_marker or "").strip()
        if not new_text:
            return False
        if not old_text:
            return True

        new_kind, new_value = cls._parse_marker_value(new_text)
        old_kind, old_value = cls._parse_marker_value(old_text)
        if new_kind == old_kind and new_kind in {"int", "iso"}:
            if new_value > old_value:
                return True
            if new_value < old_value:
                return False
            return int(new_seq) > int(old_seq)

        # Allow one-step migration between marker schemes (for example ISO -> seconds-since-2020).
        if new_kind != old_kind:
            return new_text != old_text

        if new_text > old_text:
            return True
        if new_text < old_text:
            return False
        return int(new_seq) > int(old_seq)

    def upsert_user(
        self,
        *,
        user_id: str,
        login_name: str | None = None,
        display_name: str | None = None,
        flags: dict[str, Any] | None = None,
        seen_ts_utc: str | None = None,
        increment_messages: int = 0,
    ) -> None:
        uid = str(user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required")
        seen_ts = self._normalize_ts(seen_ts_utc)
        flags_json = self._json_dump(flags or {})
        login = str(login_name or "").strip() or None
        display = str(display_name or "").strip() or None
        msg_delta = max(0, int(increment_messages or 0))

        with self.db_service.connect() as con:
            con.execute(
                """
                INSERT INTO twitch_user(
                    user_id, login_name, display_name, flags_json,
                    first_seen_utc, last_seen_utc, message_count, updated_at_utc
                )
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    login_name=COALESCE(excluded.login_name, twitch_user.login_name),
                    display_name=COALESCE(excluded.display_name, twitch_user.display_name),
                    flags_json=CASE
                      WHEN excluded.flags_json='{}' THEN twitch_user.flags_json
                      ELSE excluded.flags_json
                    END,
                    last_seen_utc=CASE
                      WHEN excluded.last_seen_utc > twitch_user.last_seen_utc THEN excluded.last_seen_utc
                      ELSE twitch_user.last_seen_utc
                    END,
                    message_count=twitch_user.message_count + excluded.message_count,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (uid, login, display, flags_json, seen_ts, seen_ts, msg_delta, seen_ts),
            )
            con.execute(
                """
                INSERT INTO twitch_user_stats(user_id, updated_at_utc)
                VALUES(?,?)
                ON CONFLICT(user_id) DO NOTHING
                """,
                (uid, seen_ts),
            )
            con.commit()

    def insert_recent_message_and_prune(
        self,
        *,
        user_id: str,
        message_ts_utc: str,
        msg_id: str | None,
        text: str,
        keep_last: int = 5,
    ) -> dict[str, Any]:
        uid = str(user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required")
        ts = self._normalize_ts(message_ts_utc)
        keep = max(1, int(keep_last))
        body = str(text or "").strip()
        if not body:
            body = "-"
        msg_key = str(msg_id or "").strip() or None
        inserted = True

        with self.db_service.connect() as con:
            if msg_key:
                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO twitch_user_recent_message(user_id, message_ts_utc, msg_id, message_text)
                    VALUES(?,?,?,?)
                    """,
                    (uid, ts, msg_key, body),
                )
                inserted = cur.rowcount > 0
            else:
                con.execute(
                    """
                    INSERT INTO twitch_user_recent_message(user_id, message_ts_utc, msg_id, message_text)
                    VALUES(?,?,NULL,?)
                    """,
                    (uid, ts, body),
                )
                inserted = True

            con.execute(
                """
                DELETE FROM twitch_user_recent_message
                WHERE user_id = ?
                  AND id IN (
                    SELECT id
                    FROM twitch_user_recent_message
                    WHERE user_id = ?
                    ORDER BY message_ts_utc DESC, id DESC
                    LIMIT -1 OFFSET ?
                  )
                """,
                (uid, uid, keep),
            )
            count_row = con.execute(
                "SELECT COUNT(*) AS n FROM twitch_user_recent_message WHERE user_id=?",
                (uid,),
            ).fetchone()
            con.commit()

        return {"inserted": inserted, "count_after_prune": int(count_row["n"]) if count_row else 0}

    def add_bits(self, *, user_id: str, amount: int, ts_utc: str) -> None:
        uid = str(user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required")
        delta = max(0, int(amount or 0))
        ts = self._normalize_ts(ts_utc)
        with self.db_service.connect() as con:
            con.execute(
                """
                INSERT INTO twitch_user_stats(user_id,bits_total,bits_count,last_bits_ts_utc,updated_at_utc)
                VALUES(?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    bits_total=twitch_user_stats.bits_total + excluded.bits_total,
                    bits_count=twitch_user_stats.bits_count + excluded.bits_count,
                    last_bits_ts_utc=excluded.last_bits_ts_utc,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (uid, delta, 1 if delta > 0 else 0, ts, ts),
            )
            con.commit()

    def add_redeem(self, *, user_id: str, reward_id: str, title: str, ts_utc: str) -> None:
        uid = str(user_id or "").strip()
        rid = str(reward_id or "").strip()
        if not uid or not rid:
            raise ValueError("user_id and reward_id are required")
        reward_title = str(title or "").strip()
        ts = self._normalize_ts(ts_utc)
        with self.db_service.connect() as con:
            con.execute(
                """
                INSERT INTO twitch_user_stats(user_id,redeem_total,last_redeem_ts_utc,updated_at_utc)
                VALUES(?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    redeem_total=twitch_user_stats.redeem_total + excluded.redeem_total,
                    last_redeem_ts_utc=excluded.last_redeem_ts_utc,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (uid, 1, ts, ts),
            )
            con.execute(
                """
                INSERT INTO twitch_user_redeem_summary(user_id,reward_id,reward_title,claim_count,last_claim_utc)
                VALUES(?,?,?,?,?)
                ON CONFLICT(user_id,reward_id) DO UPDATE SET
                    reward_title=CASE
                      WHEN excluded.reward_title='' THEN twitch_user_redeem_summary.reward_title
                      ELSE excluded.reward_title
                    END,
                    claim_count=twitch_user_redeem_summary.claim_count + 1,
                    last_claim_utc=excluded.last_claim_utc
                """,
                (uid, rid, reward_title, 1, ts),
            )
            con.commit()

    def add_hype(self, *, user_id: str, amount: int, ts_utc: str) -> None:
        uid = str(user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required")
        delta = max(0, int(amount or 0))
        ts = self._normalize_ts(ts_utc)
        with self.db_service.connect() as con:
            con.execute(
                """
                INSERT INTO twitch_user_stats(user_id,hype_total,last_hype_ts_utc,updated_at_utc)
                VALUES(?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    hype_total=twitch_user_stats.hype_total + excluded.hype_total,
                    last_hype_ts_utc=excluded.last_hype_ts_utc,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (uid, delta, ts, ts),
            )
            con.commit()

    def record_recent_event(
        self,
        *,
        event_type: str,
        commit_ts: str,
        user_id: str | None,
        payload: dict[str, Any],
        keep_last: int = 1000,
    ) -> None:
        event_key = str(event_type or "").strip().upper()
        if not event_key:
            raise ValueError("event_type is required")
        ts = self._normalize_ts(commit_ts)
        uid = str(user_id or "").strip() or None
        keep = max(50, int(keep_last or 1000))
        with self.db_service.connect() as con:
            con.execute(
                """
                INSERT INTO twitch_event_recent(event_type,commit_ts,user_id,payload_json)
                VALUES(?,?,?,?)
                """,
                (event_key, ts, uid, self._json_dump(payload or {})),
            )
            con.execute(
                """
                DELETE FROM twitch_event_recent
                WHERE id IN (
                  SELECT id
                  FROM twitch_event_recent
                  ORDER BY commit_ts DESC, id DESC
                  LIMIT -1 OFFSET ?
                )
                """,
                (keep,),
            )
            con.commit()

    def get_cursor(self, event_type: str) -> dict[str, Any]:
        event_key = str(event_type or "").strip().upper()
        if not event_key:
            raise ValueError("event_type is required")
        with self.db_service.connect() as con:
            row = con.execute(
                """
                SELECT event_type,last_commit_ts,last_seen_seq,updated_at_utc
                FROM twitch_event_cursor
                WHERE event_type=?
                """,
                (event_key,),
            ).fetchone()
        if not row:
            return {
                "event_type": event_key,
                "last_commit_ts": "",
                "last_seen_seq": 0,
                "updated_at_utc": None,
            }
        return {
            "event_type": row["event_type"],
            "last_commit_ts": row["last_commit_ts"] or "",
            "last_seen_seq": int(row["last_seen_seq"] or 0),
            "updated_at_utc": row["updated_at_utc"],
        }

    def set_cursor(self, event_type: str, commit_ts: str, seq: int = 0) -> dict[str, Any]:
        event_key = str(event_type or "").strip().upper()
        if not event_key:
            raise ValueError("event_type is required")
        ts = self._normalize_ts(commit_ts)
        seq_value = max(0, int(seq or 0))
        existing = self.get_cursor(event_key)
        existing_ts = str(existing.get("last_commit_ts") or "")
        existing_seq = int(existing.get("last_seen_seq") or 0)

        if not self._is_marker_newer(
            new_marker=ts,
            old_marker=existing_ts,
            new_seq=seq_value,
            old_seq=existing_seq,
        ):
            return {
                "event_type": event_key,
                "updated": False,
                "last_commit_ts": existing_ts,
                "last_seen_seq": existing_seq,
            }

        now_ts = _utc_now_iso()
        with self.db_service.connect() as con:
            con.execute(
                """
                INSERT INTO twitch_event_cursor(event_type,last_commit_ts,last_seen_seq,updated_at_utc)
                VALUES(?,?,?,?)
                ON CONFLICT(event_type) DO UPDATE SET
                    last_commit_ts=excluded.last_commit_ts,
                    last_seen_seq=excluded.last_seen_seq,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (event_key, ts, seq_value, now_ts),
            )
            con.commit()
        return {
            "event_type": event_key,
            "updated": True,
            "last_commit_ts": ts,
            "last_seen_seq": seq_value,
        }

    def get_top_redeems(self, user_id: str, limit: int = 5) -> list[dict[str, Any]]:
        uid = str(user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required")
        capped = max(1, min(50, int(limit or 5)))
        with self.db_service.connect() as con:
            rows = con.execute(
                """
                SELECT reward_id,reward_title,claim_count,last_claim_utc
                FROM twitch_user_redeem_summary
                WHERE user_id=?
                ORDER BY claim_count DESC, last_claim_utc DESC, reward_id ASC
                LIMIT ?
                """,
                (uid, capped),
            ).fetchall()
        return [
            {
                "reward_id": row["reward_id"],
                "reward_title": row["reward_title"],
                "claim_count": int(row["claim_count"] or 0),
                "last_claim_utc": row["last_claim_utc"],
            }
            for row in rows
        ]

    def get_user_message_count(self, user_id: str) -> int:
        uid = str(user_id or "").strip()
        if not uid:
            return 0
        with self.db_service.connect() as con:
            row = con.execute(
                "SELECT message_count FROM twitch_user WHERE user_id=?",
                (uid,),
            ).fetchone()
        if not row:
            return 0
        return int(row["message_count"] or 0)

    def get_user_context(self, user_id: str, redeem_limit: int = 5) -> dict[str, Any]:
        uid = str(user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required")
        with self.db_service.connect() as con:
            user_row = con.execute(
                """
                SELECT user_id,login_name,display_name,flags_json,first_seen_utc,last_seen_utc,message_count
                FROM twitch_user
                WHERE user_id=?
                """,
                (uid,),
            ).fetchone()
            msg_rows = con.execute(
                """
                SELECT message_ts_utc,msg_id,message_text
                FROM twitch_user_recent_message
                WHERE user_id=?
                ORDER BY message_ts_utc DESC, id DESC
                LIMIT 5
                """,
                (uid,),
            ).fetchall()
            stats_row = con.execute(
                """
                SELECT bits_total,bits_count,last_bits_ts_utc,redeem_total,last_redeem_ts_utc,hype_total,last_hype_ts_utc
                FROM twitch_user_stats
                WHERE user_id=?
                """,
                (uid,),
            ).fetchone()

        user_payload = None
        if user_row:
            user_payload = {
                "user_id": user_row["user_id"],
                "login_name": user_row["login_name"],
                "display_name": user_row["display_name"],
                "flags": self._json_load(user_row["flags_json"], {}),
                "first_seen_utc": user_row["first_seen_utc"],
                "last_seen_utc": user_row["last_seen_utc"],
                "message_count": int(user_row["message_count"] or 0),
            }
        stats_payload = {
            "bits_total": 0,
            "bits_count": 0,
            "last_bits_ts_utc": None,
            "redeem_total": 0,
            "last_redeem_ts_utc": None,
            "hype_total": 0,
            "last_hype_ts_utc": None,
        }
        if stats_row:
            stats_payload = {
                "bits_total": int(stats_row["bits_total"] or 0),
                "bits_count": int(stats_row["bits_count"] or 0),
                "last_bits_ts_utc": stats_row["last_bits_ts_utc"],
                "redeem_total": int(stats_row["redeem_total"] or 0),
                "last_redeem_ts_utc": stats_row["last_redeem_ts_utc"],
                "hype_total": int(stats_row["hype_total"] or 0),
                "last_hype_ts_utc": stats_row["last_hype_ts_utc"],
            }
        return {
            "user": user_payload,
            "last_messages": [
                {
                    "message_ts_utc": row["message_ts_utc"],
                    "msg_id": row["msg_id"],
                    "text": row["message_text"],
                }
                for row in msg_rows
            ],
            "stats": stats_payload,
            "top_redeems": self.get_top_redeems(uid, limit=redeem_limit),
        }

    def list_recent(self, *, limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]:
        capped = max(1, min(500, int(limit or 50)))
        args: list[Any] = []
        where = ""
        if event_type:
            where = "WHERE event_type=?"
            args.append(str(event_type).strip().upper())
        args.append(capped)
        with self.db_service.connect() as con:
            rows = con.execute(
                f"""
                SELECT id,event_type,commit_ts,user_id,payload_json,created_at_utc
                FROM twitch_event_recent
                {where}
                ORDER BY commit_ts DESC, id DESC
                LIMIT ?
                """,
                args,
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "event_type": row["event_type"],
                "commit_ts": row["commit_ts"],
                "user_id": row["user_id"],
                "payload": self._json_load(row["payload_json"], {}),
                "created_at_utc": row["created_at_utc"],
            }
            for row in rows
        ]

    def get_cooldown(self, *, user_id: str, action_key: str) -> str | None:
        uid = str(user_id or "").strip()
        key = str(action_key or "").strip()
        if not uid or not key:
            return None
        with self.db_service.connect() as con:
            row = con.execute(
                """
                SELECT last_trigger_ts_utc
                FROM twitch_cooldown
                WHERE user_id=? AND action_key=?
                """,
                (uid, key),
            ).fetchone()
        if not row:
            return None
        return str(row["last_trigger_ts_utc"] or "")

    def set_cooldown(self, *, user_id: str, action_key: str, ts_utc: str) -> None:
        uid = str(user_id or "").strip()
        key = str(action_key or "").strip()
        if not uid or not key:
            raise ValueError("user_id and action_key are required")
        ts = self._normalize_ts(ts_utc)
        with self.db_service.connect() as con:
            con.execute(
                """
                INSERT INTO twitch_cooldown(user_id,action_key,last_trigger_ts_utc,updated_at_utc)
                VALUES(?,?,?,?)
                ON CONFLICT(user_id,action_key) DO UPDATE SET
                    last_trigger_ts_utc=excluded.last_trigger_ts_utc,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (uid, key, ts, ts),
            )
            con.commit()
