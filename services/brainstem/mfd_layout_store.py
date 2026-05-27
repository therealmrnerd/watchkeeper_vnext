from __future__ import annotations

import json
import re
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any


LAYOUT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
ORIENTATIONS = {"landscape", "portrait"}
PANE_MODES = {"four", "single"}
FOUR_PANE_SLOTS = ("top_left", "top_right", "bottom_left", "bottom_right")
SINGLE_PANE_SLOTS = ("primary",)
BUTTON_REGIONS = ("top", "left", "right")
PANE_IDS = {
    "blank",
    "conditional",
    "docking",
    "on_foot_planet",
    "on_foot_station",
    "planet",
    "route",
    "ship",
    "slf",
    "srv",
    "station",
    "system",
    "target",
}
CONTEXT_IDS = {
    "docked",
    "docking_granted",
    "jump_route",
    "jumping",
    "on_foot_planet",
    "on_foot_station",
    "planetary_approach",
    "slf_deployed",
    "srv_deployed",
}
CONTROL_IDS = {
    "auto_dock",
    "auto_launch",
    "cargo_scoop",
    "comms_panel",
    "flight_assist",
    "flight_control",
    "fss",
    "galaxy_map",
    "hardpoints",
    "hyperspace",
    "landing_gear",
    "light_sync",
    "lights",
    "management_panel",
    "nav_panel",
    "night_vision",
    "role_panel",
    "supercruise",
    "system_map",
}
CUSTOM_CONTROL_ID_RE = re.compile(r"^custom:[a-z0-9][a-z0-9_-]{1,63}$")
CONTROL_INSTANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,80}$")

DEFAULT_LAYOUT_ID = "default-landscape-four-buttons"
DEFAULT_LAYOUT: dict[str, Any] = {
    "schema_version": "1.0",
    "layout_id": DEFAULT_LAYOUT_ID,
    "name": "Default Landscape MFD",
    "orientation": "landscape",
    "pane_mode": "four",
    "buttons_visible": True,
    "button_regions": {
        "top": [
            {"instance_id": "top-01-system-map", "control_id": "system_map"},
            {"instance_id": "top-02-galaxy-map", "control_id": "galaxy_map"},
            {"instance_id": "top-03-fss", "control_id": "fss"},
            {"instance_id": "top-04-flight-control", "control_id": "flight_control"},
            {"instance_id": "top-05-nav-panel", "control_id": "nav_panel"},
            {"instance_id": "top-06-comms-panel", "control_id": "comms_panel"},
            {"instance_id": "top-07-role-panel", "control_id": "role_panel"},
            {"instance_id": "top-08-management-panel", "control_id": "management_panel"},
        ],
        "left": [
            {"instance_id": "left-01-hardpoints", "control_id": "hardpoints"},
            {"instance_id": "left-02-flight-assist", "control_id": "flight_assist"},
            {"instance_id": "left-03-light-sync", "control_id": "light_sync"},
        ],
        "right": [
            {"instance_id": "right-01-supercruise", "control_id": "supercruise"},
            {"instance_id": "right-02-hyperspace", "control_id": "hyperspace"},
            {"instance_id": "right-03-lights", "control_id": "lights"},
            {"instance_id": "right-04-night-vision", "control_id": "night_vision"},
            {"instance_id": "right-05-landing-gear", "control_id": "landing_gear"},
            {"instance_id": "right-06-cargo-scoop", "control_id": "cargo_scoop"},
        ],
    },
    "custom_controls": [],
    "pane_slots": [
        {"slot": "top_left", "default_pane": "system", "context_switching": {"enabled": True, "rules": []}},
        {"slot": "top_right", "default_pane": "ship", "context_switching": {"enabled": False, "rules": []}},
        {"slot": "bottom_left", "default_pane": "conditional", "context_switching": {"enabled": False, "rules": []}},
        {"slot": "bottom_right", "default_pane": "target", "context_switching": {"enabled": True, "rules": []}},
    ],
}


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(Path(db_path), timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _clean_text(raw: Any, label: str, max_len: int) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{label} is required")
    if len(value) > max_len:
        raise ValueError(f"{label} must be at most {max_len} characters")
    return value


def _validate_context_switching(raw: Any, slot_label: str) -> dict[str, Any]:
    if raw is None:
        return {"enabled": False, "rules": []}
    if not isinstance(raw, dict):
        raise ValueError(f"{slot_label}.context_switching must be an object")
    enabled = raw.get("enabled", False)
    rules = raw.get("rules", [])
    if not isinstance(enabled, bool):
        raise ValueError(f"{slot_label}.context_switching.enabled must be boolean")
    if not isinstance(rules, list):
        raise ValueError(f"{slot_label}.context_switching.rules must be an array")
    clean_rules: list[dict[str, str]] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"{slot_label}.context_switching.rules[{index}] must be an object")
        context = str(rule.get("context") or "").strip()
        pane = str(rule.get("pane") or "").strip()
        if context not in CONTEXT_IDS:
            raise ValueError(f"{slot_label} uses unsupported context: {context or '-'}")
        if pane not in PANE_IDS:
            raise ValueError(f"{slot_label} uses unsupported context pane: {pane or '-'}")
        clean_rules.append({"context": context, "pane": pane})
    return {"enabled": enabled, "rules": clean_rules}


def _custom_control_ids(raw_custom_controls: Any) -> tuple[list[dict[str, Any]], set[str]]:
    if raw_custom_controls is None:
        return [], set()
    if not isinstance(raw_custom_controls, list):
        raise ValueError("layout.custom_controls must be an array")
    controls: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_custom_controls):
        if not isinstance(raw, dict):
            raise ValueError(f"layout.custom_controls[{index}] must be an object")
        raw_id = str(raw.get("control_id") or raw.get("id") or "").strip().lower()
        if raw_id and not raw_id.startswith("custom:"):
            raw_id = f"custom:{raw_id}"
        if not CUSTOM_CONTROL_ID_RE.match(raw_id):
            raise ValueError(f"layout.custom_controls[{index}].control_id must be a custom id")
        if raw_id in seen:
            raise ValueError(f"layout.custom_controls contains duplicate control: {raw_id}")
        label = _clean_text(raw.get("label") or raw.get("name"), f"layout.custom_controls[{index}].label", 48)
        icon = str(raw.get("icon") or "").strip()[:160]
        keypress = str(raw.get("keypress") or "").strip()[:80]
        macro_raw = raw.get("macro", "")
        if isinstance(macro_raw, list):
            macro = [str(item or "").strip()[:120] for item in macro_raw if str(item or "").strip()]
        else:
            macro = str(macro_raw or "").strip()[:500]
        if not keypress and not macro:
            raise ValueError(f"layout.custom_controls[{index}] requires keypress or macro")
        seen.add(raw_id)
        controls.append(
            {
                "control_id": raw_id,
                "label": label,
                "icon": icon,
                "keypress": keypress,
                "macro": macro,
            }
        )
    return controls, seen


def _normalize_button_instance(raw: Any, *, region: str, index: int, valid_controls: set[str]) -> dict[str, str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        control_id = raw.strip()
        fallback_instance = f"{region}-{index + 1:02d}-{control_id.replace('_', '-')}"
    elif isinstance(raw, dict):
        control_id = str(raw.get("control_id") or raw.get("id") or "").strip()
        fallback_instance = f"{region}-{index + 1:02d}-{control_id.replace('_', '-')}"
    else:
        raise ValueError(f"layout.button_regions.{region}[{index}] must be a control id or object")
    if control_id not in valid_controls:
        raise ValueError(f"layout.button_regions.{region} uses unsupported control: {control_id or '-'}")
    instance_id = fallback_instance
    if isinstance(raw, dict):
        instance_id = str(raw.get("instance_id") or raw.get("slot_id") or fallback_instance).strip().lower()
    instance_id = re.sub(r"[^a-z0-9_-]+", "-", instance_id).strip("-")[:80] or fallback_instance
    if not CONTROL_INSTANCE_ID_RE.match(instance_id):
        raise ValueError(f"layout.button_regions.{region}[{index}].instance_id is invalid")
    return {"instance_id": instance_id, "control_id": control_id}


def normalize_layout(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("layout must be an object")
    if payload.get("schema_version", "1.0") != "1.0":
        raise ValueError("layout.schema_version must be '1.0'")

    layout_id = _clean_text(payload.get("layout_id"), "layout.layout_id", 64).lower()
    if not LAYOUT_ID_RE.match(layout_id):
        raise ValueError("layout.layout_id must use lowercase letters, digits, dashes, or underscores")
    name = _clean_text(payload.get("name"), "layout.name", 100)
    orientation = str(payload.get("orientation") or "").strip().lower()
    pane_mode = str(payload.get("pane_mode") or "").strip().lower()
    buttons_visible = payload.get("buttons_visible")
    if orientation not in ORIENTATIONS:
        raise ValueError("layout.orientation must be landscape or portrait")
    if pane_mode not in PANE_MODES:
        raise ValueError("layout.pane_mode must be four or single")
    if not isinstance(buttons_visible, bool):
        raise ValueError("layout.buttons_visible must be boolean")

    custom_controls, custom_control_ids = _custom_control_ids(payload.get("custom_controls"))
    valid_control_ids = set(CONTROL_IDS) | custom_control_ids

    raw_regions = payload.get("button_regions", {})
    if not isinstance(raw_regions, dict):
        raise ValueError("layout.button_regions must be an object")
    clean_regions: dict[str, list[dict[str, str] | None]] = {}
    seen_instances: set[str] = set()
    for region in BUTTON_REGIONS:
        raw_controls = raw_regions.get(region, [])
        if not isinstance(raw_controls, list):
            raise ValueError(f"layout.button_regions.{region} must be an array")
        controls: list[dict[str, str] | None] = []
        for index, control in enumerate(raw_controls):
            instance = _normalize_button_instance(control, region=region, index=index, valid_controls=valid_control_ids)
            if instance is None:
                controls.append(None)
                continue
            if instance["instance_id"] in seen_instances:
                instance["instance_id"] = f"{instance['instance_id']}-{len(seen_instances) + 1}"
            seen_instances.add(instance["instance_id"])
            controls.append(instance)
        while controls and controls[-1] is None:
            controls.pop()
        clean_regions[region] = controls

    expected_slots = FOUR_PANE_SLOTS if pane_mode == "four" else SINGLE_PANE_SLOTS
    raw_slots = payload.get("pane_slots")
    if not isinstance(raw_slots, list):
        raise ValueError("layout.pane_slots must be an array")
    clean_slots: list[dict[str, Any]] = []
    seen_slots: set[str] = set()
    for index, raw_slot in enumerate(raw_slots):
        if not isinstance(raw_slot, dict):
            raise ValueError(f"layout.pane_slots[{index}] must be an object")
        slot = str(raw_slot.get("slot") or "").strip()
        pane = str(raw_slot.get("default_pane") or "").strip()
        if slot not in expected_slots:
            raise ValueError(f"layout.pane_slots[{index}] uses unsupported {pane_mode} slot: {slot or '-'}")
        if slot in seen_slots:
            raise ValueError(f"layout.pane_slots contains duplicate slot: {slot}")
        if pane not in PANE_IDS:
            raise ValueError(f"layout.pane_slots[{index}] uses unsupported pane: {pane or '-'}")
        seen_slots.add(slot)
        clean_slots.append(
            {
                "slot": slot,
                "default_pane": pane,
                "context_switching": _validate_context_switching(raw_slot.get("context_switching"), f"layout.pane_slots[{index}]"),
            }
        )
    if seen_slots != set(expected_slots):
        missing = ", ".join(slot for slot in expected_slots if slot not in seen_slots)
        raise ValueError(f"layout.pane_slots is missing slots: {missing}")

    return {
        "schema_version": "1.0",
        "layout_id": layout_id,
        "name": name,
        "orientation": orientation,
        "pane_mode": pane_mode,
        "buttons_visible": buttons_visible,
        "button_regions": clean_regions,
        "custom_controls": custom_controls,
        "pane_slots": clean_slots,
    }


def _layout_from_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(str(row["layout_json"]))
    payload["is_template"] = bool(row["is_template"])
    payload["updated_at_utc"] = row["updated_at_utc"]
    return payload


def ensure_default_layout(db_path: Path) -> None:
    with _connect(db_path) as con:
        row = con.execute("SELECT layout_id FROM mfd_layouts WHERE layout_id=?", (DEFAULT_LAYOUT_ID,)).fetchone()
        if not row:
            default_layout = normalize_layout(deepcopy(DEFAULT_LAYOUT))
            con.execute(
                """
                INSERT INTO mfd_layouts(layout_id,name,orientation,pane_mode,buttons_visible,layout_json,is_template)
                VALUES(?,?,?,?,?,?,1)
                """,
                (
                    default_layout["layout_id"],
                    default_layout["name"],
                    default_layout["orientation"],
                    default_layout["pane_mode"],
                    int(default_layout["buttons_visible"]),
                    json.dumps(default_layout, ensure_ascii=False),
                ),
            )
        for output_id in range(1, 6):
            con.execute(
                """
                INSERT OR IGNORE INTO mfd_outputs(output_id,label,enabled,active_layout_id)
                VALUES(?,?,?,?)
                """,
                (output_id, f"Output {output_id}", int(output_id == 1), DEFAULT_LAYOUT_ID if output_id == 1 else None),
            )
        con.execute(
            """
            UPDATE mfd_outputs
            SET active_layout_id=?, updated_at_utc=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE output_id=1 AND active_layout_id IS NULL
            """,
            (DEFAULT_LAYOUT_ID,),
        )
        con.commit()


def list_layouts(db_path: Path) -> list[dict[str, Any]]:
    ensure_default_layout(db_path)
    with _connect(db_path) as con:
        rows = con.execute(
            "SELECT layout_json,is_template,updated_at_utc FROM mfd_layouts ORDER BY is_template DESC,name ASC"
        ).fetchall()
    return [_layout_from_row(row) for row in rows]


def get_layout(db_path: Path, layout_id: str) -> dict[str, Any] | None:
    ensure_default_layout(db_path)
    with _connect(db_path) as con:
        row = con.execute(
            "SELECT layout_json,is_template,updated_at_utc FROM mfd_layouts WHERE layout_id=?",
            (str(layout_id or "").strip().lower(),),
        ).fetchone()
    return _layout_from_row(row) if row else None


def save_layout(db_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    layout = normalize_layout(payload)
    ensure_default_layout(db_path)
    with _connect(db_path) as con:
        existing = con.execute("SELECT is_template FROM mfd_layouts WHERE layout_id=?", (layout["layout_id"],)).fetchone()
        if existing and bool(existing["is_template"]):
            raise ValueError("template layouts cannot be overwritten")
        con.execute(
            """
            INSERT INTO mfd_layouts(layout_id,name,orientation,pane_mode,buttons_visible,layout_json,is_template)
            VALUES(?,?,?,?,?,?,0)
            ON CONFLICT(layout_id) DO UPDATE SET
              name=excluded.name,
              orientation=excluded.orientation,
              pane_mode=excluded.pane_mode,
              buttons_visible=excluded.buttons_visible,
              layout_json=excluded.layout_json,
              updated_at_utc=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """,
            (
                layout["layout_id"],
                layout["name"],
                layout["orientation"],
                layout["pane_mode"],
                int(layout["buttons_visible"]),
                json.dumps(layout, ensure_ascii=False),
            ),
        )
        con.commit()
    return get_layout(db_path, layout["layout_id"]) or layout


def list_outputs(db_path: Path) -> list[dict[str, Any]]:
    ensure_default_layout(db_path)
    with _connect(db_path) as con:
        rows = con.execute(
            """
            SELECT o.output_id,o.label,o.enabled,o.active_layout_id,o.updated_at_utc,l.name AS layout_name
            FROM mfd_outputs o
            LEFT JOIN mfd_layouts l ON l.layout_id=o.active_layout_id
            ORDER BY o.output_id
            """
        ).fetchall()
    return [
        {
            "output_id": int(row["output_id"]),
            "label": row["label"],
            "enabled": bool(row["enabled"]),
            "layout_id": row["active_layout_id"],
            "layout_name": row["layout_name"],
            "url": f"/mfd/{int(row['output_id'])}",
            "updated_at_utc": row["updated_at_utc"],
        }
        for row in rows
    ]


def get_output_layout(db_path: Path, output_id: int) -> dict[str, Any] | None:
    if output_id not in range(1, 6):
        return None
    ensure_default_layout(db_path)
    with _connect(db_path) as con:
        row = con.execute(
            """
            SELECT o.output_id,o.label,o.enabled,o.active_layout_id,l.layout_json,l.is_template,l.updated_at_utc
            FROM mfd_outputs o
            LEFT JOIN mfd_layouts l ON l.layout_id=o.active_layout_id
            WHERE o.output_id=?
            """,
            (output_id,),
        ).fetchone()
    if not row:
        return None
    layout = _layout_from_row(row) if row["layout_json"] else None
    return {
        "output_id": int(row["output_id"]),
        "label": row["label"],
        "enabled": bool(row["enabled"]),
        "layout_id": row["active_layout_id"],
        "layout": layout,
        "url": f"/mfd/{int(row['output_id'])}",
    }


def save_outputs(db_path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = payload.get("outputs") if isinstance(payload, dict) else None
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("outputs must be a non-empty array")
    ensure_default_layout(db_path)
    seen: set[int] = set()
    with _connect(db_path) as con:
        known_layouts = {
            str(row["layout_id"])
            for row in con.execute("SELECT layout_id FROM mfd_layouts").fetchall()
        }
        for index, item in enumerate(outputs):
            if not isinstance(item, dict):
                raise ValueError(f"outputs[{index}] must be an object")
            output_id = item.get("output_id")
            if not isinstance(output_id, int) or output_id not in range(1, 6):
                raise ValueError(f"outputs[{index}].output_id must be integer 1..5")
            if output_id in seen:
                raise ValueError(f"outputs contains duplicate output_id: {output_id}")
            seen.add(output_id)
            label = _clean_text(item.get("label", f"Output {output_id}"), f"outputs[{index}].label", 80)
            enabled = item.get("enabled")
            layout_id = str(item.get("layout_id") or "").strip().lower() or None
            if not isinstance(enabled, bool):
                raise ValueError(f"outputs[{index}].enabled must be boolean")
            if layout_id is not None and layout_id not in known_layouts:
                raise ValueError(f"outputs[{index}].layout_id is unknown: {layout_id}")
            if enabled and layout_id is None:
                raise ValueError(f"outputs[{index}] needs a layout_id when enabled")
            con.execute(
                """
                UPDATE mfd_outputs
                SET label=?,enabled=?,active_layout_id=?,updated_at_utc=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE output_id=?
                """,
                (label, int(enabled), layout_id, output_id),
            )
        con.commit()
    return list_outputs(db_path)
