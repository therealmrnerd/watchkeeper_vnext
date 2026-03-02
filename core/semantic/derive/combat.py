from __future__ import annotations

from ..util import get_path, truthy


def derive_combat_state(raw, _sem, _now_ms: int):
    status = raw.get_status() or {}

    if truthy(get_path(status, "Flags.BeingInterdicted")):
        return _out("interdiction", ["Status.Flags.BeingInterdicted"])

    last_interdiction = raw.get_last_journal_event_of(["Interdicted", "Interdiction"])
    if last_interdiction:
        return _out("interdiction", [f"Journal.{last_interdiction['event']}"])

    if truthy(get_path(status, "Flags.IsInDanger")):
        return _out("under_attack", ["Status.Flags.IsInDanger"])
    if truthy(get_path(status, "Flags.Firing")):
        return _out("weapons_firing", ["Status.Flags.Firing"])
    if truthy(get_path(status, "Flags.HardpointsDeployed")):
        return _out("hardpoints_deployed", ["Status.Flags.HardpointsDeployed"])
    return _out("idle", ["Status.Flags"])


def _out(value: str, deps: list[str]) -> dict[str, object]:
    return {"type": "enum", "value": value, "confidence": "best_effort", "derived_from": deps}
