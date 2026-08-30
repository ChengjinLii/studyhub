#!/usr/bin/env python3
"""Bind the 4B SFT-1 run to immutable model, data, benchmark, and protocol locks."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=project / "configs/program-v4/qwen35-4b-sft1-authorization.json",
    )
    args = parser.parse_args()

    paths = {
        "program_sha256": project / "configs/program-v4/qwen35-4b-agent-posttraining.json",
        "config_sha256": project / "configs/train/qwen35-4b-open-agentic-sft1.yaml",
        "dataset_manifest_sha256": project / "datasets/processed/open_agentic_sft_v2_qwen35_9b/manifest.json",
        "selected_jsonl_sha256": project / "datasets/interim/open_agentic_sft_v2/selected.jsonl",
        "selected_manifest_sha256": project / "datasets/interim/open_agentic_sft_v2/selected.manifest.json",
        "data_audit_sha256": project / "docs/training/evidence/open-agentic-sft-v2-data-audit.json",
        "semantic_audit_sha256": project / "docs/training/evidence/open-agentic-sft-v2-semantic-dedup.json",
        "benchmark_manifest_sha256": project / "benchmarks/studyhub-agent-v2/manifest.json",
        "model_lock_sha256": project / "docs/training/evidence/qwen35-4b-base-model-lock.json",
        "tokenizer_overlay_sha256": (project / "docs/training/evidence/qwen35-4b-canonical-tokenizer-overlay.json"),
        "tokenizer_parity_sha256": project / "docs/training/evidence/qwen35-4b-9b-tokenizer-parity.json",
        "thinking_contract_sha256": project / "docs/training/evidence/qwen35-4b-9b-thinking-contract.json",
        "bfcl_holdout_sha256": project / "configs/eval/bfcl-4b-pipeline-holdout-v1.json",
        "tau2_holdout_sha256": project / "configs/eval/tau2-4b-pipeline-holdout-v1.json",
        "recovery_gate_sha256": (
            project / "docs/training/evidence/open-only-sft-v1-1-recovery-gate-cadence-210-20260829_163552.json"
        ),
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"cannot authorize SFT-1; missing locks={missing}")

    model_lock = json.loads(paths["model_lock_sha256"].read_text(encoding="utf-8"))
    overlay = json.loads(paths["tokenizer_overlay_sha256"].read_text(encoding="utf-8"))
    parity = json.loads(paths["tokenizer_parity_sha256"].read_text(encoding="utf-8"))
    thinking = json.loads(paths["thinking_contract_sha256"].read_text(encoding="utf-8"))
    if model_lock.get("status") != "LOCKED":
        raise RuntimeError("4B model lock is not complete")
    if overlay.get("status") != "LOCKED":
        raise RuntimeError("4B canonical tokenizer overlay is not locked")
    if parity.get("status") != "PASS" or parity.get("canonical_opd_allowed") is not True:
        raise RuntimeError("4B/9B tokenizer parity is not passing")
    if thinking.get("enable_thinking") is not False:
        raise RuntimeError("non-thinking contract is not locked")

    value = {
        "schema_version": "studyhub.qwen35-4b-sft1-authorization.v1",
        "authorization_id": "qwen35-4b-base-open-agentic-sft1-r32-seed-20260827",
        "status": "AUTHORIZED_PENDING_SMOKE_AND_FORMAL_RUN",
        "scope": {
            "model": "Qwen/Qwen3.5-4B-Base",
            "method": "AReaL SFT BF16 FSDP2 LoRA",
            "smoke_runs": 1,
            "formal_training_runs": 1,
            "no_main_grpo": True,
            "no_opd_in_sft1": True,
            "no_sealed": True,
            "no_benchmark_modification": True,
            "legacy_teacher_reverse_replay_disabled": True,
        },
        "lineage": {
            **{key: sha256(path) for key, path in paths.items()},
            "model_revision": model_lock["resolved_revision"],
            "model_weight_set_sha256": model_lock["aggregate_weight_set_sha256"],
            "canonical_tokenizer_overlay": overlay["overlay"],
            "run_commit_required": "SET_AT_LAUNCH_FROM_CLEAN_WORKTREE",
        },
        "budget": {
            "global_batch_size": 8,
            "smoke_optimizer_updates": 24,
            "smoke_checkpoint_every_updates": 16,
            "smoke_maximum_wall_time_seconds": 3600,
            "planned_optimizer_updates": 2100,
            "planned_sequences": 16800,
            "actual_total_tokens": 19188650,
            "actual_assistant_loss_tokens": 3107404,
            "checkpoint_every_updates": 210,
            "maximum_wall_time_seconds": 28800,
        },
        "recipe": {
            "backend": "fsdp:d2p1t1",
            "dtype": "bfloat16",
            "lora_rank": 32,
            "lora_alpha": 32,
            "target_modules": ["o_proj", "gate_proj", "up_proj", "down_proj"],
            "learning_rate": 0.00002,
            "weight_decay": 0.05,
            "beta1": 0.9,
            "beta2": 0.95,
            "eps": 0.00001,
            "scheduler": "cosine",
            "scheduler_total_steps": 2100,
            "warmup_fraction": 0.03,
            "warmup_steps": 63,
            "gradient_clip": 1.0,
            "seed": 20260827,
            "enable_thinking": False,
        },
        "completion_contract": {
            "smoke_marker": "QWEN35_4B_SFT1_SMOKE_PASS.json",
            "formal_marker": "QWEN35_4B_SFT1_COMPLETE.json",
            "require_lora_update": True,
            "require_complete_recovery_checkpoint": True,
            "require_exact_lr_schedule_audit": True,
            "expected_scheduler_total_steps": 2100,
            "expected_warmup_steps": 63,
            "require_sealed_used_false": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
