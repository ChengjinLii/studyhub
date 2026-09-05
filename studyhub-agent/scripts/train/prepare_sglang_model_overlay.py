#!/usr/bin/env python3
"""Create a traceable SGLang-only overlay for composite Qwen3.5 configs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

LORA_CONFIG_FIELDS = (
    "vocab_size",
    "hidden_size",
    "num_hidden_layers",
    "intermediate_size",
    "num_attention_heads",
    "num_key_value_heads",
    "head_dim",
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def prepare_overlay(model: Path, output: Path) -> dict[str, object]:
    model = model.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config_path = model / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    text_config = config.get("text_config")
    if config.get("model_type") != "qwen3_5" or not isinstance(text_config, dict):
        raise ValueError(f"expected a composite Qwen3.5 config: {config_path}")
    if text_config.get("model_type", "qwen3_5_text") != "qwen3_5_text" or any(
        text_config.get(name) not in (None, 0, 1) for name in ("num_experts", "num_local_experts", "n_routed_experts")
    ):
        raise ValueError("dense Qwen3.5 overlay must not rewrite a MoE architecture")
    # Pinned SGLang's dense text config inherits Qwen3Next's 512-expert default.
    # The dense forward path is correct, but LoRAMemoryPool misclassifies its MLP.
    text_config["num_experts"] = 1

    mapped = {}
    for name in LORA_CONFIG_FIELDS:
        if name not in text_config:
            raise KeyError(f"text_config.{name} is missing from {config_path}")
        config[name] = text_config[name]
        mapped[name] = text_config[name]

    for source in model.iterdir():
        if source.name in {"config.json", "studyhub_download_manifest.json", ".cache"}:
            continue
        destination = output / source.name
        if destination.is_symlink() and destination.resolve() == source.resolve():
            continue
        if destination.exists() or destination.is_symlink():
            if destination.is_dir() and not destination.is_symlink():
                raise RuntimeError(f"refusing to replace overlay directory: {destination}")
            destination.unlink()
        destination.symlink_to(source)

    config_payload = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode()
    (output / "config.json").write_bytes(config_payload)
    manifest = {
        "schema_version": "studyhub.sglang-model-overlay.v1",
        "base_model": str(model),
        "base_config_sha256": sha256_bytes(config_path.read_bytes()),
        "overlay_config_sha256": sha256_bytes(config_payload),
        "mapped_text_config_fields": mapped,
        "dense_lora_num_experts": 1,
        "weight_files_are_symlinks": True,
    }
    (output / "studyhub_sglang_overlay_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = prepare_overlay(args.model, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
