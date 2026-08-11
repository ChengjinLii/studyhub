from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from app.services.agent_tool_loop_service import (
    AGENT_TOOL_LOOP_SYSTEM_PROMPT,
    build_agent_routing_state,
)
from backend.tests.agentic_platform.test_router_v1_2_replay_mixture import (
    replay_tree as _replay_tree_fixture,
)
from ml.agentic_platform.sft.build_router_v1_4_runtime_aligned import (
    EXPECTED_RUNTIME_PATH_COUNTS,
    EXPECTED_SPLIT_COUNTS,
    FAMILY_COUNTS,
    build_router_v1_4_runtime_aligned,
)
from ml.agentic_platform.sft.export_llamafactory import (
    export_llamafactory_dataset,
)
from ml.agentic_platform.sft.spec import load_jsonl

pytestmark = pytest.mark.private_sft_corpus


@pytest.fixture(scope="module")
def runtime_aligned_tree(
    _replay_tree_fixture: dict[str, Path],  # noqa: F811
) -> Path:
    output_dir = _replay_tree_fixture["root"] / "v1-4-runtime-aligned"
    build_router_v1_4_runtime_aligned(
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
        generated_at="2026-08-11T00:00:00+00:00",
    )
    return output_dir


def test_v1_4_counts_and_isolation(runtime_aligned_tree: Path) -> None:
    rows = load_jsonl(runtime_aligned_tree / "router_tool_2b_v1_4.jsonl")
    audit = json.loads((runtime_aligned_tree / "audit.json").read_text())

    assert len(rows) == 1800
    assert audit["passed"] is True
    assert audit["split_counts"] == {
        key: value for key, value in EXPECTED_SPLIT_COUNTS.items() if value
    }
    assert audit["family_counts"] == FAMILY_COUNTS
    assert audit["runtime_path_counts"] == EXPECTED_RUNTIME_PATH_COUNTS
    assert audit["sealed_final_holdout_read"] is False
    assert audit["offline_pilot_overlap_audit"]["exact_query_overlap"] == 0
    assert audit["offline_pilot_overlap_audit"]["pilot_outputs_or_labels_read"] is False
    assert audit["spec_audit"]["duplicate_pairs"] == []
    assert audit["spec_audit"]["material_split_leaks"] == {}


def test_v1_4_uses_exact_production_prompt_and_state(
    runtime_aligned_tree: Path,
) -> None:
    rows = load_jsonl(runtime_aligned_tree / "router_tool_2b_v1_4.jsonl")
    paths = Counter()
    for row in rows:
        assert row["messages"][0]["content"] == AGENT_TOOL_LOOP_SYSTEM_PROMPT
        payload = json.loads(row["messages"][1]["content"])
        path = row["remediation_contract"]["runtime_path"]
        paths[path] += 1
        if path == "runtime_state":
            assert payload["routing_state"] == build_agent_routing_state(payload)
        else:
            assert "routing_state" not in payload
    assert paths == EXPECTED_RUNTIME_PATH_COUNTS


def test_v1_4_key_decision_contracts(runtime_aligned_tree: Path) -> None:
    rows = load_jsonl(runtime_aligned_tree / "router_tool_2b_v1_4.jsonl")
    expected_tools = {
        "search_before_candidate_use_v1_4": "search_materials",
        "inspect_after_search_v1_4": "inspect_materials",
        "page_number_fidelity_v1_4": "read_pdf_evidence",
        "injection_continue_readonly_v1_4": "read_pdf_evidence",
        "evidence_pending_read_v1_4": "read_pdf_evidence",
        "evidence_ready_synthesize_v1_4": "synthesize_course_context",
    }
    for family, tool_name in expected_tools.items():
        family_rows = [row for row in rows if row["task_family"] == family]
        assert len(family_rows) == FAMILY_COUNTS[family]
        assert all(
            row["assistant_target"]["mode"] == "tools"
            and row["assistant_target"]["actions"][0]["name"] == tool_name
            for row in family_rows
        )

    final_families = {
        "permission_refusal_v1_4",
        "must_finish_without_tools_v1_4",
        "compare_complete_final_v1_4",
        "direct_answer_retention_v1_4",
        "force_final_retention_v1_4",
    }
    assert all(
        row["assistant_target"]["mode"] == "final"
        for row in rows
        if row["task_family"] in final_families
    )


def test_v1_4_exports_assistant_only_splits(
    runtime_aligned_tree: Path,
) -> None:
    export = export_llamafactory_dataset(
        source_path=runtime_aligned_tree / "router_tool_2b_v1_4.jsonl",
        dataset_dir=runtime_aligned_tree / "llamafactory",
        expected_profile_count=1800,
        expected_split_counts=EXPECTED_SPLIT_COUNTS,
    )

    assert export["counts"] == EXPECTED_SPLIT_COUNTS
    assert export["assistant_only_loss"] is True
    assert len(
        load_jsonl(
            runtime_aligned_tree
            / "llamafactory/router_tool_2b_train.jsonl"
        )
    ) == 1620
