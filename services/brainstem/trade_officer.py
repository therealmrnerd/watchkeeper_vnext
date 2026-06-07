from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SINGLE_JUMP_LY = 25.0
DEFAULT_MULTI_JUMP_LY = 90.0
DEFAULT_MAX_ROWS = 8


def _as_float(value: Any) -> float | None:
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    return raw if raw == raw else None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_key(value: Any) -> str:
    return str(value or "").strip().casefold()


def _display_name(item: dict[str, Any]) -> str:
    return str(item.get("name_localised") or item.get("commodity_localised") or item.get("name") or item.get("commodity_name") or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _distance_ly(origin: dict[str, Any] | None, candidate: dict[str, Any]) -> float | None:
    if not origin:
        return None
    coords = [
        _as_float(origin.get("coords_x")),
        _as_float(origin.get("coords_y")),
        _as_float(origin.get("coords_z")),
        _as_float(candidate.get("coords_x")),
        _as_float(candidate.get("coords_y")),
        _as_float(candidate.get("coords_z")),
    ]
    if any(value is None for value in coords):
        return None
    ox, oy, oz, cx, cy, cz = [float(value) for value in coords]
    return round(math.sqrt((cx - ox) ** 2 + (cy - oy) ** 2 + (cz - oz) ** 2), 2)


def _current_system_row(con: sqlite3.Connection, state: dict[str, Any]) -> dict[str, Any] | None:
    address = _as_int(state.get("ed.location.system_address") or state.get("ed.status.system_address"))
    name = str(state.get("ed.location.system") or state.get("ed.status.system_name") or "").strip()
    row = None
    if address is not None:
        row = con.execute(
            "SELECT system_address,name,coords_x,coords_y,coords_z FROM ed_systems WHERE system_address=? LIMIT 1",
            (address,),
        ).fetchone()
    if row is None and name:
        row = con.execute(
            "SELECT system_address,name,coords_x,coords_y,coords_z FROM ed_systems WHERE name=? COLLATE NOCASE LIMIT 1",
            (name,),
        ).fetchone()
    return dict(row) if row else None


def _remote_market_rows(con: sqlite3.Connection, *, current_market_id: int | None) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = "1=1"
    if current_market_id is not None:
        where += " AND m.market_id<>?"
        params.append(current_market_id)
    rows = con.execute(
        f"""
        SELECT
          m.market_id,m.station_name,m.station_type,m.system_address,m.system_name,
          m.commodity_name,m.commodity_localised,m.category,m.buy_price,m.sell_price,
          m.stock,m.demand,m.distance_to_arrival_ls,m.source,m.provider_updated_at,
          m.last_refreshed_at,s.coords_x,s.coords_y,s.coords_z
        FROM ed_market_commodities m
        LEFT JOIN ed_systems s ON s.system_address=m.system_address
        WHERE {where}
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _local_market_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    items = state.get("ed.market.items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _cargo_capacity_t(state: dict[str, Any]) -> int | None:
    for key in ("ed.modules.cargo_capacity", "ed.ship.cargo_capacity", "ed.telemetry.cargo_capacity"):
        value = _as_int(state.get(key))
        if value is not None and value > 0:
            return value
    return None


def _cargo_used_t(state: dict[str, Any]) -> int:
    for key in ("ed.cargo.count", "ed.status.cargo"):
        value = _as_int(state.get(key))
        if value is not None and value >= 0:
            return value
    return 0


def _jump_bucket(distance_ly: float | None, single_jump_ly: float, multi_jump_ly: float) -> str:
    if distance_ly is None:
        return "unknown"
    if distance_ly <= single_jump_ly:
        return "single"
    if distance_ly <= multi_jump_ly:
        return "multi"
    return "distant"


def build_trade_officer_payload(
    *,
    state: dict[str, Any],
    db_path: Path,
    single_jump_ly: float = DEFAULT_SINGLE_JUMP_LY,
    multi_jump_ly: float = DEFAULT_MULTI_JUMP_LY,
    limit: int = DEFAULT_MAX_ROWS,
) -> dict[str, Any]:
    local_items = _local_market_items(state)
    market_id = _as_int(state.get("ed.market.market_id") or state.get("ed.station.market_id"))
    station_name = str(state.get("ed.market.station_name") or state.get("ed.location.station") or state.get("ed.station.name") or "").strip()
    system_name = str(state.get("ed.market.system_name") or state.get("ed.location.system") or "").strip()
    capacity = _cargo_capacity_t(state)
    cargo_used = _cargo_used_t(state)
    free_capacity = max(0, capacity - cargo_used) if capacity is not None else None
    max_rows = max(1, min(30, int(limit or DEFAULT_MAX_ROWS)))
    one_jump = max(1.0, float(single_jump_ly or DEFAULT_SINGLE_JUMP_LY))
    multi_jump = max(one_jump, float(multi_jump_ly or DEFAULT_MULTI_JUMP_LY))

    status = "ready"
    notes: list[str] = []
    if not bool(state.get("ed.market.available")) or not local_items:
        status = "no_local_market"
        notes.append("Open the local commodity market once so Elite writes Market.json.")

    opportunities: list[dict[str, Any]] = []
    remote_count = 0
    nearest_updated_at = None
    try:
        with sqlite3.connect(db_path, timeout=2.0) as con:
            con.row_factory = sqlite3.Row
            origin = _current_system_row(con, state)
            remote_rows = _remote_market_rows(con, current_market_id=market_id)
            remote_count = len(remote_rows)
    except sqlite3.Error as exc:
        remote_rows = []
        origin = None
        status = "market_cache_error" if status == "ready" else status
        notes.append(f"Market cache unavailable: {exc}")

    if not remote_rows and status == "ready":
        status = "no_remote_market"
        notes.append("No remote market commodity rows are cached yet. Import EDDN/provider market data to rank sell stations.")

    remote_by_commodity: dict[str, list[dict[str, Any]]] = {}
    for row in remote_rows:
        key = _clean_key(row.get("commodity_name") or row.get("commodity_localised"))
        if not key:
            continue
        remote_by_commodity.setdefault(key, []).append(row)
        updated = row.get("last_refreshed_at") or row.get("provider_updated_at")
        if updated and (nearest_updated_at is None or str(updated) > str(nearest_updated_at)):
            nearest_updated_at = str(updated)

    for local in local_items:
        key = _clean_key(local.get("name") or local.get("name_localised"))
        buy_price = _as_int(local.get("buy_price")) or 0
        stock = _as_int(local.get("stock")) or 0
        if not key or buy_price <= 0 or stock <= 0:
            continue
        for remote in remote_by_commodity.get(key, []):
            sell_price = _as_int(remote.get("sell_price")) or 0
            demand = _as_int(remote.get("demand"))
            if sell_price <= buy_price:
                continue
            if demand is not None and demand <= 0:
                continue
            distance = _distance_ly(origin, remote)
            bucket = _jump_bucket(distance, one_jump, multi_jump)
            if bucket == "distant":
                continue
            available_tons = min(stock, demand if demand is not None and demand > 0 else stock)
            cargo_tons = min(available_tons, free_capacity) if free_capacity is not None else available_tons
            profit_per_t = sell_price - buy_price
            opportunities.append(
                {
                    "commodity": _display_name(local) or _display_name(remote) or str(local.get("name") or ""),
                    "buy": {
                        "station": station_name or None,
                        "system": system_name or None,
                        "market_id": market_id,
                        "price": buy_price,
                        "stock": stock,
                    },
                    "sell": {
                        "station": remote.get("station_name"),
                        "system": remote.get("system_name"),
                        "market_id": remote.get("market_id"),
                        "station_type": remote.get("station_type"),
                        "price": sell_price,
                        "demand": demand,
                        "distance_to_arrival_ls": remote.get("distance_to_arrival_ls"),
                    },
                    "profit_per_t": profit_per_t,
                    "profit_per_100t": profit_per_t * 100,
                    "profit_for_vessel": (profit_per_t * cargo_tons) if free_capacity is not None else None,
                    "trade_tons": cargo_tons,
                    "capacity_known": free_capacity is not None,
                    "distance_ly": distance,
                    "jump_bucket": bucket,
                    "source": remote.get("source"),
                    "market_updated_at": remote.get("last_refreshed_at") or remote.get("provider_updated_at"),
                }
            )

    opportunities.sort(
        key=lambda item: (
            item.get("profit_for_vessel") if item.get("profit_for_vessel") is not None else item.get("profit_per_100t") or 0,
            item.get("profit_per_t") or 0,
        ),
        reverse=True,
    )
    if status == "ready" and not opportunities:
        status = "no_profitable_routes"
        notes.append("Local and cached remote markets have no profitable routes inside the configured jump envelope.")

    return {
        "status": status,
        "generated_at_utc": _utc_now_iso(),
        "local_market": {
            "available": bool(state.get("ed.market.available")),
            "station": station_name or None,
            "system": system_name or None,
            "market_id": market_id,
            "updated_at": state.get("ed.market.updated_at"),
            "item_count": len(local_items),
            "sellable_count": state.get("ed.market.sellable_count"),
        },
        "ship": {
            "cargo_capacity_t": capacity,
            "cargo_used_t": cargo_used,
            "free_capacity_t": free_capacity,
        },
        "search": {
            "single_jump_ly": one_jump,
            "multi_jump_ly": multi_jump,
            "remote_market_rows": remote_count,
            "remote_latest_updated_at": nearest_updated_at,
        },
        "opportunities": opportunities[:max_rows],
        "notes": notes,
    }
