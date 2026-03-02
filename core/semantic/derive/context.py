from __future__ import annotations

from ..util import get_path, truthy


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
