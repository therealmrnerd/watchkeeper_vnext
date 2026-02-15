import importlib.util
import json
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
    fixture_dir = root / "data" / "edparser_fixture"
    ed_dir = fixture_dir / "Elite Dangerous"
    ed_dir.mkdir(parents=True, exist_ok=True)

    status_path = ed_dir / "Status.json"
    status_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-02-15T00:00:00Z",
                "event": "Status",
                "System": "Shinrarta Dezhra",
                "Flags": 17,
                "Health": 0.88,
            }
        ),
        encoding="utf-8",
    )

    journal = ed_dir / "Journal.2026-02-15T000000.01.log"
    journal.write_text(
        "\n".join(
            [
                json.dumps({"timestamp": "2026-02-15T00:00:01Z", "event": "Location", "StarSystem": "Sol"}),
                json.dumps({"timestamp": "2026-02-15T00:00:02Z", "event": "HullDamage", "Health": 0.77}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    telemetry_out = fixture_dir / "ed_telemetry.json"
    os.environ["WKV_ED_STATUS_PATH"] = str(status_path)
    os.environ["WKV_ED_JOURNAL_DIR"] = str(ed_dir)
    os.environ["WKV_ED_TELEMETRY_OUT"] = str(telemetry_out)
    os.environ["WKV_ED_PROCESS_NAMES"] = "DefinitelyNotRunning.exe"
    os.environ["WKV_EDPARSER_ASSUME_RUNNING"] = "1"
    os.environ["WKV_EDPARSER_LOG_LEVEL"] = "error"

    mod = load_module("edparser_vnext", root / "services" / "adapters" / "edparser_vnext.py")
    mod.run_once()

    data = json.loads(telemetry_out.read_text(encoding="utf-8"))
    print("HAS_VERSION", bool(data.get("parser_version")))
    print("ED_RUNNING", data.get("ed_running"))
    print("SYSTEM_NAME", data.get("system_name"))
    print("HULL_PERCENT", data.get("hull_percent"))
    print("LAST_EVENT", data.get("last_event"))


if __name__ == "__main__":
    main()
