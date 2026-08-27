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
        "status": "DESIGN_FROZEN_PENDING_BENCHMARK_V1",
        "capabilities": len(EXPECTED_CAPABILITIES),
        "regression_tasks": 160,
        "development_tasks": 1005,
        "sealed_tasks": 500,
        "sft_final_trajectories": 45000,
        "rl_post_qa_tasks": 10000,
        "initial_grpo_updates": 500,
        "algorithms": len(EXPECTED_ALGORITHMS),
        "design_defects": 17,
        "launch_authorized": False,
    }


def test_v3_program_keeps_local_model_check_optional_for_ci() -> None:
    errors, summary = validate_program(PROJECT, check_local_assets=False)

    assert errors == []
    assert summary["launch_authorized"] is False


def test_v3_plan_has_human_and_machine_readable_entry_points() -> None:
    assert (PROJECT / "docs/StudyHub_9B_Agentic_Post_Training_Program_v3.html").is_file()
    assert (PROJECT / "configs/program-v3/training-program-v3.json").is_file()
    assert (PROJECT / "configs/program-v3/capability-matrix-v1.json").is_file()
    assert (PROJECT / "configs/program-v3/algorithm-decision-matrix-v1.json").is_file()
    assert (PROJECT / "research/primary-source-review.md").is_file()
    assert (PROJECT / "design-defects/index.json").is_file()
