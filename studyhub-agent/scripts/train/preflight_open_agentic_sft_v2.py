#!/usr/bin/env python3
"""Fail-closed preflight for the controlled Open-Agentic 9B SFT run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
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
    parser.add_argument("--mode", choices=("smoke", "formal"), required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/train/open-agentic-sft-v2-qwen35-9b.yaml",
    )
    parser.add_argument(
        "--mixed-config",
        type=Path,
        default=PROJECT_ROOT / "configs/train/runtime-sft-v3-qwen35-9b.yaml",
    )
    parser.add_argument(
        "--program",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v3/open-agentic-sft-v2.json",
    )
    parser.add_argument(
        "--authorization",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v3/open-agentic-sft-v2-authorization.json",
    )
    parser.add_argument(
        "--smoke-marker",
        type=Path,
        default=(
            PROJECT_ROOT
            / "artifacts/areal/checkpoints"
            / os.environ.get("USER", "chengjin")
            / "studyhub-open-agentic-sft-v2-9b"
            / "open-agentic-sft-v2-smoke-r16-seed-20260827"
            / "OPEN_AGENTIC_SFT_V2_SMOKE_PASS.json"
        ),
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

    paths = {
        "program_sha256": args.program,
        "config_sha256": args.config,
        "dataset_manifest_sha256": (PROJECT_ROOT / "datasets/processed/open_agentic_sft_v2_qwen35_9b/manifest.json"),
        "selected_jsonl_sha256": (PROJECT_ROOT / "datasets/interim/open_agentic_sft_v2/selected.jsonl"),
        "selected_manifest_sha256": (PROJECT_ROOT / "datasets/interim/open_agentic_sft_v2/selected.manifest.json"),
        "data_card_sha256": PROJECT_ROOT / "docs/training/OPEN_AGENTIC_SFT_V2_DATA_CARD.md",
        "data_audit_sha256": (PROJECT_ROOT / "docs/training/evidence/open-agentic-sft-v2-data-audit.json"),
        "semantic_audit_sha256": (PROJECT_ROOT / "docs/training/evidence/open-agentic-sft-v2-semantic-dedup.json"),
        "candidate_semantic_audit_sha256": (
            PROJECT_ROOT / "docs/training/evidence/open-agentic-sft-v2-candidate-semantic-dedup.json"
        ),
        "source_registry_sha256": PROJECT_ROOT / "data_registry/open_agentic_sft_v2_sources.json",
        "recovery_gate_sha256": (
            PROJECT_ROOT / "docs/training/evidence/open-only-sft-v1-1-recovery-gate-cadence-210-20260829_163552.json"
        ),
        "benchmark_manifest_sha256": PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json",
    }
    config, _ = load_expr_config(["--config", str(args.config)], SFTConfig)
    mixed, _ = load_expr_config(["--config", str(args.mixed_config)], SFTConfig)
    model = Path(config.actor.path)
    paths["model_config_sha256"] = model / "config.json"
    paths["model_index_sha256"] = model / "model.safetensors.index.json"

    program = load_json(args.program)
    authorization = load_json(args.authorization)
    audit = load_json(paths["data_audit_sha256"])
    semantic = load_json(paths["semantic_audit_sha256"])
    recovery = load_json(paths["recovery_gate_sha256"])
    benchmark = load_json(paths["benchmark_manifest_sha256"])
    dataset_manifest = load_json(paths["dataset_manifest_sha256"])

    if program.get("status") != "DATA_AND_RECOVERY_GATES_PASS_PENDING_SMOKE":
        raise RuntimeError("Open-Agentic program is not ready for smoke")
    if authorization.get("status") != "AUTHORIZED_PENDING_SMOKE_AND_FORMAL_RUN":
        raise RuntimeError("Open-Agentic authorization is not pending")
    for key in (
        "no_rl",
        "no_sealed",
        "no_benchmark_modification",
        "only_training_data_changes",
        "teacher_legacy_disabled",
        "codex_spark_disabled",
        "studyhub_deterministic_fixture_disabled",
    ):
        if authorization.get("scope", {}).get(key) is not True:
            raise RuntimeError(f"authorization scope is missing {key}")

    lineage = authorization["lineage"]
    actual_hashes = {key: sha256(path) for key, path in paths.items()}
    drift = {
        key: {"authorized": lineage.get(key), "actual": value}
        for key, value in actual_hashes.items()
        if lineage.get(key) != value
    }
    if drift:
        raise RuntimeError(f"Open-Agentic lineage drift: {drift}")

    if audit.get("status") != "PASS" or not all(audit.get("gates", {}).values()):
        raise RuntimeError("Open-Agentic data audit is not passing")
    if semantic.get("status") != "PASS" or semantic.get("hard_cross_group_pairs") != 0:
        raise RuntimeError("Open-Agentic semantic dedup audit is not passing")
    if recovery.get("status") != "PASS" or recovery.get("scope", {}).get("formal_training_eligible") is not True:
        raise RuntimeError("cadence-210 recovery gate is not passing")
    required_equivalence = authorization["completion_contract"]["required_recovery_equivalence"]
    if recovery.get("gates", {}).get("R4_final_equivalence", {}).get("status") != required_equivalence:
        raise RuntimeError("recovery equivalence class differs from authorization")
    for gate in ("R1_lr_schedule", "R2_snapshot_integrity", "R3_state_continuity"):
        if recovery.get("gates", {}).get(gate, {}).get("status") != "PASS":
            raise RuntimeError(f"recovery gate is missing {gate}")
    if benchmark.get("status") != "FROZEN_FOR_BASELINE":
        raise RuntimeError("Benchmark v2 is not frozen")

    dataset = load_from_disk(Path(config.train_dataset.path))
    expected_splits = {key: int(value) for key, value in audit["rows"].items() if key != "total"}
    actual_splits = {split: len(dataset[split]) for split in expected_splits}
    if actual_splits != expected_splits:
        raise RuntimeError(f"dataset split drift: {actual_splits}")
    budget = authorization["budget"]
    if len(dataset["train"]) != int(budget["planned_sequences"]):
        raise RuntimeError("controlled sequence budget drift")
    if len(dataset["train"]) // config.train_dataset.batch_size != int(budget["planned_optimizer_updates"]):
        raise RuntimeError("controlled optimizer-update budget drift")
    train_summary = dataset_manifest["summaries"]["train"]
    if int(train_summary["assistant_loss_tokens"]) != int(budget["actual_assistant_loss_tokens"]):
        raise RuntimeError("assistant-loss token budget drift")
    if int(train_summary["total_tokens"]) != int(budget["actual_total_tokens"]):
        raise RuntimeError("total-token budget drift")

    recipe_pairs = {
        "seed": (config.seed, mixed.seed),
        "backend": (config.actor.backend, mixed.actor.backend),
        "dtype": (config.actor.dtype, mixed.actor.dtype),
        "lora_rank": (config.actor.lora_rank, mixed.actor.lora_rank),
        "lora_alpha": (config.actor.lora_alpha, mixed.actor.lora_alpha),
        "target_modules": (list(config.actor.target_modules), list(mixed.actor.target_modules)),
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
        "gradient_clip": (
            config.actor.optimizer.gradient_clipping,
            mixed.actor.optimizer.gradient_clipping,
        ),
        "global_batch_size": (config.train_dataset.batch_size, mixed.train_dataset.batch_size),
        "gpus": (config.cluster.n_gpus_per_node, mixed.cluster.n_gpus_per_node),
    }
    changed = {key: values for key, values in recipe_pairs.items() if values[0] != values[1]}
    if changed or Path(config.actor.path).resolve() != Path(mixed.actor.path).resolve():
        raise RuntimeError(f"non-data controlled variables changed: {changed}")

    scheduler_total_steps = int(authorization["recipe"]["scheduler_total_steps"])
    if (
        os.environ.get("STUDYHUB_AREAL_SCHEDULER_BRIDGE") != "1"
        or int(os.environ.get("STUDYHUB_AREAL_SCHEDULER_TOTAL_STEPS", -1)) != scheduler_total_steps
    ):
        raise RuntimeError("controlled scheduler bridge is not configured")
    finetune_spec = FinetuneSpec(
        total_train_epochs=config.total_train_epochs,
        dataset_size=len(dataset["train"]),
        train_batch_size=config.train_dataset.batch_size,
    )
    if finetune_spec.total_train_steps != scheduler_total_steps:
        raise RuntimeError("scheduler horizon bridge did not take effect")

    if args.mode == "formal":
        if not args.smoke_marker.is_file():
            raise RuntimeError("formal run requires a passing Open-Agentic smoke marker")
        smoke = load_json(args.smoke_marker)
        if (
            smoke.get("status") != "SMOKE_PASS"
            or smoke.get("authorization_sha256") != sha256(args.authorization)
            or smoke.get("dataset_manifest_sha256") != actual_hashes["dataset_manifest_sha256"]
        ):
            raise RuntimeError("Open-Agentic smoke marker has drifted")

    state = gpu_state(args.gpus)
    if state["compute_pids"]:
        raise RuntimeError(f"requested GPUs already have compute processes: {state['compute_pids']}")
    low_memory = [row for row in state["gpus"] if row["memory_free_mib"] < args.min_free_mib]
    if low_memory:
        raise RuntimeError(f"requested GPUs do not meet the free-memory gate: {low_memory}")

    result = {
        "schema_version": "studyhub.open-agentic-sft-preflight.v2",
        "status": "PASS",
        "mode": args.mode,
        "controlled_variable": "training_data",
        "dataset": {
            "splits": actual_splits,
            "total_tokens": train_summary["total_tokens"],
            "assistant_loss_tokens": train_summary["assistant_loss_tokens"],
            "studyhub_custom_rows": 0,
            "action_only_rows": 0,
            "semantic_cross_group_duplicates": 0,
        },
        "recovery": {
            "status": recovery["status"],
            "equivalence": required_equivalence,
        },
        "benchmark": {
            "revision": benchmark["benchmark_revision"],
            "sealed_used": False,
        },
        "training": {
            "smoke_updates": budget["smoke_optimizer_updates"],
            "formal_updates": budget["planned_optimizer_updates"],
            "scheduler_total_steps": scheduler_total_steps,
            "warmup_steps": authorization["recipe"]["warmup_steps"],
        },
        "gpu_state": state,
        "lineage": actual_hashes,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
