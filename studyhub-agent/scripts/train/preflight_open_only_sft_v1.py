#!/usr/bin/env python3
"""Fail-closed preflight for the Open-Only 9B SFT controlled run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROXY_VARIABLES = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def gpu_state(gpus: str) -> dict[str, Any]:
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/train/open-only-sft-v1-qwen35-9b.yaml",
    )
    parser.add_argument(
        "--mixed-config",
        type=Path,
        default=PROJECT_ROOT / "configs/train/runtime-sft-v3-qwen35-9b.yaml",
    )
    parser.add_argument(
        "--program",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v3/open-only-sft-v1.json",
    )
    parser.add_argument(
        "--authorization",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v3/open-only-sft-v1-authorization.json",
    )
    parser.add_argument(
        "--data-card",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v3/open-only-sft-v1-data-card.json",
    )
    parser.add_argument("--gpus", default="0,1")
    parser.add_argument("--min-free-mib", type=int, default=76000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for name in PROXY_VARIABLES:
        os.environ.pop(name, None)

    from areal.api import FinetuneSpec
    from areal.api.cli_args import SFTConfig, load_expr_config

    from datasets import load_from_disk

    config, _ = load_expr_config(["--config", str(args.config)], SFTConfig)
    mixed, _ = load_expr_config(["--config", str(args.mixed_config)], SFTConfig)
    program = load_json(args.program)
    authorization = load_json(args.authorization)
    card = load_json(args.data_card)
    dataset_manifest_path = PROJECT_ROOT / "datasets/processed/open_only_sft_v1_qwen35_9b/manifest.json"
    selected_path = PROJECT_ROOT / "datasets/interim/open_only_sft_v1/selected.jsonl"
    selected_manifest_path = selected_path.with_suffix(".manifest.json")
    source_audit_path = selected_path.parent / "source-audit.json"
    dataset_manifest = load_json(dataset_manifest_path)
    selected_manifest = load_json(selected_manifest_path)
    source_audit = load_json(source_audit_path)
    benchmark_path = PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json"
    benchmark = load_json(benchmark_path)

    if program.get("status") != "AUTHORIZED_PENDING_RUN":
        raise RuntimeError("Open-Only program is not authorized")
    if authorization.get("status") != "AUTHORIZED_PENDING_RUN":
        raise RuntimeError("Open-Only run authorization is not pending")
    if authorization.get("scope", {}).get("only_training_data_changes") is not True:
        raise RuntimeError("the controlled-variable contract is absent")
    for key in ("no_rl", "no_sealed", "no_benchmark_modification"):
        if authorization.get("scope", {}).get(key) is not True:
            raise RuntimeError(f"authorization scope is missing {key}")

    lineage = authorization["lineage"]
    actual_hashes = {
        "program_sha256": sha256(args.program),
        "dataset_manifest_sha256": sha256(dataset_manifest_path),
        "selected_jsonl_sha256": sha256(selected_path),
        "selected_manifest_sha256": sha256(selected_manifest_path),
        "data_card_sha256": sha256(args.data_card),
        "benchmark_manifest_sha256": sha256(benchmark_path),
        "model_config_sha256": sha256(Path(config.actor.path) / "config.json"),
        "model_index_sha256": sha256(Path(config.actor.path) / "model.safetensors.index.json"),
    }
    if "config_sha256" in lineage:
        actual_hashes["config_sha256"] = sha256(args.config)
    drift = {
        key: {"authorized": lineage.get(key), "actual": value}
        for key, value in actual_hashes.items()
        if lineage.get(key) != value
    }
    if drift:
        raise RuntimeError(f"Open-Only lineage drift: {drift}")
    if benchmark.get("status") != "FROZEN_FOR_BASELINE":
        raise RuntimeError("Benchmark v2 is not frozen")
    if card.get("status") != "ACCEPTED_FOR_CONTROLLED_SFT" or card.get("audit", {}).get("status") != "PASS":
        raise RuntimeError("Open-Only data card is not accepted")

    isolation = card["isolation"]
    zero_fields = (
        "studyhub_custom_rows",
        "action_only_rows",
        "benchmark_prompt_overlap",
        "exact_duplicates",
        "near_duplicates",
    )
    if any(int(isolation.get(key, -1)) != 0 for key in zero_fields):
        raise RuntimeError(f"Open-Only isolation gate failed: {isolation}")
    if isolation.get("sealed_exposure") is not False or any(isolation["group_overlap"].values()):
        raise RuntimeError(f"Open-Only split/sealed isolation failed: {isolation}")
    if source_audit.get("status") != "PASS":
        raise RuntimeError("Open-Only source audit is not passing")

    allowed = set(program["allowed_sources"])
    forbidden = tuple(program["forbidden_source_prefixes"])
    source_counts: Counter[str] = Counter()
    with selected_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            source = str(row.get("source_dataset", ""))
            if source not in allowed or source.startswith(forbidden):
                raise RuntimeError(f"forbidden source in selected data: {source}")
            if row.get("trajectory_status") != "complete":
                raise RuntimeError(f"action-only row in selected data: {row.get('id')}")
            source_counts[source] += 1
    if set(source_counts) != allowed:
        raise RuntimeError(f"selected source coverage drift: {dict(source_counts)}")

    dataset = load_from_disk(Path(config.train_dataset.path))
    mixed_dataset = load_from_disk(Path(mixed.train_dataset.path))
    expected_splits = {key: int(value) for key, value in card["rows"].items() if key in dataset}
    actual_splits = {split: len(dataset[split]) for split in expected_splits}
    if actual_splits != expected_splits:
        raise RuntimeError(f"dataset split drift: expected={expected_splits}, actual={actual_splits}")
    budget = authorization["budget"]
    if len(dataset["train"]) != int(budget["planned_sequences"]):
        raise RuntimeError("controlled sequence budget drift")
    if len(dataset["train"]) // config.train_dataset.batch_size != int(budget["planned_optimizer_updates"]):
        raise RuntimeError("controlled optimizer-update budget drift")
    if dataset_manifest["train_assistant_loss_tokens"] != int(budget["projected_assistant_loss_tokens"]):
        raise RuntimeError("controlled assistant-loss token budget drift")
    if selected_manifest["actual_assistant_loss_tokens"] != int(budget["projected_assistant_loss_tokens"]):
        raise RuntimeError("selected and tokenized assistant budgets differ")

    scheduler_total_steps = authorization.get("recipe", {}).get(
        "scheduler_total_steps"
    )
    if scheduler_total_steps is not None:
        scheduler_total_steps = int(scheduler_total_steps)
        mixed_scheduler_total_steps = (
            len(mixed_dataset["train"]) // mixed.train_dataset.batch_size
        )
        if scheduler_total_steps != mixed_scheduler_total_steps:
            raise RuntimeError(
                "scheduler horizon does not match the Mixed control: "
                f"authorized={scheduler_total_steps}, mixed={mixed_scheduler_total_steps}"
            )
        if int(program.get("recipe", {}).get("scheduler_total_steps", -1)) != scheduler_total_steps:
            raise RuntimeError("program and authorization scheduler horizons differ")
        if os.environ.get("STUDYHUB_AREAL_SCHEDULER_BRIDGE") != "1":
            raise RuntimeError("the controlled scheduler bridge is not enabled")
        if int(os.environ.get("STUDYHUB_AREAL_SCHEDULER_TOTAL_STEPS", -1)) != scheduler_total_steps:
            raise RuntimeError("runtime scheduler horizon differs from authorization")
        finetune_spec = FinetuneSpec(
            total_train_epochs=config.total_train_epochs,
            dataset_size=len(dataset["train"]),
            train_batch_size=config.train_dataset.batch_size,
        )
        if finetune_spec.total_train_steps != scheduler_total_steps:
            raise RuntimeError(
                "scheduler bridge did not override FinetuneSpec.total_train_steps"
            )

    recipe_pairs = {
        "seed": (config.seed, mixed.seed),
        "backend": (config.actor.backend, mixed.actor.backend),
        "dtype": (config.actor.dtype, mixed.actor.dtype),
        "lora_rank": (config.actor.lora_rank, mixed.actor.lora_rank),
        "lora_alpha": (config.actor.lora_alpha, mixed.actor.lora_alpha),
        "target_modules": (list(config.actor.target_modules), list(mixed.actor.target_modules)),
        "max_tokens_per_mb": (config.actor.mb_spec.max_tokens_per_mb, mixed.actor.mb_spec.max_tokens_per_mb),
        "optimizer": (config.actor.optimizer.type, mixed.actor.optimizer.type),
        "lr": (config.actor.optimizer.lr, mixed.actor.optimizer.lr),
        "weight_decay": (config.actor.optimizer.weight_decay, mixed.actor.optimizer.weight_decay),
        "beta1": (config.actor.optimizer.beta1, mixed.actor.optimizer.beta1),
        "beta2": (config.actor.optimizer.beta2, mixed.actor.optimizer.beta2),
        "eps": (config.actor.optimizer.eps, mixed.actor.optimizer.eps),
        "scheduler": (config.actor.optimizer.lr_scheduler_type, mixed.actor.optimizer.lr_scheduler_type),
        "warmup": (
            config.actor.optimizer.warmup_steps_proportion,
            mixed.actor.optimizer.warmup_steps_proportion,
        ),
        "gradient_clip": (config.actor.optimizer.gradient_clipping, mixed.actor.optimizer.gradient_clipping),
        "global_batch_size": (config.train_dataset.batch_size, mixed.train_dataset.batch_size),
        "gpus": (config.cluster.n_gpus_per_node, mixed.cluster.n_gpus_per_node),
    }
    changed = {key: values for key, values in recipe_pairs.items() if values[0] != values[1]}
    if changed:
        raise RuntimeError(f"non-data controlled variables changed: {changed}")
    if Path(config.actor.path).resolve() != Path(mixed.actor.path).resolve():
        raise RuntimeError("base model path differs from the Mixed control")
    if dataset_manifest["tokenizer_revision"] != program["recipe"]["model_revision"]:
        raise RuntimeError("tokenizer/model revision drift")

    state = gpu_state(args.gpus)
    if state["compute_pids"]:
        raise RuntimeError(f"requested GPUs already have compute processes: {state['compute_pids']}")
    low_memory = [row for row in state["gpus"] if row["memory_free_mib"] < args.min_free_mib]
    if low_memory:
        raise RuntimeError(f"requested GPUs do not meet the free-memory gate: {low_memory}")

    result = {
        "schema_version": "studyhub.open-only-sft-preflight.v1",
        "status": "PASS",
        "controlled_variable": "training_data",
        "dataset": {
            "id": card["dataset_id"],
            "splits": actual_splits,
            "sources": dict(sorted(source_counts.items())),
            "train_assistant_loss_tokens": dataset_manifest["train_assistant_loss_tokens"],
            "target_delta": selected_manifest["assistant_loss_token_delta"],
            "studyhub_custom_rows": 0,
            "action_only_rows": 0,
        },
        "benchmark": {
            "version": benchmark["benchmark_version"],
            "revision": benchmark["benchmark_revision"],
            "sha256": actual_hashes["benchmark_manifest_sha256"],
            "training_rows_used": 0,
            "sealed_used": False,
        },
        "training": {
            "updates": budget["planned_optimizer_updates"],
            "sequences": budget["planned_sequences"],
            "backend": config.actor.backend,
            "dtype": config.actor.dtype,
            "lora_rank": config.actor.lora_rank,
            "lora_alpha": config.actor.lora_alpha,
            "target_modules": list(config.actor.target_modules),
            "global_batch_size": config.train_dataset.batch_size,
            "scheduler_total_steps": scheduler_total_steps,
            "natural_open_only_steps": len(dataset["train"])
            // config.train_dataset.batch_size,
            "mixed_reference_steps": len(mixed_dataset["train"])
            // mixed.train_dataset.batch_size,
        },
        "gpu_state": state,
        "lineage": actual_hashes,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
