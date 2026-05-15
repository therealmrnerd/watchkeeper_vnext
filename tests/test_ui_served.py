import importlib
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))


class UIServedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="ui_served_"))
        cls.db_path = cls.temp_dir / "watchkeeper_ui.db"

        os.environ["WKV_DB_PATH"] = str(cls.db_path)
        os.environ["WKV_SCHEMA_PATH"] = str(ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
        os.environ["WKV_STANDING_ORDERS_PATH"] = str(ROOT_DIR / "config" / "standing_orders.json")
        os.environ["WKV_PROVIDER_CONFIG_PATH"] = str(ROOT_DIR / "config" / "providers.json")
        os.environ["WKV_PROVIDER_SECRETS_PATH"] = str(cls.temp_dir / "provider_secrets.dpapi")
        os.environ["WKV_ENABLE_ACTUATORS"] = "0"
        os.environ["WKV_EDPARSER_ENABLED"] = "0"

        for name in ("runtime", "validators", "queries", "actions", "handlers"):
            sys.modules.pop(name, None)

        cls.runtime = importlib.import_module("runtime")
        cls.handlers = importlib.import_module("handlers")
        cls.runtime.ensure_db()

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), cls.handlers.BrainstemHandler)
        cls.port = int(cls.server.server_address[1])
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.server.shutdown()
            cls.server.server_close()
        except Exception:
            pass
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _request(self, path: str) -> tuple[int, str]:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                status = int(getattr(resp, "status", 200))
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            raw = exc.read().decode("utf-8", errors="replace")
        return status, raw

    def test_root_serves_html(self) -> None:
        status, body = self._request("/")
        self.assertEqual(status, 200)
        self.assertIn("<!doctype html>", body.lower())
        self.assertIn("Bridge Watch Panel", body)
        self.assertIn("watchkeeper_logo.png", body)
        self.assertIn("Console", body)
        self.assertIn("ED Status", body)
        self.assertIn("Config", body)
        self.assertIn("Clear Secure Store", body)
        self.assertIn("Runtime Settings", body)
        self.assertIn("OBS Status", body)
        self.assertIn("Open MFD Display", body)

    def test_ui_asset_served(self) -> None:
        status, body = self._request("/app.js")
        self.assertEqual(status, 200)
        self.assertIn("sendAssist", body)

        status, body = self._request("/styles.css")
        self.assertEqual(status, 200)
        self.assertIn(".topbar", body)

    def test_mfd_display_served(self) -> None:
        status, body = self._request("/mfd.html")
        self.assertEqual(status, 200)
        self.assertIn("Watchkeeper MFD", body)
        self.assertIn("mfd.js", body)
        self.assertIn("mfd.webmanifest", body)
        self.assertIn("mfdLightSyncToggle", body)
        self.assertIn("mfdSrvPane", body)
        self.assertIn("mfdSlfPane", body)
        self.assertIn("mfdPlanetPane", body)
        self.assertIn("mfdOnFootPlanetPane", body)
        self.assertIn("mfdOnFootStationPane", body)
        self.assertIn("Enter MFD Fullscreen", body)

        status, body = self._request("/mfd.js")
        self.assertEqual(status, 200)
        self.assertIn("/mfd/state", body)
        self.assertIn("/mfd/stream", body)
        self.assertIn("/settings", body)
        self.assertIn("jinx_lighting", body)
        self.assertIn("renderSrvPane", body)
        self.assertIn("renderSlfPane", body)
        self.assertIn("renderPlanetPane", body)
        self.assertIn("renderOnFootPlanetPane", body)
        self.assertIn("renderOnFootStationPane", body)
        self.assertIn("requestFullscreen", body)
        self.assertIn("serviceWorker", body)

        status, body = self._request("/mfd.css")
        self.assertEqual(status, 200)
        self.assertIn(".mfd-shell", body)

        status, body = self._request("/mfd.webmanifest")
        self.assertEqual(status, 200)
        self.assertIn('"display": "fullscreen"', body)
        self.assertIn('"orientation": "landscape"', body)

        status, body = self._request("/mfd-sw.js")
        self.assertEqual(status, 200)
        self.assertIn("watchkeeper-mfd", body)
        self.assertIn("/cockpit/", body)
        self.assertIn("/mfd/", body)
        self.assertIn("/settings", body)


if __name__ == "__main__":
    unittest.main()
