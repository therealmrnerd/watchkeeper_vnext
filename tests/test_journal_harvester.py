import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ADAPTER_DIR = ROOT_DIR / "services" / "adapters"
if str(ADAPTER_DIR) not in sys.path:
    sys.path.insert(0, str(ADAPTER_DIR))

from journal_harvester import JournalHarvester


class JournalHarvesterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_journal_harvest_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_catalog(self) -> Path:
        path = self.temp_dir / "catalog.json"
        path.write_text(
            json.dumps(
                {
                    "events": {
                        "FSDTarget": {
                            "properties": [
                                {"name": "timestamp"},
                                {"name": "event"},
                                {"name": "Name"},
                                {"name": "SystemAddress"},
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        return path

    def _write_rules(self) -> Path:
        path = self.temp_dir / "rules.json"
        path.write_text(
            json.dumps({"events": {"FSDTarget": {"fields": ["Name", "SystemAddress"]}}}),
            encoding="utf-8",
        )
        return path

    def test_tolerates_missing_catalog(self) -> None:
        harvester = JournalHarvester(
            catalog_path=self.temp_dir / "missing_catalog.json",
            rules_path=self._write_rules(),
        )
        out = harvester.harvest_journal_event({"event": "FSDTarget", "Name": "Sol"})
        self.assertEqual(out["published"].get("journal_last_event"), "FSDTarget")
        self.assertNotIn("journal_unknown_event", out["published"])
        self.assertNotIn("j.FSDTarget.Name", out["published"])

    def test_allowlisted_fields_and_unknown_keys(self) -> None:
        harvester = JournalHarvester(
            catalog_path=self._write_catalog(),
            rules_path=self._write_rules(),
        )
        out = harvester.harvest_journal_event(
            {
                "timestamp": "2026-02-18T00:00:00Z",
                "event": "FSDTarget",
                "Name": "Shinrarta Dezhra",
                "SystemAddress": 10477373803,
                "UnseenField": 123,
            }
        )
        published = out["published"]
        self.assertEqual(published.get("journal_last_event"), "FSDTarget")
        self.assertEqual(published.get("j.FSDTarget.Name"), "Shinrarta Dezhra")
        self.assertEqual(published.get("j.FSDTarget.SystemAddress"), 10477373803)
        self.assertIn("UnseenField", published.get("j.FSDTarget.unknown_keys", []))

    def test_unknown_event_only_first_seen_flag(self) -> None:
        harvester = JournalHarvester(
            catalog_path=self._write_catalog(),
            rules_path=self._write_rules(),
        )
        out1 = harvester.harvest_journal_event({"event": "BrandNewEvent"})
        out2 = harvester.harvest_journal_event({"event": "BrandNewEvent"})

        self.assertEqual(out1["published"].get("journal_unknown_event"), "BrandNewEvent")
        self.assertTrue(out1["unknown_event_first_seen"])
        self.assertEqual(out2["published"].get("journal_unknown_event"), "BrandNewEvent")
        self.assertFalse(out2["unknown_event_first_seen"])


if __name__ == "__main__":
    unittest.main()
