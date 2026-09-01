import json
from pathlib import Path

from scripts.train.prepare_qwen35_4b_sft2_authorization import build_training_contract

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _program(updates: int) -> dict:
    return {
        "seed": 20260827,
        "training": {
            "primary_updates": updates,
            "global_batch_size": 8,
            "enable_thinking": False,
            "smoke_updates": 24,
            "checkpoint_every_updates": 50,
        },
        "recipe": {
            "backend": "fsdp:d2p1t1",
            "precision": "bf16",
            "lora": {
                "rank": 32,
                "alpha": 32,
                "target_modules": ["o_proj", "gate_proj", "up_proj", "down_proj"],
            },
            "optimizer": {
                "lr": 1e-5,
                "weight_decay": 0.05,
                "beta1": 0.9,
                "beta2": 0.95,
                "eps": 1e-5,
                "gradient_clip": 1.0,
            },
            "scheduler": {"name": "cosine", "warmup_fraction": 0.03},
        },
    }


def test_training_contract_uses_program_update_budget() -> None:
    budget, recipe, completion = build_training_contract(
        _program(300),
        selected_rows=2400,
        train={"total_tokens": 2_700_000, "assistant_loss_tokens": 430_000},
    )

    assert budget["planned_optimizer_updates"] == 300
    assert budget["planned_sequences"] == 2400
    assert budget["smoke_optimizer_updates"] == 24
    assert recipe["scheduler_total_steps"] == 300
    assert recipe["warmup_steps"] == 9
    assert completion["expected_scheduler_total_steps"] == 300


def test_training_contract_preserves_legacy_800_update_default() -> None:
    program = _program(800)
    program["training"].pop("smoke_updates")
    budget, recipe, _completion = build_training_contract(
        program,
        selected_rows=6400,
        train={"total_tokens": 7_300_000, "assistant_loss_tokens": 1_000_000},
    )

    assert budget["planned_optimizer_updates"] == 800
    assert budget["smoke_optimizer_updates"] == 24
    assert recipe["scheduler_total_steps"] == 800
    assert recipe["warmup_steps"] == 24


def test_compact_program_is_independent_and_matches_300_update_budget() -> None:
    compact = json.loads(
        (PROJECT_ROOT / "configs/program-v4/sft2-compact-mixed-v1.json").read_text()
    )
    legacy = json.loads(
        (
            PROJECT_ROOT
            / "configs/program-v4/sft2-mixed-teacher-retention-v2.json"
        ).read_text()
    )

    assert compact["program_id"] != legacy["program_id"]
    assert compact["selection"]["target_train_rows"] == 300 * 8
    assert compact["selection"]["target_assistant_loss_tokens"] == 430_000
    assert compact["mix"]["teacher_assistant_token_share_bounds"] == [0.30, 0.35]
    assert compact["training"]["primary_updates"] == 300
    assert compact["training"]["smoke_updates"] == 24
    assert legacy["training"]["primary_updates"] == 800


def test_sft2_evidence_and_lr_collector_share_canonical_artifact_root() -> None:
    launcher = (PROJECT_ROOT / "scripts/train/run_qwen35_4b_sft2.sh").read_text()

    assert '--output "${ARTIFACT_ROOT}/artifacts/experiments/${ATTEMPT_ID}"' in launcher
    assert '--evidence-root "${ARTIFACT_ROOT}/artifacts/experiments"' in launcher


def test_sft2_formal_completion_requires_recovery_inventory() -> None:
    recorder = (
        PROJECT_ROOT / "scripts/train/record_qwen35_4b_sft2_completion.py"
    ).read_text()

    assert 'if args.mode == "smoke":\n        metadata_files' not in recorder
    assert '"metadata_sha256": sha256(metadata_files[0])' in recorder
    assert 'raise RuntimeError("SFT-2 has no complete recovery checkpoint")' in recorder
