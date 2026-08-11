from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from ml.agentic_platform.sft.build_router_v1_2_replay_mixture import (
    ALIAS_FAMILY_COUNTS,
    EXPECTED_COMPONENT_COUNTS,
    EXPECTED_SPLIT_COUNTS,
    REPLAY_FAMILY_COUNTS,
    build_router_v1_2_replay_mixture,
)
from ml.agentic_platform.sft.build_targeted_router_v1_1 import (
    build_targeted_router_v1_1,
)
from ml.agentic_platform.sft.build_targeted_router_v1_2 import (
    build_targeted_router_v1_2,
)
from ml.agentic_platform.sft.build_teacher_hidden_eval import (
    build_teacher_hidden_eval,
)
from ml.agentic_platform.sft.build_validation_dataset import (
    build_validation_dataset,
)
from ml.agentic_platform.sft.export_llamafactory import (
    export_llamafactory_dataset,
)
from ml.agentic_platform.sft.spec import load_jsonl

pytestmark = pytest.mark.private_sft_corpus


@pytest.fixture(scope="module")
def replay_tree(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("router-v1-2-replay")
    original_dir = root / "original"
    build_validation_dataset(
        output_dir=original_dir,
        generated_at="2026-07-31T00:00:00+00:00",
    )
    original = original_dir / "router_tool_2b.jsonl"

    diagnostic_dir = root / "diagnostic"
    build_teacher_hidden_eval(
        output_dir=diagnostic_dir,
        reference_dataset_path=original,
        generated_at="2026-07-31T00:01:00+00:00",
    )
    diagnostic = diagnostic_dir / "router_hidden_300.jsonl"

    v1_1_dir = root / "v1-1"
    build_targeted_router_v1_1(
        reference_dataset_path=original,
        diagnostic_dataset_path=diagnostic,
        output_dir=v1_1_dir,
        generated_at="2026-07-31T00:02:00+00:00",
    )
    v1_1 = v1_1_dir / "router_tool_2b_combined.jsonl"

    v1_2_dir = root / "v1-2"
    build_targeted_router_v1_2(
        reference_dataset_path=v1_1,
        diagnostic_dataset_path=diagnostic,
        output_dir=v1_2_dir,
        generated_at="2026-07-31T00:03:00+00:00",
    )
    v1_2 = v1_2_dir / "router_tool_2b_v1_2.jsonl"

    replay_dir = root / "replay"
    build_router_v1_2_replay_mixture(
        v1_1_dataset_path=v1_1,
        v1_2_dataset_path=v1_2,
        diagnostic_dataset_path=diagnostic,
        output_dir=replay_dir,
        generated_at="2026-07-31T00:04:00+00:00",
    )
    return {
        "root": root,
        "v1_1": v1_1,
        "v1_2": v1_2,
        "replay_dir": replay_dir,
    }


def test_replay_mixture_counts_audit_and_isolation(
    replay_tree: dict[str, Path],
) -> None:
    root = replay_tree["replay_dir"]
    rows = load_jsonl(root / "router_tool_2b_v1_2_replay.jsonl")
    audit = json.loads((root / "audit.json").read_text())

    assert len(rows) == 1500
    assert audit["passed"] is True
    assert audit["component_counts"] == EXPECTED_COMPONENT_COUNTS
    assert audit["split_counts"] == {
        key: value for key, value in EXPECTED_SPLIT_COUNTS.items() if value
    }
    assert audit["replay_family_counts"] == REPLAY_FAMILY_COUNTS
    assert audit["alias_family_counts"] == ALIAS_FAMILY_COUNTS
    assert audit["sealed_final_holdout_read"] is False
    assert audit["spec_audit"]["duplicate_pairs"] == []
    assert audit["spec_audit"]["material_split_leaks"] == {}


def test_replay_rows_are_exact_v1_1_records(
    replay_tree: dict[str, Path],
) -> None:
    source = {
        row["example_id"]: row for row in load_jsonl(replay_tree["v1_1"])
    }
    rows = load_jsonl(
        replay_tree["replay_dir"] / "router_tool_2b_v1_2_replay.jsonl"
    )
    replay = [
        row
        for row in rows
        if row["task_family"] in REPLAY_FAMILY_COUNTS
    ]

    assert len(replay) == 300
    assert all(row == source[row["example_id"]] for row in replay)


def test_aliases_cover_failed_routing_boundaries(
    replay_tree: dict[str, Path],
) -> None:
    rows = load_jsonl(
        replay_tree["replay_dir"] / "router_tool_2b_v1_2_replay.jsonl"
    )
    aliases = [
        row
        for row in rows
        if row["task_family"] in ALIAS_FAMILY_COUNTS
    ]
    tools = Counter(
        (row["assistant_target"].get("actions") or [{}])[0].get("name")
        for row in aliases
    )
    statuses = Counter(
        row["remediation_contract"].get("evidence_state_alias")
        for row in aliases
        if row["task_family"] == "synthesis_state_alias"
    )

    assert len(aliases) == 300
    assert tools["synthesize_course_context"] == 100
    assert tools["inspect_materials"] == 80
    assert tools["read_memory"] == 50
    assert tools[None] == 70
    assert set(statuses) == {
        "available_but_not_yet_synthesized",
        "evidence_available",
        "pages_ready_for_context",
        "ready_for_synthesis",
    }
    assert all(value == 25 for value in statuses.values())


def test_replay_mixture_exports_without_test_records(
    replay_tree: dict[str, Path],
) -> None:
    root = replay_tree["replay_dir"]
    export = export_llamafactory_dataset(
        source_path=root / "router_tool_2b_v1_2_replay.jsonl",
        dataset_dir=root / "llamafactory",
        expected_profile_count=1500,
        expected_split_counts=EXPECTED_SPLIT_COUNTS,
    )

    assert export["counts"] == EXPECTED_SPLIT_COUNTS
    assert len(
        load_jsonl(root / "llamafactory/router_tool_2b_train.jsonl")
    ) == 1350
    assert (
        root / "llamafactory/router_tool_2b_test.jsonl"
    ).read_text() == ""
