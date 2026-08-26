from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.train.compare_eval_reproducibility import compare


def _row(task_id: str, answer_hash: str, rollout_id: str) -> dict:
    return {
        "recorded_at": "volatile",
        "experiment_name": "experiment",
        "trial_name": "trial",
        "run_kind": "validation",
        "rollout_group_id": "volatile-group",
        "rollout_id": rollout_id,
        "split": "validation",
        "task_id": task_id,
        "task_family": "function_calling",
        "source_dataset": "fixture",
        "source_group_id": "source-group",
        "final_answer_sha256": answer_hash,
        "final_answer_length": 12,
        "final_answer_empty": False,
        "max_steps": 6,
        "max_tool_calls": 6,
        "reward": {"total": 1.0, "violations": []},
        "trace": {
            "tool_calls": 1,
            "tool_names": ["fixture_tool"],
            "invalid_tool_calls": 0,
            "error_codes": [],
            "search_results": 0,
            "read_sources": [],
            "hermes": {
                "guardrail_halt": None,
                "api_calls": 2,
                "input_tokens": 10,
                "output_tokens": 5,
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "last_prompt_tokens": 7,
            },
        },
    }


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_reproducibility_ignores_volatile_ids_and_order(tmp_path: Path) -> None:
    reference = [_row("task-a", f"hash-{index}", f"ref-{index}") for index in range(4)]
    candidate = []
    for index, row in enumerate(reversed(reference)):
        changed = copy.deepcopy(row)
        changed["recorded_at"] = "other-time"
        changed["trial_name"] = "other-trial"
        changed["rollout_id"] = f"candidate-{index}"
        candidate.append(changed)
    reference_path = tmp_path / "reference.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    _write(reference_path, reference)
    _write(candidate_path, candidate)

    result = compare(reference_path, candidate_path)

    assert result["status"] == "EXACT"
    assert result["matched_rollout_rate"] == 1.0


def test_reproducibility_detects_behavior_change(tmp_path: Path) -> None:
    reference = [_row("task-a", f"hash-{index}", f"ref-{index}") for index in range(4)]
    candidate = copy.deepcopy(reference)
    candidate[0]["reward"]["total"] = 0.0
    reference_path = tmp_path / "reference.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    _write(reference_path, reference)
    _write(candidate_path, candidate)

    result = compare(reference_path, candidate_path)

    assert result["status"] == "MISMATCH"
    assert result["matched_rollouts"] == 3


def test_reproducibility_rejects_incomplete_groups(tmp_path: Path) -> None:
    rows = [_row("task-a", f"hash-{index}", f"ref-{index}") for index in range(3)]
    reference_path = tmp_path / "reference.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    _write(reference_path, rows)
    _write(candidate_path, rows)

    with pytest.raises(RuntimeError, match="exactly four"):
        compare(reference_path, candidate_path)
