from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from .index import create_semantic_engine
from .types import SemanticStateRecord


class TelemetryRawStore:
    def __init__(self, values: dict[str, Any], now_ms: int | None = None) -> None:
        self.values = dict(values)
        self._now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        self.status = self._build_status()

    def now_ms(self) -> int:
        return self._now_ms

    def get_status(self) -> dict[str, Any] | None:
        return self.status

    def get_status_updated_at(self) -> int | None:
        return self._now_ms if bool(self.values.get("ed.running")) else None

    def get_last_journal_event(self, event: str) -> dict[str, Any] | None:
        return None

    def get_last_journal_event_of(self, events: list[str]) -> dict[str, Any] | None:
        return None

    def get_raw_value(self, path: str) -> Any:
        if path == "NavRoute.NextLegCost":
            return self.values.get("ed.telemetry.navroute_next_leg_cost")
        return self.values.get(path)

    def _build_status(self) -> dict[str, Any]:
        running = bool(self.values.get("ed.running"))
        if not running:
            return {}

        return {
            "Flags": {
                "Docked": bool(self.values.get("ed.telemetry.dock_state")),
                "Landed": bool(self.values.get("ed.telemetry.landed")),
                "Supercruise": bool(self.values.get("ed.telemetry.supercruise")),
                "InHyperspace": bool(self.values.get("ed.telemetry.in_hyperspace")),
                "GlideMode": bool(self.values.get("ed.telemetry.glide_mode")),
                "HasLatLong": bool(self.values.get("ed.telemetry.has_lat_long")),
                "HardpointsDeployed": bool(self.values.get("ed.telemetry.hardpoints_deployed")),
                "IsInDanger": bool(self.values.get("ed.telemetry.in_danger")),
                "BeingInterdicted": bool(self.values.get("ed.telemetry.being_interdicted")),
                "Firing": bool(self.values.get("ed.telemetry.firing")),
                "MassLocked": bool(self.values.get("ed.telemetry.mass_locked")),
                "OnFoot": bool(self.values.get("ed.telemetry.on_foot")),
                "InSRV": bool(self.values.get("ed.telemetry.in_srv")),
            },
            "Heat": self.values.get("ed.telemetry.heat_percent"),
            "FuelMain": self.values.get("ed.telemetry.fuel_main"),
            "FuelReservoir": self.values.get("ed.telemetry.fuel_reservoir"),
            "FuelCapacity": self.values.get("ed.telemetry.fuel_capacity"),
            "Hull": self.values.get("ed.telemetry.hull_percent"),
            "Target": self.values.get("ed.telemetry.target"),
        }


class MemorySemanticStore:
    def __init__(self) -> None:
        self._store: dict[str, SemanticStateRecord] = {}

    def get(self, key: str) -> SemanticStateRecord | None:
        return self._store.get(key)

    def set(self, rec: SemanticStateRecord) -> None:
        self._store[rec.key] = rec

    def items(self) -> list[SemanticStateRecord]:
        return list(self._store.values())


def compute_ed_semantic_records(values: dict[str, Any], now_ms: int | None = None) -> list[SemanticStateRecord]:
    raw = TelemetryRawStore(values, now_ms=now_ms)
    sem = MemorySemanticStore()
    engine = create_semantic_engine(raw, sem)
    dirty = [
        "Status.$fresh",
        "Status.Flags",
        "Status.Target",
        "Status.Heat",
        "Status.FuelMain",
        "Status.FuelReservoir",
        "Status.Hull",
        "NavRoute.NextLegCost",
    ]
    engine.update(dirty, raw.now_ms())
    return sem.items()


def explain_ed_semantic(values: dict[str, Any], key: str, now_ms: int | None = None) -> dict[str, Any]:
    raw = TelemetryRawStore(values, now_ms=now_ms)
    sem = MemorySemanticStore()
    engine = create_semantic_engine(raw, sem)
    dirty = [
        "Status.$fresh",
        "Status.Flags",
        "Status.Target",
        "Status.Heat",
        "Status.FuelMain",
        "Status.FuelReservoir",
        "Status.Hull",
        "NavRoute.NextLegCost",
    ]
    engine.update(dirty, raw.now_ms())
    result = engine.explain(key, raw.now_ms())
    if result.get("current") is None:
        current = sem.get(key)
        result["current"] = asdict(current) if current else None
    return result
