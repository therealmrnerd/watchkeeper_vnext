import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from provider_config import load_provider_config, validate_provider_config


class ProviderConfigTests(unittest.TestCase):
    def test_repo_provider_config_loads(self) -> None:
        payload = load_provider_config(ROOT_DIR / "config" / "providers.json")
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertIn("spansh", payload["providers"])
        self.assertEqual(payload["provider_priority"]["system_lookup"][0], "spansh")

    def test_validate_provider_config_rejects_missing_provider(self) -> None:
        payload = {
            "schema_version": "1.0",
            "provider_priority": {"system_lookup": ["spansh"]},
            "providers": {
                "spansh": {
                    "enabled": True,
                    "base_url": "https://www.spansh.co.uk",
                    "timeouts_ms": {"connect": 1500, "read": 4000},
                    "rate_limit": {
                        "mode": "client",
                        "rps": 1.0,
                        "burst": 2,
                        "max_concurrent": 1,
                        "cooldown_on_fail_s": 30
                    },
                    "cache": {"default_ttl_s": 86400, "stale_if_error_s": 604800},
                    "features": {"system_lookup": True, "read_only": True}
                }
            }
        }
        with self.assertRaises(ValueError):
            validate_provider_config(payload)

    def test_validate_provider_config_rejects_bad_rate_mode(self) -> None:
        payload = load_provider_config(ROOT_DIR / "config" / "providers.json")
        payload["providers"]["spansh"]["rate_limit"]["mode"] = "server"
        with self.assertRaises(ValueError):
            validate_provider_config(payload)

    def test_load_provider_config_from_file_validates(self) -> None:
        payload = load_provider_config(ROOT_DIR / "config" / "providers.json")
        payload["providers"]["edsy"]["mode"] = "runtime_api"
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "providers.json"
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_provider_config(config_path)


if __name__ == "__main__":
    unittest.main()
