#!/usr/bin/env python3
"""Authorize strict M2 -> T9 on-policy distillation after all hard gates pass."""

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
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, default=CANONICAL_ROOT)
    parser.add_argument(
        "--m2-marker",
        type=Path,
        default=(
            CANONICAL_ROOT / "artifacts/areal/checkpoints/chengjin/studyhub-qwen35-4b-codex-sft2/"
            "qwen35-4b-sft2-formal-r32-seed-20260827/QWEN35_4B_SFT2_COMPLETE.json"
        ),
    )
    parser.add_argument(
        "--novelty-gate",
        type=Path,
        default=PROJECT_ROOT / "docs/training/evidence/qwen35-4b-opd-teacher-novelty.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v4/qwen35-4b-opd-v1-authorization.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.artifact_root.resolve()
    teacher_model = Path("/data/chengjin/studyhub/models/P1/Qwen3.5-9B")
    pool = root / "datasets/processed/opd_prompt_pool_v1"
    actor_model = root / "artifacts/areal/model-overlays/qwen35-4b-base-canonical-tokenizer"
    sglang_overlay = root / "artifacts/areal/model-overlays/qwen35-4b-opd-sglang-lora"
    paths = {
        "program_sha256": PROJECT_ROOT / "configs/program-v4/qwen35-4b-opd-v1.json",
        "config_sha256": PROJECT_ROOT / "configs/train/qwen35-4b-strict-opd.yaml",
        "opd_upstream_lock_sha256": PROJECT_ROOT / "training/opd/upstream.lock.json",
        "opd_runtime_sha256": PROJECT_ROOT / "training/opd/areal_runtime.py",
        "runtime_sitecustomize_sha256": PROJECT_ROOT / "training/runtime_shims/sitecustomize.py",
        "opd_parity_sha256": PROJECT_ROOT / "docs/training/evidence/qwen35-4b-opd-token-reward-parity.json",
        "prompt_pool_manifest_sha256": pool / "manifest.json",
        "prompt_pool_train_sha256": pool / "tasks/train.jsonl",
        "prompt_pool_dev_sha256": pool / "tasks/validation.jsonl",
        "prompt_pool_train_verifiers_sha256": pool / "verifiers/train.jsonl",
        "prompt_pool_dev_verifiers_sha256": pool / "verifiers/validation.jsonl",
        "teacher_novelty_sha256": args.novelty_gate,
        "tokenizer_parity_sha256": PROJECT_ROOT / "docs/training/evidence/qwen35-4b-9b-tokenizer-parity.json",
        "thinking_contract_sha256": PROJECT_ROOT / "docs/training/evidence/qwen35-4b-9b-thinking-contract.json",
        "benchmark_manifest_sha256": PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json",
        "areal_lock_sha256": PROJECT_ROOT / "training/areal/upstream.lock.json",
        "hermes_lock_sha256": PROJECT_ROOT / "integrations/hermes/upstream.lock.json",
        "m2_completion_sha256": args.m2_marker,
        "teacher_download_manifest_sha256": teacher_model / "studyhub_download_manifest.json",
        "teacher_config_sha256": teacher_model / "config.json",
        "teacher_index_sha256": teacher_model / "model.safetensors.index.json",
        "sglang_overlay_config_sha256": sglang_overlay / "config.json",
        "sglang_overlay_manifest_sha256": sglang_overlay / "studyhub_sglang_overlay_manifest.json",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"cannot authorize OPD; missing evidence={missing}")

    program = load_json(paths["program_sha256"])
    parity = load_json(paths["opd_parity_sha256"])
    pool_manifest = load_json(paths["prompt_pool_manifest_sha256"])
    novelty = load_json(args.novelty_gate)
    tokenizer = load_json(paths["tokenizer_parity_sha256"])
    thinking = load_json(paths["thinking_contract_sha256"])
    benchmark = load_json(paths["benchmark_manifest_sha256"])
    m2 = load_json(args.m2_marker)
    teacher_manifest = load_json(paths["teacher_download_manifest_sha256"])
    overlay_manifest = load_json(paths["sglang_overlay_manifest_sha256"])
    if program.get("status") != "PREPARED_NOT_AUTHORIZED":
        raise RuntimeError("unexpected OPD program status")
    if parity.get("status") != "PASS_OPD_COMPATIBILITY_SPIKE":
        raise RuntimeError("THUNLP OPD mathematical parity has not passed")
    if pool_manifest.get("status") != "PASS_TEACHER_ALIGNED_SELECTION":
        raise RuntimeError("teacher-aligned OPD prompt pool has not passed")
    if not 1500 <= int(pool_manifest["train_rows"]) <= 3000:
        raise RuntimeError("OPD selected prompt count is outside the frozen range")
    if (
        pool_manifest.get("train_validation_group_overlap") != 0
        or pool_manifest.get("validation_or_protocol_holdout_used") is not False
    ):
        raise RuntimeError("OPD prompt pool split isolation failed")
    if novelty.get("status") != "PASS_TEACHER_NOVELTY" or int(novelty["teacher_only_successes"]) < 20:
        raise RuntimeError("T9 does not satisfy the frozen novelty gate")
    if tokenizer.get("status") != "PASS" or tokenizer.get("canonical_opd_allowed") is not True:
        raise RuntimeError("canonical 4B/9B tokenizer parity is not proven")
    if thinking.get("enable_thinking") is not False:
        raise RuntimeError("OPD thinking-mode contract drift")
    if benchmark.get("status") != "FROZEN_FOR_BASELINE":
        raise RuntimeError("Benchmark v2 lock drift")
    if m2.get("status") != "COMPLETE" or m2.get("mode") != "formal":
        raise RuntimeError("M2 has no valid formal completion marker")
    m2_adapter = Path(str(m2.get("checkpoint", {}).get("path", ""))).resolve()
    if not m2_adapter.is_file() or sha256(m2_adapter) != m2["checkpoint"]["sha256"]:
        raise RuntimeError("M2 adapter is missing or differs from its marker")
    teacher_revision = teacher_manifest.get("revision") or teacher_manifest.get("resolved_revision")
    if teacher_revision != "c202236235762e1c871ad0ccb60c8ee5ba337b9a":
        raise RuntimeError("T9 revision drift")
    if Path(str(overlay_manifest.get("base_model", ""))).resolve() != actor_model.resolve():
        raise RuntimeError("SGLang overlay is not derived from the frozen actor model")
    expected_overlay_fields = {
        "vocab_size",
        "hidden_size",
        "num_hidden_layers",
        "intermediate_size",
        "num_attention_heads",
        "num_key_value_heads",
        "head_dim",
    }
    if set(overlay_manifest.get("mapped_text_config_fields", {})) != expected_overlay_fields:
        raise RuntimeError("SGLang overlay does not expose the complete LoRA config contract")

    value = {
        "schema_version": "studyhub.qwen35-4b-opd-authorization.v1",
        "authorization_id": "qwen35-4b-m2-to-t9-strict-opd-seed-20260827",
        "status": "AUTHORIZED_PENDING_LR_PILOTS",
        "scope": {
            "student": "M2",
            "teacher": "Qwen/Qwen3.5-9B",
            "method": "THUNLP token_reward_direct over real Hermes rollouts",
            "lr_pilots": [1.0e-6, 3.0e-6],
            "pilot_updates": 64,
            "formal_updates": 300,
            "no_main_grpo": True,
            "no_spark": True,
            "no_sealed": True,
            "teacher_executes_tools": False,
        },
        "lineage": {
            **{key: sha256(path) for key, path in paths.items()},
            "m2_adapter_path": str(m2_adapter.parent),
            "m2_adapter_sha256": sha256(m2_adapter),
            "m2_completion_path": str(args.m2_marker.resolve()),
            "teacher_model_path": str(teacher_model),
            "teacher_revision": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            "prompt_pool_path": str(pool),
            "sglang_overlay_path": str(sglang_overlay),
            "run_commit_required": "SET_AT_LAUNCH_FROM_CLEAN_WORKTREE",
        },
        "recipe": {
            **program["algorithm"],
            "student_backend": "fsdp:d1",
            "rollout_backend": "sglang:d1",
            "teacher_backend": "fsdp:d1",
            "lora_rank": 32,
            "lora_alpha": 32,
            "target_modules": ["o_proj", "gate_proj", "up_proj", "down_proj"],
            "max_context_tokens": 16384,
            "max_assistant_tokens": 4096,
            "max_turns": 6,
            "seed": 20260827,
        },
        "budgets": {
            "lr_pilot_updates": 16,
            "algorithm_pilot_updates": 64,
            "formal_updates": 300,
            "formal_batch_size": 8,
            "checkpoint_every_updates": 50,
            "maximum_wall_seconds": 28800,
        },
        "hard_gates": {
            "novelty_status": novelty["status"],
            "teacher_successes": novelty["teacher_successes"],
            "student_successes": novelty["student_successes"],
            "teacher_only_successes": novelty["teacher_only_successes"],
            "student_baseline_tool_validity": novelty["student_mean_tool_validity"],
            "tokenizer_parity": tokenizer["status"],
            "thinking_enabled": False,
            "sealed_used": False,
        },
        "completion_contract": {
            "lr_selection_evidence": "docs/training/evidence/qwen35-4b-opd-lr-selection.json",
            "pilot_marker": "QWEN35_4B_OPD_PILOT_PASS.json",
            "formal_marker": "QWEN35_4B_OPD_COMPLETE.json",
            "require_m2_initialization": True,
            "require_positive_teacher_signal": True,
            "require_lora_update": True,
            "require_runtime_backend_parity": True,
        },
    }
    write_json(args.output, value)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
