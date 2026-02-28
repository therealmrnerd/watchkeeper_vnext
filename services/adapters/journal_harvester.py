import json
from pathlib import Path
from typing import Any


class JournalHarvester:
    def __init__(
        self,
        *,
        catalog_path: Path,
        rules_path: Path,
    ) -> None:
        self.catalog_path = catalog_path
        self.rules_path = rules_path
        self._catalog_events: dict[str, dict[str, Any]] = {}
        self._allowlist: dict[str, list[str]] = {}
        self._catalog_loaded = False
        self._rules_loaded = False
        self._unknown_event_seen: set[str] = set()
        self.load_journal_schema_catalog()
        self.load_harvest_rules()

    @property
    def catalog_loaded(self) -> bool:
        return self._catalog_loaded

    @property
    def rules_loaded(self) -> bool:
        return self._rules_loaded

    def load_journal_schema_catalog(self) -> None:
        self._catalog_events = {}
        self._catalog_loaded = False
        try:
            if not self.catalog_path.exists():
                return
            payload = json.loads(self.catalog_path.read_text(encoding="utf-8", errors="ignore"))
            events = payload.get("events")
            if isinstance(events, dict):
                self._catalog_events = events
                self._catalog_loaded = True
        except Exception:
            self._catalog_events = {}
            self._catalog_loaded = False

    def load_harvest_rules(self) -> None:
        self._allowlist = {}
        self._rules_loaded = False
        try:
            if not self.rules_path.exists():
                return
            payload = json.loads(self.rules_path.read_text(encoding="utf-8", errors="ignore"))
            events = payload.get("events")
            if not isinstance(events, dict):
                return
            allowlist: dict[str, list[str]] = {}
            for event_name, value in events.items():
                if not isinstance(value, dict):
                    continue
                fields = value.get("fields")
                if not isinstance(fields, list):
                    continue
                clean_fields = [str(v).strip() for v in fields if str(v).strip()]
                if clean_fields:
                    allowlist[str(event_name)] = clean_fields
            self._allowlist = allowlist
            self._rules_loaded = True
        except Exception:
            self._allowlist = {}
            self._rules_loaded = False

    def schema_for_event(self, event_name: str) -> dict[str, Any] | None:
        if not event_name:
            return None
        schema = self._catalog_events.get(event_name)
        if isinstance(schema, dict):
            return schema
        return None

    def harvest_journal_event(self, ev: dict[str, Any]) -> dict[str, Any]:
        event_name = str(ev.get("event") or "").strip()
        if not event_name:
            return {
                "event": None,
                "published": {},
                "unknown_event_first_seen": False,
                "unknown_keys": [],
            }

        published: dict[str, Any] = {"journal_last_event": event_name}
        unknown_event_first_seen = False
        unknown_keys: list[str] = []

        # If the schema catalog is unavailable, degrade cleanly and only emit last event.
        if not self._catalog_loaded:
            return {
                "event": event_name,
                "published": published,
                "unknown_event_first_seen": False,
                "unknown_keys": [],
            }

        schema = self.schema_for_event(event_name)
        if schema is None:
            published["journal_unknown_event"] = event_name
            if event_name not in self._unknown_event_seen:
                self._unknown_event_seen.add(event_name)
                unknown_event_first_seen = True
        else:
            if self._rules_loaded:
                fields = self._allowlist.get(event_name, [])
                for field in fields:
                    if field in ev:
                        published[f"j.{event_name}.{field}"] = ev[field]

            properties = schema.get("properties")
            if isinstance(properties, list):
                known = {
                    str(prop.get("name"))
                    for prop in properties
                    if isinstance(prop, dict) and prop.get("name") is not None
                }
                unknown_keys = sorted([key for key in ev.keys() if key not in known])
                if unknown_keys:
                    published[f"j.{event_name}.unknown_keys"] = unknown_keys

        return {
            "event": event_name,
            "published": published,
            "unknown_event_first_seen": unknown_event_first_seen,
            "unknown_keys": unknown_keys,
        }
