import importlib.util
from pathlib import Path


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("assist_router", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    mod = load_module(root / "services" / "ai" / "assist_router.py")

    sample = {
        "user_text": "Set combat lights and skip track",
        "mode": "game",
        "auto_execute": True,
        "dry_run": True,
        "use_knowledge": False,
    }
    mod.validate_assist_request(sample)
    intent, retrieval_meta = mod.build_intent(sample)

    print("REQUEST_ID_PRESENT", bool(intent.get("request_id")))
    print("DOMAIN", intent.get("domain"))
    print("ACTION_COUNT", len(intent.get("proposed_actions", [])))
    print("NEEDS_TOOLS", intent.get("needs_tools"))
    print("RETRIEVAL_META_KEYS", sorted(retrieval_meta.keys()))


if __name__ == "__main__":
    main()
