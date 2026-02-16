import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_QDRANT_URL = os.getenv("WKV_QDRANT_URL", "http://127.0.0.1:6333").strip()


def _resolve_default_qdrant_bin() -> Path:
    explicit = os.getenv("WKV_QDRANT_BIN", "").strip()
    if explicit:
        return Path(explicit)
    candidates = [
        ROOT_DIR / "tools" / "qdrant" / "qdrant.exe",
        Path("C:/ai/tools/qdrant/qdrant.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


DEFAULT_QDRANT_BIN = _resolve_default_qdrant_bin()
DEFAULT_QDRANT_WORKDIR = Path(
    os.getenv("WKV_QDRANT_WORKDIR", str(DEFAULT_QDRANT_BIN.parent))
)
DEFAULT_PID_FILE = Path(
    os.getenv("WKV_QDRANT_PID_FILE", str(ROOT_DIR / "data" / "qdrant_runtime.pid.json"))
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def env_bool(name: str, default: str = "0") -> bool:
    raw = os.getenv(name, default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return False
    out = result.stdout or ""
    if "No tasks are running" in out:
        return False
    for raw_line in out.splitlines():
        line = raw_line.strip()
        if line.startswith('"'):
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) > 1 and parts[1].strip() == str(pid):
                return True
    return False


def _terminate_pid(pid: int, force: bool = False) -> bool:
    if pid <= 0:
        return False
    cmd = ["taskkill", "/PID", str(pid), "/T"]
    if force:
        cmd.append("/F")
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception:
        return False
    return not _pid_running(pid)


class QdrantRuntimeManager:
    def __init__(
        self,
        *,
        qdrant_url: str = DEFAULT_QDRANT_URL,
        binary_path: Path = DEFAULT_QDRANT_BIN,
        workdir: Path = DEFAULT_QDRANT_WORKDIR,
        pid_file: Path = DEFAULT_PID_FILE,
    ) -> None:
        self.qdrant_url = qdrant_url.rstrip("/")
        self.binary_path = Path(binary_path)
        self.workdir = Path(workdir)
        self.pid_file = Path(pid_file)

        self._process: subprocess.Popen[str] | None = None
        self._started_by_this = False
        self._last_error: str | None = None
        self._last_started_utc: str | None = None
        self._last_stopped_utc: str | None = None

    def _is_local_url(self) -> bool:
        parsed = urlparse(self.qdrant_url)
        host = (parsed.hostname or "").strip().lower()
        return host in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}

    def _collections_url(self) -> str:
        return f"{self.qdrant_url}/collections"

    def ping(self, timeout_sec: float = 2.0) -> bool:
        req = request.Request(self._collections_url(), method="GET")
        try:
            with request.urlopen(req, timeout=timeout_sec) as resp:
                return 200 <= getattr(resp, "status", 200) < 300
        except Exception:
            return False

    def _read_pid_file(self) -> int | None:
        if not self.pid_file.exists():
            return None
        try:
            raw = json.loads(self.pid_file.read_text(encoding="utf-8"))
            pid = raw.get("pid")
            if isinstance(pid, int):
                return pid
            if isinstance(pid, str) and pid.isdigit():
                return int(pid)
        except Exception:
            return None
        return None

    def _write_pid_file(self, pid: int, command: list[str]) -> None:
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(
            json.dumps(
                {
                    "pid": pid,
                    "qdrant_url": self.qdrant_url,
                    "binary_path": str(self.binary_path),
                    "workdir": str(self.workdir),
                    "command": command,
                    "started_at_utc": utc_now_iso(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _delete_pid_file(self) -> None:
        try:
            self.pid_file.unlink(missing_ok=True)
        except Exception:
            pass

    def status(self) -> dict[str, Any]:
        pid_from_file = self._read_pid_file()
        pid_from_file_running = bool(pid_from_file and _pid_running(pid_from_file))

        local_pid = None
        local_running = False
        if self._process is not None:
            local_pid = int(self._process.pid)
            local_running = self._process.poll() is None

        return {
            "url": self.qdrant_url,
            "is_local_url": self._is_local_url(),
            "ping_ok": self.ping(timeout_sec=1.5),
            "binary_path": str(self.binary_path),
            "binary_exists": self.binary_path.exists(),
            "workdir": str(self.workdir),
            "pid_file": str(self.pid_file),
            "pid_file_pid": pid_from_file,
            "pid_file_pid_running": pid_from_file_running,
            "local_pid": local_pid,
            "local_pid_running": local_running,
            "started_by_this": self._started_by_this,
            "last_error": self._last_error,
            "last_started_utc": self._last_started_utc,
            "last_stopped_utc": self._last_stopped_utc,
        }

    def ensure_started(self, timeout_sec: float = 20.0) -> dict[str, Any]:
        if self.ping():
            self._last_error = None
            return self.status() | {"ok": True, "already_running": True, "started": False}

        if not self._is_local_url():
            self._last_error = "qdrant_url is not local; autostart disabled for remote endpoints"
            return self.status() | {"ok": False, "already_running": False, "started": False}

        if not self.binary_path.exists():
            self._last_error = f"qdrant binary not found: {self.binary_path}"
            return self.status() | {"ok": False, "already_running": False, "started": False}

        command = [str(self.binary_path)]
        try:
            self._process = subprocess.Popen(
                command,
                cwd=str(self.workdir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except Exception as exc:
            self._process = None
            self._last_error = f"failed to start qdrant: {exc}"
            return self.status() | {"ok": False, "already_running": False, "started": False}

        self._started_by_this = True
        self._last_started_utc = utc_now_iso()
        self._write_pid_file(int(self._process.pid), command)

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if self.ping():
                self._last_error = None
                return self.status() | {"ok": True, "already_running": False, "started": True}
            if self._process.poll() is not None:
                break
            time.sleep(0.25)

        self._last_error = "qdrant failed to become ready within timeout"
        self.stop(force=True)
        return self.status() | {"ok": False, "already_running": False, "started": False}

    def stop(self, force: bool = True, managed_only: bool = False) -> dict[str, Any]:
        if managed_only and not self._started_by_this:
            return self.status() | {"ok": True, "stopped": False, "managed_only": True}

        did_stop = False

        if self._process is not None and self._process.poll() is None:
            did_stop = _terminate_pid(int(self._process.pid), force=force)
            self._process = None

        if not did_stop:
            pid = self._read_pid_file()
            if isinstance(pid, int) and _pid_running(pid):
                did_stop = _terminate_pid(pid, force=force)

        if did_stop:
            self._last_error = None
            self._last_stopped_utc = utc_now_iso()
            self._started_by_this = False
            self._delete_pid_file()
            time.sleep(0.2)
            return self.status() | {"ok": True, "stopped": True}

        # Nothing to stop is considered success for idempotent stop.
        self._last_stopped_utc = utc_now_iso()
        self._started_by_this = False
        self._delete_pid_file()
        return self.status() | {"ok": True, "stopped": False}


def _main() -> None:
    parser = argparse.ArgumentParser(description="Qdrant runtime manager")
    parser.add_argument("command", choices=["start", "stop", "status"])
    parser.add_argument("--url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--binary", default=str(DEFAULT_QDRANT_BIN))
    parser.add_argument("--workdir", default=str(DEFAULT_QDRANT_WORKDIR))
    parser.add_argument("--pid-file", default=str(DEFAULT_PID_FILE))
    args = parser.parse_args()

    manager = QdrantRuntimeManager(
        qdrant_url=args.url,
        binary_path=Path(args.binary),
        workdir=Path(args.workdir),
        pid_file=Path(args.pid_file),
    )

    if args.command == "start":
        result = manager.ensure_started()
    elif args.command == "stop":
        result = manager.stop(force=True)
    else:
        result = manager.status() | {"ok": True}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "start" and not result.get("ok", False):
        raise SystemExit(1)


if __name__ == "__main__":
    _main()
