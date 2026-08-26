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
                    "hermes": {
                        "api_calls": index + 1,
                        "last_prompt_tokens": 1000 + 100 * index,
                        "total_tokens": 2000 + 100 * index,
                        "guardrail_halt": (
                            {"code": "fixture_loop_halt"} if index == 3 else None
                        ),
                        "context_budget": {
                            "max_pre_guard_prompt_tokens": 1200 + 100 * index,
                            "max_sent_prompt_tokens": 1100 + 100 * index,
                            "forced_final": index == 3,
                            "forced_final_reasons": (
                                ["context_threshold"] if index == 3 else []
                            ),
                            "compacted_tool_messages": int(index == 3),
                            "compacted_tool_chars": 250 if index == 3 else 0,
                            "dropped_tool_exchanges": 0,
                            "counter_failures": 0,
                            "guard_failures": 0,
                        },
                    },
                    "runtime_errors": [],
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
    assert result["by_family"]["function_calling"]["reward"]["mean"] == 0.0
    assert result["by_family"]["function_calling"]["violations"] == {
        "empty_final_answer": 1
    }
    assert result["runtime"] == {
        "api_calls": {"mean": 2.5, "p95": 4.0, "max": 4.0},
        "last_prompt_tokens": {"mean": 1150.0, "p95": 1300.0, "max": 1300.0},
        "total_tokens": {"mean": 2150.0, "p95": 2300.0, "max": 2300.0},
        "guardrail_halts": 1,
        "guardrail_halt_rate": 0.25,
        "guardrail_halt_codes": {"fixture_loop_halt": 1},
        "context_budget": {
            "max_pre_guard_prompt_tokens": {
                "mean": 1350.0,
                "p95": 1500.0,
                "max": 1500.0,
            },
            "max_sent_prompt_tokens": {
                "mean": 1250.0,
                "p95": 1400.0,
                "max": 1400.0,
            },
            "forced_final_rollouts": 1,
            "forced_final_rate": 0.25,
            "forced_final_reasons": {"context_threshold": 1},
            "compacted_rollouts": 1,
            "compacted_rollout_rate": 0.25,
            "compacted_tool_messages": 1,
            "compacted_tool_chars": 250,
            "dropped_exchange_rollouts": 0,
            "counter_failures": 0,
            "guard_failures": 0,
            "runtime_errors": {},
        },
    }
