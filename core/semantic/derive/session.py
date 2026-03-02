from __future__ import annotations

from ..config import SEMANTIC_CONFIG
from ..util import is_fresh, ms_since


def derive_online_state(raw, _sem, now_ms: int):
    status_updated_at = raw.get_status_updated_at()
    fresh = is_fresh(now_ms, status_updated_at, SEMANTIC_CONFIG["OFFLINE_TIMEOUT_MS"])

    if not fresh:
        return {"type": "enum", "value": "offline", "confidence": "certain", "derived_from": ["Status.$fresh"]}

    last_shutdown = raw.get_last_journal_event("Shutdown")
    if last_shutdown and ms_since(now_ms, last_shutdown["timestampMs"]) < SEMANTIC_CONFIG["OFFLINE_TIMEOUT_MS"]:
        return {"type": "enum", "value": "offline", "confidence": "certain", "derived_from": ["Journal.Shutdown"]}

    last_load = raw.get_last_journal_event("LoadGame")
    recent_load = last_load and ms_since(now_ms, last_load["timestampMs"]) <= SEMANTIC_CONFIG["LOADING_WINDOW_MS"]
    if recent_load:
        anchor = raw.get_last_journal_event_of(["Location", "FSDJump", "Docked", "Undocked"])
        anchor_after_load = anchor and anchor["timestampMs"] >= last_load["timestampMs"]
        if not anchor_after_load:
            return {"type": "enum", "value": "loading", "confidence": "best_effort", "derived_from": ["Journal.LoadGame"]}

    return {"type": "enum", "value": "in_game", "confidence": "best_effort", "derived_from": ["Status.$fresh"]}
