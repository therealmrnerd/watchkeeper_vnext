import json
import shutil
import tempfile
import unittest
from pathlib import Path

import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from twitch_variable_index import load_twitch_variable_index


class TwitchVariableIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_twitch_var_index_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_file_returns_defaults(self) -> None:
        fields, commits = load_twitch_variable_index(self.temp_dir / "missing.json")
        self.assertIn("CHAT", fields)
        self.assertIn("REDEEM", fields)
        self.assertIn("BITS", fields)
        self.assertIn("FOLLOW", fields)
        self.assertIn("SUB", fields)
        self.assertIn("RAID", fields)
        self.assertIn("HYPE_TRAIN", fields)
        self.assertIn("POLL", fields)
        self.assertIn("PREDICTION", fields)
        self.assertIn("SHOUTOUT", fields)
        self.assertIn("POWER_UPS", fields)
        self.assertIn("user_id", fields["CHAT"])
        self.assertEqual(fields["CHAT"]["user_id"][0], "WK_Readchat.chat_user_id")
        self.assertEqual(fields["REDEEM"]["user_id"][0], "Twitch_Redeem.twitchredeem_user_id")
        self.assertEqual(fields["BITS"]["user_id"][0], "Twitch_Bits.new_bits_userid")
        self.assertEqual(fields["FOLLOW"]["user_id"][0], "Twitch_Follow.new_follow_userid")
        self.assertEqual(fields["SUB"]["user_id"][0], "Twitch_Sub.new_sub_userid")
        self.assertEqual(fields["RAID"]["user_id"][0], "Twitch_Raid.new_raid_userid")
        self.assertEqual(fields["SHOUTOUT"]["user_id"][0], "Twitch_Shoutout.new_shoutout_userid")
        self.assertEqual(fields["POWER_UPS"]["user_id"][0], "Twitch_PowerUps.new_powerups_userid")
        self.assertEqual(commits["CHAT"], [])

    def test_override_file_is_applied(self) -> None:
        index_path = self.temp_dir / "index.json"
        index_path.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "twitch": {
                        "CHAT": {
                            "fields": {
                                "message_text": ["WK_Readchat.chat_message_alt"],
                            },
                            "commit_keys": ["packet.ts.override"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        fields, commits = load_twitch_variable_index(index_path)
        self.assertEqual(fields["CHAT"]["message_text"], ["WK_Readchat.chat_message_alt"])
        self.assertEqual(commits["CHAT"], ["packet.ts.override"])


if __name__ == "__main__":
    unittest.main()
