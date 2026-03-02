from __future__ import annotations

from ..config import SEMANTIC_CONFIG
from ..util import get_path, ms_since, truthy


def derive_landing_state(raw, _sem, now_ms: int):
    status = raw.get_status() or {}

    if truthy(get_path(status, "Flags.Landed")):
        return _out("landed", ["Status.Flags.Landed"])

    touchdown = raw.get_last_journal_event("Touchdown")
    if touchdown and ms_since(now_ms, touchdown["timestampMs"]) <= 60_000:
        return _out("landed", ["Journal.Touchdown"])

    liftoff = raw.get_last_journal_event("Liftoff")
    if liftoff and ms_since(now_ms, liftoff["timestampMs"]) <= SEMANTIC_CONFIG["TAKEOFF_WINDOW_MS"]:
        return _out("taking_off", ["Journal.Liftoff"])

    if truthy(get_path(status, "Flags.GlideMode")):
        return _out("glide", ["Status.Flags.GlideMode"])
    if truthy(get_path(status, "Flags.HasLatLong")):
        return _out("near_surface", ["Status.Flags.HasLatLong"])

    exited_orbital = raw.get_last_journal_event("ExitOrbitalCruise")
    if exited_orbital and ms_since(now_ms, exited_orbital["timestampMs"]) <= 5 * 60_000:
        return _out("descending", ["Journal.ExitOrbitalCruise"])

    return _out("in_space", ["Status.Flags"])


def _out(value: str, deps: list[str]) -> dict[str, object]:
    return {"type": "enum", "value": value, "confidence": "best_effort", "derived_from": deps}
