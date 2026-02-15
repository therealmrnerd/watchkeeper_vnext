import argparse
import json
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.policy_engine import PolicyEngine
from core.policy_types import ActionRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Watchkeeper Standing Orders simulator")
    parser.add_argument(
        "--policy",
        default=str(ROOT_DIR / "config" / "standing_orders.json"),
        help="Path to standing orders JSON file",
    )
    parser.add_argument("--condition", help="Watch condition, e.g. GAME")
    parser.add_argument("--tool", help="Tool name, e.g. input.keypress")
    parser.add_argument("--incident-id", default="inc-policy-sim")
    parser.add_argument("--source", default="policy_sim")
    parser.add_argument("--stt", type=float, default=None)
    parser.add_argument("--foreground", default=None)
    parser.add_argument("--token", default=None, help="User confirmation token")
    parser.add_argument("--now", type=float, default=None, help="Unix epoch timestamp")

    parser.add_argument(
        "--confirm",
        default=None,
        metavar="INCIDENT_ID",
        help="Record confirmation for an incident",
    )
    parser.add_argument(
        "--confirm-tool",
        default=None,
        help="Tool name used when recording confirmation (defaults to --tool)",
    )
    parser.add_argument(
        "--confirm-token",
        default=None,
        help="Confirmation token (defaults to --token or 'cli-confirm')",
    )
    parser.add_argument(
        "--confirm-ts",
        type=float,
        default=None,
        help="Confirmation timestamp epoch (defaults to --now or current time)",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    now_ts = float(args.now if args.now is not None else time.time())

    engine = PolicyEngine(args.policy)

    if args.confirm:
        confirm_tool = args.confirm_tool or args.tool or "twitch.redeem"
        confirm_token = args.confirm_token or args.token or "cli-confirm"
        confirm_ts = float(args.confirm_ts if args.confirm_ts is not None else now_ts)
        engine.record_confirmation(args.confirm, confirm_tool, confirm_token, confirm_ts)
        print(
            json.dumps(
                {
                    "ok": True,
                    "recorded_confirmation": {
                        "incident_id": args.confirm,
                        "tool_name": confirm_tool,
                        "token": confirm_token,
                        "ts": confirm_ts,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    if not args.condition or not args.tool:
        if args.confirm:
            return
        parser.error("--condition and --tool are required unless using only --confirm")

    incident_id = args.confirm or args.incident_id
    req = ActionRequest(
        incident_id=incident_id,
        watch_condition=args.condition,
        tool_name=args.tool,
        args={},
        source=args.source,
        stt_confidence=args.stt,
        foreground_process=args.foreground,
        now_ts=now_ts,
        user_confirm_token=args.token or args.confirm_token,
    )
    decision = engine.evaluate(req)
    print(
        json.dumps(
            {
                "request": {
                    "incident_id": req.incident_id,
                    "watch_condition": req.watch_condition,
                    "tool_name": req.tool_name,
                    "stt_confidence": req.stt_confidence,
                    "foreground_process": req.foreground_process,
                    "now_ts": req.now_ts,
                    "token": req.user_confirm_token,
                },
                "decision": decision.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
