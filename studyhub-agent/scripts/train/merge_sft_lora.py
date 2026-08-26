#!/usr/bin/env python3
"""Merge one completed AReaL LoRA adapter into its fixed base checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


PROCESSOR_CONFIG_FILES = (
    "preprocessor_config.json",
    "video_preprocessor_config.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_model_io_assets(
    base: Path,
    output: Path,
    *,
    tokenizer_class: Any,
    processor_class: Any,
) -> list[str]:
    tokenizer = tokenizer_class.from_pretrained(
        base,
        local_files_only=True,
        trust_remote_code=True,
    )
    tokenizer.save_pretrained(output)

    # Qwen3.5 is a composite vision-language model even for text-only runs.
    # SGLang initializes its processor before serving, so merged checkpoints
    # must preserve the image/video processor configs from the fixed base.
    processor = processor_class.from_pretrained(
        base,
        local_files_only=True,
        trust_remote_code=True,
    )
    processor.save_pretrained(output)
    for component_name in ("image_processor", "video_processor"):
        component = getattr(processor, component_name, None)
        if component is None:
            raise RuntimeError(f"base processor has no {component_name}")
        component.save_pretrained(output)

    missing = [name for name in PROCESSOR_CONFIG_FILES if not (output / name).is_file()]
    if missing:
        raise RuntimeError(f"merged checkpoint is missing processor assets: {missing}")
    return sorted(path.name for path in output.iterdir() if path.is_file())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-shard-size", default="4GB")
    parser.add_argument("--stage", choices=("sft", "grpo"), default="sft")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to replace existing output: {args.output}")
    adapter_weights = args.adapter / "adapter_model.safetensors"
    adapter_config = args.adapter / "adapter_config.json"
    if not adapter_weights.is_file() or not adapter_config.is_file():
        raise FileNotFoundError("adapter_model.safetensors or adapter_config.json is missing")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForImageTextToText, AutoProcessor, AutoTokenizer

    base = AutoModelForImageTextToText.from_pretrained(
        args.base,
        local_files_only=True,
        trust_remote_code=True,
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
        device_map={"": "cpu"},
    )
    peft_model = PeftModel.from_pretrained(base, args.adapter, is_trainable=False)
    merged = peft_model.merge_and_unload(safe_merge=True)
    args.output.mkdir(parents=True)
    merged.save_pretrained(
        args.output,
        safe_serialization=True,
        max_shard_size=args.max_shard_size,
    )
    model_io_assets = save_model_io_assets(
        args.base,
        args.output,
        tokenizer_class=AutoTokenizer,
        processor_class=AutoProcessor,
    )
    shards = sorted(args.output.glob("model*.safetensors"))
    if not shards:
        raise RuntimeError("merged checkpoint contains no safetensors weights")
    manifest = {
        "schema_version": "studyhub.merged-lora-checkpoint.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "training_stage": args.stage,
        "base": str(args.base.resolve()),
        "adapter": str(args.adapter.resolve()),
        "adapter_sha256": sha256(adapter_weights),
        "dtype": "bfloat16",
        "weight_shards": [{"name": path.name, "bytes": path.stat().st_size} for path in shards],
        "model_io_assets": model_io_assets,
    }
    (args.output / "studyhub_merged_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
