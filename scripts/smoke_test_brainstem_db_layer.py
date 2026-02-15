import importlib.util
import os
import uuid
from pathlib import Path


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    db_path = root / "data" / "db_layer_smoke.db"
    schema_path = root / "schemas" / "sqlite" / "001_brainstem_core.sql"

    db_mod = load_module("db_service", root / "services" / "brainstem" / "db_service.py")
    db = db_mod.BrainstemDB(db_path, schema_path)
    db.ensure_schema()

    set_result = db.set_state(
        state_key="test.alpha",
        state_value={"value": 123},
        source="db_layer_smoke",
        observed_at_utc="2026-02-15T00:00:00.000000Z",
        confidence=1.0,
        emit_event=True,
        event_meta={
            "event_id": str(uuid.uuid4()),
            "timestamp_utc": "2026-02-15T00:00:00.000000Z",
            "event_type": "STATE_UPDATED",
            "event_source": "db_layer_smoke",
            "payload": {"state_key": "test.alpha"},
        },
    )

    batch_result = db.batch_set_state(
        items=[
            {
                "state_key": "test.beta",
                "state_value": "hello",
                "source": "db_layer_smoke",
                "confidence": 1.0,
                "observed_at_utc": "2026-02-15T00:00:01.000000Z",
                "event_id": str(uuid.uuid4()),
            },
            {
                "state_key": "test.gamma",
                "state_value": True,
                "source": "db_layer_smoke",
                "confidence": 1.0,
                "observed_at_utc": "2026-02-15T00:00:01.000000Z",
                "event_id": str(uuid.uuid4()),
            },
        ],
        emit_events=True,
        event_defaults={
            "event_type": "STATE_UPDATED",
            "event_source": "db_layer_smoke",
        },
    )

    db.append_event(
        event_id=str(uuid.uuid4()),
        timestamp_utc="2026-02-15T00:00:02.000000Z",
        event_type="CAPABILITY_CHANGED",
        source="db_layer_smoke",
        payload={"name": "demo", "status": "available"},
    )

    alpha = db.get_state("test.alpha")
    states = db.list_state()
    events = db.list_events(limit=10)

    print("SET_CHANGED", set_result["changed"])
    print("BATCH_UPSERTED", batch_result["upserted"])
    print("BATCH_CHANGED", batch_result["changed"])
    print("ALPHA_EXISTS", bool(alpha))
    print("STATE_COUNT", len(states))
    print("EVENT_COUNT", len(events))


if __name__ == "__main__":
    main()
