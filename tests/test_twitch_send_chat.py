import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))


class _FakeSammiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call(self, request_name: str, params: dict | None = None):
        self.calls.append((str(request_name), dict(params or {})))
        return True, {"response": {"data": "Ok."}, "latency_ms": 1}


class TwitchSendChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_twitch_send_chat_"))
        cls.db_path = cls.temp_dir / "twitch_send_chat.db"

        os.environ["WKV_DB_PATH"] = str(cls.db_path)
        os.environ["WKV_SCHEMA_PATH"] = str(ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
        os.environ["WKV_STANDING_ORDERS_PATH"] = str(ROOT_DIR / "config" / "standing_orders.json")
        os.environ["WKV_TWITCH_CHAT_SEND_VAR"] = "Twitch_Chat.wk_chat"
        os.environ["WKV_TWITCH_CHAT_SEND_BUTTON"] = "Twitch_Chat"

        for name in ("runtime", "actions"):
            sys.modules.pop(name, None)

        cls.runtime = importlib.import_module("runtime")
        cls.actions = importlib.import_module("actions")
        cls.runtime.ensure_db()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self) -> None:
        self.fake = _FakeSammiClient()
        self._orig_sammi_client = self.actions.SAMMI_CLIENT
        self.actions.SAMMI_CLIENT = self.fake

    def tearDown(self) -> None:
        self.actions.SAMMI_CLIENT = self._orig_sammi_client

    def test_game_mode_requires_confirmation_without_user_confirm(self) -> None:
        result = self.actions.send_twitch_chat(
            {
                "message": "hello from test",
                "mode": "game",
                "watch_condition": "GAME",
                "incident_id": "inc-chat-needs-confirm-1",
            },
            source="test",
        )
        self.assertFalse(result.get("accepted"))
        self.assertFalse(result.get("sent"))
        self.assertTrue(bool(result.get("policy", {}).get("requires_confirmation")))
        self.assertEqual(len(self.fake.calls), 0)

    def test_game_mode_sends_when_confirmed(self) -> None:
        first = self.actions.send_twitch_chat(
            {
                "message": "hello from test",
                "mode": "game",
                "watch_condition": "GAME",
                "incident_id": "inc-chat-send-1",
            },
            source="test",
        )
        self.assertFalse(first.get("accepted"))
        self.assertFalse(first.get("sent"))
        token = str(first.get("confirm_token") or "")
        self.assertTrue(token)

        confirm = self.actions.record_confirmation(
            {
                "incident_id": "inc-chat-send-1",
                "confirm_token": token,
                "tool_name": "twitch.send_chat",
            },
            source="test",
        )
        self.assertEqual(confirm.get("incident_id"), "inc-chat-send-1")

        result = self.actions.send_twitch_chat(
            {
                "message": "hello from test",
                "mode": "game",
                "watch_condition": "GAME",
                "incident_id": "inc-chat-send-1",
                "confirm_token": token,
            },
            source="test",
        )
        self.assertTrue(result.get("accepted"))
        self.assertTrue(result.get("sent"))
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual(self.fake.calls[0][0], "setVariable")
        self.assertEqual(
            self.fake.calls[0][1],
            {"name": "Twitch_Chat.wk_chat", "value": "hello from test"},
        )
        self.assertEqual(self.fake.calls[1][0], "triggerButton")
        self.assertEqual(self.fake.calls[1][1], {"buttonID": "Twitch_Chat"})

    def test_strict_mode_rejects_inline_user_confirmed(self) -> None:
        with self.assertRaisesRegex(ValueError, "strict confirm mode enabled"):
            self.actions.send_twitch_chat(
                {
                    "message": "inline confirm should fail",
                    "mode": "game",
                    "watch_condition": "GAME",
                    "incident_id": "inc-chat-inline-confirm-1",
                    "user_confirmed": True,
                },
                source="test",
            )

    def test_standby_mode_denies(self) -> None:
        result = self.actions.send_twitch_chat(
            {
                "message": "hello from test",
                "mode": "standby",
                "watch_condition": "STANDBY",
                "incident_id": "inc-chat-standby-deny-1",
            },
            source="test",
        )
        self.assertFalse(result.get("accepted"))
        self.assertFalse(result.get("sent"))
        self.assertIn(result.get("policy", {}).get("deny_reason_code"), {"DENY_EXPLICITLY_DENIED"})
        self.assertEqual(len(self.fake.calls), 0)


if __name__ == "__main__":
    unittest.main()
