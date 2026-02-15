import importlib.util
import os
from pathlib import Path


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    temp_db = root / "data" / "integration_smoke.db"
    os.environ["WKV_DB_PATH"] = str(temp_db)
    os.environ["WKV_AI_DB_PATH"] = str(temp_db)

    brain = load("brain_app", root / "services" / "brainstem" / "app.py")
    assist = load("assist_router", root / "services" / "ai" / "assist_router.py")
    collector = load("state_collector", root / "services" / "adapters" / "state_collector.py")

    brain.ensure_db()

    previous = {}
    state_payload = {
        "items": (
            collector._build_changed_items(collector.collect_ed_state(), previous, "ed_probe")
            + collector._build_changed_items(
                collector.collect_music_state(), previous, "music_probe"
            )
            + collector._build_changed_items(
                collector.collect_system_state(), previous, "system_probe"
            )
        ),
        "emit_events": True,
        "profile": "watchkeeper",
        "session_id": "sess-integ-1",
        "correlation_id": "corr-integ-1",
    }
    brain.validate_state_ingest(state_payload)
    state_result = brain.ingest_state(state_payload, source="integration_test")

    assist_req = {
        "user_text": "set combat lights and skip track",
        "mode": "game",
        "use_knowledge": False,
        "auto_execute": True,
        "dry_run": True,
    }
    assist.validate_assist_request(assist_req)
    intent, _ = assist.build_intent(assist_req)
    brain.validate_intent(intent)
    with brain.connect_db() as con:
        action_count = brain.upsert_intent(con, intent, source="integration_test")
        con.commit()

    execute_result = brain.execute_actions(
        {
            "request_id": intent["request_id"],
            "incident_id": "inc-smoke-001",
            "watch_condition": "GAME",
            "stt_confidence": 0.95,
            "dry_run": True,
            "allow_high_risk": False,
        },
        source="integration_test",
    )

    state_items = brain.query_state({})
    event_items = brain.query_events({"limit": ["20"]})

    print("STATE_UPSERTED", state_result["upserted"])
    print("INTENT_ACTIONS", action_count)
    print("EXEC_RESULTS", len(execute_result["results"]))
    print("STATE_ROWS", len(state_items))
    print("EVENT_ROWS", len(event_items))
    print("LATEST_EVENT", event_items[0]["event_type"] if event_items else "NONE")


if __name__ == "__main__":
    main()
