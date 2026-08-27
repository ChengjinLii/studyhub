from pathlib import Path

from scripts.train.validate_v3_program import (
    EXPECTED_ALGORITHMS,
    EXPECTED_CAPABILITIES,
    validate_program,
)

PROJECT = Path(__file__).resolve().parents[3]


def test_committed_v3_program_is_internally_consistent() -> None:
    errors, summary = validate_program(PROJECT)

    assert errors == []
    assert summary == {
        "program_id": "studyhub-9b-agentic-post-training-v3",
        "status": "BENCHMARK_V2_FROZEN_BASE_CALIBRATED_SFT_FORMAL_AUTHORIZED",
        "capabilities": len(EXPECTED_CAPABILITIES),
        "benchmark_version": "studyhub-agentbench-v2",
        "benchmark_manifest_sha256": "da804b10f53dec585255598c3e256445b8ade3acf35fd8c766ca0ab4d759c88b",
        "regression_tasks": 12,
        "development_tasks": 51,
        "sealed_tasks": 25,
        "calibration_challenge_tasks": 10,
        "base_development_scored": 51,
        "base_variance_scored": 140,
        "sft_final_trajectories": 48500,
        "sft_data_status": "ACCEPTED_FOR_SFT_GATE",
        "sft_all_tokens": 61725581,
        "sft_gate_status": "PASSED",
        "sft_gate_trial": "gate-seed-20260827-20260827_233653",
        "sft_profile_status": "PASSED",
        "sft_profile_selected_recipe": "r16",
        "formal_sft": {
            "status": "AUTHORIZED_PENDING_START",
            "training_trial": "formal-r16-seed-20260827",
            "expected_optimizer_updates": 5456,
            "train_all_tokens": 55554221,
            "train_assistant_loss_tokens": 8152342,
        },
        "rl_post_qa_tasks": 10000,
        "initial_grpo_updates": 500,
        "algorithms": len(EXPECTED_ALGORITHMS),
        "design_defects": 17,
        "launch_authorized": True,
    }


def test_v3_program_keeps_local_model_check_optional_for_ci() -> None:
    errors, summary = validate_program(PROJECT, check_local_assets=False)

    assert errors == []
    assert summary["launch_authorized"] is True


def test_v3_plan_has_human_and_machine_readable_entry_points() -> None:
    assert (PROJECT / "docs/StudyHub_9B_Agentic_Post_Training_Program_v3.html").is_file()
    assert (PROJECT / "configs/program-v3/training-program-v3.json").is_file()
    assert (PROJECT / "configs/program-v3/capability-matrix-v1.json").is_file()
    assert (PROJECT / "configs/program-v3/algorithm-decision-matrix-v1.json").is_file()
    assert (PROJECT / "configs/program-v3/runtime-sft-v3-data-card.json").is_file()
    assert (PROJECT / "docs/training/RUNTIME_SFT_V3_DATA_CARD.md").is_file()
    assert (PROJECT / "docs/training/evidence/runtime-sft-v3-9b-gate-20260827.json").is_file()
    assert (PROJECT / "docs/training/evidence/runtime-sft-v3-9b-profile-20260828.json").is_file()
    assert (PROJECT / "research/primary-source-review.md").is_file()
    assert (PROJECT / "design-defects/index.json").is_file()
