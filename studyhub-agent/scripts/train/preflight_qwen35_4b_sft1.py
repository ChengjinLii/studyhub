#!/usr/bin/env python3
"""Fail-closed preflight for Qwen3.5-4B-Base Open-Agentic SFT-1."""

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
        ["nvidia-smi", "-i", gpus, "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
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
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--smoke-marker", type=Path)
    parser.add_argument("--gpus", default="0,1")
    parser.add_argument("--min-free-mib", type=int, default=76000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for name in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        os.environ.pop(name, None)

    from areal.api import FinetuneSpec
    from areal.api.cli_args import SFTConfig, load_expr_config

    from datasets import load_from_disk

    config, _ = load_expr_config(["--config", str(args.config)], SFTConfig)
    model = Path(config.actor.path)
    paths = {
        "program_sha256": args.program,
        "config_sha256": args.config,
        "dataset_manifest_sha256": PROJECT_ROOT / "datasets/processed/open_agentic_sft_v2_qwen35_9b/manifest.json",
        "selected_jsonl_sha256": PROJECT_ROOT / "datasets/interim/open_agentic_sft_v2/selected.jsonl",
        "selected_manifest_sha256": PROJECT_ROOT / "datasets/interim/open_agentic_sft_v2/selected.manifest.json",
        "data_audit_sha256": PROJECT_ROOT / "docs/training/evidence/open-agentic-sft-v2-data-audit.json",
        "semantic_audit_sha256": PROJECT_ROOT / "docs/training/evidence/open-agentic-sft-v2-semantic-dedup.json",
        "benchmark_manifest_sha256": PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json",
        "model_lock_sha256": PROJECT_ROOT / "docs/training/evidence/qwen35-4b-base-model-lock.json",
        "tokenizer_overlay_sha256": (
            PROJECT_ROOT / "docs/training/evidence/qwen35-4b-canonical-tokenizer-overlay.json"
        ),
        "tokenizer_parity_sha256": PROJECT_ROOT / "docs/training/evidence/qwen35-4b-9b-tokenizer-parity.json",
        "thinking_contract_sha256": PROJECT_ROOT / "docs/training/evidence/qwen35-4b-9b-thinking-contract.json",
        "bfcl_holdout_sha256": PROJECT_ROOT / "configs/eval/bfcl-4b-pipeline-holdout-v1.json",
        "tau2_holdout_sha256": PROJECT_ROOT / "configs/eval/tau2-4b-pipeline-holdout-v1.json",
        "recovery_gate_sha256": (
            PROJECT_ROOT / "docs/training/evidence/open-only-sft-v1-1-recovery-gate-cadence-210-20260829_163552.json"
        ),
    }
    authorization = load_json(args.authorization)
    lineage = authorization["lineage"]
    drift = {
        key: {"authorized": lineage.get(key), "actual": sha256(path)}
        for key, path in paths.items()
        if lineage.get(key) != sha256(path)
    }
    if drift:
        raise RuntimeError(f"4B SFT-1 lineage drift: {drift}")

    program = load_json(args.program)
    model_lock = load_json(paths["model_lock_sha256"])
    overlay = load_json(paths["tokenizer_overlay_sha256"])
    parity = load_json(paths["tokenizer_parity_sha256"])
    thinking = load_json(paths["thinking_contract_sha256"])
    audit = load_json(paths["data_audit_sha256"])
    semantic = load_json(paths["semantic_audit_sha256"])
    benchmark = load_json(paths["benchmark_manifest_sha256"])
    dataset_manifest = load_json(paths["dataset_manifest_sha256"])
    bfcl_holdout = load_json(paths["bfcl_holdout_sha256"])
    tau2_holdout = load_json(paths["tau2_holdout_sha256"])

    if program.get("status") != "PHASE_A_LOCKED_PENDING_M0_AND_SFT1":
        raise RuntimeError("4B post-training program has not completed Phase A")
    if authorization.get("status") != "AUTHORIZED_PENDING_SMOKE_AND_FORMAL_RUN":
        raise RuntimeError("4B SFT-1 is not authorized")
    if model_lock.get("status") != "LOCKED":
        raise RuntimeError("4B model lock is incomplete")
    if (
        overlay.get("status") != "LOCKED"
        or Path(overlay["overlay"]).resolve() != model.resolve()
        or Path(overlay["student_weights"]["path"]).resolve() != Path(model_lock["local_path"]).resolve()
    ):
        raise RuntimeError("4B canonical tokenizer overlay does not match actor/base locks")
    if model_lock.get("aggregate_weight_set_sha256") != lineage.get("model_weight_set_sha256"):
        raise RuntimeError("4B weight set drift")
    if parity.get("status") != "PASS" or parity.get("canonical_opd_allowed") is not True:
        raise RuntimeError("canonical OPD tokenizer parity is not proven")
    if thinking.get("enable_thinking") is not False or Path(config.actor.path).resolve() != model.resolve():
        raise RuntimeError("non-thinking/model contract drift")
    if any(
        lock.get("status") != "LOCKED_UNEXPOSED"
        or lock.get("training_access") is not False
        or lock.get("opened_for_model_selection") is not False
        for lock in (bfcl_holdout, tau2_holdout)
    ):
        raise RuntimeError("fresh external holdout is exposed")
    if benchmark.get("status") != "FROZEN_FOR_BASELINE":
        raise RuntimeError("Benchmark v2 is not frozen")
    if audit.get("status") != "PASS" or not all(audit.get("gates", {}).values()):
        raise RuntimeError("Open-Agentic data audit is not passing")
    if semantic.get("status") != "PASS" or semantic.get("hard_cross_group_pairs") != 0:
        raise RuntimeError("Open-Agentic semantic audit is not passing")

    dataset = load_from_disk(Path(config.train_dataset.path))
    expected_splits = dataset_manifest["split_counts"]
    actual_splits = {split: len(dataset[split]) for split in expected_splits}
    if actual_splits != expected_splits:
        raise RuntimeError(f"dataset split drift: {actual_splits}")
    budget = authorization["budget"]
    train_summary = dataset_manifest["summaries"]["train"]
    if len(dataset["train"]) != budget["planned_sequences"]:
        raise RuntimeError("SFT-1 sequence budget drift")
    if train_summary["assistant_loss_tokens"] != budget["actual_assistant_loss_tokens"]:
        raise RuntimeError("SFT-1 assistant-token budget drift")

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
    mismatch = {key: (actual_recipe[key], recipe[key]) for key in actual_recipe if actual_recipe[key] != recipe[key]}
    if mismatch or config.train_dataset.batch_size != budget["global_batch_size"]:
        raise RuntimeError(f"SFT-1 recipe drift: {mismatch}")

    weight_keys = load_json(model / "model.safetensors.index.json")["weight_map"]
    for target in recipe["target_modules"]:
        if not any(key.endswith(f".{target}.weight") for key in weight_keys):
            raise RuntimeError(f"LoRA target absent from 4B language model: {target}")
    if any("visual" in key and any(f".{target}." in key for target in recipe["target_modules"]) for key in weight_keys):
        raise RuntimeError("LoRA target selector would match the vision encoder")

    scheduler_total_steps = int(recipe["scheduler_total_steps"])
    if (
        os.environ.get("STUDYHUB_AREAL_SCHEDULER_BRIDGE") != "1"
        or int(os.environ.get("STUDYHUB_AREAL_SCHEDULER_TOTAL_STEPS", -1)) != scheduler_total_steps
    ):
        raise RuntimeError("SFT-1 scheduler bridge is not configured")
    spec = FinetuneSpec(
        total_train_epochs=config.total_train_epochs,
        dataset_size=len(dataset["train"]),
        train_batch_size=config.train_dataset.batch_size,
    )
    if spec.total_train_steps != scheduler_total_steps:
        raise RuntimeError("SFT-1 scheduler horizon drift")

    if args.mode == "formal":
        if args.smoke_marker is None or not args.smoke_marker.is_file():
            raise RuntimeError("formal SFT-1 requires a passing smoke marker")
        smoke = load_json(args.smoke_marker)
        if smoke.get("status") != "SMOKE_PASS" or smoke.get("authorization_sha256") != sha256(args.authorization):
            raise RuntimeError("SFT-1 smoke marker has drifted")

    state = gpu_state(args.gpus)
    if state["compute_pids"]:
        raise RuntimeError(f"requested GPUs already have compute processes: {state['compute_pids']}")
    low_memory = [row for row in state["gpus"] if row["memory_free_mib"] < args.min_free_mib]
    if low_memory:
        raise RuntimeError(f"requested GPUs do not meet memory gate: {low_memory}")

    print(
        json.dumps(
            {
                "schema_version": "studyhub.qwen35-4b-sft1-preflight.v1",
                "status": "PASS",
                "mode": args.mode,
                "model": model_lock["repo_id"],
                "model_revision": model_lock["resolved_revision"],
                "tokenizer_parity": parity["status"],
                "thinking_enabled": False,
                "dataset_splits": actual_splits,
                "fresh_holdouts_opened": False,
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
