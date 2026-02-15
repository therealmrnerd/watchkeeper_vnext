import os
import shlex
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return value != 0
    return False


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
        out = result.stdout or ""
        if "No tasks are running" in out:
            return False
        for raw in out.splitlines():
            line = raw.strip()
            if line.startswith('"'):
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) > 1 and parts[1].strip() == str(pid):
                    return True
        return False
    except Exception:
        return False


def _terminate_pid(pid: int, force: bool) -> bool:
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


class EDParserTool:
    def __init__(self, db_service: Any | None = None) -> None:
        self.db_service = db_service
        self.enabled = _as_bool(os.getenv("WKV_EDPARSER_ENABLED", "1"))
        self.command = os.getenv("WKV_EDPARSER_COMMAND", "").strip()
        self.python_bin = os.getenv("WKV_EDPARSER_PYTHON", sys.executable).strip() or sys.executable
        self.node_bin = os.getenv("WKV_EDPARSER_NODE", "node").strip() or "node"
        self.script_path = Path(
            os.getenv(
                "WKV_EDPARSER_SCRIPT",
                str(Path(__file__).resolve().parents[1] / "adapters" / "edparser_compat.mjs"),
            )
        )
        self.script_args = os.getenv("WKV_EDPARSER_ARGS", "").strip()
        self.stop_timeout_sec = float(os.getenv("WKV_EDPARSER_STOP_TIMEOUT_SEC", "4"))
        self.kill_external_pid = _as_bool(os.getenv("WKV_EDPARSER_KILL_EXTERNAL_PID", "1"))

        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._last_error: str | None = None
        self._last_exit_code: int | None = None
        self._last_started_utc: str | None = None
        self._last_stopped_utc: str | None = None

    def _build_command(self) -> list[str]:
        if self.command:
            return shlex.split(self.command, posix=False)
        if self.script_path.suffix.lower() == ".py":
            cmd = [self.python_bin, str(self.script_path)]
        else:
            cmd = [self.node_bin, str(self.script_path)]
        if self.script_args:
            cmd.extend(shlex.split(self.script_args, posix=False))
        return cmd

    def _pid_from_state(self) -> int | None:
        if self.db_service is None:
            return None
        try:
            row = self.db_service.get_state("ed.parser.pid")
            if not row:
                return None
            value = row.get("state_value")
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.strip().isdigit():
                return int(value.strip())
            if isinstance(value, float):
                return int(value)
        except Exception:
            return None
        return None

    def _refresh_local_process(self) -> None:
        if self._process is None:
            return
        code = self._process.poll()
        if code is None:
            return
        self._last_exit_code = int(code)
        self._last_stopped_utc = utc_now_iso()
        self._process = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_local_process()
            script_exists = self.script_path.exists()

            running = False
            pid: int | None = None
            managed_by = "none"

            if self._process is not None and self._process.poll() is None:
                running = True
                pid = int(self._process.pid)
                managed_by = "brainstem-local"
            else:
                state_pid = self._pid_from_state()
                if isinstance(state_pid, int) and _pid_running(state_pid):
                    running = True
                    pid = state_pid
                    managed_by = "external"

            return {
                "enabled": self.enabled,
                "running": running,
                "pid": pid,
                "managed_by": managed_by,
                "script_path": str(self.script_path),
                "script_exists": script_exists,
                "command": self.command or " ".join(self._build_command()),
                "node_bin": self.node_bin,
                "last_error": self._last_error,
                "last_exit_code": self._last_exit_code,
                "last_started_utc": self._last_started_utc,
                "last_stopped_utc": self._last_stopped_utc,
            }

    def start(self, reason: str = "manual", force_restart: bool = False) -> dict[str, Any]:
        with self._lock:
            self._refresh_local_process()
            if not self.enabled:
                self._last_error = "edparser disabled by WKV_EDPARSER_ENABLED=0"
                return self.status() | {"ok": False, "reason": reason}

            current = self.status()
            if current["running"] and not force_restart:
                return current | {"ok": True, "already_running": True, "reason": reason}
            if current["running"] and force_restart:
                self.stop(reason=f"{reason}:force_restart", force=True)

            if not self.command and not self.script_path.exists():
                self._last_error = f"edparser script not found: {self.script_path}"
                return self.status() | {"ok": False, "reason": reason}

            cmd = self._build_command()
            try:
                self._process = subprocess.Popen(
                    cmd,
                    cwd=str(self.script_path.parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
            except Exception as exc:
                self._process = None
                self._last_error = f"failed to start edparser: {exc}"
                return self.status() | {"ok": False, "reason": reason}

            self._last_error = None
            self._last_started_utc = utc_now_iso()
            return self.status() | {"ok": True, "reason": reason, "command": cmd}

    def stop(self, reason: str = "manual", force: bool = False) -> dict[str, Any]:
        with self._lock:
            self._refresh_local_process()
            stopped = False
            if self._process is not None and self._process.poll() is None:
                pid = int(self._process.pid)
                # Use taskkill process-tree first to avoid orphaning wrapper child processes.
                stopped = _terminate_pid(pid, force=force)
                if not stopped:
                    try:
                        self._process.terminate()
                        self._process.wait(timeout=self.stop_timeout_sec)
                        stopped = True
                    except Exception:
                        if force:
                            try:
                                self._process.kill()
                                self._process.wait(timeout=max(1.0, self.stop_timeout_sec))
                                stopped = True
                            except Exception:
                                stopped = False
                self._last_exit_code = self._process.poll()
                self._process = None

            if not stopped and self.kill_external_pid:
                state_pid = self._pid_from_state()
                if isinstance(state_pid, int) and _pid_running(state_pid):
                    stopped = _terminate_pid(state_pid, force=force)

            self._last_stopped_utc = utc_now_iso()
            if not stopped:
                current = self.status()
                if current["running"]:
                    self._last_error = "edparser stop requested but process is still running"
                    return current | {"ok": False, "reason": reason}

            self._last_error = None
            return self.status() | {"ok": True, "reason": reason}
