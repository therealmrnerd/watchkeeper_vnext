from __future__ import annotations

import unittest

from core.semantic import create_semantic_engine
from core.semantic.types import SemanticStateRecord


class MemSemStore:
    def __init__(self) -> None:
        self._store: dict[str, SemanticStateRecord] = {}

    def get(self, key: str) -> SemanticStateRecord | None:
        return self._store.get(key)

    def set(self, rec: SemanticStateRecord) -> None:
        self._store[rec.key] = rec


class FakeRaw:
    def __init__(self) -> None:
        self.status = None
        self.status_at = None
        self.last_journal: dict[str, dict[str, object]] = {}
        self.raw: dict[str, object] = {}

    def now_ms(self) -> int:
        return 0

    def set_status(self, status, timestamp_ms: int) -> None:
        self.status = status
        self.status_at = timestamp_ms

    def push_journal(self, event: str, payload, timestamp_ms: int) -> None:
        self.last_journal[event] = {"event": event, "timestampMs": timestamp_ms, "payload": payload}

    def set_raw(self, path: str, value) -> None:
        self.raw[path] = value

    def get_status(self):
        return self.status

    def get_status_updated_at(self):
        return self.status_at

    def get_last_journal_event(self, event: str):
        return self.last_journal.get(event)

    def get_last_journal_event_of(self, events: list[str]):
        best = None
        for event in events:
            item = self.last_journal.get(event)
            if item is None:
                continue
            if best is None or item["timestampMs"] > best["timestampMs"]:
                best = item
        return best

    def get_raw_value(self, path: str):
        return self.raw.get(path)


class SemanticMvpTest(unittest.TestCase):
    def test_computes_basic_states_and_conservative_gating(self) -> None:
        raw = FakeRaw()
        sem = MemSemStore()
        engine = create_semantic_engine(raw, sem)

        t0 = 1_000_000
        raw.set_status(
            {
                "Flags": {
                    "Docked": False,
                    "Landed": False,
                    "Supercruise": False,
                    "InHyperspace": False,
                },
                "Heat": 25,
                "FuelMain": 8,
                "Hull": 0.95,
            },
            t0,
        )

        engine.update(["Status.$fresh", "Status.Flags", "Status.Heat", "Status.FuelMain", "Status.Hull"], t0)

        self.assertEqual(sem.get("ed.semantic.session.online_state").value, "in_game")
        self.assertEqual(sem.get("ed.semantic.context.primary_mode").value, "space")
        self.assertEqual(sem.get("ed.semantic.flight.flight_status").value, "normal_space")
        self.assertTrue(sem.get("ed.semantic.interaction.safe_for_keypress").value)

        raw.set_status(
            {
                "Flags": {
                    "InHyperspace": True,
                    "Supercruise": False,
                    "Docked": False,
                    "Landed": False,
                },
                "Heat": 25,
                "FuelMain": 8,
                "Hull": 0.95,
            },
            t0 + 1000,
        )
        engine.update(["Status.Flags.InHyperspace"], t0 + 1000)

        self.assertEqual(sem.get("ed.semantic.flight.fsd_state").value, "hyperspace")
        self.assertFalse(sem.get("ed.semantic.interaction.safe_for_keypress").value)


if __name__ == "__main__":
    unittest.main()
