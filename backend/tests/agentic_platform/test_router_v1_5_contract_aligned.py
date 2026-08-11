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
    runtime_aligned_tree as _runtime_aligned_tree_fixture,
)
from ml.agentic_platform.sft.build_router_v1_5_contract_aligned import (
    EXPECTED_RUNTIME_PATH_COUNTS,
    EXPECTED_SPLIT_COUNTS,
    build_router_v1_5_contract_aligned,
)
from ml.agentic_platform.sft.spec import load_jsonl


@pytest.fixture(scope="module")
def contract_aligned_tree(
    _runtime_aligned_tree_fixture: Path,  # noqa: F811
) -> Path:
    output_dir = _runtime_aligned_tree_fixture.parent / "v1-5-contract-aligned"
    build_router_v1_5_contract_aligned(
        source_path=_runtime_aligned_tree_fixture / "router_tool_2b_v1_4.jsonl",
        split_reference_path=(
            _runtime_aligned_tree_fixture.parent
            / "v1-1/router_tool_2b_combined.jsonl"
        ),
        diagnostic_path=(
            _runtime_aligned_tree_fixture.parent
            / "diagnostic/router_hidden_300.jsonl"
        ),
        output_dir=output_dir,
        generated_at="2026-08-11T00:00:00+00:00",
    )
    return output_dir


def test_v1_5_rebuilds_exact_production_states(contract_aligned_tree: Path) -> None:
    rows = load_jsonl(contract_aligned_tree / "router_tool_2b_v1_5.jsonl")
    audit = json.loads((contract_aligned_tree / "audit.json").read_text())

    assert len(rows) == 1800
    assert audit["passed"] is True
    assert audit["split_counts"] == {
        key: value for key, value in EXPECTED_SPLIT_COUNTS.items() if value
    }
    assert audit["runtime_path_counts"] == EXPECTED_RUNTIME_PATH_COUNTS
    assert audit["sealed_final_holdout_read"] is False
    for row in rows:
        assert row["messages"][0]["content"] == AGENT_TOOL_LOOP_SYSTEM_PROMPT
        payload = json.loads(row["messages"][1]["content"])
        if row["remediation_contract"]["runtime_path"] == "runtime_state":
            assert payload["routing_state"] == build_agent_routing_state(payload)
        else:
            assert "routing_state" not in payload


def test_v1_5_uses_production_observation_fields(contract_aligned_tree: Path) -> None:
    rows = load_jsonl(contract_aligned_tree / "router_tool_2b_v1_5.jsonl")
    required = {
        "search_materials": "candidates",
        "inspect_materials": "materials",
        "read_pdf_evidence": "evidence",
        "read_memory": "memory",
    }
    for row in rows:
        payload = json.loads(row["messages"][1]["content"])
        for observation in payload["tool_observations"]:
            field = required.get(observation["tool"])
            if field:
                assert field in observation["result"]


def test_v1_5_balances_injection_continuation_stage(
    contract_aligned_tree: Path,
) -> None:
    rows = load_jsonl(contract_aligned_tree / "router_tool_2b_v1_5.jsonl")
    injection_rows = [row for row in rows if row["task_family"].startswith("injection_")]
    counts = Counter(row["task_family"] for row in injection_rows)

    assert counts == {
        "injection_after_search_inspect_v1_5": 30,
        "injection_after_inspect_read_v1_5": 30,
    }
    for row in injection_rows:
        payload = json.loads(row["messages"][1]["content"])
        target_tool = row["assistant_target"]["actions"][0]["name"]
        if target_tool == "inspect_materials":
            assert [item["tool"] for item in payload["tool_observations"]] == [
                "search_materials"
            ]
        else:
            assert [item["tool"] for item in payload["tool_observations"]] == [
                "search_materials",
                "inspect_materials",
            ]
