#!/usr/bin/env python3
"""Fail-closed preflight for M1 -> Codex-Hermes Qwen3.5-4B SFT-2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
        "compute_pids": [
            int(value.strip()) for value in processes if value.strip().isdigit()
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "formal"), required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--smoke-marker", type=Path)
    parser.add_argument("--gpus", default="0,1")
    parser.add_argument("--min-free-mib", type=int, default=76000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for name in (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
    ):
        os.environ.pop(name, None)

    from areal.api import FinetuneSpec
    from areal.api.cli_args import SFTConfig, load_expr_config

    from datasets import load_from_disk

    config, _ = load_expr_config(["--config", str(args.config)], SFTConfig)
    authorization = load_json(args.authorization)
    if authorization.get("status") != "AUTHORIZED_PENDING_SMOKE_AND_FORMAL_RUN":
        raise RuntimeError("SFT-2 is not authorized")
    scope = authorization.get("scope", {})
    if (
        scope.get("no_spark_runtime_calls") is not True
        and scope.get("no_spark") is not True
    ):
        raise RuntimeError("SFT-2 must not call a teacher provider during training")

    artifact_root = Path(config.cluster.fileroot).resolve().parents[1]
    dataset_id = str(scope.get("dataset_id", "qwen35_4b_sft2_codex_retention_v1"))
    evidence_prefix = str(scope.get("evidence_prefix", "qwen35-4b-sft2"))
    paths = {
        "program_sha256": args.program,
        "config_sha256": args.config,
        "dataset_manifest_sha256": Path(config.train_dataset.path).resolve().parent
        / "manifest.json",
        "selected_jsonl_sha256": artifact_root
        / f"datasets/interim/{dataset_id}/selected.jsonl",
        "selected_manifest_sha256": artifact_root
        / f"datasets/interim/{dataset_id}/selected.manifest.json",
        "data_audit_sha256": artifact_root
        / f"docs/training/evidence/{evidence_prefix}-data-audit.json",
        "semantic_audit_sha256": artifact_root
        / f"docs/training/evidence/{evidence_prefix}-selected-semantic-dedup.json",
        "teacher_audit_sha256": artifact_root
        / f"docs/training/evidence/{evidence_prefix}-teacher-input-audit.json",
        "benchmark_manifest_sha256": PROJECT_ROOT
        / "benchmarks/studyhub-agent-v2/manifest.json",
        "model_lock_sha256": PROJECT_ROOT
        / "docs/training/evidence/qwen35-4b-base-model-lock.json",
        "tokenizer_overlay_sha256": PROJECT_ROOT
        / "docs/training/evidence/qwen35-4b-canonical-tokenizer-overlay.json",
        "tokenizer_parity_sha256": PROJECT_ROOT
        / "docs/training/evidence/qwen35-4b-9b-tokenizer-parity.json",
        "thinking_contract_sha256": PROJECT_ROOT
        / "docs/training/evidence/qwen35-4b-9b-thinking-contract.json",
        "m1_completion_sha256": Path(
            "/data/chengjin/studyhub/studyhub-agent/artifacts/areal/checkpoints/chengjin/"
            "studyhub-qwen35-4b-open-agentic-sft1/"
            "qwen35-4b-sft1-formal-r32-seed-20260827/QWEN35_4B_SFT1_COMPLETE.json"
        ),
    }
    lineage = authorization["lineage"]
    drift = {
        key: {
            "authorized": lineage.get(key),
            "actual": sha256(path) if path.is_file() else "MISSING",
        }
        for key, path in paths.items()
        if not path.is_file() or lineage.get(key) != sha256(path)
    }
    if drift:
        raise RuntimeError(f"SFT-2 lineage drift: {drift}")

    program = load_json(args.program)
    manifest = load_json(paths["dataset_manifest_sha256"])
    audit = load_json(paths["data_audit_sha256"])
    semantic = load_json(paths["semantic_audit_sha256"])
    teacher = load_json(paths["teacher_audit_sha256"])
    benchmark = load_json(paths["benchmark_manifest_sha256"])
    parity = load_json(paths["tokenizer_parity_sha256"])
    thinking = load_json(paths["thinking_contract_sha256"])
    m1 = load_json(paths["m1_completion_sha256"])
    authorized_program = scope.get(
        "program_id", "qwen35-4b-sft2-codex-retention-v1"
    )
    if program.get("program_id") != authorized_program:
        raise RuntimeError("SFT-2 program differs from authorization")
    configured_identities = program["teacher_gate"].get("allowed_teacher_identities")
    if configured_identities is None:
        gate = program["teacher_gate"]
        configured_identities = [
            {
                "source_dataset": gate["source_dataset"],
                "interface": gate["required_teacher_interface"],
                "model": gate["required_teacher_model"],
            }
        ]
    authorized_identities = scope.get("teacher_identities")
    if authorized_identities is None:
        authorized_identities = [
            {
                "source_dataset": program["teacher_gate"]["source_dataset"],
                "interface": scope.get("teacher_interface"),
                "model": scope.get("teacher_model"),
            }
        ]
    if configured_identities != authorized_identities:
        raise RuntimeError("SFT-2 teacher identity allowlist drift")
    if teacher.get("status") != "PASS" or audit.get("status") != "PASS":
        raise RuntimeError("SFT-2 teacher/data audit is not passing")
    if semantic.get("status") != "PASS":
        raise RuntimeError("SFT-2 semantic audit is not passing")
    if benchmark.get("status") != "FROZEN_FOR_BASELINE":
        raise RuntimeError("Benchmark v2 is not frozen")
    if (
        parity.get("status") != "PASS"
        or parity.get("canonical_opd_allowed") is not True
    ):
        raise RuntimeError("4B/9B tokenizer parity is not proven")
    if thinking.get("enable_thinking") is not False:
        raise RuntimeError("non-thinking contract drift")
    if m1.get("status") != "COMPLETE" or m1.get("sealed_used") is not False:
        raise RuntimeError("M1 completion marker is invalid")

    adapter_dir = Path(lineage["m1_adapter_path"]).resolve()
    adapter_weights = adapter_dir / "adapter_model.safetensors"
    if (
        os.environ.get("STUDYHUB_AREAL_INITIAL_ADAPTER_BRIDGE") != "1"
        or Path(os.environ.get("STUDYHUB_AREAL_INITIAL_ADAPTER", "")).resolve()
        != adapter_dir
        or sha256(adapter_weights) != lineage["m1_adapter_sha256"]
    ):
        raise RuntimeError("M1 adapter continuation bridge is not locked")

    dataset = load_from_disk(Path(config.train_dataset.path))
    actual_splits = {split: len(dataset[split]) for split in manifest["split_counts"]}
    if actual_splits != manifest["split_counts"]:
        raise RuntimeError(f"SFT-2 dataset split drift: {actual_splits}")
    budget = authorization["budget"]
    train = manifest["summaries"]["train"]
    if len(dataset["train"]) != budget["planned_sequences"]:
        raise RuntimeError("SFT-2 sequence budget drift")
    if int(train["assistant_loss_tokens"]) != int(
        budget["actual_assistant_loss_tokens"]
    ):
        raise RuntimeError("SFT-2 assistant-token budget drift")

    recipe = authorization["recipe"]
    actual_recipe = {
        "backend": config.actor.backend,
        "dtype": config.actor.dtype,
        "lora_rank": config.actor.lora_rank,
        "lora_alpha": config.actor.lora_alpha,
        "target_modules": list(config.actor.target_modules),
        "learning_rate": config.actor.optimizer.lr,
        "weight_decay": config.actor.optimizer.weight_decay,
        "beta1": config.actor.optimizer.beta1,
        "beta2": config.actor.optimizer.beta2,
        "eps": config.actor.optimizer.eps,
        "scheduler": config.actor.optimizer.lr_scheduler_type,
        "warmup_fraction": config.actor.optimizer.warmup_steps_proportion,
        "gradient_clip": config.actor.optimizer.gradient_clipping,
        "seed": config.seed,
    }
    mismatch = {
        key: (actual_recipe[key], recipe[key])
        for key in actual_recipe
        if actual_recipe[key] != recipe[key]
    }
    if mismatch or config.train_dataset.batch_size != budget["global_batch_size"]:
        raise RuntimeError(f"SFT-2 recipe drift: {mismatch}")
    scheduler_total_steps = int(recipe["scheduler_total_steps"])
    if (
        os.environ.get("STUDYHUB_AREAL_SCHEDULER_BRIDGE") != "1"
        or int(os.environ.get("STUDYHUB_AREAL_SCHEDULER_TOTAL_STEPS", -1))
        != scheduler_total_steps
    ):
        raise RuntimeError("SFT-2 scheduler bridge is not configured")
    spec = FinetuneSpec(
        total_train_epochs=config.total_train_epochs,
        dataset_size=len(dataset["train"]),
        train_batch_size=config.train_dataset.batch_size,
    )
    if spec.total_train_steps != scheduler_total_steps:
        raise RuntimeError("SFT-2 dataset does not produce exactly 800 updates")

    if args.mode == "formal":
        if args.smoke_marker is None or not args.smoke_marker.is_file():
            raise RuntimeError("formal SFT-2 requires a passing smoke marker")
        smoke = load_json(args.smoke_marker)
        if (
            smoke.get("status") != "SMOKE_PASS"
            or smoke.get("authorization_sha256") != sha256(args.authorization)
            or smoke.get("m1_initialization_verified") is not True
        ):
            raise RuntimeError("SFT-2 smoke marker has drifted")

    state = gpu_state(args.gpus)
    if state["compute_pids"]:
        raise RuntimeError(
            f"requested GPUs already have compute processes: {state['compute_pids']}"
        )
    low_memory = [
        row for row in state["gpus"] if row["memory_free_mib"] < args.min_free_mib
    ]
    if low_memory:
        raise RuntimeError(f"requested GPUs do not meet memory gate: {low_memory}")
    print(
        json.dumps(
            {
                "schema_version": "studyhub.qwen35-4b-sft2-preflight.v1",
                "status": "PASS",
                "mode": args.mode,
                "teacher_identities": configured_identities,
                "m1_adapter_sha256": lineage["m1_adapter_sha256"],
                "dataset_splits": actual_splits,
                "sealed_used": False,
                "gpu_state": state,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
