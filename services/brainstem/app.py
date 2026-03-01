import ctypes
import os
from http.server import ThreadingHTTPServer

from handlers import BrainstemHandler
from runtime import (
    DB_SERVICE,
    ED_PROVIDER_HEALTH_SCHEDULER,
    HOST,
    PORT,
    TWITCH_INGEST_SERVICE,
    TWITCH_UDP_ENABLED,
    TWITCH_UDP_HOST,
    TWITCH_UDP_PORT,
    ensure_db,
)
from settings_store import load_runtime_settings, runtime_setting_enabled
from twitch_ingest import TwitchDoorbellListener


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _sammi_running_gate() -> bool:
    row = DB_SERVICE.get_state("app.sammi.running")
    if not row:
        return False
    return _as_bool(row.get("state_value"))


def _runtime_sync_enabled(sync_id: str, default: bool = True) -> bool:
    try:
        settings = load_runtime_settings(DB_SERVICE.db_path)
    except Exception:
        return bool(default)
    return runtime_setting_enabled(settings, "syncs", sync_id, default)


def _twitch_udp_gate() -> bool:
    if not _sammi_running_gate():
        return False
    if not _runtime_sync_enabled("sammi_bridge", True):
        return False
    if not _runtime_sync_enabled("twitch_ingest", True):
        return False
    return True


def _hide_console_window() -> None:
    if os.name != "nt":
        return
    if os.getenv("WKV_HIDE_CONSOLE", "1").strip().lower() not in {"1", "true", "yes"}:
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        return


def main() -> None:
    _hide_console_window()
    ensure_db()
    ED_PROVIDER_HEALTH_SCHEDULER.start()
    twitch_listener = TwitchDoorbellListener(
        ingest_service=TWITCH_INGEST_SERVICE,
        host=TWITCH_UDP_HOST,
        port=TWITCH_UDP_PORT,
        enabled=TWITCH_UDP_ENABLED,
        should_listen=_twitch_udp_gate,
    )
    twitch_listener.start()

    server = ThreadingHTTPServer((HOST, PORT), BrainstemHandler)
    print(f"Brainstem API listening on http://{HOST}:{PORT}")
    if TWITCH_UDP_ENABLED:
        print(
            f"Twitch UDP listener gate active on udp://{TWITCH_UDP_HOST}:{TWITCH_UDP_PORT} "
            "(binds only when app.sammi.running=true and SAMMI/Twitch syncs are enabled)"
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ED_PROVIDER_HEALTH_SCHEDULER.stop()
        twitch_listener.stop()
        server.server_close()


if __name__ == "__main__":
    main()
