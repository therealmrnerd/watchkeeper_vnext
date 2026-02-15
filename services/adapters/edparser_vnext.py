import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


POLL_ACTIVE_SEC = float(os.getenv("WKV_EDPARSER_ACTIVE_SEC", "0.6"))
POLL_IDLE_SEC = float(os.getenv("WKV_EDPARSER_IDLE_SEC", "2.5"))
STATUS_PATH = Path(
    os.getenv(
        "WKV_ED_STATUS_PATH",
        str(
            Path(os.getenv("USERPROFILE", "C:/Users/YourUser"))
            / "Saved Games"
            / "Frontier Developments"
            / "Elite Dangerous"
            / "Status.json"
        ),
    )
)
JOURNAL_DIR = Path(
    os.getenv(
        "WKV_ED_JOURNAL_DIR",
        str(
            Path(os.getenv("USERPROFILE", "C:/Users/YourUser"))
            / "Saved Games"
            / "Frontier Developments"
            / "Elite Dangerous"
        ),
    )
)
TELEMETRY_OUT = Path(
    os.getenv("WKV_ED_TELEMETRY_OUT", str(Path(__file__).resolve().parents[2] / "data" / "ed_telemetry.json"))
)
PROCESS_NAMES = [
    p.strip().lower()
    for p in os.getenv("WKV_ED_PROCESS_NAMES", "EliteDangerous64.exe,EliteDangerous.exe").split(",")
    if p.strip()
]
ASSUME_RUNNING = os.getenv("WKV_EDPARSER_ASSUME_RUNNING", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
LOG_LEVEL = os.getenv("WKV_EDPARSER_LOG_LEVEL", "info").strip().lower()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def log(level: str, msg: str) -> None:
    order = {"debug": 10, "info": 20, "warn": 30, "error": 40}
    if order.get(level, 20) < order.get(LOG_LEVEL, 20):
        return
    print(f"[{utc_now_iso()}] [{level.upper()}] {msg}")


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        tmp.replace(path)
    except PermissionError:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _list_process_names() -> set[str]:
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        names: set[str] = set()
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if line.startswith('"'):
                parts = [p.strip('"') for p in line.split('","')]
                if parts and parts[0]:
                    names.add(parts[0].lower())
        return names
    except Exception:
        return set()


def _ed_running() -> tuple[bool, str | None]:
    if ASSUME_RUNNING:
        return True, "assumed"
    running = _list_process_names()
    for name in PROCESS_NAMES:
        if name in running:
            return True, name
    return False, None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}


def _find_latest_journal(journal_dir: Path) -> Path | None:
    if not journal_dir.exists():
        return None
    latest: Path | None = None
    latest_mtime = 0.0
    for p in journal_dir.glob("Journal.*.log"):
        try:
            mtime = p.stat().st_mtime
        except Exception:
            continue
        if mtime > latest_mtime:
            latest = p
            latest_mtime = mtime
    return latest


class ParserState:
    def __init__(self) -> None:
        self.running = True
        self.last_status_mtime: float = 0.0
        self.last_journal_path: Path | None = None
        self.last_journal_pos: int = 0
        self.telemetry: dict[str, Any] = {
            "parser_version": "vnext-1",
            "timestamp_utc": utc_now_iso(),
            "ed_running": False,
            "process_name": None,
            "system_name": None,
            "hull_percent": None,
            "dock_state": None,
            "supercruise": None,
            "landed": None,
            "status_source_mtime": None,
            "journal_source": None,
            "last_event": None,
        }
        self.last_written_json = ""

    def stop(self, *_args: Any) -> None:
        self.running = False

    def _set_hull(self, raw: Any) -> None:
        if isinstance(raw, (int, float)):
            if raw > 1.0:
                self.telemetry["hull_percent"] = max(0.0, min(1.0, float(raw) / 100.0))
            else:
                self.telemetry["hull_percent"] = max(0.0, min(1.0, float(raw)))

    def apply_status(self, status: dict[str, Any], mtime: float) -> None:
        if not status:
            return
        self.telemetry["status_source_mtime"] = mtime
        if isinstance(status.get("System"), str) and status["System"].strip():
            self.telemetry["system_name"] = status["System"].strip()
        if "Health" in status:
            self._set_hull(status.get("Health"))
        flags = status.get("Flags")
        if isinstance(flags, int):
            self.telemetry["dock_state"] = bool(flags & (1 << 0))
            self.telemetry["landed"] = bool(flags & (1 << 1))
            self.telemetry["supercruise"] = bool(flags & (1 << 4))
        self.telemetry["last_event"] = "status_update"

    def apply_journal_event(self, ev: dict[str, Any]) -> None:
        event_name = str(ev.get("event") or "").strip()
        if not event_name:
            return
        if event_name in {"Location", "FSDJump"}:
            star = ev.get("StarSystem") or ev.get("System")
            if isinstance(star, str) and star.strip():
                self.telemetry["system_name"] = star.strip()
        if "HullHealth" in ev:
            self._set_hull(ev.get("HullHealth"))
        if "Health" in ev:
            self._set_hull(ev.get("Health"))
        self.telemetry["last_event"] = event_name

    def read_status_if_changed(self) -> None:
        try:
            mtime = STATUS_PATH.stat().st_mtime
        except Exception:
            return
        if mtime <= self.last_status_mtime:
            return
        self.last_status_mtime = mtime
        status = _read_json(STATUS_PATH)
        self.apply_status(status, mtime=mtime)

    def read_journal_tail(self) -> None:
        latest = _find_latest_journal(JOURNAL_DIR)
        if latest is None:
            return
        if self.last_journal_path is None or latest != self.last_journal_path:
            self.last_journal_path = latest
            self.last_journal_pos = 0
            self.telemetry["journal_source"] = str(latest)

        try:
            size = latest.stat().st_size
            if size < self.last_journal_pos:
                self.last_journal_pos = 0
            if size == self.last_journal_pos:
                return
            with latest.open("r", encoding="utf-8", errors="ignore") as f:
                f.seek(self.last_journal_pos)
                chunk = f.read()
                self.last_journal_pos = f.tell()
        except Exception:
            return

        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if isinstance(ev, dict):
                self.apply_journal_event(ev)

    def update_running(self, is_running: bool, process_name: str | None) -> None:
        self.telemetry["ed_running"] = is_running
        self.telemetry["process_name"] = process_name

    def maybe_write_telemetry(self) -> None:
        self.telemetry["timestamp_utc"] = utc_now_iso()
        raw = json.dumps(self.telemetry, sort_keys=True, ensure_ascii=False)
        if raw == self.last_written_json:
            return
        _atomic_write_json(TELEMETRY_OUT, self.telemetry)
        self.last_written_json = raw


def run_loop() -> None:
    state = ParserState()
    signal.signal(signal.SIGINT, state.stop)
    signal.signal(signal.SIGTERM, state.stop)

    log("info", f"ED parser vNext starting. telemetry_out={TELEMETRY_OUT}")
    while state.running:
        is_running, process_name = _ed_running()
        state.update_running(is_running, process_name)
        if is_running:
            state.read_status_if_changed()
            state.read_journal_tail()
            state.maybe_write_telemetry()
            time.sleep(max(0.1, POLL_ACTIVE_SEC))
        else:
            state.maybe_write_telemetry()
            time.sleep(max(0.3, POLL_IDLE_SEC))
    log("info", "ED parser vNext stopped.")


def run_once() -> None:
    state = ParserState()
    is_running, process_name = _ed_running()
    state.update_running(is_running, process_name)
    if is_running:
        state.read_status_if_changed()
        state.read_journal_tail()
    state.maybe_write_telemetry()


def main() -> None:
    if "--once" in os.sys.argv:
        run_once()
        return
    run_loop()


if __name__ == "__main__":
    main()
