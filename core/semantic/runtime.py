from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime, timezone
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
        if not event:
            return None
        payload = self.values.get(f"ed.event.{event}.payload")
        if not isinstance(payload, dict):
            return None
        out = dict(payload)
        timestamp_ms = self.values.get(f"ed.event.{event}.timestamp_ms")
        if timestamp_ms is None:
            timestamp_ms = _timestamp_ms(payload.get("timestamp"))
        if timestamp_ms is not None:
            out["timestampMs"] = int(timestamp_ms)
        return out

    def get_last_journal_event_of(self, events: list[str]) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        latest_ms = -1
        for event in events:
            item = self.get_last_journal_event(event)
            if not item:
                continue
            timestamp_ms = item.get("timestampMs")
            try:
                item_ms = int(timestamp_ms)
            except (TypeError, ValueError):
                item_ms = -1
            if item_ms >= latest_ms:
                latest = item
                latest_ms = item_ms
        return latest

    def get_raw_value(self, path: str) -> Any:
        if path == "NavRoute.NextLegCost":
            return self.values.get("ed.telemetry.navroute_next_leg_cost")
        if path == "ed.station.no_fire_zone":
            return self.values.get("ed.station.no_fire_zone")
        value = self.values.get(path)
        if value is not None:
            return value
        if path.startswith("ed.telemetry."):
            suffix = path.removeprefix("ed.telemetry.")
            return self.values.get(f"ed.status.{suffix}")
        return None

    def _build_status(self) -> dict[str, Any]:
        running = bool(self.values.get("ed.running"))
        if not running:
            return {}

        return {
            "Flags": {
                "Docked": _bool_value(self.values, "ed.telemetry.dock_state", "ed.status.docked"),
                "Landed": _bool_value(self.values, "ed.telemetry.landed", "ed.status.landed"),
                "Supercruise": _bool_value(self.values, "ed.telemetry.supercruise", "ed.status.supercruise"),
                "InHyperspace": _bool_value(self.values, "ed.telemetry.in_hyperspace", "ed.status.in_hyperspace"),
                "GlideMode": _bool_value(self.values, "ed.telemetry.glide_mode", "ed.status.glide_mode"),
                "HasLatLong": _bool_value(self.values, "ed.telemetry.has_lat_long", "ed.status.has_lat_long"),
                "HardpointsDeployed": _bool_value(self.values, "ed.telemetry.hardpoints_deployed", "ed.status.hardpoints_deployed"),
                "IsInDanger": _bool_value(self.values, "ed.telemetry.in_danger", "ed.status.in_danger"),
                "BeingInterdicted": _bool_value(self.values, "ed.telemetry.being_interdicted", "ed.status.being_interdicted"),
                "Firing": _bool_value(self.values, "ed.telemetry.firing", "ed.status.firing"),
                "MassLocked": _bool_value(self.values, "ed.telemetry.mass_locked", "ed.status.fsd_mass_locked"),
                "FsdCharging": _bool_value(self.values, "ed.telemetry.fsd_charging", "ed.status.fsd_charging"),
                "FsdCooldown": _bool_value(self.values, "ed.telemetry.fsd_cooldown", "ed.status.fsd_cooldown"),
                "FsdHyperdriveCharging": _bool_value(self.values, "ed.telemetry.fsd_hyperdrive_charging", "ed.status.fsd_hyperdrive_charging"),
                "OnFoot": _bool_value(self.values, "ed.telemetry.on_foot", "ed.status.on_foot"),
                "InSRV": _bool_value(self.values, "ed.telemetry.in_srv", "ed.status.in_srv"),
            },
            "Heat": self.values.get("ed.telemetry.heat_percent"),
            "FuelMain": self.values.get("ed.telemetry.fuel_main"),
            "FuelReservoir": self.values.get("ed.telemetry.fuel_reservoir"),
            "FuelCapacity": self.values.get("ed.telemetry.fuel_capacity"),
            "Hull": self.values.get("ed.telemetry.hull_percent"),
            "Target": self.values.get("ed.telemetry.target"),
            "Destination": {
                "Name": self.values.get("ed.telemetry.destination_name"),
                "System": self.values.get("ed.telemetry.destination_system"),
                "Body": self.values.get("ed.telemetry.destination_body"),
                "BodyType": self.values.get("ed.telemetry.destination_body_type"),
            },
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
        "Status.Destination",
        "Status.Heat",
        "Status.FuelMain",
        "Status.FuelReservoir",
        "Status.Hull",
        "ed.telemetry.destination_name",
        "ed.telemetry.destination_system",
        "ed.telemetry.destination_body",
        "ed.telemetry.destination_body_type",
        "ed.station.no_fire_zone",
        "NavRoute.NextLegCost",
        "Journal.StartJump",
        "Journal.FSDJump",
        "Journal.FSDTarget",
        "Journal.NavRoute",
        "Journal.NavRouteClear",
        "Journal.SupercruiseEntry",
        "Journal.SupercruiseExit",
        "Journal.SupercruiseDestinationDrop",
        "Journal.DockingRequested",
        "Journal.DockingGranted",
        "Journal.DockingDenied",
        "Journal.DockingCancelled",
        "Journal.DockingTimeout",
        "Journal.Docked",
        "Journal.Undocked",
        "Journal.Touchdown",
        "Journal.Liftoff",
        "Journal.ShipTargeted",
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
        "Status.Destination",
        "Status.Heat",
        "Status.FuelMain",
        "Status.FuelReservoir",
        "Status.Hull",
        "ed.telemetry.destination_name",
        "ed.telemetry.destination_system",
        "ed.telemetry.destination_body",
        "ed.telemetry.destination_body_type",
        "ed.station.no_fire_zone",
        "NavRoute.NextLegCost",
        "Journal.StartJump",
        "Journal.FSDJump",
        "Journal.FSDTarget",
        "Journal.NavRoute",
        "Journal.NavRouteClear",
        "Journal.SupercruiseEntry",
        "Journal.SupercruiseExit",
        "Journal.SupercruiseDestinationDrop",
        "Journal.DockingRequested",
        "Journal.DockingGranted",
        "Journal.DockingDenied",
        "Journal.DockingCancelled",
        "Journal.DockingTimeout",
        "Journal.Docked",
        "Journal.Undocked",
        "Journal.Touchdown",
        "Journal.Liftoff",
        "Journal.ShipTargeted",
    ]
    engine.update(dirty, raw.now_ms())
    result = engine.explain(key, raw.now_ms())
    if result.get("current") is None:
        current = sem.get(key)
        result["current"] = asdict(current) if current else None
    return result


def _timestamp_ms(value: Any) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except Exception:
        return None


def _bool_value(values: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        if key not in values:
            continue
        value = values.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
    return False
