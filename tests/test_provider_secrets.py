import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from provider_secrets import (
    clear_provider_secret_entry,
    get_provider_secret_entry,
    load_provider_secret_store,
    save_inara_secret_entry,
    save_openai_secret_entry,
)


class _FakeCodec:
    def encrypt(self, plaintext: bytes) -> bytes:
        return b"enc:" + plaintext[::-1]

    def decrypt(self, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(b"enc:"):
            raise ValueError("bad ciphertext")
        return ciphertext[4:][::-1]


class ProviderSecretsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="provider_secrets_"))
        self.secret_path = self.temp_dir / "provider_secrets.dpapi"
        self.codec = _FakeCodec()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_inara_secret_entry_encrypts_at_rest(self) -> None:
        entry = save_inara_secret_entry(
            commander_name="Cmdr Nerd",
            frontier_id="6206398",
            app_key="secret-api-key",
            path=self.secret_path,
            codec=self.codec,
        )
        self.assertEqual(entry["commander_name"], "Cmdr Nerd")
        self.assertTrue(self.secret_path.exists())
        raw = self.secret_path.read_bytes()
        self.assertNotIn(b"secret-api-key", raw)

        store = load_provider_secret_store(self.secret_path, codec=self.codec)
        self.assertTrue(store["updated_at_utc"])
        self.assertEqual(store["providers"]["inara"]["frontier_id"], "6206398")
        loaded = get_provider_secret_entry("inara", self.secret_path, codec=self.codec)
        self.assertEqual(loaded["app_key"], "secret-api-key")
        self.assertTrue(loaded["_updated_at_utc"])

    def test_blank_api_key_preserves_existing_secret(self) -> None:
        save_inara_secret_entry(
            commander_name="Cmdr Nerd",
            frontier_id="6206398",
            app_key="secret-api-key",
            path=self.secret_path,
            codec=self.codec,
        )
        save_inara_secret_entry(
            commander_name="Cmdr Nerd",
            frontier_id="6206398",
            app_key="",
            path=self.secret_path,
            codec=self.codec,
        )
        loaded = get_provider_secret_entry("inara", self.secret_path, codec=self.codec)
        self.assertEqual(loaded["app_key"], "secret-api-key")

    def test_save_openai_secret_entry_encrypts_at_rest(self) -> None:
        entry = save_openai_secret_entry(
            api_key="openai-secret-key",
            path=self.secret_path,
            codec=self.codec,
        )
        self.assertEqual(entry["api_key"], "openai-secret-key")
        raw = self.secret_path.read_bytes()
        self.assertNotIn(b"openai-secret-key", raw)

        loaded = get_provider_secret_entry("openai", self.secret_path, codec=self.codec)
        self.assertEqual(loaded["api_key"], "openai-secret-key")
        self.assertTrue(loaded["_updated_at_utc"])

    def test_clear_provider_secret_entry_removes_provider_data(self) -> None:
        save_openai_secret_entry(
            api_key="openai-secret-key",
            path=self.secret_path,
            codec=self.codec,
        )
        removed = clear_provider_secret_entry("openai", self.secret_path, codec=self.codec)
        self.assertTrue(removed)
        loaded = get_provider_secret_entry("openai", self.secret_path, codec=self.codec)
        self.assertEqual(loaded, {})


if __name__ == "__main__":
    unittest.main()
