import json
import sqlite3
from pathlib import Path


def _list_migration_files(schema_dir: Path) -> list[Path]:
    files = []
    for path in schema_dir.glob("*.sql"):
        if path.is_file() and path.name[:3].isdigit() and "_" in path.name:
            files.append(path)
    files.sort(key=lambda p: p.name)
    return files


def _ensure_migration_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            applied_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )
        """
    )


def _applied_versions(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT version FROM schema_migrations").fetchall()
    return {str(r[0]) for r in rows}


def _upsert_schema_version(con: sqlite3.Connection, version: str) -> None:
    con.execute(
        """
        INSERT INTO config(key, value_json, updated_at_utc)
        VALUES('schema_version', ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        ON CONFLICT(key) DO UPDATE SET
          value_json=excluded.value_json,
          updated_at_utc=excluded.updated_at_utc
        """,
        (json.dumps(version, ensure_ascii=False),),
    )


def apply_migrations(con: sqlite3.Connection, schema_dir: Path) -> dict[str, object]:
    schema_dir = Path(schema_dir)
    if not schema_dir.exists():
        raise RuntimeError(f"Schema directory not found: {schema_dir}")

    _ensure_migration_table(con)
    applied = _applied_versions(con)
    migrations = _list_migration_files(schema_dir)
    if not migrations:
        raise RuntimeError(f"No migration files found in {schema_dir}")

    applied_now: list[str] = []
    current_version = ""
    for migration in migrations:
        version = migration.stem.split("_", 1)[0]
        current_version = version
        if version in applied:
            continue

        sql = migration.read_text(encoding="utf-8")
        if sql.strip():
            con.executescript(sql)
        con.execute(
            "INSERT INTO schema_migrations(version, filename) VALUES(?, ?)",
            (version, migration.name),
        )
        applied_now.append(version)

    if current_version:
        _upsert_schema_version(con, current_version)

    return {
        "applied": applied_now,
        "current_version": current_version,
        "migration_count": len(migrations),
    }
