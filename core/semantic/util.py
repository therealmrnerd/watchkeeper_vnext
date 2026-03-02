from __future__ import annotations

import re
from typing import Any


def clamp(n: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, n))


def is_fresh(now_ms: int, updated_at_ms: int | None, timeout_ms: int) -> bool:
    if not updated_at_ms:
        return False
    return now_ms - updated_at_ms <= timeout_ms


def ms_since(now_ms: int, then_ms: int | None) -> float:
    if not then_ms:
        return float("inf")
    return now_ms - then_ms


def truthy(value: Any) -> bool:
    return value is True or value == 1 or value == "true"


def get_path(obj: Any, path: str) -> Any:
    if obj is None:
        return None
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
    return cur


def looks_like_fleet_carrier_callsign(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{3}-[A-Z0-9]{3}", name.strip(), flags=re.IGNORECASE))
