#!/usr/bin/env python3
"""Merge one completed AReaL SFT LoRA adapter into its fixed base checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-shard-size", default="4GB")
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
    from transformers import AutoModelForImageTextToText, AutoTokenizer

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
    tokenizer = AutoTokenizer.from_pretrained(
        args.base,
        local_files_only=True,
        trust_remote_code=True,
    )
    tokenizer.save_pretrained(args.output)
    shards = sorted(args.output.glob("model*.safetensors"))
    if not shards:
        raise RuntimeError("merged checkpoint contains no safetensors weights")
    manifest = {
        "schema_version": "studyhub.merged-sft-checkpoint.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base": str(args.base.resolve()),
        "adapter": str(args.adapter.resolve()),
        "adapter_sha256": sha256(adapter_weights),
        "dtype": "bfloat16",
        "weight_shards": [{"name": path.name, "bytes": path.stat().st_size} for path in shards],
    }
    (args.output / "studyhub_merged_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
