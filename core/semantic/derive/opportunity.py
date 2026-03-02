from __future__ import annotations


def derive_can_request_docking(_raw, sem, _now_ms: int):
    flight = _semantic_value(sem, "ed.semantic.flight.flight_status")
    docking = _semantic_value(sem, "ed.semantic.docking.docking_state")
    combat = _semantic_value(sem, "ed.semantic.combat.combat_state")
    risk = _semantic_value(sem, "ed.semantic.risk.risk_level")
    target = _semantic_value(sem, "ed.semantic.target.target_type")

    value = (
        flight in {"normal_space", "supercruise"}
        and docking in {"not_docking", "can_request"}
        and combat == "idle"
        and risk != "red"
        and target in {"station", "outpost", "fleet_carrier"}
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
        ],
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
