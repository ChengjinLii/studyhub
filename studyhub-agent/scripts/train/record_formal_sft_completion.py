#!/usr/bin/env python3
"""Write a fail-closed completion marker for one resumable formal SFT trial."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

GLOBAL_STEP = re.compile(r"globalstep(\d+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return value


def override_value(metadata: dict[str, Any], key: str) -> str | None:
    prefix = f"{key}="
    for item in metadata.get("config", {}).get("overrides", []):
        if str(item).startswith(prefix):
            return str(item)[len(prefix) :]
    return None


def final_adapter(checkpoint_root: Path) -> tuple[int, Path]:
    candidates: list[tuple[int, Path]] = []
    for path in checkpoint_root.rglob("adapter_model.safetensors"):
        match = GLOBAL_STEP.search(str(path))
        if match:
            candidates.append((int(match.group(1)), path))
    if not candidates:
        raise RuntimeError(f"no optimizer checkpoint adapter found under {checkpoint_root}")
    return max(candidates, key=lambda row: row[0])


def build_marker(args: argparse.Namespace) -> dict[str, Any]:
    metadata = load_json(args.run_metadata)
    if metadata.get("exit_status") != 0:
        raise RuntimeError("formal SFT attempt did not exit successfully")
    training_trial = override_value(metadata, "trial_name")
    if not training_trial:
        raise RuntimeError("training trial is absent from run metadata overrides")
    global_step, adapter = final_adapter(args.checkpoint_root)
    expected_final_step = args.expected_updates - 1
    if global_step != expected_final_step:
        raise RuntimeError(f"formal SFT stopped at global step {global_step}; expected {expected_final_step}")
    benchmark = metadata.get("benchmark", {})
    if benchmark.get("status") != "FROZEN_FOR_BASELINE" or benchmark.get("sealed_content_used") is not False:
        raise RuntimeError("formal SFT metadata is not bound to the frozen public Benchmark v2 contract")

    return {
        "schema_version": "studyhub.formal-sft-completion.v1",
        "status": "COMPLETE",
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "training_trial": training_trial,
        "completed_attempt": args.run_metadata.stem.removesuffix(".run"),
        "expected_optimizer_updates": args.expected_updates,
        "final_global_step": global_step,
        "run_metadata": {
            "path": str(args.run_metadata.resolve()),
            "sha256": sha256(args.run_metadata),
        },
        "checkpoint": {
            "path": str(adapter.resolve()),
            "bytes": adapter.stat().st_size,
            "sha256": sha256(adapter),
        },
        "dataset_manifest_sha256": metadata.get("dataset_manifest_sha256"),
        "benchmark_manifest_sha256": benchmark.get("sha256"),
        "git_commit": metadata.get("git", {}).get("commit"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-metadata", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-updates", type=int, required=True)
    args = parser.parse_args()
    if args.expected_updates < 1:
        parser.error("--expected-updates must be positive")
    return args


def main() -> int:
    args = parse_args()
    marker = build_marker(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps(marker, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
