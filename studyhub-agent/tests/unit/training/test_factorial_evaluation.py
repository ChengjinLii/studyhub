from __future__ import annotations

import pytest

from scripts.train.summarize_factorial_eval import summarize_factorial


def _payload(values: dict[str, tuple[float, float, float, float]]) -> dict:
    runs = {}
    labels = {
        "base4b": 0,
        "sft4b": 1,
        "direct_rl4b": 2,
        "sft_rl4b": 3,
    }
    for label, index in labels.items():
        rows = []
        for task_id, task_values in values.items():
            value = task_values[index]
            rows.append(
                {
                    "task_id": task_id,
                    "strict_success_rate": value,
                    "pass_at_4": bool(value),
                    "consistent_at_4": bool(value == 1.0),
                    "mean_reward": value,
                }
            )
        mean = sum(row["mean_reward"] for row in rows) / len(rows)
        runs[label] = {
            "overall": {
                "strict_rollout_success_rate": mean,
                "pass_at_4": sum(row["pass_at_4"] for row in rows) / len(rows),
                "consistent_at_4": sum(row["consistent_at_4"] for row in rows)
                / len(rows),
                "mean_reward": mean,
            },
            "per_task": rows,
        }
    return {"schema_version": "fixture", "runs": runs}


def test_factorial_summary_calculates_main_and_interaction_effects() -> None:
    payload = _payload(
        {
            "a": (0.0, 0.2, 0.3, 0.8),
            "b": (0.0, 0.2, 0.3, 0.8),
        }
    )

    result = summarize_factorial(payload, bootstrap_samples=100, seed=1)
    reward = result["contrasts"]["mean_reward"]

    assert reward["sft_without_rl"]["estimate"] == pytest.approx(0.2)
    assert reward["rl_without_sft"]["estimate"] == pytest.approx(0.3)
    assert reward["rl_after_sft"]["estimate"] == pytest.approx(0.6)
    assert reward["sft_after_rl"]["estimate"] == pytest.approx(0.5)
    assert reward["interaction"]["estimate"] == pytest.approx(0.3)
    assert reward["interaction"]["ci95"] == pytest.approx([0.3, 0.3])


def test_factorial_summary_rejects_unpaired_task_sets() -> None:
    payload = _payload({"a": (0.0, 0.2, 0.3, 0.8)})
    payload["runs"]["sft_rl4b"]["per_task"][0]["task_id"] = "other"

    with pytest.raises(ValueError, match="do not share task IDs"):
        summarize_factorial(payload, bootstrap_samples=10)


def test_factorial_summary_rejects_missing_run() -> None:
    payload = _payload({"a": (0.0, 0.2, 0.3, 0.8)})
    del payload["runs"]["direct_rl4b"]

    with pytest.raises(ValueError, match="missing run label"):
        summarize_factorial(payload, bootstrap_samples=10)
