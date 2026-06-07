import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock


ROOT_DIR = Path(__file__).resolve().parents[1]
ADAPTERS_DIR = ROOT_DIR / "services" / "adapters"
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
for path in (ADAPTERS_DIR, BRAINSTEM_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class EdFileCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="cockpit_ed_files_"))
        sys.modules.pop("state_collector", None)
        self.collector = importlib.import_module("state_collector")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_collect_ed_file_state_reads_status_json_flags(self) -> None:
        status_path = self.temp_dir / "Status.json"
        flags = (1 << 0) | (1 << 4) | (1 << 19) | (1 << 20) | (1 << 21)
        flags2 = (1 << 0) | (1 << 12)
        status_path.write_text(
            json.dumps(
                {
                    "Flags": flags,
                    "Flags2": flags2,
                    "GuiFocus": 0,
                    "Pips": [2, 4, 6],
                    "Fuel": {"FuelMain": 8.5, "FuelReservoir": 0.3},
                    "Cargo": 12,
                    "LegalState": "Clean",
                    "FireGroup": 1,
                    "Temperature": 0.72,
                    "BodyName": "Test Body",
                    "Latitude": 12.5,
                    "Longitude": -55.25,
                    "Altitude": 7234,
                    "Heading": 271,
                    "SelectedWeapon_Localised": "Karma AR-50",
                }
            ),
            encoding="utf-8",
        )

        result = self.collector.collect_ed_file_state(
            status_path=status_path,
            journal_dir=self.temp_dir,
        )

        self.assertTrue(result["ed.status.available"])
        self.assertTrue(result["ed.status.docked"])
        self.assertTrue(result["ed.status.supercruise"])
        self.assertTrue(result["ed.status.low_fuel"])
        self.assertTrue(result["ed.status.overheating"])
        self.assertEqual(result["ed.status.fuel_main"], 8.5)
        self.assertEqual(result["ed.status.temperature"], 0.72)
        self.assertEqual(result["ed.status.body_name"], "Test Body")
        self.assertTrue(result["ed.status.has_lat_long"])
        self.assertTrue(result["ed.status.on_foot"])
        self.assertTrue(result["ed.status.glide_mode"])
        self.assertEqual(result["ed.status.latitude"], 12.5)
        self.assertEqual(result["ed.status.selected_weapon_localised"], "Karma AR-50")

    def test_collect_ed_file_state_handles_missing_and_malformed_files(self) -> None:
        bad_status = self.temp_dir / "Status.json"
        bad_status.write_text("{not json", encoding="utf-8")

        result = self.collector.collect_ed_file_state(
            status_path=bad_status,
            journal_dir=self.temp_dir,
        )

        self.assertFalse(result["ed.status.available"])
        self.assertIsNone(result["ed.journal.last_event"])

    def test_collect_ed_file_state_reads_latest_journal_event(self) -> None:
        old_log = self.temp_dir / "Journal.001.log"
        new_log = self.temp_dir / "Journal.002.log"
        old_log.write_text(json.dumps({"event": "Location", "StarSystem": "Old"}) + "\n", encoding="utf-8")
        new_log.write_text(
            "\n".join(
                [
                    json.dumps({"event": "FSDJump", "StarSystem": "Sol", "SystemAddress": 123}),
                    json.dumps({"event": "Docked", "StarSystem": "Sol", "StationName": "Galileo"}),
                ]
            ),
            encoding="utf-8",
        )

        result = self.collector.collect_ed_file_state(
            status_path=self.temp_dir / "missing-status.json",
            journal_dir=self.temp_dir,
        )

        self.assertEqual(result["ed.journal.last_event"], "Docked")
        self.assertEqual(result["ed.location.system"], "Sol")
        self.assertEqual(result["ed.location.station"], "Galileo")

    def test_collect_ed_file_state_keeps_latest_location_context(self) -> None:
        journal = self.temp_dir / "Journal.004.log"
        journal.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "event": "Docked",
                            "StarSystem": "Puppis Sector ON-T b3-5",
                            "SystemAddress": 12345,
                            "StationName": "Blackstar's Cove",
                        }
                    ),
                    json.dumps({"event": "Friends", "Status": "Online"}),
                ]
            ),
            encoding="utf-8",
        )

        result = self.collector.collect_ed_file_state(
            status_path=self.temp_dir / "missing-status.json",
            journal_dir=self.temp_dir,
        )

        self.assertEqual(result["ed.journal.last_event"], "Friends")
        self.assertEqual(result["ed.location.system"], "Puppis Sector ON-T b3-5")
        self.assertEqual(result["ed.location.system_address"], 12345)
        self.assertEqual(result["ed.location.station"], "Blackstar's Cove")

    def test_collect_ed_file_state_clears_system_conflict_state_for_clean_location(self) -> None:
        journal = self.temp_dir / "Journal.0041.log"
        journal.write_text(
            json.dumps(
                {
                    "event": "Location",
                    "StarSystem": "Puppis Sector ON-T b3-5",
                    "SystemFaction": {"Name": "Blackstar", "FactionState": "Expansion"},
                    "Factions": [{"Name": "Blackstar", "FactionState": "Expansion"}],
                }
            ),
            encoding="utf-8",
        )

        result = self.collector.collect_ed_file_state(
            status_path=self.temp_dir / "missing-status.json",
            journal_dir=self.temp_dir,
        )

        self.assertEqual(result["ed.system.faction_state"], "Expansion")
        self.assertFalse(result["ed.system.civil_war"])
        self.assertEqual(result["ed.system.conflicts"], [])
        self.assertEqual(result["ed.system.conflict_count"], 0)

    def test_collect_ed_file_state_tracks_fighter_launch_context(self) -> None:
        journal = self.temp_dir / "Journal.0045.log"
        journal.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "timestamp": "2026-05-08T16:59:00Z",
                            "event": "LaunchFighter",
                            "ID": 43,
                            "Loadout": "AX1",
                            "PlayerControlled": True,
                        }
                    ),
                    json.dumps({"timestamp": "2026-05-08T16:59:05Z", "event": "Friends"}),
                ]
            ),
            encoding="utf-8",
        )

        result = self.collector.collect_ed_file_state(
            status_path=self.temp_dir / "missing-status.json",
            journal_dir=self.temp_dir,
        )

        self.assertTrue(result["ed.fighter.active"])
        self.assertEqual(result["ed.fighter.last_event"], "LaunchFighter")
        self.assertEqual(result["ed.fighter.id"], 43)
        self.assertEqual(result["ed.fighter.model"], "taipan")

    def test_collect_ed_file_state_tracks_srv_launch_context(self) -> None:
        journal = self.temp_dir / "Journal.0046.log"
        journal.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "timestamp": "2026-05-08T17:01:00Z",
                            "event": "LaunchSRV",
                            "ID": 12,
                            "SRVType": "testbuggy",
                            "SRVType_Localised": "Scarab SRV",
                        }
                    ),
                    json.dumps({"timestamp": "2026-05-08T17:01:05Z", "event": "Friends"}),
                ]
            ),
            encoding="utf-8",
        )

        result = self.collector.collect_ed_file_state(
            status_path=self.temp_dir / "missing-status.json",
            journal_dir=self.temp_dir,
        )

        self.assertTrue(result["ed.srv.active"])
        self.assertEqual(result["ed.srv.last_event"], "LaunchSRV")
        self.assertEqual(result["ed.srv.id"], 12)
        self.assertEqual(result["ed.srv.model"], "testbuggy")

    def test_collect_ed_file_state_tracks_suit_loadout_context(self) -> None:
        journal = self.temp_dir / "Journal.0047.log"
        journal.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "timestamp": "2026-05-08T17:05:00Z",
                            "event": "SuitLoadout",
                            "SuitID": 99,
                            "SuitName": "tactical_suit_class1",
                            "SuitName_Localised": "Dominator Suit",
                            "LoadoutName": "Ground Combat",
                            "Modules": [
                                {
                                    "SlotName": "PrimaryWeapon1",
                                    "ModuleName": "wpn_m_assaultrifle_laser_fauto",
                                    "ModuleName_Localised": "TK Aphelion",
                                }
                            ],
                        }
                    ),
                    json.dumps({"timestamp": "2026-05-08T17:05:05Z", "event": "Friends"}),
                ]
            ),
            encoding="utf-8",
        )

        result = self.collector.collect_ed_file_state(
            status_path=self.temp_dir / "missing-status.json",
            journal_dir=self.temp_dir,
        )

        self.assertEqual(result["ed.suit.id"], 99)
        self.assertEqual(result["ed.suit.name_localised"], "Dominator Suit")
        self.assertEqual(result["ed.suit.loadout_name"], "Ground Combat")
        self.assertEqual(result["ed.suit.modules"][0]["ModuleName_Localised"], "TK Aphelion")

    def test_collect_ed_file_state_derives_no_fire_zone_from_station_chatter(self) -> None:
        journal = self.temp_dir / "Journal.005.log"
        journal.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "timestamp": "2026-05-03T15:38:39Z",
                            "event": "ReceiveText",
                            "From": "Blackstar's Cove",
                            "Message": "$STATION_NoFireZone_entered;",
                            "Message_Localised": "No fire zone entered.",
                        }
                    ),
                    json.dumps({"timestamp": "2026-05-03T15:39:00Z", "event": "Friends"}),
                ]
            ),
            encoding="utf-8",
        )

        result = self.collector.collect_ed_file_state(
            status_path=self.temp_dir / "missing-status.json",
            journal_dir=self.temp_dir,
        )

        self.assertTrue(result["ed.station.no_fire_zone"])
        self.assertEqual(result["ed.station.no_fire_zone_event"], "entered")
        self.assertEqual(result["ed.station.no_fire_zone_station"], "Blackstar's Cove")

    def test_collect_ed_file_state_clears_no_fire_zone_after_exit_or_docked(self) -> None:
        journal = self.temp_dir / "Journal.006.log"
        journal.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "timestamp": "2026-05-03T15:38:39Z",
                            "event": "ReceiveText",
                            "From": "Blackstar's Cove",
                            "Message": "$STATION_NoFireZone_entered;",
                        }
                    ),
                    json.dumps(
                        {
                            "timestamp": "2026-05-03T15:46:38Z",
                            "event": "Docked",
                            "StationName": "Blackstar's Cove",
                        }
                    ),
                ]
            ),
            encoding="utf-8",
        )

        result = self.collector.collect_ed_file_state(
            status_path=self.temp_dir / "missing-status.json",
            journal_dir=self.temp_dir,
        )

        self.assertFalse(result["ed.station.no_fire_zone"])
        self.assertEqual(result["ed.station.no_fire_zone_event"], "Docked")

    def test_collect_ed_file_state_tracks_docking_lifecycle(self) -> None:
        journal = self.temp_dir / "Journal.007.log"
        journal.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "timestamp": "2026-05-03T15:38:39Z",
                            "event": "DockingRequested",
                            "StationName": "Blackstar's Cove",
                        }
                    ),
                    json.dumps(
                        {
                            "timestamp": "2026-05-03T15:38:42Z",
                            "event": "DockingGranted",
                            "StationName": "Blackstar's Cove",
                            "LandingPad": 40,
                        }
                    ),
                ]
            ),
            encoding="utf-8",
        )

        result = self.collector.collect_ed_file_state(
            status_path=self.temp_dir / "missing-status.json",
            journal_dir=self.temp_dir,
        )

        self.assertEqual(result["ed.station.docking_state"], "granted")
        self.assertEqual(result["ed.station.docking_state_event"], "DockingGranted")
        self.assertEqual(result["ed.station.docking_state_station"], "Blackstar's Cove")

    def test_collect_ed_file_state_reads_loadout_module_health(self) -> None:
        journal = self.temp_dir / "Journal.003.log"
        modules_path = self.temp_dir / "ModulesInfo.json"
        modules_path.write_text(
            json.dumps(
                {
                    "event": "ModuleInfo",
                    "Modules": [
                        {"Slot": "MainEngines", "Item": "int_engine_size2_class2", "Power": 2.4},
                    ],
                }
            ),
            encoding="utf-8",
        )
        journal.write_text(
            "\n".join(
                [
                    json.dumps({"event": "Location", "StarSystem": "Sol"}),
                    json.dumps(
                        {
                            "timestamp": "2026-05-01T10:00:00Z",
                            "event": "Loadout",
                            "Ship": "sidewinder",
                            "ShipID": 42,
                            "ShipName": "WK-TEST",
                            "ShipIdent": "WK",
                            "HullHealth": 0.875,
                            "Modules": [
                                {
                                    "Slot": "MainEngines",
                                    "Item": "int_engine_size2_class2",
                                    "Health": 0.625,
                                    "On": True,
                                    "Priority": 1,
                                },
                                {
                                    "Slot": "TinyHardpoint1",
                                    "Item": "hpt_pulselaser_fixed_small",
                                    "Health": 1.0,
                                    "AmmoInClip": 0,
                                    "AmmoInHopper": 0,
                                },
                            ],
                        }
                    ),
                    json.dumps({"event": "ReceiveText"}),
                ]
            ),
            encoding="utf-8",
        )

        result = self.collector.collect_ed_file_state(
            status_path=self.temp_dir / "missing-status.json",
            journal_dir=self.temp_dir,
            modules_path=modules_path,
        )

        self.assertTrue(result["ed.modules.available"])
        self.assertTrue(result["ed.modules.health_available"])
        self.assertEqual(result["ed.modules.source"], "journal_loadout")
        self.assertEqual(result["ed.modules.hull_health_percent"], 88)
        self.assertEqual(result["ed.modules.power_capacity_mw"], 5.0)
        self.assertEqual(result["ed.modules.power_usage_percent"], 48)
        self.assertEqual(result["ed.modules.count"], 2)
        self.assertEqual(result["ed.modules.items"][0]["slot"], "MainEngines")
        self.assertEqual(result["ed.modules.items"][0]["health_percent"], 62)
        self.assertEqual(result["ed.modules.items"][0]["power"], 2.4)
        self.assertEqual(result["ed.modules.items"][0]["power_percent"], 48)

    def test_collect_ed_file_state_reads_limpet_cargo(self) -> None:
        cargo_path = self.temp_dir / "Cargo.json"
        cargo_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-05-08T10:00:00Z",
                    "event": "Cargo",
                    "Vessel": "Ship",
                    "Count": 4,
                    "Inventory": [
                        {"Name": "drones", "Name_Localised": "Limpet", "Count": 4},
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = self.collector.collect_ed_file_state(
            status_path=self.temp_dir / "missing-status.json",
            journal_dir=self.temp_dir,
            cargo_path=cargo_path,
        )

        self.assertTrue(result["ed.cargo.available"])
        self.assertEqual(result["ed.cargo.count"], 4)
        self.assertEqual(result["ed.cargo.limpet_count"], 4)


class CockpitStateQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="cockpit_state_"))
        self.db_path = self.temp_dir / "watchkeeper.db"
        os.environ["WKV_DB_PATH"] = str(self.db_path)
        os.environ["WKV_SCHEMA_PATH"] = str(ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql")
        os.environ["WKV_STANDING_ORDERS_PATH"] = str(ROOT_DIR / "config" / "standing_orders.json")
        os.environ["WKV_PROVIDER_CONFIG_PATH"] = str(ROOT_DIR / "config" / "providers.json")
        os.environ["WKV_PROVIDER_SECRETS_PATH"] = str(self.temp_dir / "provider_secrets.dpapi")
        os.environ["WKV_ENABLE_KEYPRESS"] = "0"
        os.environ["WKV_ENABLE_ACTUATORS"] = "0"
        os.environ["WKV_TESTING_MODE"] = "1"
        os.environ["WKV_KEYPRESS_TEST_LOG"] = str(self.temp_dir / "keypress_test_log.txt")
        for name in ("runtime", "queries", "handlers", "actions", "validators"):
            sys.modules.pop(name, None)
        self.runtime = importlib.import_module("runtime")
        self.queries = importlib.import_module("queries")
        self.actions = importlib.import_module("actions")
        self.handlers = importlib.import_module("handlers")
        self.runtime.ensure_db()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _set_state(self, key: str, value: object) -> None:
        self.runtime.DB_SERVICE.set_state(
            state_key=key,
            state_value=value,
            source="test",
            observed_at_utc=self.runtime.utc_now_iso(),
            confidence=1.0,
            emit_event=False,
        )

    def _keypress_log_entries(self) -> list[dict[str, object]]:
        log_path = Path(os.environ["WKV_KEYPRESS_TEST_LOG"])
        self.assertTrue(log_path.exists(), f"Expected keypress test log at {log_path}")
        entries: list[dict[str, object]] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def test_query_cockpit_state_includes_action_intent(self) -> None:
        self._set_state("ed.running", True)
        self._set_state("ed.status.available", True)
        self._set_state("ed.status.overheating", True)
        self._set_state("ed.location.system", "Sol")

        result = self.queries.query_cockpit_state({})

        self.assertTrue(result["ok"])
        self.assertEqual(result["telemetry"]["system"], "Sol")
        heat = next(item for item in result["suggestions"] if item["id"] == "heat_high_heatsink")
        action = heat["cockpit_action_intent"]["recommended_action"]
        self.assertEqual(action["tool"], "input.keypress")
        self.assertEqual(action["action"], "deploy_heatsink")
        self.assertTrue(action["requires_confirmation"])

    def test_query_cockpit_state_does_not_report_sammi(self) -> None:
        self._set_state("app.sammi.running", False)

        result = self.queries.query_cockpit_state({})

        self.assertNotIn("sammi", result["integrations"])
        self.assertNotIn(
            "sammi_unavailable",
            {str(item.get("id")) for item in result["suggestions"]},
        )

    def test_query_cockpit_state_includes_module_health(self) -> None:
        modules = [
            {
                "slot": "PowerPlant",
                "item": "int_powerplant_size2_class2",
                "health_percent": 73,
                "on": True,
            }
        ]
        self._set_state("ed.modules.available", True)
        self._set_state("ed.modules.health_available", True)
        self._set_state("ed.modules.source", "journal_loadout")
        self._set_state("ed.modules.power_capacity_mw", 30.0)
        self._set_state("ed.modules.power_usage_percent", 87)
        self._set_state("ed.modules.power_percent_basis", "estimated_next_5mw")
        self._set_state("ed.modules.count", 1)
        self._set_state("ed.modules.items", modules)
        self._set_state("ed.modules.hull_health_percent", 91)

        result = self.queries.query_cockpit_state({})

        self.assertTrue(result["telemetry"]["modules_available"])
        self.assertTrue(result["telemetry"]["modules_health_available"])
        self.assertEqual(result["telemetry"]["module_source"], "journal_loadout")
        self.assertEqual(result["telemetry"]["module_power_capacity_mw"], 30.0)
        self.assertEqual(result["telemetry"]["module_power_usage_percent"], 87)
        self.assertEqual(result["telemetry"]["module_power_percent_basis"], "estimated_next_5mw")
        self.assertEqual(result["telemetry"]["module_count"], 1)
        self.assertEqual(result["telemetry"]["hull_percent"], 91)
        self.assertEqual(result["telemetry"]["modules"], modules)

    def test_query_cockpit_state_uses_journal_fighter_active_as_vehicle_fallback(self) -> None:
        self._set_state("ed.running", True)
        self._set_state("ed.status.in_fighter", False)
        self._set_state("ed.fighter.active", True)
        self._set_state("ed.fighter.model", "taipan")
        self._set_state("ed.fighter.model_localised", "Taipan")

        result = self.queries.query_cockpit_state({})

        self.assertEqual(result["telemetry"]["active_vehicle"], "fighter")
        self.assertTrue(result["telemetry"]["in_fighter"])
        self.assertEqual(result["telemetry"]["fighter"]["model"], "taipan")

    def test_query_cockpit_state_includes_srv_surface_fields(self) -> None:
        self._set_state("ed.running", True)
        self._set_state("ed.srv.active", True)
        self._set_state("ed.srv.model", "testbuggy")
        self._set_state("ed.status.latitude", 12.3456)
        self._set_state("ed.status.longitude", -65.4321)
        self._set_state("ed.status.altitude", 123)
        self._set_state("ed.status.heading", 271)

        result = self.queries.query_cockpit_state({})

        self.assertEqual(result["telemetry"]["active_vehicle"], "srv")
        self.assertTrue(result["telemetry"]["in_srv"])
        self.assertEqual(result["telemetry"]["srv"]["model"], "testbuggy")
        self.assertEqual(result["telemetry"]["latitude"], 12.3456)
        self.assertEqual(result["telemetry"]["heading"], 271)

    def test_query_cockpit_state_reports_planetary_flight_status(self) -> None:
        self._set_state("ed.running", True)
        self._set_state("ed.status.has_lat_long", True)
        self._set_state("ed.status.supercruise", True)
        self._set_state("ed.status.body_name", "Puppis Sector ON-T b3-5 1")
        self._set_state("ed.status.latitude", 1.23)
        self._set_state("ed.status.longitude", 4.56)
        self._set_state("ed.status.altitude", 110000)

        result = self.queries.query_cockpit_state({})

        self.assertEqual(result["telemetry"]["planetary_status"], "OC")
        self.assertTrue(result["telemetry"]["has_lat_long"])
        self.assertEqual(result["telemetry"]["body"], "Puppis Sector ON-T b3-5 1")

    def test_query_cockpit_state_reports_on_foot_suit_context(self) -> None:
        self._set_state("ed.running", True)
        self._set_state("ed.status.on_foot", True)
        self._set_state("ed.status.on_foot_on_planet", True)
        self._set_state("ed.status.selected_weapon_localised", "TK Aphelion")
        self._set_state("ed.status.low_oxygen", True)
        self._set_state("ed.suit.name_localised", "Dominator Suit")
        self._set_state("ed.suit.loadout_name", "Ground Combat")

        result = self.queries.query_cockpit_state({})

        self.assertEqual(result["telemetry"]["active_vehicle"], "foot")
        self.assertTrue(result["telemetry"]["on_foot_on_planet"])
        self.assertEqual(result["telemetry"]["planetary_status"], "On Foot")
        self.assertEqual(result["telemetry"]["suit"]["name_localised"], "Dominator Suit")
        self.assertEqual(result["telemetry"]["suit"]["selected_weapon_localised"], "TK Aphelion")
        self.assertTrue(result["telemetry"]["suit"]["low_oxygen"])

    def test_query_cockpit_state_contextual_docking_button_requests_in_no_fire_zone(self) -> None:
        self._set_state("ed.running", True)
        self._set_state("ed.status.docked", False)
        self._set_state("ed.semantic.station.no_fire_zone", True)
        self._set_state("ed.semantic.opportunity.can_request_docking", True)
        self._set_state("ed.semantic.target.target_type", "station")

        result = self.queries.query_cockpit_state({})

        self.assertTrue(result["semantic"]["no_fire_zone"])
        suggestion = next(
            item for item in result["suggestions"] if item["id"] == "single_press_request_docking"
        )
        action = suggestion["cockpit_action_intent"]["recommended_action"]
        self.assertEqual(action["action"], "request_docking")

    def test_query_cockpit_state_allows_docking_button_from_no_fire_zone_only(self) -> None:
        self._set_state("ed.running", True)
        self._set_state("ed.status.docked", False)
        self._set_state("ed.semantic.station.no_fire_zone", True)
        self._set_state("ed.semantic.opportunity.can_request_docking", False)
        self._set_state("ed.semantic.target.target_type", "none")
        self._set_state("ed.semantic.flight.flight_status", "normal_space")
        self._set_state("ed.semantic.docking.docking_state", "not_docking")

        result = self.queries.query_cockpit_state({})

        self.assertTrue(result["semantic"]["no_fire_zone"])
        suggestion = next(
            item for item in result["suggestions"] if item["id"] == "single_press_request_docking"
        )
        action = suggestion["cockpit_action_intent"]["recommended_action"]
        self.assertEqual(action["action"], "request_docking")

    def test_query_cockpit_state_hides_docking_button_after_approval(self) -> None:
        self._set_state("ed.running", True)
        self._set_state("ed.status.docked", False)
        self._set_state("ed.station.no_fire_zone", True)
        self._set_state("ed.station.docking_state", "granted")
        self._set_state("ed.semantic.opportunity.can_request_docking", False)
        self._set_state("ed.semantic.flight.flight_status", "normal_space")

        result = self.queries.query_cockpit_state({})

        self.assertEqual(result["semantic"]["docking_state"], "granted")
        self.assertFalse(
            any(item["id"] == "single_press_request_docking" for item in result["suggestions"])
        )

    def test_query_cockpit_state_contextual_docking_button_launches_when_docked(self) -> None:
        self._set_state("ed.running", True)
        self._set_state("ed.status.docked", True)
        self._set_state("ed.semantic.opportunity.station_services_available", True)

        result = self.queries.query_cockpit_state({})

        launch = next(
            item for item in result["suggestions"] if item["id"] == "single_press_auto_launch"
        )
        service = next(
            item for item in result["suggestions"] if item["id"] == "post_dock_repair_refuel"
        )
        self.assertEqual(launch["cockpit_action_intent"]["recommended_action"]["action"], "auto_launch")
        self.assertEqual(service["cockpit_action_intent"]["recommended_action"]["action"], "repair_refuel")

    def test_cockpit_state_endpoint(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.handlers.BrainstemHandler)
        port = int(server.server_address[1])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/cockpit/state", timeout=8) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/mfd/state", timeout=8) as resp:
                mfd_payload = json.loads(resp.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
        self.assertTrue(payload["ok"])
        self.assertIn("telemetry", payload)
        self.assertIn("suggestions", payload)
        self.assertTrue(mfd_payload["ok"])
        self.assertIn("telemetry", mfd_payload)

    def test_cockpit_control_endpoint_queues_policy_gated_keypress(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.handlers.BrainstemHandler)
        port = int(server.server_address[1])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(
                self.actions,
                "_get_foreground_process_name",
                return_value="EliteDangerous64.exe",
            ):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/cockpit/control",
                    data=json.dumps({"action": "landing_gear", "dry_run": False}).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "landing_gear")
        self.assertEqual(payload["key"], "l")
        self.assertEqual(payload["execute"]["results"][0]["status"], "success")
        self.assertEqual(self._keypress_log_entries()[-1]["parameters"]["sequence"][0]["key"], "l")

    def test_cockpit_lights_control_uses_alt_t_binding(self) -> None:
        with mock.patch.object(
            self.actions,
            "_get_foreground_process_name",
            return_value="EliteDangerous64.exe",
        ):
            payload = self.actions.cockpit_control_action(
                {"action": "lights", "dry_run": False},
                source="test",
            )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["key"], "alt+t")
        self.assertEqual(payload["execute"]["results"][0]["status"], "success")
        self.assertEqual(self._keypress_log_entries()[-1]["parameters"]["sequence"][0]["key"], "alt+t")

    def test_cockpit_panel_controls_use_number_bindings(self) -> None:
        expected = {
            "nav_panel": "1",
            "comms_panel": "2",
            "role_panel": "3",
            "management_panel": "4",
            "galaxy_map": "ctrl+g",
            "system_map": "alt+s",
            "fss": "f5",
            "flight_control": "esc",
            "cockpit_mode": "m",
            "flight_assist": "z",
            "night_vision": "alt+n",
            "supercruise": "j",
            "hyperspace": "j",
        }
        with mock.patch.object(
            self.actions,
            "_get_foreground_process_name",
            return_value="EliteDangerous64.exe",
        ):
            for action, key in expected.items():
                with self.subTest(action=action):
                    payload = self.actions.cockpit_control_action(
                        {"action": action, "dry_run": False},
                        source="test",
                    )
                    self.assertTrue(payload["ok"])
                    self.assertEqual(payload["key"], key)
                    self.assertEqual(payload["execute"]["results"][0]["status"], "success")
                    self.assertEqual(self._keypress_log_entries()[-1]["parameters"]["sequence"][0]["key"], key)

    def test_cockpit_auto_dock_dry_run_exposes_macro_sequence(self) -> None:
        payload = self.actions.cockpit_control_action(
            {"action": "auto_dock", "dry_run": True},
            source="test",
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "auto_dock")
        self.assertEqual(payload["execute"]["results"][0]["status"], "dry_run")
        steps = payload["sequence"]["steps"]
        self.assertEqual(steps[0]["key"], "1")
        self.assertEqual(steps[-1]["key"], "1")
        self.assertIn({"key": "space", "at_ms": 2250, "hold_ms": 200}, steps)

    def test_cockpit_auto_dock_requires_no_fire_zone_when_live(self) -> None:
        with self.assertRaises(ValueError):
            self.actions.cockpit_control_action(
                {"action": "auto_dock", "dry_run": False},
                source="test",
            )

    def test_cockpit_auto_launch_warns_once_when_limpets_missing(self) -> None:
        self._set_state("ed.status.docked", True)
        self._set_state(
            "ed.modules.items",
            [
                {"slot": "Slot01_Size7", "item": "int_cargorack_size6_class1"},
                {"slot": "Slot07_Size5", "item": "int_dronecontrol_collection_size5_class5"},
            ],
        )
        self._set_state("ed.cargo.limpet_count", 0)

        payload = self.actions.cockpit_control_action(
            {"action": "auto_launch", "dry_run": False},
            source="test",
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["execute"]["results"][0]["status"], "warning")
        self.assertEqual(payload["warning"]["code"], "missing_limpets")
        warning_state = self.runtime.DB_SERVICE.get_state("ed.autolaunch.limpet_warning_active")
        self.assertTrue(warning_state["state_value"])

    def test_cockpit_auto_launch_dry_run_exposes_sequence(self) -> None:
        payload = self.actions.cockpit_control_action(
            {"action": "auto_launch", "dry_run": True},
            source="test",
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "auto_launch")
        self.assertEqual([step["key"] for step in payload["sequence"]["steps"]], ["w", "w", "s", "s", "space"])

    def test_ahk_key_translation_supports_lights_combo(self) -> None:
        self.assertEqual(self.actions._key_to_ahk_send("alt+t"), "!t")
        self.assertEqual(self.actions._key_to_ahk_send("f10"), "{F10}")

    def test_ahk_backend_runs_one_shot_sender(self) -> None:
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(self.actions, "_resolve_ahk_exe", return_value="C:\\AutoHotkey.exe"):
            with mock.patch.object(self.actions.subprocess, "run", return_value=completed) as run_mock:
                result = self.actions._send_key_combo_ahk("alt+t")
        self.assertEqual(result["backend"], "ahk")
        self.assertEqual(result["send"], "!t")
        args = run_mock.call_args.args[0]
        self.assertEqual(args[0], "C:\\AutoHotkey.exe")
        self.assertTrue(str(args[1]).endswith(".ahk"))


if __name__ == "__main__":
    unittest.main()
