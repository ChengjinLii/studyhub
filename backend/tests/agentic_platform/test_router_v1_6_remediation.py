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
    replay_tree as _replay_tree_fixture,  # noqa: F401
)
from backend.tests.agentic_platform.test_router_v1_4_runtime_aligned import (
    runtime_aligned_tree as _runtime_aligned_tree_fixture,  # noqa: F401
)
from backend.tests.agentic_platform.test_router_v1_5_contract_aligned import (
    contract_aligned_tree as _contract_aligned_tree_fixture,
)
from ml.agentic_platform.sft.build_router_v1_6_remediation import (
    EXPECTED_RUNTIME_PATH_COUNTS,
    EXPECTED_SPLIT_COUNTS,
    FAMILY_COUNTS,
    build_router_v1_6_remediation,
)
from ml.agentic_platform.sft.spec import load_jsonl, validate_assistant_target

pytestmark = pytest.mark.private_sft_corpus


@pytest.fixture(scope="module")
def remediation_tree(
    _contract_aligned_tree_fixture: Path,  # noqa: F811
) -> Path:
    output_dir = _contract_aligned_tree_fixture.parent / "v1-6-remediation"
    build_router_v1_6_remediation(
        source_path=_contract_aligned_tree_fixture / "router_tool_2b_v1_5.jsonl",
        split_reference_path=(
            _contract_aligned_tree_fixture.parent
            / "v1-1/router_tool_2b_combined.jsonl"
        ),
        diagnostic_path=(
            _contract_aligned_tree_fixture.parent
            / "diagnostic/router_hidden_300.jsonl"
        ),
        output_dir=output_dir,
        generated_at="2026-08-11T00:00:00+00:00",
    )
    return output_dir


def test_v1_6_counts_and_exact_runtime_states(remediation_tree: Path) -> None:
    rows = load_jsonl(remediation_tree / "router_tool_2b_v1_6.jsonl")
    audit = json.loads((remediation_tree / "audit.json").read_text())

    assert len(rows) == 1440
    assert audit["passed"] is True
    assert Counter(row["task_family"] for row in rows) == FAMILY_COUNTS
    assert Counter(row["split"] for row in rows) == {
        key: value for key, value in EXPECTED_SPLIT_COUNTS.items() if value
    }
    assert Counter(
        row["remediation_contract"]["runtime_path"] for row in rows
    ) == EXPECTED_RUNTIME_PATH_COUNTS
    assert audit["sealed_final_holdout_read"] is False

    for row in rows:
        assert row["messages"][0]["content"] == AGENT_TOOL_LOOP_SYSTEM_PROMPT
        payload = json.loads(row["messages"][1]["content"])
        if row["remediation_contract"]["runtime_path"] == "runtime_state":
            assert payload["routing_state"] == build_agent_routing_state(payload)
        else:
            assert "routing_state" not in payload
        validate_assistant_target(row["assistant_target"], profile="router_tool_2b")


def test_v1_6_injection_stage_and_runtime_form_four_cells(
    remediation_tree: Path,
) -> None:
    rows = load_jsonl(remediation_tree / "router_tool_2b_v1_6.jsonl")
    injection_rows = [
        row for row in rows if row["task_family"].startswith("injection_")
    ]
    cells = Counter(
        (
            row["task_family"],
            row["remediation_contract"]["runtime_path"],
        )
        for row in injection_rows
    )
    assert cells == {
        ("injection_after_search_inspect_v1_6", "raw"): 80,
        ("injection_after_search_inspect_v1_6", "runtime_state"): 80,
        ("injection_after_inspect_read_v1_6", "raw"): 80,
        ("injection_after_inspect_read_v1_6", "runtime_state"): 80,
    }

    split_cells = Counter(
        (
            row["split"],
            row["task_family"],
            row["remediation_contract"]["runtime_path"],
        )
        for row in injection_rows
    )
    for family in (
        "injection_after_search_inspect_v1_6",
        "injection_after_inspect_read_v1_6",
    ):
        assert split_cells[("train", family, "raw")] == 72
        assert split_cells[("train", family, "runtime_state")] == 72
        assert split_cells[("validation", family, "raw")] == 8
        assert split_cells[("validation", family, "runtime_state")] == 8


def test_v1_6_natural_concept_cases_do_not_reveal_the_label(
    remediation_tree: Path,
) -> None:
    rows = load_jsonl(remediation_tree / "router_tool_2b_v1_6.jsonl")
    concept_rows = [
        row for row in rows if row["task_family"] == "natural_concept_read_v1_6"
    ]
    assert len(concept_rows) == 240
    observation_shapes = Counter()
    for row in concept_rows:
        payload = json.loads(row["messages"][1]["content"])
        query = payload["current_user_query"]
        assert "必须先读取页面" not in query
        assert "唯一正确的下一步" not in query
        assert row["assistant_target"]["actions"][0]["name"] == "read_pdf_evidence"
        observation_shapes[tuple(item["tool"] for item in payload["tool_observations"])] += 1
    assert observation_shapes == {
        ("inspect_materials",): 120,
        ("search_materials", "inspect_materials"): 120,
    }


def test_v1_6_final_targets_are_complete_and_budget_safe(
    remediation_tree: Path,
) -> None:
    rows = load_jsonl(remediation_tree / "router_tool_2b_v1_6.jsonl")
    final_rows = [
        row
        for row in rows
        if row["task_family"]
        in {"force_final_strict_json_v1_6", "direct_complete_final_v1_6"}
    ]
    assert len(final_rows) == 280
    for row in final_rows:
        target = row["assistant_target"]
        payload = json.loads(row["messages"][1]["content"])
        assert target["mode"] == "final"
        assert len(target["answer"]) >= 40
        if row["task_family"] == "force_final_strict_json_v1_6":
            assert payload["force_final"] is True
            assert payload["budget"]["remaining_tool_calls"] == 0
            assert build_agent_routing_state(payload)["must_finish_without_tools"] is True
