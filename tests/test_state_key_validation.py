import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from validators import validate_state_ingest


class StateKeyValidationTests(unittest.TestCase):
    def _payload(self, state_key: str) -> dict:
        return {
            "items": [
                {
                    "state_key": state_key,
                    "state_value": {"v": 1},
                    "source": "test",
                }
            ]
        }

    def test_valid_state_keys(self) -> None:
        for key in [
            "ed.running",
            "music.now_playing",
            "hw.cpu.logical_cores",
            "policy.watch_condition",
            "ai.router.health",
        ]:
            validate_state_ingest(self._payload(key))

    def test_invalid_state_keys(self) -> None:
        for key in [
            "system.cpu",
            "ed",
            "ED.running",
            "ed..running",
            "music-now_playing",
        ]:
            with self.assertRaises(ValueError, msg=f"expected invalid state key: {key}"):
                validate_state_ingest(self._payload(key))


if __name__ == "__main__":
    unittest.main()
