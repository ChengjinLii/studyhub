from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.agentic_platform.sft.build_targeted_router_v1_1 import (
    build_targeted_router_v1_1,
)
from ml.agentic_platform.sft.build_targeted_router_v1_2 import (
    EXPECTED_SPLIT_COUNTS,
    FAMILY_COUNTS,
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
def v1_2_tree(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("targeted-router-v1-2")
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

    v1_2_dir = root / "v1-2"
    build_targeted_router_v1_2(
        reference_dataset_path=v1_1_dir / "router_tool_2b_combined.jsonl",
        diagnostic_dataset_path=diagnostic,
        output_dir=v1_2_dir,
        generated_at="2026-07-31T00:03:00+00:00",
    )
    return {"root": root, "v1_2_dir": v1_2_dir}


def test_v1_2_counts_audit_and_isolation(
    v1_2_tree: dict[str, Path],
) -> None:
    root = v1_2_tree["v1_2_dir"]
    rows = load_jsonl(root / "router_tool_2b_v1_2.jsonl")
    audit = json.loads((root / "audit.json").read_text())

    assert len(rows) == 900
    assert audit["passed"] is True
    assert audit["family_counts"] == FAMILY_COUNTS
    assert audit["split_counts"] == {
        key: value for key, value in EXPECTED_SPLIT_COUNTS.items() if value
    }
    assert audit["contrast_pairs"] == {"budget": 150, "synthesis": 180}
    assert audit["diversity"]["unique_user_payloads"] == 900
    assert audit["diversity"]["unique_query_target_pairs"] == 900
    assert audit["sealed_final_holdout_read"] is False
    assert all(
        value == 0
        for key, value in audit["overlap_audit"].items()
        if key.startswith("exact_")
    )
    assert audit["overlap_audit"]["reserved_test_material_overlap"] == []


def test_v1_2_budget_contrast_pairs_change_only_policy_state(
    v1_2_tree: dict[str, Path],
) -> None:
    rows = load_jsonl(
        v1_2_tree["v1_2_dir"] / "router_tool_2b_v1_2.jsonl"
    )
    zero = {
        row["remediation_contract"]["contrast_index"]: row
        for row in rows
        if row["task_family"] == "budget_zero_final_contrast"
    }
    one = {
        row["remediation_contract"]["contrast_index"]: row
        for row in rows
        if row["task_family"] == "budget_one_continue_contrast"
    }

    assert set(zero) == set(one)
    for index in zero:
        zero_payload = json.loads(zero[index]["messages"][1]["content"])
        one_payload = json.loads(one[index]["messages"][1]["content"])
        assert zero_payload["current_user_query"] == one_payload["current_user_query"]
        assert zero_payload["tool_observations"] == one_payload["tool_observations"]
        assert zero_payload["force_final"] is True
        assert one_payload["force_final"] is False
        assert set(zero_payload["budget"].values()) == {0}
        assert one_payload["budget"]["remaining_tool_calls"] == 1
        assert zero[index]["assistant_target"]["mode"] == "final"
        assert (
            one[index]["assistant_target"]["actions"][0]["name"]
            == "read_pdf_evidence"
        )


def test_v1_2_synthesis_pairs_follow_evidence_readiness(
    v1_2_tree: dict[str, Path],
) -> None:
    rows = load_jsonl(
        v1_2_tree["v1_2_dir"] / "router_tool_2b_v1_2.jsonl"
    )
    ready = {
        row["remediation_contract"]["contrast_index"]: row
        for row in rows
        if row["task_family"] == "synthesis_ready_contrast"
    }
    pending = {
        row["remediation_contract"]["contrast_index"]: row
        for row in rows
        if row["task_family"] == "evidence_pending_contrast"
    }

    assert set(ready) == set(pending)
    for index in ready:
        ready_payload = json.loads(ready[index]["messages"][1]["content"])
        pending_payload = json.loads(pending[index]["messages"][1]["content"])
        assert (
            ready_payload["current_user_query"]
            == pending_payload["current_user_query"]
        )
        assert (
            ready[index]["assistant_target"]["actions"][0]["name"]
            == "synthesize_course_context"
        )
        assert (
            pending[index]["assistant_target"]["actions"][0]["name"]
            == "read_pdf_evidence"
        )


def test_v1_2_injection_rows_keep_readonly_action(
    v1_2_tree: dict[str, Path],
) -> None:
    rows = load_jsonl(
        v1_2_tree["v1_2_dir"] / "router_tool_2b_v1_2.jsonl"
    )
    injection_rows = [
        row
        for row in rows
        if row["task_family"] == "observation_injection_continue"
    ]

    assert len(injection_rows) == 150
    assert all(
        row["assistant_target"]["mode"] == "tools"
        and row["assistant_target"]["actions"][0]["name"]
        == "read_pdf_evidence"
        and "untrusted_tool_observation" in row["policy_tags"]
        for row in injection_rows
    )


def test_v1_2_exports_as_targeted_continuation_dataset(
    v1_2_tree: dict[str, Path],
) -> None:
    root = v1_2_tree["v1_2_dir"]
    export = export_llamafactory_dataset(
        source_path=root / "router_tool_2b_v1_2.jsonl",
        dataset_dir=root / "llamafactory",
        expected_profile_count=900,
        expected_split_counts=EXPECTED_SPLIT_COUNTS,
    )

    assert export["counts"] == EXPECTED_SPLIT_COUNTS
    assert len(
        load_jsonl(root / "llamafactory/router_tool_2b_train.jsonl")
    ) == 810
