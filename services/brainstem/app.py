import ctypes
import os
from http.server import ThreadingHTTPServer

from handlers import BrainstemHandler
from runtime import (
    DB_SERVICE,
    HOST,
    PORT,
    TWITCH_INGEST_SERVICE,
    TWITCH_UDP_ENABLED,
    TWITCH_UDP_HOST,
    TWITCH_UDP_PORT,
    ensure_db,
)
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
    twitch_listener = TwitchDoorbellListener(
        ingest_service=TWITCH_INGEST_SERVICE,
        host=TWITCH_UDP_HOST,
        port=TWITCH_UDP_PORT,
        enabled=TWITCH_UDP_ENABLED,
        should_listen=_sammi_running_gate,
    )
    twitch_listener.start()

    server = ThreadingHTTPServer((HOST, PORT), BrainstemHandler)
    print(f"Brainstem API listening on http://{HOST}:{PORT}")
    if TWITCH_UDP_ENABLED:
        print(
            f"Twitch UDP listener gate active on udp://{TWITCH_UDP_HOST}:{TWITCH_UDP_PORT} "
            "(binds only when app.sammi.running=true)"
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        twitch_listener.stop()
        server.server_close()


if __name__ == "__main__":
    main()
