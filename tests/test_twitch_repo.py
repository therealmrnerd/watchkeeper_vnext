import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from db_service import BrainstemDB

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from db.twitch_repo import TwitchRepository


class TwitchRepoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_twitch_repo_"))
        self.db_path = self.temp_dir / "repo.db"
        self.schema_path = ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql"
        self.db = BrainstemDB(self.db_path, self.schema_path)
        self.db.ensure_schema()
        self.repo = TwitchRepository(self.db)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_insert_recent_message_prunes_to_five(self) -> None:
        self.repo.upsert_user(user_id="u1", login_name="tester", display_name="Tester", increment_messages=0)
        for idx in range(7):
            ts = f"2026-02-20T10:00:0{idx}.000000Z"
            self.repo.insert_recent_message_and_prune(
                user_id="u1",
                message_ts_utc=ts,
                msg_id=f"m-{idx}",
                text=f"msg {idx}",
            )

        context = self.repo.get_user_context("u1")
        self.assertEqual(len(context["last_messages"]), 5)
        self.assertEqual(context["last_messages"][0]["msg_id"], "m-6")
        self.assertEqual(context["last_messages"][-1]["msg_id"], "m-2")

        with sqlite3.connect(self.db_path) as con:
            row = con.execute(
                "SELECT COUNT(*) FROM twitch_user_recent_message WHERE user_id='u1'"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(int(row[0]), 5)

    def test_cursor_dedupe_rules(self) -> None:
        first = self.repo.set_cursor("chat", "2026-02-20T12:00:00.000000Z", seq=1)
        self.assertTrue(first["updated"])

        same = self.repo.set_cursor("chat", "2026-02-20T12:00:00.000000Z", seq=1)
        self.assertFalse(same["updated"])

        higher_seq = self.repo.set_cursor("chat", "2026-02-20T12:00:00.000000Z", seq=2)
        self.assertTrue(higher_seq["updated"])

        older = self.repo.set_cursor("chat", "2026-02-20T11:59:59.000000Z", seq=9)
        self.assertFalse(older["updated"])

    def test_cursor_numeric_marker_order(self) -> None:
        first = self.repo.set_cursor("chat", "193735314", seq=0)
        self.assertTrue(first["updated"])

        same = self.repo.set_cursor("chat", "193735314", seq=0)
        self.assertFalse(same["updated"])

        lower = self.repo.set_cursor("chat", "193735313", seq=0)
        self.assertFalse(lower["updated"])

        higher = self.repo.set_cursor("chat", "193735315", seq=0)
        self.assertTrue(higher["updated"])

    def test_cursor_allows_marker_type_migration(self) -> None:
        first = self.repo.set_cursor("chat", "2026-02-20T12:00:00.000000Z", seq=0)
        self.assertTrue(first["updated"])
        migrated = self.repo.set_cursor("chat", "193735314", seq=0)
        self.assertTrue(migrated["updated"])

    def test_user_aggregates_bits_and_redeems(self) -> None:
        self.repo.upsert_user(user_id="u2", login_name="bitsguy", display_name="Bits Guy")
        self.repo.add_bits(user_id="u2", amount=250, ts_utc="2026-02-20T12:01:00.000000Z")
        self.repo.add_bits(user_id="u2", amount=100, ts_utc="2026-02-20T12:02:00.000000Z")
        self.repo.add_redeem(
            user_id="u2",
            reward_id="r-hydrate",
            title="Hydrate",
            ts_utc="2026-02-20T12:03:00.000000Z",
        )
        self.repo.add_redeem(
            user_id="u2",
            reward_id="r-hydrate",
            title="Hydrate",
            ts_utc="2026-02-20T12:04:00.000000Z",
        )
        context = self.repo.get_user_context("u2")
        stats = context["stats"]
        self.assertEqual(int(stats["bits_total"]), 350)
        self.assertEqual(int(stats["redeem_total"]), 2)
        self.assertGreaterEqual(len(context["top_redeems"]), 1)
        self.assertEqual(context["top_redeems"][0]["reward_id"], "r-hydrate")
        self.assertEqual(int(context["top_redeems"][0]["claim_count"]), 2)


if __name__ == "__main__":
    unittest.main()
