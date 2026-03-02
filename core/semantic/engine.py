from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .types import Catalog, CatalogState, DirtyRawKey, SemanticStateRecord, SemanticStore

DeriveOutput = dict[str, Any]
DeriveFn = Callable[[Any, SemanticStore, int], DeriveOutput]


class SemanticEngine:
    def __init__(self, raw: Any, sem: SemanticStore, catalog_path: str | Path) -> None:
        self.raw = raw
        self.sem = sem
        self.catalog = self._load_catalog(catalog_path)
        self.states_by_key = {state.key: state for state in self.catalog.states}
        self.deps_index: dict[str, set[str]] = {}
        self.derive_fns: dict[str, DeriveFn] = {}
        self._build_deps_index()

    def register(self, key: str, fn: DeriveFn) -> None:
        self.derive_fns[key] = fn

    def update(self, dirty: list[DirtyRawKey], now_ms: int) -> list[SemanticStateRecord]:
        affected: set[str] = set()
        for dep in dirty:
            for indexed_dep, keys in self.deps_index.items():
                if self._dep_matches_dirty(indexed_dep, dep):
                    for key in keys:
                        affected.add(key)

        changed: list[SemanticStateRecord] = []
        for _ in range(2):
            for key in self._order_keys(list(affected)):
                fn = self.derive_fns.get(key)
                if fn is None or key not in self.states_by_key:
                    continue

                out = fn(self.raw, self.sem, now_ms)
                next_rec = SemanticStateRecord(
                    key=key,
                    value=out.get("value"),
                    type=out.get("type"),
                    derived_from=list(out.get("derived_from") or []),
                    confidence=out.get("confidence"),
                    ttl_ms=out.get("ttl_ms"),
                    updated_at=now_ms,
                )
                prev = self.sem.get(key)
                same = (
                    prev is not None
                    and prev.type == next_rec.type
                    and prev.value == next_rec.value
                    and prev.confidence == next_rec.confidence
                    and prev.derived_from == next_rec.derived_from
                    and prev.ttl_ms == next_rec.ttl_ms
                )
                if same:
                    continue

                self.sem.set(next_rec)
                changed.append(next_rec)
                for dep_key in self.deps_index.get(key, set()):
                    affected.add(dep_key)

        return changed

    @staticmethod
    def _dep_matches_dirty(indexed_dep: str, dirty_dep: str) -> bool:
        return (
            indexed_dep == dirty_dep
            or indexed_dep.startswith(dirty_dep + ".")
            or dirty_dep.startswith(indexed_dep + ".")
        )

    def explain(self, key: str, now_ms: int) -> dict[str, Any]:
        definition = self.states_by_key.get(key)
        current = self.sem.get(key)
        fn = self.derive_fns.get(key)
        preview = fn(self.raw, self.sem, now_ms) if fn else None
        inputs = self._collect_inputs((preview or {}).get("derived_from") or (current.derived_from if current else []))
        return {
            "key": key,
            "definition": asdict(definition) if definition else None,
            "current": asdict(current) if current else None,
            "preview": preview,
            "inputs": inputs,
            "registered": fn is not None,
        }

    def _collect_inputs(self, dependencies: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        status = self.raw.get_status()
        for dep in dependencies:
            if dep.startswith("Status."):
                path = dep.removeprefix("Status.")
                cur = status
                for part in path.split("."):
                    if isinstance(cur, dict):
                        cur = cur.get(part)
                    else:
                        cur = None
                    if cur is None:
                        break
                out[dep] = cur
            elif dep.startswith("Journal."):
                event = dep.removeprefix("Journal.")
                if event.endswith("*"):
                    out[dep] = None
                else:
                    out[dep] = self.raw.get_last_journal_event(event)
            elif dep.startswith("ed.semantic."):
                record = self.sem.get(dep)
                out[dep] = asdict(record) if record else None
            else:
                out[dep] = self.raw.get_raw_value(dep)
        return out

    def _build_deps_index(self) -> None:
        for state in self.catalog.states:
            for dep in state.derive_from:
                self.deps_index.setdefault(dep, set()).add(state.key)

    def _order_keys(self, keys: list[str]) -> list[str]:
        return [
            item["key"]
            for item in sorted(
                (
                    {"key": key, "priority": self.states_by_key.get(key).priority if key in self.states_by_key else 999}
                    for key in keys
                ),
                key=lambda item: (item["priority"], item["key"]),
            )
        ]

    @staticmethod
    def _load_catalog(catalog_path: str | Path) -> Catalog:
        payload = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        states = [CatalogState(**state) for state in payload["states"]]
        return Catalog(version=int(payload["version"]), states=states)
