from __future__ import annotations


def derive_control_profile(_raw, sem, _now_ms: int):
    player_platform = sem.get("ed.semantic.context.player_platform")
    on_foot_area = sem.get("ed.semantic.context.on_foot_area")

    platform_value = player_platform.value if player_platform else None
    on_foot_area_value = on_foot_area.value if on_foot_area else None

    if platform_value == "ship":
        value = "ship"
    elif platform_value == "srv":
        value = "srv"
    elif platform_value == "on_foot":
        if on_foot_area_value == "station":
            value = "on_foot_station"
        elif on_foot_area_value in {"planet_surface", "settlement"}:
            value = "on_foot_surface"
        else:
            value = "unknown"
    else:
        value = "unknown"

    return {
        "type": "enum",
        "value": value,
        "confidence": "best_effort",
        "derived_from": [
            "ed.semantic.context.player_platform",
            "ed.semantic.context.on_foot_area",
        ],
    }
