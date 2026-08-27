from __future__ import annotations

import json

from scripts.train.build_experiment_evidence import (
    SYSTEM_PROMPT_MARKER,
    index_rollout_interactions,
    parse_metric_series,
    summarize_lora_immutability,
    summarize_metric_series,
)


def test_parse_metric_series_extracts_all_stats_table_columns() -> None:
    log = """
\x1b[37m(AReaL)\x1b[0m stats
│ timeperf/rollout │ 8.8992e+01 │ ppo_actor/update/lr │ 5.0000e-06 │
│ ppo_actor/update/entropy/avg │ 2.2102e-01 │ rollout/reward │ 2.6204e-01 │
│ non_metric │ ignored │
│ ppo_actor/update/lr │ 4.5000e-06 │ rollout/reward │ nan │
"""

    series = parse_metric_series(log)

    assert series == {
        "ppo_actor/update/entropy/avg": [0.22102],
        "ppo_actor/update/lr": [5e-6, 4.5e-6],
        "rollout/reward": [0.26204],
        "timeperf/rollout": [88.992],
    }


def test_summarize_metric_series_preserves_endpoints_and_range() -> None:
    summary = summarize_metric_series({"metric/value": [3.0, 1.0, 2.0]})

    assert summary["metric/value"] == {
        "count": 3,
        "first": 3.0,
        "last": 2.0,
        "min": 1.0,
        "max": 3.0,
        "mean": 2.0,
    }


def test_eval_lora_immutability_compares_initial_and_latest_step() -> None:
    checkpoints = [
        {
            "relative_path": "actor/initial_lora/adapter_model.safetensors",
            "sha256": "same",
            "global_step": None,
        },
        {
            "relative_path": "default/epoch0epochstep0globalstep0/adapter_model.safetensors",
            "sha256": "same",
            "global_step": 0,
        },
    ]

    result = summarize_lora_immutability(checkpoints, required=True)

    assert result["unchanged"] is True
    assert result["update_observed"] is False
    assert result["comparison_status"] == "unchanged"
    assert result["status"] == "passed"


def test_training_lora_comparison_records_an_observed_update() -> None:
    checkpoints = [
        {
            "relative_path": "actor/initial_lora/adapter_model.safetensors",
            "sha256": "before",
            "global_step": None,
        },
        {
            "relative_path": "default/epoch0epochstep0globalstep0/adapter_model.safetensors",
            "sha256": "after",
            "global_step": 0,
        },
    ]

    result = summarize_lora_immutability(checkpoints, required=False)

    assert result["unchanged"] is False
    assert result["update_observed"] is True
    assert result["comparison_status"] == "updated"
    assert result["status"] == "diagnostic"


def test_rollout_index_preserves_policy_version_and_task_lineage(tmp_path) -> None:
    task_root = tmp_path / "tasks"
    task_root.mkdir()
    request = "Find the grounded answer."
    task = {
        "task_id": "rl-test-1",
        "family": "search_multihop",
        "environment_seed": 123,
        "user_request": request,
        "metadata": {"source_dataset": "fixture", "split": "train"},
    }
    (task_root / "train.jsonl").write_text(json.dumps(task) + "\n")
    rollout_root = tmp_path / "rollout"
    version_root = rollout_root / "3"
    version_root.mkdir(parents=True)
    interaction = {
        "task_id": 7,
        "sample_idx": 0,
        "seqlen": 4096,
        "prompt_len": 1000,
        "head_version": 3,
        "tail_version": 3,
        "version_rle": [[3, 3096]],
        "reward": 0.5,
        "prompt": (f"<|im_start|>system\n{SYSTEM_PROMPT_MARKER}<|im_end|><|im_start|>user\n{request}<|im_end|>"),
        "completion": "answer",
    }
    (version_root / "7.jsonl").write_text(json.dumps(interaction) + "\n")

    files, records, summary = index_rollout_interactions(
        rollout_root,
        task_root=task_root,
        trial="trial-1",
        run_seed=6209,
        max_sequence_tokens=4096,
    )

    assert files[0]["task_id"] == "rl-test-1"
    assert records[0]["tail_policy_version"] == 3
    assert records[0]["environment_seed"] == 123
    assert records[0]["run_seed"] == 6209
    assert records[0]["at_sequence_limit"] is True
    assert summary is not None
    assert summary["unmapped_files"] == 0
    assert summary["policy_version_counts"] == {"3": 1}
    assert summary["sequence_tokens"]["at_limit_rate"] == 1.0
    assert summary["system_prompt_integrity"]["all_records_exactly_once"] is True


def test_rollout_index_accepts_a_single_task_jsonl(tmp_path) -> None:
    request = "Evaluate one fixed task."
    task_path = tmp_path / "tasks.jsonl"
    task_path.write_text(
        json.dumps(
            {
                "task_id": "rl-eval-1",
                "family": "function_calling",
                "environment_seed": 321,
                "user_request": request,
                "metadata": {"source_dataset": "fixture", "split": "validation"},
            }
        )
        + "\n"
    )
    version_root = tmp_path / "eval-rollout" / "1"
    version_root.mkdir(parents=True)
    (version_root / "1.jsonl").write_text(
        json.dumps(
            {
                "task_id": 1,
                "sample_idx": 0,
                "seqlen": 128,
                "prompt_len": 96,
                "head_version": 1,
                "tail_version": 1,
                "version_rle": [[1, 32]],
                "reward": 0.75,
                "prompt": (
                    f"<|im_start|>system\n{SYSTEM_PROMPT_MARKER}<|im_end|><|im_start|>user\n{request}<|im_end|>"
                ),
                "completion": "answer",
            }
        )
        + "\n"
    )

    _, records, summary = index_rollout_interactions(
        tmp_path / "eval-rollout",
        task_root=task_path,
        trial="eval-trial",
        run_seed=6209,
        max_sequence_tokens=4096,
    )

    assert records[0]["task_id"] == "rl-eval-1"
    assert records[0]["split"] == "validation"
    assert summary is not None
    assert summary["mapped_tasks"] == 1
    assert summary["unmapped_files"] == 0
