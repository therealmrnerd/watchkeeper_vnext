import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BRAINSTEM_DIR = ROOT_DIR / "services" / "brainstem"
if str(BRAINSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(BRAINSTEM_DIR))

from db_service import BrainstemDB
from mfd_layout_store import DEFAULT_LAYOUT_ID, get_output_layout, list_layouts, list_outputs, save_layout, save_outputs


class GuidedLayoutStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="wkv_mfd_layout_"))
        self.db_path = self.temp_dir / "layout_test.db"
        self.schema_path = ROOT_DIR / "schemas" / "sqlite" / "001_brainstem_core.sql"
        BrainstemDB(self.db_path, self.schema_path).ensure_schema()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_layout_and_outputs_are_seeded(self) -> None:
        layouts = list_layouts(self.db_path)
        outputs = list_outputs(self.db_path)
        self.assertEqual(layouts[0]["layout_id"], DEFAULT_LAYOUT_ID)
        self.assertEqual(len(outputs), 5)
        self.assertTrue(outputs[0]["enabled"])
        self.assertEqual(outputs[0]["layout_id"], DEFAULT_LAYOUT_ID)
        self.assertFalse(outputs[1]["enabled"])

    def test_save_guided_single_pane_and_assign_output(self) -> None:
        layout = save_layout(
            self.db_path,
            {
                "schema_version": "1.0",
                "layout_id": "portrait-target",
                "name": "Portrait Target",
                "orientation": "portrait",
                "pane_mode": "single",
                "buttons_visible": False,
                "button_regions": {"top": [], "left": [], "right": []},
                "pane_slots": [
                    {
                        "slot": "primary",
                        "default_pane": "target",
                        "context_switching": {
                            "enabled": True,
                            "rules": [{"context": "docking_granted", "pane": "docking"}],
                        },
                    }
                ],
            },
        )
        outputs = save_outputs(
            self.db_path,
            {
                "outputs": [
                    {"output_id": 2, "label": "Portrait Screen", "enabled": True, "layout_id": layout["layout_id"]}
                ]
            },
        )
        output = next(item for item in outputs if item["output_id"] == 2)
        output_layout = get_output_layout(self.db_path, 2)
        self.assertEqual(output["layout_id"], "portrait-target")
        self.assertEqual(output_layout["layout"]["pane_slots"][0]["default_pane"], "target")
        self.assertEqual(output_layout["layout"]["pane_slots"][0]["context_switching"]["rules"][0]["pane"], "docking")

    def test_layout_buttons_can_repeat_and_include_custom_controls(self) -> None:
        layout = save_layout(
            self.db_path,
            {
                "schema_version": "1.0",
                "layout_id": "mirrored-buttons",
                "name": "Mirrored Buttons",
                "orientation": "landscape",
                "pane_mode": "four",
                "buttons_visible": True,
                "custom_controls": [
                    {
                        "control_id": "custom:heat_sink",
                        "label": "Heat Sink",
                        "icon": "icons/heat-sink.png",
                        "keypress": "H",
                        "macro": "",
                    }
                ],
                "button_regions": {
                    "top": [
                        {"instance_id": "top-01-system", "control_id": "system_map"},
                        {"instance_id": "top-02-system-copy", "control_id": "system_map"},
                    ],
                    "left": [None, {"instance_id": "left-02-heat", "control_id": "custom:heat_sink"}],
                    "right": [{"instance_id": "right-01-heat", "control_id": "custom:heat_sink"}],
                },
                "pane_slots": [
                    {"slot": "top_left", "default_pane": "system", "context_switching": {"enabled": False, "rules": []}},
                    {"slot": "top_right", "default_pane": "ship", "context_switching": {"enabled": False, "rules": []}},
                    {"slot": "bottom_left", "default_pane": "conditional", "context_switching": {"enabled": False, "rules": []}},
                    {"slot": "bottom_right", "default_pane": "target", "context_switching": {"enabled": False, "rules": []}},
                ],
            },
        )

        self.assertEqual(layout["button_regions"]["top"][0]["control_id"], "system_map")
        self.assertEqual(layout["button_regions"]["top"][1]["control_id"], "system_map")
        self.assertIsNone(layout["button_regions"]["left"][0])
        self.assertEqual(layout["button_regions"]["left"][1]["control_id"], "custom:heat_sink")
        self.assertEqual(layout["button_regions"]["right"][0]["control_id"], "custom:heat_sink")
        self.assertEqual(layout["custom_controls"][0]["label"], "Heat Sink")


if __name__ == "__main__":
    unittest.main()
