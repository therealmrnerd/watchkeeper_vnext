from __future__ import annotations

from ..util import looks_like_fleet_carrier_callsign


def derive_target_type(raw, _sem, _now_ms: int):
    status = raw.get_status() or {}
    target = status.get("Target")
    if not target:
        return {"type": "enum", "value": "none", "confidence": "best_effort", "derived_from": ["Status.Target"]}

    explicit_type = target.get("Type") or target.get("TargetType") or target.get("Kind")
    if isinstance(explicit_type, str) and explicit_type:
        mapped = _map_explicit(explicit_type)
        if mapped:
            return _out(mapped, ["Status.Target.Type"])

    name = str(target.get("Name") or target.get("TargetName") or "").strip()
    if name:
        if looks_like_fleet_carrier_callsign(name):
            return _out("fleet_carrier", ["Status.Target.Name"])
        if "signal source" in name.lower():
            return _out("signal_source", ["Status.Target.Name"])
        if "nav beacon" in name.lower():
            return _out("nav_beacon", ["Status.Target.Name"])

    return {"type": "enum", "value": "unknown", "confidence": "unknown", "derived_from": ["Status.Target"]}


def _out(value: str, deps: list[str]) -> dict[str, object]:
    return {"type": "enum", "value": value, "confidence": "best_effort", "derived_from": deps}


def _map_explicit(target_type: str) -> str | None:
    value = target_type.lower()
    if "ship" in value:
        return "ship"
    if "fleetcarrier" in value or "carrier" in value:
        return "fleet_carrier"
    if "station" in value:
        return "station"
    if "outpost" in value:
        return "outpost"
    if "settlement" in value:
        return "settlement"
    if "asteroid" in value:
        return "asteroid"
    if "star" in value:
        return "star"
    if "planet" in value:
        return "planet"
    if "moon" in value:
        return "moon"
    if "signal" in value:
        return "signal_source"
    if "navbeacon" in value or "nav beacon" in value:
        return "nav_beacon"
    return None
