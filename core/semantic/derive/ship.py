from __future__ import annotations

from ..config import SEMANTIC_CONFIG


def derive_heat_state(raw, _sem, _now_ms: int):
    status = raw.get_status() or {}
    try:
        heat = float(status.get("Heat"))
    except Exception:
        heat = None

    if heat is None:
        return {"type": "enum", "value": "normal", "confidence": "unknown", "derived_from": ["Status.Heat"]}

    thresholds = SEMANTIC_CONFIG["HEAT_THRESHOLDS"]
    if heat < thresholds["NORMAL_MAX"]:
        return _heat_out("normal")
    if heat < thresholds["WARM_MAX"]:
        return _heat_out("warm")
    if heat < thresholds["HOT_MAX"]:
        return _heat_out("hot")
    if heat < thresholds["OVERHEATING_MAX"]:
        return _heat_out("overheating")
    return _heat_out("critical")


def derive_fuel_state(raw, _sem, _now_ms: int):
    status = raw.get_status() or {}
    fuel = status.get("Fuel")
    fuel_main = _number_or_none(status.get("FuelMain", fuel.get("FuelMain") if isinstance(fuel, dict) else fuel))
    fuel_res = _number_or_none(status.get("FuelReservoir", fuel.get("FuelReservoir") if isinstance(fuel, dict) else None))

    if fuel_main is None and fuel_res is None:
        return {"type": "enum", "value": "unknown", "confidence": "unknown", "derived_from": ["Status.Fuel*"]}

    total = (fuel_main or 0.0) + (fuel_res or 0.0)
    if total <= 0.0001:
        return _fuel_out("out_of_fuel")

    capacity = _number_or_none(status.get("FuelCapacity", fuel.get("FuelCapacity") if isinstance(fuel, dict) else None))
    fraction = (total / capacity) if capacity and capacity > 0 else None
    if fraction is not None and fraction < SEMANTIC_CONFIG["FUEL_LOW_THRESHOLD_FRACTION"]:
        return _fuel_out("low")
    if fraction is None and fuel_main is not None and fuel_main < 2:
        return _fuel_out("low")

    next_leg_cost = _number_or_none(raw.get_raw_value("NavRoute.NextLegCost"))
    if next_leg_cost is not None and fuel_main is not None and fuel_main < next_leg_cost:
        return _fuel_out("critical")
    return _fuel_out("ok")


def derive_integrity_state(raw, _sem, _now_ms: int):
    status = raw.get_status() or {}
    hull = _number_or_none(status.get("Hull", status.get("HullHealth")))
    if hull is None:
        return {"type": "enum", "value": "unknown", "confidence": "unknown", "derived_from": ["Status.Hull*"]}

    pct = hull * 100 if hull <= 1.0 else hull
    if pct >= 70:
        return _hull_out("healthy")
    if pct >= 30:
        return _hull_out("damaged")
    return _hull_out("critical")


def _number_or_none(value):
    try:
        number = float(value)
    except Exception:
        return None
    return number if number == number else None


def _heat_out(value: str) -> dict[str, object]:
    return {"type": "enum", "value": value, "confidence": "certain", "derived_from": ["Status.Heat"]}


def _fuel_out(value: str) -> dict[str, object]:
    return {"type": "enum", "value": value, "confidence": "best_effort", "derived_from": ["Status.Fuel*"]}


def _hull_out(value: str) -> dict[str, object]:
    return {"type": "enum", "value": value, "confidence": "best_effort", "derived_from": ["Status.Hull*"]}
