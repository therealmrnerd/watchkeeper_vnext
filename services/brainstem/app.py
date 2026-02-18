from http.server import ThreadingHTTPServer

from handlers import BrainstemHandler
from runtime import HOST, PORT, ensure_db


def main() -> None:
    ensure_db()
    server = ThreadingHTTPServer((HOST, PORT), BrainstemHandler)
    print(f"Brainstem API listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
