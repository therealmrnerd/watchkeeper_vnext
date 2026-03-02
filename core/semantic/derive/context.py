from __future__ import annotations

from ..util import get_path, truthy


def derive_player_platform(raw, _sem, _now_ms: int):
    if raw.get_status_updated_at() is None:
        return {"type": "enum", "value": "unknown", "confidence": "unknown", "derived_from": ["Status.$fresh"]}

    status = raw.get_status() or {}
    on_foot = truthy(get_path(status, "Flags.OnFoot"))
    in_srv = truthy(get_path(status, "Flags.InSRV"))

    if on_foot:
        return _out("on_foot", ["Status.Flags.OnFoot"])
    if in_srv:
        return _out("srv", ["Status.Flags.InSRV"])
    return _out("ship", ["Status.Flags"])


def derive_on_foot_area(raw, _sem, _now_ms: int):
    if raw.get_status_updated_at() is None:
        return {"type": "enum", "value": "unknown", "confidence": "unknown", "derived_from": ["Status.$fresh"]}

    status = raw.get_status() or {}
    on_foot = truthy(get_path(status, "Flags.OnFoot"))
    if not on_foot:
        return _out("not_on_foot", ["Status.Flags.OnFoot"])

    location_hint = str(raw.get_raw_value("ed.telemetry.on_foot_location") or "").strip().lower()
    if location_hint:
        if "station" in location_hint or "hangar" in location_hint or "concourse" in location_hint:
            return _out("station", ["ed.telemetry.on_foot_location"])
        if "settlement" in location_hint or "base" in location_hint or "port" in location_hint:
            return _out("settlement", ["ed.telemetry.on_foot_location"])
        if "surface" in location_hint or "planet" in location_hint:
            return _out("planet_surface", ["ed.telemetry.on_foot_location"])

    docked = truthy(get_path(status, "Flags.Docked"))
    if docked:
        return _out("station", ["Status.Flags.Docked", "Status.Flags.OnFoot"])

    landed = truthy(get_path(status, "Flags.Landed"))
    has_lat_long = truthy(get_path(status, "Flags.HasLatLong"))
    if landed or has_lat_long:
        return _out("planet_surface", ["Status.Flags.Landed"] if landed else ["Status.Flags.HasLatLong"])

    return {"type": "enum", "value": "unknown", "confidence": "best_effort", "derived_from": ["Status.Flags.OnFoot"]}


def derive_primary_mode(raw, _sem, _now_ms: int):
    if raw.get_status_updated_at() is None:
        return {"type": "enum", "value": "unknown", "confidence": "unknown", "derived_from": ["Status.$fresh"]}

    status = raw.get_status() or {}

    on_foot = truthy(get_path(status, "Flags.OnFoot"))
    in_srv = truthy(get_path(status, "Flags.InSRV"))
    docked = truthy(get_path(status, "Flags.Docked"))
    landed = truthy(get_path(status, "Flags.Landed"))
    supercruise = truthy(get_path(status, "Flags.Supercruise"))
    hyperspace = truthy(get_path(status, "Flags.InHyperspace"))
    has_lat_long = truthy(get_path(status, "Flags.HasLatLong"))

    if on_foot:
        return _out("on_foot", ["Status.Flags.OnFoot"])
    if in_srv:
        return _out("srv", ["Status.Flags.InSRV"])
    if hyperspace:
        return _out("hyperspace", ["Status.Flags.InHyperspace"])
    if supercruise:
        return _out("supercruise", ["Status.Flags.Supercruise"])
    if docked:
        return _out("hangar", ["Status.Flags.Docked"])
    if landed or has_lat_long:
        return _out("planetary", ["Status.Flags.Landed"] if landed else ["Status.Flags.HasLatLong"])
    return _out("space", ["Status.Flags"])


def _out(value: str, deps: list[str]) -> dict[str, object]:
    return {"type": "enum", "value": value, "confidence": "certain", "derived_from": deps}
