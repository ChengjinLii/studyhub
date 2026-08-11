from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ml.agentic_platform.sft.build_router_v1_7_state_transitions import (
    EXPECTED_RUNTIME_PATH_COUNTS,
    EXPECTED_SPLIT_COUNTS,
    FAMILY_PLAN,
    TOTAL_RECORDS,
    build_router_v1_7_state_transitions,
)


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_v1_7_builds_balanced_leak_free_transition_data(tmp_path: Path) -> None:
    result = build_router_v1_7_state_transitions(
        output_dir=tmp_path,
        generated_at="2026-08-11T00:00:00+00:00",
    )
    rows = _rows(tmp_path / "router_tool_2b_v1_7.jsonl")
    audit = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))

    assert result["validation_passed"] is True
    assert audit["passed"] is True
    assert len(rows) == TOTAL_RECORDS
    assert Counter(row["split"] for row in rows) == {
        "train": EXPECTED_SPLIT_COUNTS["train"],
        "validation": EXPECTED_SPLIT_COUNTS["validation"],
    }
    assert Counter(
        row["remediation_contract"]["runtime_path"] for row in rows
    ) == EXPECTED_RUNTIME_PATH_COUNTS
    assert Counter(row["task_family"] for row in rows) == {
        family: count for family, (_, count) in FAMILY_PLAN.items()
    }
    assert audit["development_overlap_audit"]["exact_query_overlap_diagnostic"] == 0
    assert audit["development_overlap_audit"]["exact_payload_overlap_diagnostic"] == 0
    assert audit["sealed_final_holdout_read"] is False


def test_v1_7_memory_targets_are_minimal_and_exact(tmp_path: Path) -> None:
    build_router_v1_7_state_transitions(
        output_dir=tmp_path,
        generated_at="2026-08-11T00:00:00+00:00",
    )
    memory_rows = [
        row
        for row in _rows(tmp_path / "router_tool_2b_v1_7.jsonl")
        if row["task_family"] == "personal_memory_minimal_v1_7"
    ]

    assert len(memory_rows) == 320
    for row in memory_rows:
        target = row["assistant_target"]
        assert set(target) == {"mode", "progress", "task_context", "actions"}
        assert target["mode"] == "tools"
        assert target["actions"][0]["name"] == "read_memory"
        assert target["actions"][0]["arguments"]["focus"] == (
            row["remediation_contract"]["focus"]
        )
        assert row["quality"]["human_gold"] is False
