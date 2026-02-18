import argparse
import json
import random
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from db_service import BrainstemDB


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def bench_state_set(db: BrainstemDB, n_keys: int, change_rate: float) -> dict[str, Any]:
    if n_keys < 1:
        raise ValueError("n_keys must be >= 1")
    if change_rate < 0 or change_rate > 1:
        raise ValueError("change_rate must be 0..1")

    keys = [f"bench.state.key_{idx:05d}" for idx in range(n_keys)]
    values = {key: {"value": 0} for key in keys}
    changed = 0
    started = time.perf_counter()

    for key in keys:
        if random.random() < change_rate:
            values[key]["value"] += 1
            changed += 1
        db.set_state(
            state_key=key,
            state_value=values[key],
            source="bench_db",
            observed_at_utc=utc_now_iso(),
            confidence=1.0,
            emit_event=False,
        )

    elapsed = max(time.perf_counter() - started, 1e-9)
    return {
        "name": "bench_state_set",
        "n_keys": n_keys,
        "change_rate": change_rate,
        "changed_keys": changed,
        "elapsed_sec": elapsed,
        "ops": n_keys,
        "ops_per_sec": n_keys / elapsed,
    }


def bench_event_append(db: BrainstemDB, n_events: int) -> dict[str, Any]:
    if n_events < 1:
        raise ValueError("n_events must be >= 1")

    started = time.perf_counter()
    for idx in range(n_events):
        db.append_event(
            event_id=str(uuid.uuid4()),
            timestamp_utc=utc_now_iso(),
            event_type="BENCH_EVENT",
            source="bench_db",
            payload={"seq": idx},
            severity="info",
            tags=["bench"],
        )

    elapsed = max(time.perf_counter() - started, 1e-9)
    return {
        "name": "bench_event_append",
        "n_events": n_events,
        "elapsed_sec": elapsed,
        "ops": n_events,
        "ops_per_sec": n_events / elapsed,
    }


def bench_mixed(db: BrainstemDB, read_ratio: float, ops_per_sec: int, duration: float) -> dict[str, Any]:
    if read_ratio < 0 or read_ratio > 1:
        raise ValueError("read_ratio must be 0..1")
    if ops_per_sec < 1:
        raise ValueError("ops_per_sec must be >= 1")
    if duration <= 0:
        raise ValueError("duration must be > 0")

    seed_keys = [f"bench.mixed.key_{idx:04d}" for idx in range(256)]
    for key in seed_keys:
        db.set_state(
            state_key=key,
            state_value={"value": 0},
            source="bench_db",
            observed_at_utc=utc_now_iso(),
            confidence=1.0,
            emit_event=False,
        )

    reads = 0
    writes = 0
    op_count = 0
    period = 1.0 / float(ops_per_sec)
    start = time.perf_counter()
    deadline = start + duration

    while True:
        now = time.perf_counter()
        if now >= deadline:
            break

        key = random.choice(seed_keys)
        if random.random() < read_ratio:
            db.get_state(key)
            reads += 1
        else:
            writes += 1
            db.set_state(
                state_key=key,
                state_value={"value": op_count},
                source="bench_db",
                observed_at_utc=utc_now_iso(),
                confidence=1.0,
                emit_event=False,
            )
        op_count += 1

        target = start + (op_count * period)
        sleep_for = target - time.perf_counter()
        if sleep_for > 0:
            time.sleep(sleep_for)

    elapsed = max(time.perf_counter() - start, 1e-9)
    return {
        "name": "bench_mixed",
        "read_ratio": read_ratio,
        "target_ops_per_sec": ops_per_sec,
        "duration_sec": duration,
        "reads": reads,
        "writes": writes,
        "ops": op_count,
        "elapsed_sec": elapsed,
        "actual_ops_per_sec": op_count / elapsed,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db_path)
    schema_path = ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql"
    db = BrainstemDB(db_path=db_path, schema_path=schema_path)
    db.ensure_schema()

    return {
        "ok": True,
        "db_path": str(db_path),
        "results": {
            "state_set": bench_state_set(db, args.n_keys, args.change_rate),
            "event_append": bench_event_append(db, args.n_events),
            "mixed": bench_mixed(db, args.read_ratio, args.ops_per_sec, args.duration),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watchkeeper DB benchmark harness")
    parser.add_argument("--db-path", default="", help="SQLite DB path (temp file when omitted)")
    parser.add_argument("--n-keys", type=int, default=1000, help="bench_state_set key count")
    parser.add_argument("--change-rate", type=float, default=0.25, help="bench_state_set change rate")
    parser.add_argument("--n-events", type=int, default=1000, help="bench_event_append event count")
    parser.add_argument("--read-ratio", type=float, default=0.7, help="bench_mixed read ratio")
    parser.add_argument("--ops-per-sec", type=int, default=500, help="bench_mixed target ops/sec")
    parser.add_argument("--duration", type=float, default=5.0, help="bench_mixed duration seconds")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()
    if not args.db_path:
        tmp = Path(tempfile.gettempdir()) / f"watchkeeper_bench_{uuid.uuid4().hex}.db"
        args.db_path = str(tmp)
    return args


def main() -> None:
    args = parse_args()
    result = run(args)
    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
