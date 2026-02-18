import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]


def _parse_json(raw: Any, fallback: Any) -> Any:
    if raw is None:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _read_policy_summary(policy_path: Path) -> dict[str, Any]:
    if not policy_path.exists():
        return {"ok": False, "error": f"missing policy file: {policy_path}"}
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"failed to parse policy: {exc}"}

    conditions = policy.get("watch_conditions", {})
    defaults = policy.get("defaults", {})
    return {
        "ok": True,
        "version": policy.get("version"),
        "watch_conditions": sorted(list(conditions.keys())),
        "tool_policy_count": len(policy.get("tool_policies", {})),
        "confirm_window_seconds": defaults.get("confirm_window_seconds"),
        "stt_min_confidence": defaults.get("stt_min_confidence"),
    }


def _safe_query(con: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def build_diag_report(db_path: Path, policy_path: Path, events_limit: int) -> dict[str, Any]:
    report: dict[str, Any] = {
        "ok": True,
        "db_path": str(db_path),
        "policy_path": str(policy_path),
        "policy_summary": _read_policy_summary(policy_path),
        "schema_versions": [],
        "config": {},
        "events": [],
    }

    if not db_path.exists():
        report["ok"] = False
        report["error"] = f"missing db file: {db_path}"
        return report

    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        migration_rows = _safe_query(
            con,
            """
            SELECT version, filename, applied_at_utc
            FROM schema_migrations
            ORDER BY version
            """,
        )
        report["schema_versions"] = [dict(row) for row in migration_rows]

        config_rows = _safe_query(
            con,
            "SELECT key, value_json, updated_at_utc FROM config ORDER BY key ASC",
        )
        cfg = {}
        for row in config_rows:
            cfg[row["key"]] = {
                "value": _parse_json(row["value_json"], row["value_json"]),
                "updated_at_utc": row["updated_at_utc"],
            }
        report["config"] = cfg

        events_rows = _safe_query(
            con,
            """
            SELECT event_id, timestamp_utc, event_type, source, severity, payload_json
            FROM event_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(int(events_limit), 500)),),
        )
        events = []
        for row in events_rows:
            events.append(
                {
                    "event_id": row["event_id"],
                    "timestamp_utc": row["timestamp_utc"],
                    "event_type": row["event_type"],
                    "source": row["source"],
                    "severity": row["severity"],
                    "payload": _parse_json(row["payload_json"], {}),
                }
            )
        report["events"] = events

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watchkeeper diagnostics report")
    parser.add_argument(
        "--db-path",
        default=str(ROOT_DIR / "data" / "watchkeeper_vnext.db"),
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--policy-path",
        default=str(ROOT_DIR / "config" / "standing_orders.json"),
        help="Path to standing orders policy JSON",
    )
    parser.add_argument("--events-limit", type=int, default=50, help="Number of latest events to include")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_diag_report(
        db_path=Path(args.db_path),
        policy_path=Path(args.policy_path),
        events_limit=args.events_limit,
    )
    if args.pretty:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
