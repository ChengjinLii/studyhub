from __future__ import annotations

import json

from scripts.train.summarize_reward_groups import summarize


def test_reward_summary_reports_group_variance_and_quality_rates(tmp_path) -> None:
    path = tmp_path / "reward-v2.jsonl"
    rows = []
    for index, reward in enumerate((1.0, 0.5, -0.5, -1.0)):
        rows.append(
            {
                "experiment_name": "fixture-experiment",
                "trial_name": "fixture-trial",
                "task_id": "fixture-task",
                "task_family": "function_calling",
                "rollout_group_id": "fixture-group",
                "rollout_id": f"rollout-{index}",
                "final_answer_empty": index == 3,
                "trace": {
                    "tool_calls": 1,
                    "invalid_tool_calls": int(index == 2),
                },
                "reward": {
                    "total": reward,
                    "task_success": reward,
                    "answer_quality": reward,
                    "function_call_quality": 1.0,
                    "evidence": 1.0,
                    "citation": 1.0,
                    "tool_quality": reward,
                    "efficiency": 0.0,
                    "hard_gate_triggered": index == 3,
                    "violations": ["empty_final_answer"] if index == 3 else [],
                },
            }
        )
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    result = summarize(path, expected_group_size=4)

    assert result["rollouts"] == 4
    assert result["groups"] == 1
    assert result["complete_groups"] == 1
    assert result["zero_variance_group_rate"] == 0.0
    assert result["mean_group_reward_std"] > 0
    assert result["quality_rates"] == {
        "empty_final_answer": 0.25,
        "invalid_tool_call": 0.25,
        "no_tool_call": 0.0,
        "hard_gate": 0.25,
    }
