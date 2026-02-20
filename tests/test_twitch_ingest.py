import shutil
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db_service import BrainstemDB
from db.twitch_repo import TwitchRepository
from twitch_ingest import TwitchDoorbellListener, TwitchEventType, TwitchIngestService, TwitchSnapshot


class FakeSammiClient:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def get_var(self, name: str) -> Any:
        return self.values.get(name)

    def get_vars(self, names: list[str]) -> dict[str, Any]:
        return {name: self.values.get(name) for name in names}


class NoCallSammiClient:
    def get_var(self, name: str) -> Any:
        raise AssertionError("get_var should not be called in ack-only mode")

    def get_vars(self, names: list[str]) -> dict[str, Any]:
        raise AssertionError("get_vars should not be called in ack-only mode")


class _PingRecorder:
    def __init__(self) -> None:
        self.count = 0
        self.payloads: list[str] = []

    def handle_ping(self, payload_text: str) -> None:
        self.count += 1
        self.payloads.append(str(payload_text))

    def record_packet_parse_error(self, payload_text: str, error_text: str) -> None:
        return


class TwitchIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_twitch_ingest_"))
        self.db_path = self.temp_dir / "ingest.db"
        schema_path = ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql"
        self.db = BrainstemDB(self.db_path, schema_path)
        self.db.ensure_schema()
        self.repo = TwitchRepository(self.db)
        self.sammi = FakeSammiClient()
        self.ingest = TwitchIngestService(
            db_service=self.db,
            repo=self.repo,
            sammi_client=self.sammi,  # type: ignore[arg-type]
            chat_debounce_ms=0,
            source="test_ingest",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_handlers_can_persist_chat_redeem_bits_independently(self) -> None:
        base_ts = "2026-02-20T12:00:00.000000Z"
        chat = TwitchSnapshot(
            event_type=TwitchEventType.CHAT,
            commit_ts=base_ts,
            payload={
                "user_id": "u1",
                "login_name": "pilot",
                "display_name": "Pilot",
                "message_id": "chat-1",
                "message_text": "o7 CMDR",
                "is_mod": False,
                "is_vip": True,
                "is_sub": False,
            },
        )
        redeem = TwitchSnapshot(
            event_type=TwitchEventType.REDEEM,
            commit_ts="2026-02-20T12:01:00.000000Z",
            payload={
                "user_id": "u1",
                "reward_id": "redeem-1",
                "reward_title": "Hydrate",
            },
        )
        bits = TwitchSnapshot(
            event_type=TwitchEventType.BITS,
            commit_ts="2026-02-20T12:02:00.000000Z",
            payload={
                "user_id": "u1",
                "amount": 150,
            },
        )

        self.assertTrue(self.ingest.persist(chat)["processed"])
        self.assertTrue(self.ingest.persist(redeem)["processed"])
        self.assertTrue(self.ingest.persist(bits)["processed"])

        ctx = self.repo.get_user_context("u1")
        self.assertEqual(len(ctx["last_messages"]), 1)
        self.assertEqual(int(ctx["stats"]["redeem_total"]), 1)
        self.assertEqual(int(ctx["stats"]["bits_total"]), 150)

    def test_doorbell_dedupe_ignores_duplicate_commit(self) -> None:
        self.sammi.values = {
            "WK_Readchat.chat_user_id": "u2",
            "WK_Readchat.chat_messageuser": "dedupe",
            "WK_Readchat.chat_user_name": "Dedupe",
            "WK_Readchat.chat_message": "first",
            "WK_Readchat.chat_is_vip": False,
            "WK_Readchat.chat_is_subscriber": False,
            "WK_Readchat.chat_is_broadcaster": False,
        }
        first = self.ingest.handle_ping("CHAT|2026-02-20T13:00:00.000000Z")
        self.assertTrue(first.get("processed"))

        second = self.ingest.handle_ping("CHAT|2026-02-20T13:00:00.000000Z")
        self.assertFalse(second.get("processed"))

    def test_chat_debounce_coalesces_burst(self) -> None:
        ingest = TwitchIngestService(
            db_service=self.db,
            repo=self.repo,
            sammi_client=self.sammi,  # type: ignore[arg-type]
            chat_debounce_ms=80,
            source="test_ingest",
        )
        self.sammi.values = {
            "WK_Readchat.chat_user_id": "u3",
            "WK_Readchat.chat_messageuser": "burst",
            "WK_Readchat.chat_user_name": "Burst",
            "WK_Readchat.chat_message": "burst message",
            "WK_Readchat.chat_is_vip": False,
            "WK_Readchat.chat_is_subscriber": False,
            "WK_Readchat.chat_is_broadcaster": False,
        }
        for _ in range(100):
            ingest.handle_ping("CHAT|2026-02-20T14:00:00.000000Z")
        time.sleep(0.2)
        ctx = self.repo.get_user_context("u3")
        self.assertEqual(len(ctx["last_messages"]), 1)

    def test_doorbell_supports_marker_variable_alias(self) -> None:
        self.sammi.values = {
            "global.since_2020": "2026-02-20T16:00:00.000000Z",
            "WK_Readchat.chat_user_id": "u4",
            "WK_Readchat.chat_messageuser": "alias",
            "WK_Readchat.chat_user_name": "Alias",
            "WK_Readchat.chat_message": "using marker alias",
            "WK_Readchat.chat_is_vip": False,
            "WK_Readchat.chat_is_subscriber": False,
            "WK_Readchat.chat_is_broadcaster": False,
        }
        result = self.ingest.handle_ping("chat|global.since_2020|1")
        self.assertTrue(result.get("processed"))
        cursor = self.repo.get_cursor("CHAT")
        self.assertEqual(cursor["last_commit_ts"], "2026-02-20T16:00:00.000000Z")

    def test_chat_field_aliases_from_sammi_variables(self) -> None:
        self.sammi.values = {
            "WK_Readchat.chat_message": "alias message text",
            "WK_Readchat.chat_messageuser": "AliasUser",
            "WK_Readchat.chat_user_id": "alias-user-1",
            "WK_Readchat.chat_is_broadcaster": True,
            "WK_Readchat.chat_is_subscriber": False,
            "WK_Readchat.chat_is_vip": True,
        }
        result = self.ingest.handle_ping("chat|2026-02-20T17:00:00.000000Z")
        self.assertTrue(result.get("processed"))

        ctx = self.repo.get_user_context("alias-user-1")
        self.assertIsNotNone(ctx.get("user"))
        self.assertEqual(ctx["user"]["login_name"], "AliasUser")
        self.assertEqual(ctx["last_messages"][0]["text"], "alias message text")
        flags = ctx["user"].get("flags") or {}
        self.assertTrue(bool(flags.get("is_vip")))
        self.assertTrue(bool(flags.get("is_broadcaster")))

    def test_chat_first_seen_and_message_count_flags(self) -> None:
        self.sammi.values = {
            "WK_Readchat.chat_message": "first hello",
            "WK_Readchat.chat_messageuser": "WelcomeUser",
            "WK_Readchat.chat_user_id": "u-welcome-1",
            "WK_Readchat.chat_is_broadcaster": False,
            "WK_Readchat.chat_is_subscriber": False,
            "WK_Readchat.chat_is_vip": False,
        }
        first = self.ingest.handle_ping("chat|193800001")
        self.assertTrue(first.get("processed"))
        self.assertTrue(bool(first.get("is_first_chat")))
        self.assertEqual(int(first.get("chat_seen_count") or 0), 1)

        self.sammi.values["WK_Readchat.chat_message"] = "second hello"
        second = self.ingest.handle_ping("chat|193800002")
        self.assertTrue(second.get("processed"))
        self.assertFalse(bool(second.get("is_first_chat")))
        self.assertEqual(int(second.get("chat_seen_count") or 0), 2)

        recent = self.repo.list_recent(limit=1, event_type="CHAT")
        self.assertEqual(len(recent), 1)
        payload = recent[0]["payload"]
        self.assertEqual(int(payload.get("chat_seen_count") or 0), 2)
        self.assertFalse(bool(payload.get("is_first_chat")))

    def test_ack_only_mode_logs_packet_without_sammi_reads(self) -> None:
        ingest = TwitchIngestService(
            db_service=self.db,
            repo=self.repo,
            sammi_client=NoCallSammiClient(),  # type: ignore[arg-type]
            chat_debounce_ms=0,
            source="test_ingest",
            ack_only=True,
        )
        result = ingest.handle_ping("chat|193735314")
        self.assertTrue(result.get("accepted"))
        self.assertTrue(result.get("processed"))
        self.assertTrue(result.get("ack_only"))

        events = self.db.list_events(limit=10, event_type="TWITCH_PACKET_RECEIVED")
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0]["payload"].get("event_type"), "CHAT")

    def test_chat_commit_marker_uses_packet_timestamp(self) -> None:
        self.sammi.values = {
            "WK_Readchat.chat_message": "priority marker test",
            "WK_Readchat.chat_messageuser": "Tester",
            "WK_Readchat.chat_user_id": "u-priority-1",
        }
        result = self.ingest.handle_ping("chat|193736050")
        self.assertTrue(result.get("processed"))
        recent = self.repo.list_recent(limit=1)
        self.assertEqual(recent[0]["commit_ts"], "193736050")

    def test_udp_listener_binds_only_when_gate_enabled(self) -> None:
        gate = {"enabled": False}

        def _should_listen() -> bool:
            return bool(gate["enabled"])

        recorder = _PingRecorder()

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tmp:
            tmp.bind(("127.0.0.1", 0))
            port = int(tmp.getsockname()[1])

        def _can_bind_udp_port(target_port: int) -> bool:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.bind(("127.0.0.1", target_port))
                return True
            except OSError:
                return False
            finally:
                try:
                    probe.close()
                except Exception:
                    pass

        def _wait_for(predicate, timeout_sec: float = 2.0) -> bool:
            deadline = time.monotonic() + timeout_sec
            while time.monotonic() < deadline:
                if predicate():
                    return True
                time.sleep(0.05)
            return predicate()

        listener = TwitchDoorbellListener(
            ingest_service=recorder,  # type: ignore[arg-type]
            host="127.0.0.1",
            port=port,
            enabled=True,
            should_listen=_should_listen,
        )
        listener.start()
        try:
            self.assertTrue(_wait_for(lambda: _can_bind_udp_port(port)))

            gate["enabled"] = True
            self.assertTrue(_wait_for(lambda: not _can_bind_udp_port(port)))

            sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sender.sendto(b"chat|193735314", ("127.0.0.1", port))
            finally:
                sender.close()
            self.assertTrue(_wait_for(lambda: recorder.count >= 1))

            gate["enabled"] = False
            self.assertTrue(_wait_for(lambda: _can_bind_udp_port(port)))
        finally:
            listener.stop()

    def test_null_payload_falls_back_without_parse_error(self) -> None:
        self.sammi.values = {
            "WK_Readchat.chat_user_id": "u-null-1",
            "WK_Readchat.chat_messageuser": "nuller",
            "WK_Readchat.chat_user_name": "Nuller",
            "WK_Readchat.chat_message": "null payload fallback",
        }
        result = self.ingest.handle_ping("\x00")
        self.assertTrue(result.get("accepted"))
        ctx = self.repo.get_user_context("u-null-1")
        self.assertEqual(len(ctx["last_messages"]), 1)

    def test_ambiguous_boolean_payload_detects_bits_and_follow(self) -> None:
        self.sammi.values = {
            "Twitch_Bits.new_bits_display": "BitsUser",
            "Twitch_Bits.new_bits_userid": "u-bool-bits-1",
            "Twitch_Bits.new_bits_username": "bits_user",
            "Twitch_Bits.new_bits_amount": "250",
            "Twitch_Bits.new_bits_type": "cheer",
        }
        bits_result = self.ingest.handle_ping("\x00")
        self.assertTrue(bits_result.get("processed"))
        self.assertEqual(bits_result.get("event_type"), "BITS")
        bits_ctx = self.repo.get_user_context("u-bool-bits-1")
        self.assertEqual(int(bits_ctx["stats"]["bits_total"]), 250)

        self.sammi.values = {
            "Twitch_Follow.new_follow_display": "FollowUser",
            "Twitch_Follow.new_follow_userid": "u-bool-follow-1",
            "Twitch_Follow.new_follow_username": "follow_user",
        }
        follow_result = self.ingest.handle_ping("\x00")
        self.assertTrue(follow_result.get("processed"))
        self.assertEqual(follow_result.get("event_type"), "FOLLOW")
        follow_ctx = self.repo.get_user_context("u-bool-follow-1")
        self.assertEqual(follow_ctx["user"]["display_name"], "FollowUser")

    def test_ambiguous_boolean_prefers_chat_when_chat_changes(self) -> None:
        self.sammi.values = {
            "WK_Readchat.chat_message": "ambiguous chat text",
            "WK_Readchat.chat_messageuser": "chat_user",
            "WK_Readchat.chat_user_id": "u-amb-chat-1",
            "WK_Readchat.chat_is_broadcaster": False,
            "WK_Readchat.chat_is_subscriber": False,
            "WK_Readchat.chat_is_vip": False,
            "Twitch_Bits.new_bits_display": "BitsUser",
            "Twitch_Bits.new_bits_userid": "u-amb-bits-1",
            "Twitch_Bits.new_bits_username": "bits_user",
            "Twitch_Bits.new_bits_amount": "250",
            "Twitch_Bits.new_bits_type": "cheer",
        }
        result = self.ingest.handle_ping("\x00")
        self.assertTrue(result.get("processed"))
        self.assertEqual(result.get("event_type"), "CHAT")
        chat_ctx = self.repo.get_user_context("u-amb-chat-1")
        self.assertEqual(chat_ctx["last_messages"][0]["text"], "ambiguous chat text")

    def test_doorbell_aliases_support_newfollow_and_bitdonation(self) -> None:
        self.sammi.values = {
            "new_bits_display": "BitsUser",
            "new_bits_userid": "u-bits-1",
            "new_bits_username": "bits_user",
            "new_bits_amount": "125",
            "new_bits_type": "cheer",
        }
        bits_result = self.ingest.handle_ping("bitdonation|193736200")
        self.assertTrue(bits_result.get("processed"))
        bits_ctx = self.repo.get_user_context("u-bits-1")
        self.assertEqual(int(bits_ctx["stats"]["bits_total"]), 125)

        self.sammi.values = {
            "new_follow_display": "FollowUser",
            "new_follow_userid": "u-follow-1",
            "new_follow_username": "follow_user",
        }
        follow_result = self.ingest.handle_ping("newfollow|193736201")
        self.assertTrue(follow_result.get("processed"))
        follow_ctx = self.repo.get_user_context("u-follow-1")
        self.assertEqual(follow_ctx["user"]["display_name"], "FollowUser")

    def test_extended_aliases_support_sub_raid_shoutout_powerups(self) -> None:
        self.sammi.values = {
            "Twitch_Sub.new_sub_display": "SubUser",
            "Twitch_Sub.new_sub_userid": "u-sub-1",
            "Twitch_Sub.new_sub_username": "sub_user",
            "Twitch_Sub.new_sub_tier": "Tier 1",
        }
        sub_result = self.ingest.handle_ping("subscription|193736300")
        self.assertTrue(sub_result.get("processed"))
        self.assertEqual(sub_result.get("event_type"), "SUB")

        self.sammi.values = {
            "Twitch_Raid.new_raid_display": "Raider",
            "Twitch_Raid.new_raid_userid": "u-raid-1",
            "Twitch_Raid.new_raid_username": "raid_user",
            "Twitch_Raid.new_raid_viewers": "42",
        }
        raid_result = self.ingest.handle_ping("raid|193736301")
        self.assertTrue(raid_result.get("processed"))
        self.assertEqual(raid_result.get("event_type"), "RAID")

        self.sammi.values = {
            "Twitch_Shoutout.new_shoutout_display": "Host",
            "Twitch_Shoutout.new_shoutout_userid": "u-shout-1",
            "Twitch_Shoutout.new_shoutout_username": "shout_user",
            "Twitch_Shoutout.new_shoutout_target_display": "Target",
            "Twitch_Shoutout.new_shoutout_target_userid": "u-target-1",
            "Twitch_Shoutout.new_shoutout_target_username": "target_user",
        }
        shout_result = self.ingest.handle_ping("shoutout|193736302")
        self.assertTrue(shout_result.get("processed"))
        self.assertEqual(shout_result.get("event_type"), "SHOUTOUT")

        self.sammi.values = {
            "Twitch_PowerUps.new_powerups_display": "PowerUser",
            "Twitch_PowerUps.new_powerups_userid": "u-power-1",
            "Twitch_PowerUps.new_powerups_username": "power_user",
            "Twitch_PowerUps.new_powerups_type": "gigantify",
            "Twitch_PowerUps.new_powerups_amount": "1",
        }
        power_result = self.ingest.handle_ping("powerups|193736303")
        self.assertTrue(power_result.get("processed"))
        self.assertEqual(power_result.get("event_type"), "POWER_UPS")

    def test_user_id_float_is_normalized_to_integer_string(self) -> None:
        self.sammi.values = {
            "Twitch_Bits.new_bits_display": "FloatUser",
            "Twitch_Bits.new_bits_userid": 76159058.0,
            "Twitch_Bits.new_bits_username": "float_user",
            "Twitch_Bits.new_bits_amount": "50",
            "Twitch_Bits.new_bits_type": "cheer",
        }
        result = self.ingest.handle_ping("bitdonation|193736450")
        self.assertTrue(result.get("processed"))
        self.assertEqual(result.get("event_type"), "BITS")
        self.assertEqual(result.get("user_id"), "76159058")
        ctx = self.repo.get_user_context("76159058")
        self.assertEqual(int(ctx["stats"]["bits_total"]), 50)


if __name__ == "__main__":
    unittest.main()
