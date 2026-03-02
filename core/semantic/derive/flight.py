from __future__ import annotations

from ..config import SEMANTIC_CONFIG
from ..util import get_path, ms_since, truthy


def derive_flight_status(raw, _sem, now_ms: int):
    status = raw.get_status() or {}

    died = raw.get_last_journal_event_of(["Died", "ShipDestroyed"])
    if died and ms_since(now_ms, died["timestampMs"]) < 60000:
        return {"type": "enum", "value": "dead", "confidence": "certain", "derived_from": [f"Journal.{died['event']}"]}

    if truthy(get_path(status, "Flags.Docked")):
        return _out("docked", ["Status.Flags.Docked"])
    if truthy(get_path(status, "Flags.Landed")):
        return _out("landed", ["Status.Flags.Landed"])
    if truthy(get_path(status, "Flags.GlideMode")):
        return _out("glide", ["Status.Flags.GlideMode"])
    if truthy(get_path(status, "Flags.InHyperspace")):
        return _out("witch_space", ["Status.Flags.InHyperspace"])
    if truthy(get_path(status, "Flags.Supercruise")):
        return _out("supercruise", ["Status.Flags.Supercruise"])

    start_jump = raw.get_last_journal_event("StartJump")
    if start_jump and ms_since(now_ms, start_jump["timestampMs"]) <= SEMANTIC_CONFIG["FSD_CHARGE_WINDOW_MS"]:
        completed = raw.get_last_journal_event_of(["FSDJump", "SupercruiseEntry"])
        if not completed or completed["timestampMs"] < start_jump["timestampMs"]:
            return _out("witch_space", ["Journal.StartJump"])

    if raw.get_status_updated_at():
        return _out("normal_space", ["Status.Flags"])
    return {"type": "enum", "value": "unknown", "confidence": "unknown", "derived_from": ["Status.Flags"]}


def derive_fsd_state(raw, _sem, now_ms: int):
    status = raw.get_status() or {}

    if truthy(get_path(status, "Flags.InHyperspace")):
        return _out("hyperspace", ["Status.Flags.InHyperspace"])
    if truthy(get_path(status, "Flags.Supercruise")):
        return _out("supercruise", ["Status.Flags.Supercruise"])

    start_jump = raw.get_last_journal_event("StartJump")
    if start_jump and ms_since(now_ms, start_jump["timestampMs"]) <= SEMANTIC_CONFIG["FSD_CHARGE_WINDOW_MS"]:
        completion = raw.get_last_journal_event_of(["FSDJump", "SupercruiseEntry"])
        completed = completion and completion["timestampMs"] >= start_jump["timestampMs"]
        if not completed:
            return _out("charging", ["Journal.StartJump"])

    fsd_jump = raw.get_last_journal_event("FSDJump")
    if fsd_jump and ms_since(now_ms, fsd_jump["timestampMs"]) <= SEMANTIC_CONFIG["FSD_COOLDOWN_MS"]:
        return _out("cooldown", ["Journal.FSDJump"])

    mass_locked = truthy(get_path(status, "Flags.MassLocked"))
    if mass_locked and start_jump and ms_since(now_ms, start_jump["timestampMs"]) <= SEMANTIC_CONFIG["FSD_CHARGE_WINDOW_MS"]:
        return {"type": "enum", "value": "inhibited", "confidence": "best_effort", "derived_from": ["Status.Flags.MassLocked", "Journal.StartJump"]}

    return _out("idle", ["Status.Flags"])


def _out(value: str, deps: list[str]) -> dict[str, object]:
    return {"type": "enum", "value": value, "confidence": "certain", "derived_from": deps}
