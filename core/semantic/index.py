from __future__ import annotations

from pathlib import Path

from .derive.combat import derive_combat_state
from .derive.context import derive_on_foot_area, derive_player_platform, derive_primary_mode
from .derive.docking import derive_docking_state
from .derive.flight import derive_flight_status, derive_fsd_state
from .derive.interface import derive_control_profile
from .derive.landing import derive_landing_state
from .derive.opportunity import (
    derive_can_request_docking,
    derive_market_access_available,
    derive_safe_for_keypress,
    derive_station_no_fire_zone,
    derive_station_services_available,
)
from .derive.risk import derive_primary_risk, derive_risk_level
from .derive.session import derive_online_state
from .derive.ship import derive_fuel_state, derive_heat_state, derive_integrity_state
from .derive.target import derive_target_type
from .engine import SemanticEngine


def create_semantic_engine(raw, sem) -> SemanticEngine:
    catalog_path = Path(__file__).with_name("catalog.json")
    engine = SemanticEngine(raw, sem, catalog_path)

    engine.register("ed.semantic.session.online_state", derive_online_state)
    engine.register("ed.semantic.context.primary_mode", derive_primary_mode)
    engine.register("ed.semantic.context.player_platform", derive_player_platform)
    engine.register("ed.semantic.context.on_foot_area", derive_on_foot_area)
    engine.register("ed.semantic.flight.flight_status", derive_flight_status)
    engine.register("ed.semantic.flight.fsd_state", derive_fsd_state)
    engine.register("ed.semantic.docking.docking_state", derive_docking_state)
    engine.register("ed.semantic.landing.landing_state", derive_landing_state)
    engine.register("ed.semantic.combat.combat_state", derive_combat_state)
    engine.register("ed.semantic.ship.heat_state", derive_heat_state)
    engine.register("ed.semantic.ship.fuel_state", derive_fuel_state)
    engine.register("ed.semantic.ship.integrity_state", derive_integrity_state)
    engine.register("ed.semantic.target.target_type", derive_target_type)
    engine.register("ed.semantic.risk.risk_level", derive_risk_level)
    engine.register("ed.semantic.risk.primary_risk", derive_primary_risk)
    engine.register("ed.semantic.station.no_fire_zone", derive_station_no_fire_zone)
    engine.register("ed.semantic.opportunity.can_request_docking", derive_can_request_docking)
    engine.register("ed.semantic.opportunity.station_services_available", derive_station_services_available)
    engine.register("ed.semantic.opportunity.market_access_available", derive_market_access_available)
    engine.register("ed.semantic.interaction.safe_for_keypress", derive_safe_for_keypress)
    engine.register("ed.semantic.interface.control_profile", derive_control_profile)

    return engine
