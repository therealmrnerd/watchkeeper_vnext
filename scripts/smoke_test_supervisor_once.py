import importlib.util
import os
from pathlib import Path


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    db_path = root / "data" / "supervisor_smoke.db"
    schema_path = root / "schemas" / "sqlite" / "001_brainstem_core.sql"

    fixture_dir = root / "data" / "supervisor_fixture"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    now_playing_dir = fixture_dir / "now-playing"
    now_playing_dir.mkdir(parents=True, exist_ok=True)
    (now_playing_dir / "ytm-title.txt").write_text("Smoke Track", encoding="utf-8")
    (now_playing_dir / "ytm-artist.txt").write_text("Smoke Artist", encoding="utf-8")
    (now_playing_dir / "ytm-album.txt").write_text("Smoke Album", encoding="utf-8")

    hardware_json = fixture_dir / "hardware_probe.json"
    hardware_json.write_text(
        '{"cpu_percent": 10, "gpu_temp_c": 60, "memory_used_percent": 0.95}',
        encoding="utf-8",
    )

    ed_telemetry_json = fixture_dir / "ed_telemetry.json"
    ed_telemetry_json.write_text(
        '{"system_name": "Shinrarta Dezhra", "hull_percent": 0.99}',
        encoding="utf-8",
    )

    os.environ["WKV_DB_PATH"] = str(db_path)
    os.environ["WKV_SCHEMA_PATH"] = str(schema_path)
    os.environ["WKV_NOW_PLAYING_DIR"] = str(now_playing_dir)
    os.environ["WKV_HARDWAREPROBE_JSON"] = str(hardware_json)
    os.environ["WKV_ED_TELEMETRY_JSON"] = str(ed_telemetry_json)
    os.environ["WKV_ED_PROCESS_NAMES"] = "DefinitelyNotRunning.exe"
    os.environ["WKV_HARDWARE_MEMORY_THRESHOLD"] = "0.90"

    supervisor = load_module("supervisor", root / "services" / "brainstem" / "supervisor.py")
    db_mod = load_module("db_service", root / "services" / "brainstem" / "db_service.py")

    supervisor.run_supervisor_once()

    db = db_mod.BrainstemDB(db_path, schema_path)
    states = db.list_state()
    events = db.list_events(limit=50)

    state_keys = {s["state_key"] for s in states}
    event_types = [e["event_type"] for e in events]

    print("STATE_COUNT", len(states))
    print("EVENT_COUNT", len(events))
    print("HAS_HARDWARE_MEMORY", "hardware.memory_used_percent" in state_keys)
    print("HAS_ED_RUNNING", "ed.running" in state_keys)
    print("HAS_MUSIC_TITLE", "music.track.title" in state_keys)
    print("HAS_THRESHOLD_EVENT", "HARDWARE_THRESHOLD" in event_types)


if __name__ == "__main__":
    main()
