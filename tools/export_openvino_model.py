from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a Hugging Face causal LM to OpenVINO with a compatibility patch for optimum-intel + OpenVINO 2026.")
    parser.add_argument("--model-id", required=True, help="Hugging Face model id or local source path.")
    parser.add_argument("--output", required=True, help="Destination directory.")
    parser.add_argument("--task", default="text-generation-with-past", help="Export task.")
    parser.add_argument("--weight-format", default="int4", choices=["fp32", "fp16", "int8", "int4"], help="Weight format.")
    parser.add_argument("--group-size", type=int, default=128, help="Quantization group size.")
    parser.add_argument("--ratio", type=float, default=1.0, help="Int4/int8 mixed ratio. 1.0 means full int4.")
    parser.add_argument("--trust-remote-code", action="store_true", help="Allow model-side custom code.")
    parser.add_argument("--convert-tokenizer", action="store_true", default=True, help="Export OpenVINO tokenizer models too.")
    parser.add_argument("--no-convert-tokenizer", dest="convert_tokenizer", action="store_false", help="Skip tokenizer export.")
    args = parser.parse_args()

    import openvino

    # optimum-intel 1.26.x expects openvino.runtime to exist. OpenVINO 2026
    # exports Model/CompiledModel at top-level, so provide the old alias.
    if not hasattr(openvino, "runtime"):
        openvino.runtime = openvino  # type: ignore[attr-defined]

    from optimum.exporters.openvino import main_export
    from optimum.intel.openvino.configuration import OVConfig, OVWeightQuantizationConfig

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    quant_config = OVWeightQuantizationConfig(
        bits=4 if args.weight_format == "int4" else 8,
        group_size=args.group_size,
        ratio=args.ratio,
        trust_remote_code=args.trust_remote_code,
    )
    ov_config = OVConfig(quantization_config=quant_config, dtype=args.weight_format)

    main_export(
        model_name_or_path=args.model_id,
        output=output_dir,
        task=args.task,
        trust_remote_code=args.trust_remote_code,
        ov_config=ov_config,
        convert_tokenizer=args.convert_tokenizer,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
