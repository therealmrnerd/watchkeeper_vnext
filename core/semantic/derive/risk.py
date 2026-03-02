from __future__ import annotations


def derive_risk_level(_raw, sem, _now_ms: int):
    heat = _semantic_value(sem, "ed.semantic.ship.heat_state")
    fuel = _semantic_value(sem, "ed.semantic.ship.fuel_state")
    integrity = _semantic_value(sem, "ed.semantic.ship.integrity_state")
    combat = _semantic_value(sem, "ed.semantic.combat.combat_state")

    if heat in {"overheating", "critical"} or fuel == "out_of_fuel" or integrity == "critical":
        return _out("red", ["ed.semantic.ship.*", "ed.semantic.combat.combat_state"])
    if combat in {"under_attack", "interdiction", "engaged"} or fuel == "critical":
        return _out("orange", ["ed.semantic.ship.*", "ed.semantic.combat.combat_state"])
    if heat == "hot" or integrity == "damaged" or fuel == "low":
        return _out("yellow", ["ed.semantic.ship.*"])
    return _out("green", ["ed.semantic.ship.*"])


def derive_primary_risk(_raw, sem, _now_ms: int):
    heat = _semantic_value(sem, "ed.semantic.ship.heat_state")
    fuel = _semantic_value(sem, "ed.semantic.ship.fuel_state")
    integrity = _semantic_value(sem, "ed.semantic.ship.integrity_state")
    combat = _semantic_value(sem, "ed.semantic.combat.combat_state")
    landing = _semantic_value(sem, "ed.semantic.landing.landing_state")

    if heat in {"overheating", "critical"}:
        return _out("heat")
    if fuel in {"out_of_fuel", "critical"}:
        return _out("fuel")
    if integrity == "critical":
        return _out("hull")
    if combat == "interdiction":
        return _out("interdiction")
    if combat in {"under_attack", "engaged"}:
        return _out("piracy")
    if landing in {"glide", "landing"}:
        return _out("landing")
    return _out("none")


def _semantic_value(sem, key: str):
    record = sem.get(key)
    return record.value if record else None


def _out(value: str, deps: list[str] | None = None) -> dict[str, object]:
    return {"type": "enum", "value": value, "confidence": "best_effort", "derived_from": deps or ["ed.semantic.*"]}
