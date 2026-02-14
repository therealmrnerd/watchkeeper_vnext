import importlib.util
from pathlib import Path


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("state_collector", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    mod = load_module(root / "services" / "adapters" / "state_collector.py")

    prev = {}
    ed = mod.collect_ed_state()
    music = mod.collect_music_state()
    system = mod.collect_system_state()

    items = []
    items.extend(mod._build_changed_items(ed, prev, "ed_probe"))
    items.extend(mod._build_changed_items(music, prev, "music_probe"))
    items.extend(mod._build_changed_items(system, prev, "system_probe"))

    print("ED_RUNNING", ed.get("ed.running"))
    print("MUSIC_PLAYING", music.get("music.playing"))
    print("SYSTEM_KEYS", sorted(system.keys()))
    print("CHANGED_ITEMS", len(items))


if __name__ == "__main__":
    main()
