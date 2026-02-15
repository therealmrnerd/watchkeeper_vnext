import json
import sqlite3
from pathlib import Path
from typing import Any


class BrainstemDB:
    def __init__(self, db_path: Path, schema_path: Path) -> None:
        self.db_path = db_path
        self.schema_path = schema_path

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10.0)
        con.row_factory = sqlite3.Row
        return con

    def ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL;")
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_log'"
            ).fetchone()
            if exists:
                return
            schema_sql = self.schema_path.read_text(encoding="utf-8")
            con.executescript(schema_sql)
            con.commit()

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
    def _state_equal(a: Any, b: Any) -> bool:
        try:
            return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
                b, sort_keys=True, ensure_ascii=False
            )
        except Exception:
            return a == b

    def append_event(
        self,
        *,
        event_id: str,
        timestamp_utc: str,
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
        with self.connect() as con:
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
                    timestamp_utc,
                    event_type,
                    source,
                    profile,
                    session_id,
                    correlation_id,
                    mode,
                    severity,
                    self._json_dump(payload),
                    self._json_dump(tags or []),
                ),
            )
            con.commit()
        return event_id

    def set_state(
        self,
        *,
        state_key: str,
        state_value: Any,
        source: str,
        observed_at_utc: str,
        confidence: float | None = None,
        emit_event: bool = True,
        event_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_meta = event_meta or {}
        with self.connect() as con:
            existing_row = con.execute(
                "SELECT state_value_json,source,confidence,observed_at_utc,updated_at_utc FROM state_current WHERE state_key=?",
                (state_key,),
            ).fetchone()

            previous_value = (
                self._json_load(existing_row["state_value_json"], None) if existing_row else None
            )
            changed = (existing_row is None) or (not self._state_equal(previous_value, state_value))
            updated_at_utc = event_meta.get("updated_at_utc") or observed_at_utc

            con.execute(
                """
                INSERT INTO state_current(
                    state_key,state_value_json,source,confidence,observed_at_utc,updated_at_utc
                )
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value_json=excluded.state_value_json,
                    source=excluded.source,
                    confidence=excluded.confidence,
                    observed_at_utc=excluded.observed_at_utc,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (
                    state_key,
                    self._json_dump(state_value),
                    source,
                    confidence,
                    observed_at_utc,
                    updated_at_utc,
                ),
            )

            event_id = None
            if emit_event and changed:
                event_id = event_meta.get("event_id")
                if not event_id:
                    raise ValueError("event_id is required when emit_event=True")
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
                        event_meta.get("timestamp_utc") or observed_at_utc,
                        event_meta.get("event_type", "STATE_UPDATED"),
                        event_meta.get("event_source", source),
                        event_meta.get("profile"),
                        event_meta.get("session_id"),
                        event_meta.get("correlation_id"),
                        event_meta.get("mode"),
                        event_meta.get("severity", "info"),
                        self._json_dump(
                            event_meta.get("payload")
                            or {
                                "state_key": state_key,
                                "source": source,
                                "confidence": confidence,
                                "observed_at_utc": observed_at_utc,
                            }
                        ),
                        self._json_dump(event_meta.get("tags") or []),
                    ),
                )

            con.commit()
            return {
                "state_key": state_key,
                "changed": changed,
                "event_id": event_id,
                "previous_value": previous_value,
                "state_value": state_value,
            }

    def batch_set_state(
        self,
        *,
        items: list[dict[str, Any]],
        emit_events: bool = True,
        event_defaults: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not items:
            return {"upserted": 0, "changed": 0, "items": []}

        event_defaults = event_defaults or {}
        results: list[dict[str, Any]] = []
        upserted = 0
        changed_count = 0

        with self.connect() as con:
            for item in items:
                state_key = item["state_key"]
                state_value = item["state_value"]
                source = item["source"]
                confidence = item.get("confidence")
                observed_at_utc = item["observed_at_utc"]
                updated_at_utc = item.get("updated_at_utc") or observed_at_utc

                existing_row = con.execute(
                    "SELECT state_value_json FROM state_current WHERE state_key=?",
                    (state_key,),
                ).fetchone()
                previous_value = (
                    self._json_load(existing_row["state_value_json"], None) if existing_row else None
                )
                changed = (existing_row is None) or (not self._state_equal(previous_value, state_value))

                con.execute(
                    """
                    INSERT INTO state_current(
                        state_key,state_value_json,source,confidence,observed_at_utc,updated_at_utc
                    )
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(state_key) DO UPDATE SET
                        state_value_json=excluded.state_value_json,
                        source=excluded.source,
                        confidence=excluded.confidence,
                        observed_at_utc=excluded.observed_at_utc,
                        updated_at_utc=excluded.updated_at_utc
                    """,
                    (
                        state_key,
                        self._json_dump(state_value),
                        source,
                        confidence,
                        observed_at_utc,
                        updated_at_utc,
                    ),
                )
                upserted += 1
                if changed:
                    changed_count += 1

                event_id = None
                if emit_events and changed:
                    event_id = item.get("event_id") or event_defaults.get("event_id")
                    if not event_id:
                        raise ValueError("event_id is required for changed state items when emit_events=True")
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
                            item.get("event_timestamp_utc")
                            or event_defaults.get("timestamp_utc")
                            or observed_at_utc,
                            item.get("event_type")
                            or event_defaults.get("event_type")
                            or "STATE_UPDATED",
                            item.get("event_source")
                            or event_defaults.get("event_source")
                            or source,
                            item.get("profile") or event_defaults.get("profile"),
                            item.get("session_id") or event_defaults.get("session_id"),
                            item.get("correlation_id") or event_defaults.get("correlation_id"),
                            item.get("mode") or event_defaults.get("mode"),
                            item.get("severity") or event_defaults.get("severity") or "info",
                            self._json_dump(
                                item.get("event_payload")
                                or {
                                    "state_key": state_key,
                                    "source": source,
                                    "confidence": confidence,
                                    "observed_at_utc": observed_at_utc,
                                }
                            ),
                            self._json_dump(item.get("tags") or event_defaults.get("tags") or []),
                        ),
                    )

                results.append(
                    {
                        "state_key": state_key,
                        "changed": changed,
                        "event_id": event_id,
                        "previous_value": previous_value,
                        "state_value": state_value,
                    }
                )

            con.commit()

        return {"upserted": upserted, "changed": changed_count, "items": results}

    def get_state(self, state_key: str) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT state_key,state_value_json,source,confidence,observed_at_utc,updated_at_utc
                FROM state_current
                WHERE state_key=?
                """,
                (state_key,),
            ).fetchone()
        if not row:
            return None
        return {
            "state_key": row["state_key"],
            "state_value": self._json_load(row["state_value_json"], row["state_value_json"]),
            "source": row["source"],
            "confidence": row["confidence"],
            "observed_at_utc": row["observed_at_utc"],
            "updated_at_utc": row["updated_at_utc"],
        }

    def list_state(self, state_key: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as con:
            if state_key:
                rows = con.execute(
                    """
                    SELECT state_key,state_value_json,source,confidence,observed_at_utc,updated_at_utc
                    FROM state_current
                    WHERE state_key=?
                    ORDER BY updated_at_utc DESC
                    """,
                    (state_key,),
                ).fetchall()
            else:
                rows = con.execute(
                    """
                    SELECT state_key,state_value_json,source,confidence,observed_at_utc,updated_at_utc
                    FROM state_current
                    ORDER BY updated_at_utc DESC
                    """
                ).fetchall()

        return [
            {
                "state_key": row["state_key"],
                "state_value": self._json_load(row["state_value_json"], row["state_value_json"]),
                "source": row["source"],
                "confidence": row["confidence"],
                "observed_at_utc": row["observed_at_utc"],
                "updated_at_utc": row["updated_at_utc"],
            }
            for row in rows
        ]

    def list_events(
        self,
        *,
        limit: int = 100,
        event_type: str | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        args: list[Any] = []
        if event_type:
            clauses.append("event_type=?")
            args.append(event_type)
        if session_id:
            clauses.append("session_id=?")
            args.append(session_id)
        if correlation_id:
            clauses.append("correlation_id=?")
            args.append(correlation_id)
        if since:
            clauses.append("timestamp_utc>=?")
            args.append(since)
        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)
        sql = (
            "SELECT event_id,timestamp_utc,event_type,source,profile,session_id,correlation_id,"
            "mode,severity,payload_json,tags_json "
            f"FROM event_log {where} ORDER BY timestamp_utc DESC LIMIT ?"
        )
        args.append(max(1, min(1000, int(limit))))

        with self.connect() as con:
            rows = con.execute(sql, args).fetchall()

        return [
            {
                "event_id": row["event_id"],
                "timestamp_utc": row["timestamp_utc"],
                "event_type": row["event_type"],
                "source": row["source"],
                "profile": row["profile"],
                "session_id": row["session_id"],
                "correlation_id": row["correlation_id"],
                "mode": row["mode"],
                "severity": row["severity"],
                "payload": self._json_load(row["payload_json"], {}),
                "tags": self._json_load(row["tags_json"], []),
            }
            for row in rows
        ]
