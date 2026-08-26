from __future__ import annotations

import pytest

from scripts.train.evaluate_dev_rollouts import _strict_success, compare_runs


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
