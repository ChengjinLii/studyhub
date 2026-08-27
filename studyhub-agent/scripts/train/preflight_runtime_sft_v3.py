#!/usr/bin/env python3
"""Fail-closed preflight for the accepted 9B runtime-native SFT v3 dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from scripts.train.validate_v3_program import validate_program

PROXY_VARIABLES = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _gpu_state(gpus: str) -> dict[str, Any]:
    rows = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            gpus,
            "--query-gpu=index,memory.free,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    processes = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            gpus,
            "--query-compute-apps=pid",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {
        "gpus": [
            {
                "index": int(values[0]),
                "memory_free_mib": int(values[1]),
                "memory_used_mib": int(values[2]),
                "utilization_gpu_pct": int(values[3]),
            }
            for row in rows
            if (values := [part.strip() for part in row.split(",")])
        ],
        "compute_pids": [int(value.strip()) for value in processes if value.strip().isdigit()],
    }


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=project / "configs/train/runtime-sft-v3-qwen35-9b.yaml",
    )
    parser.add_argument(
        "--data-card",
        type=Path,
        default=project / "configs/program-v3/runtime-sft-v3-data-card.json",
    )
    parser.add_argument("--gpus")
    parser.add_argument("--min-free-mib", type=int, default=76000)
    parser.add_argument("--lora-rank", type=int)
    parser.add_argument("--lora-alpha", type=int)
    parser.add_argument("--formal", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = Path(__file__).resolve().parents[2]
    errors, program_summary = validate_program(project, check_local_assets=True)
    if errors:
        raise RuntimeError("v3 program validation failed: " + "; ".join(errors))

    for name in PROXY_VARIABLES:
        os.environ.pop(name, None)

    from areal.api.cli_args import SFTConfig, load_expr_config

    from datasets import load_from_disk

    config, _ = load_expr_config(["--config", str(args.config)], SFTConfig)
    effective_lora_rank = args.lora_rank if args.lora_rank is not None else config.actor.lora_rank
    effective_lora_alpha = args.lora_alpha if args.lora_alpha is not None else config.actor.lora_alpha
    if effective_lora_rank <= 0 or effective_lora_alpha <= 0:
        raise RuntimeError("effective LoRA rank and alpha must be positive")
    card = _load(args.data_card)
    benchmark_manifest_path = project / "benchmarks/studyhub-agent-v2/manifest.json"
    benchmark_quality_path = project / "benchmarks/studyhub-agent-v2/quality-gate.json"
    benchmark_manifest = _load(benchmark_manifest_path)
    benchmark_quality = _load(benchmark_quality_path)
    benchmark_manifest_sha256 = _sha256(benchmark_manifest_path)
    card_isolation = card.get("isolation", {})
    if benchmark_manifest.get("status") != "FROZEN_FOR_BASELINE":
        raise RuntimeError("StudyHub AgentBench v2 is not frozen")
    if benchmark_quality.get("status") != "PASS":
        raise RuntimeError("StudyHub AgentBench v2 quality gate is not passing")
    if benchmark_manifest_sha256 != card_isolation.get("benchmark_manifest_sha256"):
        raise RuntimeError("SFT data is not bound to the frozen Benchmark v2 manifest")
    if card_isolation.get("benchmark_prompt_overlap") != 0:
        raise RuntimeError("SFT data overlaps a Benchmark v2 prompt")
    dataset_root = Path(config.train_dataset.path)
    dataset = load_from_disk(dataset_root)
    expected_splits = {
        "train": card["rows"]["train"],
        "validation": card["rows"]["validation"],
        "protocol_holdout": card["rows"]["protocol_holdout"],
    }
    actual_splits = {split: len(dataset[split]) for split in expected_splits}
    if actual_splits != expected_splits:
        raise RuntimeError(f"dataset split drift: expected={expected_splits}, actual={actual_splits}")
    if config.cluster.n_gpus_per_node != 2 or config.actor.backend != "fsdp:d2p1t1":
        raise RuntimeError("runtime SFT v3 must use the pinned dual-H100 FSDP layout")
    if not config.actor.use_lora or config.actor.dtype != "bfloat16":
        raise RuntimeError("runtime SFT v3 requires BF16 LoRA")
    if config.actor.mb_spec.max_tokens_per_mb < card["tokenization"]["token_length"]["max"]:
        raise RuntimeError("microbatch token cap is below the longest accepted trajectory")
    if args.formal:
        formal = program_summary.get("formal_sft", {})
        if program_summary.get("launch_authorized") is not True:
            raise RuntimeError("formal SFT is not authorized by the machine-readable program")
        if effective_lora_rank != 16 or effective_lora_alpha != 16:
            raise RuntimeError("formal SFT must use the selected r16/alpha16 recipe")
        if formal.get("expected_optimizer_updates") != len(dataset["train"]) // config.train_dataset.batch_size:
            raise RuntimeError("formal SFT optimizer budget does not match the accepted train split")

    model_path = Path(config.actor.path)
    weight_index = _load(model_path / "model.safetensors.index.json")
    weight_names = tuple(weight_index.get("weight_map", {}))
    missing_modules = [
        module for module in config.actor.target_modules if not any(f".{module}." in name for name in weight_names)
    ]
    if missing_modules:
        raise RuntimeError(f"LoRA targets are absent from Qwen3.5-9B: {missing_modules}")

    gpu_state = None
    if args.gpus:
        gpu_state = _gpu_state(args.gpus)
        if gpu_state["compute_pids"]:
            raise RuntimeError(f"requested GPUs already have compute processes: {gpu_state['compute_pids']}")
        low_memory = [row for row in gpu_state["gpus"] if row["memory_free_mib"] < args.min_free_mib]
        if low_memory:
            raise RuntimeError(f"requested GPUs do not meet the free-memory gate: {low_memory}")

    result = {
        "schema_version": "studyhub.runtime-sft-preflight.v3",
        "status": "PASS",
        "program": program_summary,
        "dataset": {
            "id": card["dataset_id"],
            "rows": actual_splits,
            "all_tokens": card["tokenization"]["all_tokens"],
            "audit": card["audit"]["status"],
            "benchmark_prompt_overlap": card_isolation["benchmark_prompt_overlap"],
        },
        "benchmark": {
            "version": benchmark_manifest["benchmark_version"],
            "revision": benchmark_manifest["benchmark_revision"],
            "status": benchmark_manifest["status"],
            "manifest_sha256": benchmark_manifest_sha256,
            "quality_gate": benchmark_quality["status"],
            "training_rows_used": 0,
            "sealed_content_used": False,
        },
        "training": {
            "backend": config.actor.backend,
            "gpus": config.cluster.n_gpus_per_node,
            "dtype": config.actor.dtype,
            "lora_rank": effective_lora_rank,
            "lora_alpha": effective_lora_alpha,
            "override_applied": args.lora_rank is not None or args.lora_alpha is not None,
            "target_modules": list(config.actor.target_modules),
            "max_tokens_per_microbatch": config.actor.mb_spec.max_tokens_per_mb,
            "global_batch_size": config.train_dataset.batch_size,
            "formal": args.formal,
        },
        "gpu_state": gpu_state,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
