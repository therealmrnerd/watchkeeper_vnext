from __future__ import annotations

STATIONISH_TOKENS = (
    "hub",
    "station",
    "outpost",
    "port",
    "terminal",
    "base",
    "dock",
    "starport",
    "installation",
    "settlement",
    "carrier",
    "cove",
)


def derive_can_request_docking(raw, sem, _now_ms: int):
    flight = _semantic_value(sem, "ed.semantic.flight.flight_status")
    docking = _semantic_value(sem, "ed.semantic.docking.docking_state")
    combat = _semantic_value(sem, "ed.semantic.combat.combat_state")
    risk = _semantic_value(sem, "ed.semantic.risk.risk_level")
    target = _semantic_value(sem, "ed.semantic.target.target_type")
    no_fire_zone = _semantic_value(sem, "ed.semantic.station.no_fire_zone")
    destination_name = str(raw.get_raw_value("ed.telemetry.destination_name") or "").strip()
    destination_body_type = str(raw.get_raw_value("ed.telemetry.destination_body_type") or "").strip().lower()
    station_approach = bool(
        no_fire_zone is True
        or (
            destination_name
            and (
                target in {"station", "outpost", "fleet_carrier"}
                or destination_body_type in {"station", "outpost", "fleetcarrier", "fleet_carrier"}
                or any(token in destination_name.lower() for token in STATIONISH_TOKENS)
            )
        )
    )

    value = (
        flight in {"normal_space", "planetary_flight"}
        and docking in {"not_docking", "can_request"}
        and combat == "idle"
        and risk != "red"
        and station_approach
        and no_fire_zone is True
    )
    return {
        "type": "boolean",
        "value": bool(value),
        "confidence": "best_effort",
        "derived_from": [
            "ed.semantic.flight.flight_status",
            "ed.semantic.docking.docking_state",
            "ed.semantic.combat.combat_state",
            "ed.semantic.risk.risk_level",
            "ed.semantic.target.target_type",
            "ed.semantic.station.no_fire_zone",
            "ed.telemetry.destination_name",
            "ed.telemetry.destination_body_type",
        ],
    }


def derive_station_no_fire_zone(raw, _sem, _now_ms: int):
    value = raw.get_raw_value("ed.station.no_fire_zone")
    return {
        "type": "boolean",
        "value": bool(value),
        "confidence": "event_derived" if value is not None else "unknown",
        "derived_from": [
            "Journal.ReceiveText.STATION_NoFireZone_entered",
            "Journal.ReceiveText.STATION_NoFireZone_exited",
            "Journal.Docked",
            "Journal.FSDJump",
            "Journal.SupercruiseEntry",
        ],
    }


def derive_station_services_available(_raw, sem, _now_ms: int):
    player_platform = sem.get("ed.semantic.context.player_platform")
    on_foot_area = sem.get("ed.semantic.context.on_foot_area")
    flight_status = sem.get("ed.semantic.flight.flight_status")
    docking_state = sem.get("ed.semantic.docking.docking_state")

    platform_value = player_platform.value if player_platform else None
    on_foot_area_value = on_foot_area.value if on_foot_area else None
    flight_value = flight_status.value if flight_status else None
    docking_value = docking_state.value if docking_state else None

    value = bool(
        flight_value == "docked"
        or docking_value == "docked"
        or (platform_value == "on_foot" and on_foot_area_value == "station")
    )

    return {
        "type": "boolean",
        "value": value,
        "confidence": "best_effort",
        "derived_from": [
            "ed.semantic.context.player_platform",
            "ed.semantic.context.on_foot_area",
            "ed.semantic.flight.flight_status",
            "ed.semantic.docking.docking_state",
        ],
    }


def derive_market_access_available(_raw, sem, _now_ms: int):
    services = sem.get("ed.semantic.opportunity.station_services_available")
    value = bool(services.value) if services is not None else False
    return {
        "type": "boolean",
        "value": value,
        "confidence": "best_effort",
        "derived_from": ["ed.semantic.opportunity.station_services_available"],
    }


def derive_safe_for_keypress(_raw, sem, _now_ms: int):
    online = _semantic_value(sem, "ed.semantic.session.online_state")
    flight = _semantic_value(sem, "ed.semantic.flight.flight_status")
    fsd = _semantic_value(sem, "ed.semantic.flight.fsd_state")
    combat = _semantic_value(sem, "ed.semantic.combat.combat_state")
    risk = _semantic_value(sem, "ed.semantic.risk.risk_level")

    value = (
        online == "in_game"
        and flight != "dead"
        and fsd not in {"charging", "hyperspace"}
        and combat not in {"under_attack", "interdiction", "engaged"}
        and risk != "red"
    )
    return {
        "type": "boolean",
        "value": bool(value),
        "confidence": "best_effort",
        "derived_from": [
            "ed.semantic.session.online_state",
            "ed.semantic.flight.flight_status",
            "ed.semantic.flight.fsd_state",
            "ed.semantic.combat.combat_state",
            "ed.semantic.risk.risk_level",
        ],
    }


def _semantic_value(sem, key: str):
    record = sem.get(key)
    return record.value if record else None
