#!/usr/bin/env python3
"""Authorize M1 -> Codex-Hermes SFT-2 against immutable local evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ROOT = Path("/data/chengjin/studyhub/studyhub-agent")


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


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, default=CANONICAL_ROOT)
    parser.add_argument(
        "--program",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v4/sft2-codex-retention-v1.json",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/train/qwen35-4b-codex-sft2.yaml",
    )
    parser.add_argument(
        "--dataset-id", default="qwen35_4b_sft2_codex_retention_v1"
    )
    parser.add_argument("--evidence-prefix", default="qwen35-4b-sft2")
    parser.add_argument(
        "--m1-marker",
        type=Path,
        default=(
            CANONICAL_ROOT
            / "artifacts/areal/checkpoints/chengjin/studyhub-qwen35-4b-open-agentic-sft1"
            "/qwen35-4b-sft1-formal-r32-seed-20260827/QWEN35_4B_SFT1_COMPLETE.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v4/qwen35-4b-sft2-authorization.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_root = args.artifact_root.resolve()
    paths = {
        "program_sha256": args.program,
        "config_sha256": args.config,
        "dataset_manifest_sha256": artifact_root
        / f"datasets/processed/{args.dataset_id}/manifest.json",
        "selected_jsonl_sha256": artifact_root
        / f"datasets/interim/{args.dataset_id}/selected.jsonl",
        "selected_manifest_sha256": artifact_root
        / f"datasets/interim/{args.dataset_id}/selected.manifest.json",
        "data_audit_sha256": artifact_root
        / f"docs/training/evidence/{args.evidence_prefix}-data-audit.json",
        "semantic_audit_sha256": artifact_root
        / f"docs/training/evidence/{args.evidence_prefix}-selected-semantic-dedup.json",
        "teacher_audit_sha256": artifact_root
        / f"docs/training/evidence/{args.evidence_prefix}-teacher-input-audit.json",
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
        "m1_completion_sha256": args.m1_marker,
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"cannot authorize SFT-2; missing evidence={missing}")

    program = load_json(paths["program_sha256"])
    manifest = load_json(paths["dataset_manifest_sha256"])
    data_audit = load_json(paths["data_audit_sha256"])
    semantic_audit = load_json(paths["semantic_audit_sha256"])
    teacher_audit = load_json(paths["teacher_audit_sha256"])
    m1 = load_json(args.m1_marker)
    if m1.get("status") != "COMPLETE" or m1.get("mode") != "formal":
        raise RuntimeError("M1 has no valid formal completion marker")
    m1_adapter = Path(str(m1.get("checkpoint", {}).get("path", ""))).resolve()
    if not m1_adapter.is_file() or sha256(m1_adapter) != m1["checkpoint"]["sha256"]:
        raise RuntimeError(
            "M1 adapter is missing or differs from its completion marker"
        )
    if teacher_audit.get("status") != "PASS":
        raise RuntimeError("Codex-Hermes teacher data did not pass its hard gate")
    if data_audit.get("status") != "PASS" or not all(
        data_audit.get("gates", {}).values()
    ):
        raise RuntimeError("SFT-2 data audit is not passing")
    if semantic_audit.get("status") != "PASS":
        raise RuntimeError("SFT-2 semantic dedup audit is not passing")
    if manifest.get("status") != "TOKENIZED_PENDING_FINAL_DATA_GATE":
        raise RuntimeError("SFT-2 tokenized manifest status is invalid")

    train = manifest["summaries"]["train"]
    selected_rows = int(manifest["split_counts"]["train"])
    if selected_rows != int(program["selection"]["target_train_rows"]):
        raise RuntimeError("SFT-2 selected train rows differ from the frozen contract")
    if int(teacher_audit["selected_rows"]) < int(
        program["teacher_gate"]["minimum_selected_rows"]
    ) or int(teacher_audit["assistant_loss_tokens"]) < int(
        program["teacher_gate"]["minimum_assistant_loss_tokens"]
    ):
        raise RuntimeError("Codex-Hermes minimum data gate is not satisfied")

    model_lock = load_json(paths["model_lock_sha256"])
    overlay = load_json(paths["tokenizer_overlay_sha256"])
    teacher_gate = program["teacher_gate"]
    teacher_identities = teacher_gate.get("allowed_teacher_identities")
    if not teacher_identities:
        teacher_identities = [
            {
                "source_dataset": teacher_gate["source_dataset"],
                "interface": teacher_gate["required_teacher_interface"],
                "model": teacher_gate["required_teacher_model"],
            }
        ]
    value = {
        "schema_version": "studyhub.qwen35-4b-sft2-authorization.v1",
        "authorization_id": f"{program['program_id']}-r32-seed-20260827",
        "status": "AUTHORIZED_PENDING_SMOKE_AND_FORMAL_RUN",
        "scope": {
            "model": "Qwen/Qwen3.5-4B-Base",
            "student_input": "M1",
            "program_id": program["program_id"],
            "dataset_id": args.dataset_id,
            "evidence_prefix": args.evidence_prefix,
            "teacher_identities": teacher_identities,
            "method": "AReaL SFT BF16 FSDP2 LoRA continuation",
            "smoke_runs": 1,
            "formal_training_runs": 1,
            "spark_training_data_allowed": any(
                item["interface"] == "codex-spark-cli"
                for item in teacher_identities
            ),
            "no_spark_runtime_calls": True,
            "no_main_grpo": True,
            "no_opd_in_sft2": True,
            "no_sealed": True,
        },
        "lineage": {
            **{key: sha256(path) for key, path in paths.items()},
            "model_revision": model_lock["resolved_revision"],
            "model_weight_set_sha256": model_lock["aggregate_weight_set_sha256"],
            "canonical_tokenizer_overlay": overlay["overlay"],
            "m1_adapter_path": str(m1_adapter.parent),
            "m1_adapter_sha256": sha256(m1_adapter),
            "run_commit_required": "SET_AT_LAUNCH_FROM_CLEAN_WORKTREE",
        },
        "budget": {
            "global_batch_size": 8,
            "smoke_optimizer_updates": 24,
            "smoke_checkpoint_every_updates": 16,
            "smoke_maximum_wall_time_seconds": 3600,
            "planned_optimizer_updates": 800,
            "planned_sequences": selected_rows,
            "actual_total_tokens": int(train["total_tokens"]),
            "actual_assistant_loss_tokens": int(train["assistant_loss_tokens"]),
            "checkpoint_every_updates": 100,
            "maximum_wall_time_seconds": 18000,
        },
        "recipe": {
            "backend": "fsdp:d2p1t1",
            "dtype": "bfloat16",
            "lora_rank": 32,
            "lora_alpha": 32,
            "target_modules": ["o_proj", "gate_proj", "up_proj", "down_proj"],
            "learning_rate": 1.0e-5,
            "weight_decay": 0.05,
            "beta1": 0.9,
            "beta2": 0.95,
            "eps": 1.0e-5,
            "scheduler": "cosine",
            "scheduler_total_steps": 800,
            "warmup_fraction": 0.03,
            "warmup_steps": 24,
            "gradient_clip": 1.0,
            "seed": 20260827,
            "enable_thinking": False,
        },
        "completion_contract": {
            "smoke_marker": "QWEN35_4B_SFT2_SMOKE_PASS.json",
            "formal_marker": "QWEN35_4B_SFT2_COMPLETE.json",
            "require_exact_m1_initialization": True,
            "require_lora_update": True,
            "require_complete_recovery_checkpoint": True,
            "require_exact_lr_schedule_audit": True,
            "expected_scheduler_total_steps": 800,
            "expected_warmup_steps": 24,
            "require_sealed_used_false": True,
        },
    }
    write_json(args.output, value)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
