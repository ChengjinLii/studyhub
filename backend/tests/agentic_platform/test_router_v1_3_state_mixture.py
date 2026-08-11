from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from backend.tests.agentic_platform.test_router_v1_2_replay_mixture import (
    replay_tree as _replay_tree_fixture,
)
from ml.agentic_platform.sft.build_router_v1_3_state_mixture import (
    EXPECTED_COMPONENT_COUNTS,
    EXPECTED_SPLIT_COUNTS,
    STRUCTURAL_FAMILY_COUNTS,
    build_router_v1_3_state_mixture,
)
from ml.agentic_platform.sft.export_llamafactory import (
    export_llamafactory_dataset,
)
from ml.agentic_platform.sft.spec import load_jsonl


@pytest.fixture(scope="module")
def state_tree(
    _replay_tree_fixture: dict[str, Path],  # noqa: F811
) -> Path:
    output_dir = _replay_tree_fixture["root"] / "v1-3-state"
    build_router_v1_3_state_mixture(
        source_dataset_path=(
            _replay_tree_fixture["replay_dir"]
            / "router_tool_2b_v1_2_replay.jsonl"
        ),
        split_reference_path=_replay_tree_fixture["v1_1"],
        diagnostic_dataset_path=(
            _replay_tree_fixture["root"]
            / "diagnostic/router_hidden_300.jsonl"
        ),
        output_dir=output_dir,
        generated_at="2026-07-31T00:05:00+00:00",
    )
    return output_dir


def test_v1_3_counts_audit_and_normalization(state_tree: Path) -> None:
    rows = load_jsonl(state_tree / "router_tool_2b_v1_3_state.jsonl")
    audit = json.loads((state_tree / "audit.json").read_text())

    assert len(rows) == 1800
    assert audit["passed"] is True
    assert audit["component_counts"] == EXPECTED_COMPONENT_COUNTS
    assert audit["split_counts"] == {
        key: value for key, value in EXPECTED_SPLIT_COUNTS.items() if value
    }
    assert audit["structural_family_counts"] == STRUCTURAL_FAMILY_COUNTS
    assert audit["sealed_final_holdout_read"] is False
    assert audit["spec_audit"]["duplicate_pairs"] == []
    assert audit["spec_audit"]["material_split_leaks"] == {}
    assert all(
        json.loads(row["messages"][1]["content"])["routing_state"][
            "version"
        ]
        == "studyhub.router.state.v1"
        for row in rows
    )


def test_v1_3_structural_targets_match_normalized_state(
    state_tree: Path,
) -> None:
    rows = load_jsonl(state_tree / "router_tool_2b_v1_3_state.jsonl")
    structural = [
        row for row in rows if row["task_family"] in STRUCTURAL_FAMILY_COUNTS
    ]
    routes = Counter()
    for row in structural:
        target = row["assistant_target"]
        actions = target.get("actions") or []
        routes[actions[0]["name"] if actions else "final"] += 1

    assert len(structural) == 300
    assert routes == {
        "synthesize_course_context": 100,
        "read_pdf_evidence": 40,
        "final": 160,
    }


def test_v1_3_exports_without_test_records(state_tree: Path) -> None:
    export = export_llamafactory_dataset(
        source_path=state_tree / "router_tool_2b_v1_3_state.jsonl",
        dataset_dir=state_tree / "llamafactory",
        expected_profile_count=1800,
        expected_split_counts=EXPECTED_SPLIT_COUNTS,
    )

    assert export["counts"] == EXPECTED_SPLIT_COUNTS
    assert len(
        load_jsonl(state_tree / "llamafactory/router_tool_2b_train.jsonl")
    ) == 1620
