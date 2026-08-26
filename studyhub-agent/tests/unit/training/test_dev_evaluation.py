from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.train.evaluate_dev_rollouts import (
    _strict_success,
    _summarize_rows,
    compare_runs,
)


def _row(family: str, **reward_overrides):
    reward = {
        "answer_quality": 1.0,
        "citation": 1.0,
        "evidence": 1.0,
        "function_call_quality": 1.0,
        "hard_gate_triggered": False,
        "task_success": 1.0,
        "tool_quality": 1.0,
        "total": 0.9,
        "violations": [],
    }
    reward.update(reward_overrides)
    return {
        "final_answer_empty": False,
        "task_family": family,
        "reward": reward,
    }


def test_strict_success_rejects_rewarded_but_ungrounded_answer() -> None:
    assert _strict_success(_row("search_multihop")) is True
    assert _strict_success(_row("search_multihop", citation=-1.0)) is False
    assert _strict_success(_row("function_calling", answer_quality=0.7)) is False


def test_paired_comparison_uses_matching_task_ids() -> None:
    baseline = {
        "per_task": [
            {
                "task_id": "a",
                "mean_reward": 0.2,
                "strict_success_rate": 0.25,
                "pass_at_4": True,
            }
        ]
    }
    candidate = {
        "per_task": [
            {
                "task_id": "a",
                "mean_reward": 0.6,
                "strict_success_rate": 0.75,
                "pass_at_4": True,
            }
        ]
    }

    result = compare_runs(baseline, candidate)

    assert result["paired_tasks"] == 1
    assert result["candidate_minus_baseline"]["mean_reward"]["mean"] == pytest.approx(0.4)
    assert result["candidate_minus_baseline"]["strict_success_rate"]["mean"] == 0.5
    assert result["task_outcomes"] == {
        "strict_improved": 1,
        "strict_unchanged": 0,
        "strict_regressed": 0,
    }


def test_dev_evaluation_rejects_incomplete_four_rollout_group() -> None:
    rows = []
    for index in range(3):
        row = _row("function_calling")
        row.update(
            {
                "task_id": "task-a",
                "source_dataset": "fixture",
                "trace": {"tool_calls": 1, "hermes": {"total_tokens": 10}},
                "rollout_id": f"rollout-{index}",
            }
        )
        rows.append(row)

    with pytest.raises(RuntimeError, match="exactly 4 rollouts"):
        _summarize_rows(rows)


def test_frozen_v2_protocol_records_reproducibility_contract() -> None:
    project_root = Path(__file__).parents[3]
    protocol = json.loads(
        (project_root / "configs/eval/studyhub-dev-eval-v2.json").read_text()
    )

    assert protocol["schema_version"] == "studyhub.dev-eval.v2"
    assert protocol["subset"]["tasks"] == 32
    assert protocol["subset"]["rollouts_per_task"] == 4
    assert protocol["generation"]["deterministic_sampling"] is True
    assert protocol["generation"]["deterministic_inference"] is True
    assert protocol["execution"] == {
        "optimizer_lr": 0.0,
        "require_unchanged_lora": True,
        "exact_rollout_group_size": 4,
    }
