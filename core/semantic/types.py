from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

SemanticType = Literal["enum", "boolean", "integer", "number", "string", "object"]
SemanticConfidence = Literal["certain", "best_effort", "unknown"]
SemanticValue = bool | int | float | str | dict[str, Any] | None


@dataclass(slots=True)
class SemanticStateRecord:
    key: str
    value: SemanticValue
    type: SemanticType
    updated_at: int
    derived_from: list[str]
    confidence: SemanticConfidence | None = None
    ttl_ms: int | None = None


@dataclass(slots=True)
class CatalogState:
    key: str
    domain: str
    type: SemanticType
    meaning: str
    derive_from: list[str]
    priority: int
    allowed_values: list[Any] | None = None
    mvp: bool | None = None


@dataclass(slots=True)
class Catalog:
    version: int
    states: list[CatalogState]


DirtyRawKey = str


class RawStore(Protocol):
    def get_status(self) -> Any | None: ...
    def get_status_updated_at(self) -> int | None: ...
    def get_last_journal_event(self, event: str) -> dict[str, Any] | None: ...
    def get_last_journal_event_of(self, events: list[str]) -> dict[str, Any] | None: ...
    def get_raw_value(self, path: str) -> Any: ...
    def now_ms(self) -> int: ...


class SemanticStore(Protocol):
    def get(self, key: str) -> SemanticStateRecord | None: ...
    def set(self, rec: SemanticStateRecord) -> None: ...
