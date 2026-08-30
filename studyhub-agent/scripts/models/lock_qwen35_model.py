#!/usr/bin/env python3
"""Create a content-addressed lock for one local Qwen3.5 snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

TOKENIZER_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def aggregate_weight_set(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(f"{record['name']}\0{record['bytes']}\0{record['sha256']}\n".encode())
    return digest.hexdigest()


def build_lock(model: Path, repo_id: str, revision: str, license_spdx: str) -> dict[str, Any]:
    model = model.resolve()
    config_path = model / "config.json"
    index_path = model / "model.safetensors.index.json"
    license_path = model / "LICENSE"
    required = [config_path, index_path, license_path, *(model / name for name in TOKENIZER_FILES)]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"incomplete model snapshot; missing={missing}")

    index = json.loads(index_path.read_text(encoding="utf-8"))
    shard_names = sorted(set(index.get("weight_map", {}).values()))
    if not shard_names:
        raise RuntimeError("model index contains no weight shards")
    shard_paths = [model / name for name in shard_names]
    missing_shards = [str(path) for path in shard_paths if not path.is_file() or path.stat().st_size == 0]
    if missing_shards:
        raise RuntimeError(f"missing or empty weight shards: {missing_shards}")

    weights = [{"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)} for path in shard_paths]
    tokenizer = {
        name: {"bytes": (model / name).stat().st_size, "sha256": sha256(model / name)} for name in TOKENIZER_FILES
    }
    tokenizer_config = json.loads((model / "tokenizer_config.json").read_text(encoding="utf-8"))
    template_path = model / "chat_template.jinja"
    embedded_template = tokenizer_config.get("chat_template")
    if template_path.is_file():
        template = template_path.read_text(encoding="utf-8")
        template_source = "chat_template.jinja"
        tokenizer[template_path.name] = {
            "bytes": template_path.stat().st_size,
            "sha256": sha256(template_path),
        }
        if isinstance(embedded_template, str) and embedded_template != template:
            raise RuntimeError("chat_template.jinja differs from tokenizer_config.json")
    elif isinstance(embedded_template, str) and embedded_template:
        template = embedded_template
        template_source = "tokenizer_config.json:chat_template"
    else:
        raise RuntimeError("model snapshot has no effective chat template")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("model_type") != "qwen3_5":
        raise RuntimeError(f"unexpected model_type: {config.get('model_type')}")

    return {
        "schema_version": "studyhub.qwen35-model-lock.v1",
        "status": "LOCKED",
        "repo_id": repo_id,
        "resolved_revision": revision,
        "local_path": str(model),
        "model_type": config["model_type"],
        "config_sha256": sha256(config_path),
        "model_index_sha256": sha256(index_path),
        "weight_shards": weights,
        "aggregate_weight_set_sha256": aggregate_weight_set(weights),
        "tokenizer_files": tokenizer,
        "chat_template": {
            "source": template_source,
            "sha256": hashlib.sha256(template.encode()).hexdigest(),
            "characters": len(template),
        },
        "license": {
            "spdx": license_spdx,
            "file": "LICENSE",
            "sha256": sha256(license_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--license", default="Apache-2.0")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    value = build_lock(args.model, args.repo_id, args.revision, args.license)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
