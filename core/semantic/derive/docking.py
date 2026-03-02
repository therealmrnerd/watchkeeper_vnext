from __future__ import annotations

from ..config import SEMANTIC_CONFIG
from ..util import get_path, ms_since, truthy


def derive_docking_state(raw, _sem, now_ms: int):
    status = raw.get_status() or {}
    if truthy(get_path(status, "Flags.Docked")):
        return _out("docked", ["Status.Flags.Docked"])

    denied = raw.get_last_journal_event("DockingDenied")
    if denied and ms_since(now_ms, denied["timestampMs"]) <= SEMANTIC_CONFIG["DOCK_DENY_COOLDOWN_MS"]:
        return {"type": "enum", "value": "denied", "confidence": "certain", "derived_from": ["Journal.DockingDenied"]}

    requested = raw.get_last_journal_event("DockingRequested")
    if requested:
        granted = raw.get_last_journal_event("DockingGranted")
        deny = raw.get_last_journal_event("DockingDenied")
        cancel = raw.get_last_journal_event("DockingCancelled")
        resolved_ts = max(granted["timestampMs"] if granted else 0, deny["timestampMs"] if deny else 0, cancel["timestampMs"] if cancel else 0)
        if resolved_ts < requested["timestampMs"]:
            age = ms_since(now_ms, requested["timestampMs"])
            if age > SEMANTIC_CONFIG["DOCK_REQUEST_TIMEOUT_MS"]:
                return {"type": "enum", "value": "timeout", "confidence": "best_effort", "derived_from": ["Journal.DockingRequested"]}
            return {"type": "enum", "value": "requested", "confidence": "certain", "derived_from": ["Journal.DockingRequested"]}

    granted = raw.get_last_journal_event("DockingGranted")
    if granted and ms_since(now_ms, granted["timestampMs"]) <= 5 * 60_000:
        return {"type": "enum", "value": "granted", "confidence": "best_effort", "derived_from": ["Journal.DockingGranted"]}

    return _out("not_docking", ["Journal.Docking*"])


def _out(value: str, deps: list[str]) -> dict[str, object]:
    return {"type": "enum", "value": value, "confidence": "best_effort", "derived_from": deps}
