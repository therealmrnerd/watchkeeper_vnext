import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.policy_engine import PolicyEngine
from core.policy_types import (
    ActionRequest,
    REASON_ALLOW,
    REASON_DENY_CONFIRMATION_EXPIRED,
    REASON_DENY_EXPLICITLY_DENIED,
    REASON_DENY_FOREGROUND_MISMATCH,
    REASON_DENY_LOW_STT_CONFIDENCE,
    REASON_DENY_NEEDS_CONFIRMATION,
    REASON_DENY_NOT_ALLOWED_IN_CONDITION,
    REASON_DENY_RATE_LIMIT,
)


class PolicyEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy_path = ROOT_DIR / "config" / "standing_orders.json"

    def setUp(self) -> None:
        self.engine = PolicyEngine(self.policy_path)
        self.base_ts = 1_700_000_000.0

    def _req(
        self,
        *,
        condition: str,
        tool: str,
        incident_id: str = "inc-test",
        stt: float | None = None,
        foreground: str | None = None,
        ts_offset: float = 0.0,
        token: str | None = None,
    ) -> ActionRequest:
        return ActionRequest(
            incident_id=incident_id,
            watch_condition=condition,
            tool_name=tool,
            args={},
            source="test",
            stt_confidence=stt,
            foreground_process=foreground,
            now_ts=self.base_ts + ts_offset,
            user_confirm_token=token,
        )

    def test_work_denies_keypress(self) -> None:
        decision = self.engine.evaluate(
            self._req(condition="WORK", tool="input.keypress", stt=0.95, foreground="chrome.exe")
        )
        self.assertFalse(decision.allowed)
        self.assertIn(
            decision.deny_reason_code,
            {REASON_DENY_NOT_ALLOWED_IN_CONDITION, REASON_DENY_EXPLICITLY_DENIED},
        )

    def test_game_allows_keypress_with_good_stt_and_foreground(self) -> None:
        decision = self.engine.evaluate(
            self._req(
                condition="GAME",
                tool="input.keypress",
                stt=0.95,
                foreground="EliteDangerous64.exe",
            )
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.deny_reason_code, REASON_ALLOW)

    def test_game_blocks_keypress_when_low_stt(self) -> None:
        decision = self.engine.evaluate(
            self._req(
                condition="GAME",
                tool="input.keypress",
                stt=0.50,
                foreground="EliteDangerous64.exe",
            )
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.deny_reason_code, REASON_DENY_LOW_STT_CONFIDENCE)

    def test_game_blocks_keypress_when_foreground_wrong(self) -> None:
        decision = self.engine.evaluate(
            self._req(
                condition="GAME",
                tool="input.keypress",
                stt=0.95,
                foreground="chrome.exe",
            )
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.deny_reason_code, REASON_DENY_FOREGROUND_MISMATCH)

    def test_confirmation_required_for_twitch(self) -> None:
        incident_id = "inc-twitch"
        tool = "twitch.redeem"
        token = "tok-1"

        first = self.engine.evaluate(
            self._req(condition="GAME", tool=tool, incident_id=incident_id, ts_offset=0, token=token)
        )
        self.assertFalse(first.allowed)
        self.assertTrue(first.requires_confirmation)
        self.assertEqual(first.deny_reason_code, REASON_DENY_NEEDS_CONFIRMATION)

        self.engine.record_confirmation(
            incident_id=incident_id,
            tool_name=tool,
            token=token,
            ts=self.base_ts + 2,
        )
        second = self.engine.evaluate(
            self._req(condition="GAME", tool=tool, incident_id=incident_id, ts_offset=3, token=token)
        )
        self.assertTrue(second.allowed)

        expired = self.engine.evaluate(
            self._req(condition="GAME", tool=tool, incident_id=incident_id, ts_offset=20, token=token)
        )
        self.assertFalse(expired.allowed)
        self.assertEqual(expired.deny_reason_code, REASON_DENY_CONFIRMATION_EXPIRED)

    def test_web_search_rate_limit(self) -> None:
        for idx in range(12):
            decision = self.engine.evaluate(
                self._req(
                    condition="WORK",
                    tool="web.search",
                    ts_offset=float(idx),
                    incident_id=f"inc-web-{idx}",
                )
            )
            self.assertTrue(decision.allowed)

        thirteenth = self.engine.evaluate(
            self._req(
                condition="WORK",
                tool="web.search",
                ts_offset=12.5,
                incident_id="inc-web-13",
            )
        )
        self.assertFalse(thirteenth.allowed)
        self.assertEqual(thirteenth.deny_reason_code, REASON_DENY_RATE_LIMIT)

    def test_restricted_inheritance_keypress_limit(self) -> None:
        incident_id = "inc-restricted"
        token = "tok-restricted"
        tool = "input.keypress"

        self.engine.record_confirmation(
            incident_id=incident_id,
            tool_name=tool,
            token=token,
            ts=self.base_ts,
        )

        for idx in range(10):
            decision = self.engine.evaluate(
                self._req(
                    condition="RESTRICTED",
                    tool=tool,
                    incident_id=incident_id,
                    stt=0.95,
                    foreground="EliteDangerous64.exe",
                    ts_offset=float(idx + 1),
                    token=token,
                )
            )
            self.assertTrue(decision.allowed)

        eleventh = self.engine.evaluate(
            self._req(
                condition="RESTRICTED",
                tool=tool,
                incident_id=incident_id,
                stt=0.95,
                foreground="EliteDangerous64.exe",
                ts_offset=11.0,
                token=token,
            )
        )
        self.assertFalse(eleventh.allowed)
        self.assertEqual(eleventh.deny_reason_code, REASON_DENY_RATE_LIMIT)


if __name__ == "__main__":
    unittest.main()
