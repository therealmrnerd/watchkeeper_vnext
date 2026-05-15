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
        self.assertEqual(sem.get("ed.semantic.context.player_platform").value, "ship")
        self.assertEqual(sem.get("ed.semantic.context.on_foot_area").value, "not_on_foot")
        self.assertEqual(sem.get("ed.semantic.interface.control_profile").value, "ship")
        self.assertFalse(sem.get("ed.semantic.opportunity.station_services_available").value)
        self.assertFalse(sem.get("ed.semantic.opportunity.market_access_available").value)
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

    def test_computes_srv_and_on_foot_station_semantics(self) -> None:
        raw = FakeRaw()
        sem = MemSemStore()
        engine = create_semantic_engine(raw, sem)

        t0 = 2_000_000
        raw.set_status(
            {
                "Flags": {
                    "OnFoot": False,
                    "InSRV": True,
                    "Docked": False,
                    "Landed": False,
                    "Supercruise": False,
                    "InHyperspace": False,
                },
                "Heat": 15,
                "FuelMain": 5,
                "Hull": 1.0,
            },
            t0,
        )
        engine.update(["Status.$fresh", "Status.Flags"], t0)

        self.assertEqual(sem.get("ed.semantic.context.primary_mode").value, "srv")
        self.assertEqual(sem.get("ed.semantic.context.player_platform").value, "srv")
        self.assertEqual(sem.get("ed.semantic.context.on_foot_area").value, "not_on_foot")
        self.assertEqual(sem.get("ed.semantic.interface.control_profile").value, "srv")
        self.assertFalse(sem.get("ed.semantic.opportunity.station_services_available").value)

        raw.set_status(
            {
                "Flags": {
                    "OnFoot": True,
                    "InSRV": False,
                    "Docked": True,
                    "Landed": False,
                    "Supercruise": False,
                    "InHyperspace": False,
                },
                "Heat": 15,
                "FuelMain": 5,
                "Hull": 1.0,
            },
            t0 + 1000,
        )
        engine.update(["Status.Flags.OnFoot", "Status.Flags.Docked"], t0 + 1000)

        self.assertEqual(sem.get("ed.semantic.context.primary_mode").value, "on_foot")
        self.assertEqual(sem.get("ed.semantic.context.player_platform").value, "on_foot")
        self.assertEqual(sem.get("ed.semantic.context.on_foot_area").value, "station")
        self.assertEqual(sem.get("ed.semantic.interface.control_profile").value, "on_foot_station")
        self.assertTrue(sem.get("ed.semantic.opportunity.station_services_available").value)
        self.assertTrue(sem.get("ed.semantic.opportunity.market_access_available").value)

    def test_computes_planetary_flight_from_surface_telemetry(self) -> None:
        raw = FakeRaw()
        sem = MemSemStore()
        engine = create_semantic_engine(raw, sem)

        t0 = 3_000_000
        raw.set_status(
            {
                "Flags": {
                    "Docked": False,
                    "Landed": False,
                    "Supercruise": False,
                    "InHyperspace": False,
                    "GlideMode": False,
                    "HasLatLong": True,
                },
                "Heat": 22,
                "FuelMain": 6,
                "Hull": 0.98,
            },
            t0,
        )
        raw.set_raw("ed.telemetry.altitude", 1543.0)
        raw.set_raw("ed.telemetry.latitude_raw", -12.34)
        raw.set_raw("ed.telemetry.longitude_raw", 45.67)

        engine.update(
            [
                "Status.$fresh",
                "Status.Flags",
                "Status.Flags.HasLatLong",
                "ed.telemetry.altitude",
                "ed.telemetry.latitude_raw",
                "ed.telemetry.longitude_raw",
            ],
            t0,
        )

        self.assertEqual(sem.get("ed.semantic.context.primary_mode").value, "planetary")
        self.assertEqual(sem.get("ed.semantic.flight.flight_status").value, "planetary_flight")

    def test_can_request_docking_from_station_destination_context(self) -> None:
        raw = FakeRaw()
        sem = MemSemStore()
        engine = create_semantic_engine(raw, sem)

        t0 = 4_000_000
        raw.set_status(
            {
                "Flags": {
                    "Docked": False,
                    "Landed": False,
                    "Supercruise": False,
                    "InHyperspace": False,
                    "HardpointsDeployed": False,
                    "IsInDanger": False,
                    "BeingInterdicted": False,
                    "Firing": False,
                },
                "Destination": {
                    "Name": "Kregel Hub",
                    "System": 9468121261481,
                    "Body": 31,
                },
                "Heat": 25,
                "FuelMain": 8,
                "Hull": 0.95,
            },
            t0,
        )
        raw.set_raw("ed.telemetry.destination_name", "Kregel Hub")
        raw.set_raw("ed.telemetry.destination_body_type", "Station")
        raw.set_raw("ed.station.no_fire_zone", True)

        engine.update(
            [
                "Status.$fresh",
                "Status.Flags",
                "Status.Destination",
                "ed.telemetry.destination_name",
                "ed.telemetry.destination_body_type",
                "ed.station.no_fire_zone",
                "Status.Heat",
                "Status.FuelMain",
                "Status.Hull",
            ],
            t0,
        )

        self.assertEqual(sem.get("ed.semantic.target.target_type").value, "station")
        self.assertTrue(sem.get("ed.semantic.station.no_fire_zone").value)
        self.assertEqual(sem.get("ed.semantic.flight.flight_status").value, "normal_space")
        self.assertTrue(sem.get("ed.semantic.opportunity.can_request_docking").value)

    def test_station_destination_cannot_request_docking_outside_no_fire_zone(self) -> None:
        raw = FakeRaw()
        sem = MemSemStore()
        engine = create_semantic_engine(raw, sem)

        t0 = 4_100_000
        raw.set_status(
            {
                "Flags": {
                    "Docked": False,
                    "Landed": False,
                    "Supercruise": False,
                    "InHyperspace": False,
                    "HardpointsDeployed": False,
                    "IsInDanger": False,
                    "BeingInterdicted": False,
                    "Firing": False,
                },
                "Destination": {
                    "Name": "Kregel Hub",
                    "System": 9468121261481,
                    "Body": 31,
                },
                "Heat": 25,
                "FuelMain": 8,
                "Hull": 0.95,
            },
            t0,
        )
        raw.set_raw("ed.telemetry.destination_name", "Kregel Hub")
        raw.set_raw("ed.telemetry.destination_body_type", "Station")
        raw.set_raw("ed.station.no_fire_zone", False)

        engine.update(
            [
                "Status.$fresh",
                "Status.Flags",
                "Status.Destination",
                "ed.telemetry.destination_name",
                "ed.telemetry.destination_body_type",
                "ed.station.no_fire_zone",
                "Status.Heat",
                "Status.FuelMain",
                "Status.Hull",
            ],
            t0,
        )

        self.assertEqual(sem.get("ed.semantic.target.target_type").value, "station")
        self.assertFalse(sem.get("ed.semantic.station.no_fire_zone").value)
        self.assertFalse(sem.get("ed.semantic.opportunity.can_request_docking").value)

    def test_no_fire_zone_can_request_docking_without_station_target(self) -> None:
        raw = FakeRaw()
        sem = MemSemStore()
        engine = create_semantic_engine(raw, sem)

        t0 = 4_200_000
        raw.set_status(
            {
                "Flags": {
                    "Docked": False,
                    "Landed": False,
                    "Supercruise": False,
                    "InHyperspace": False,
                    "HardpointsDeployed": False,
                    "IsInDanger": False,
                    "BeingInterdicted": False,
                    "Firing": False,
                },
                "Heat": 25,
                "FuelMain": 8,
                "Hull": 0.95,
            },
            t0,
        )
        raw.set_raw("ed.station.no_fire_zone", True)

        engine.update(
            [
                "Status.$fresh",
                "Status.Flags",
                "ed.station.no_fire_zone",
                "Status.Heat",
                "Status.FuelMain",
                "Status.Hull",
            ],
            t0,
        )

        self.assertTrue(sem.get("ed.semantic.station.no_fire_zone").value)
        self.assertTrue(sem.get("ed.semantic.opportunity.can_request_docking").value)

    def test_target_type_uses_destination_when_target_missing(self) -> None:
        raw = FakeRaw()
        sem = MemSemStore()
        engine = create_semantic_engine(raw, sem)

        t0 = 5_000_000
        raw.set_status(
            {
                "Flags": {
                    "Docked": False,
                    "Landed": False,
                    "Supercruise": False,
                    "InHyperspace": False,
                },
                "Destination": {
                    "Name": "Kregel Hub",
                    "System": 9468121261481,
                    "Body": 31,
                    "BodyType": "Station",
                },
                "Heat": 25,
                "FuelMain": 8,
                "Hull": 0.95,
            },
            t0,
        )
        engine.update(["Status.$fresh", "Status.Flags", "Status.Destination"], t0)
        self.assertEqual(sem.get("ed.semantic.target.target_type").value, "station")


if __name__ == "__main__":
    unittest.main()
