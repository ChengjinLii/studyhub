from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.services.agent_tool_loop_service import AgentToolLoopService
from app.services.agent_tool_loop_service import (
    AGENT_TOOL_LOOP_SYSTEM_PROMPT,
    build_agent_routing_state,
)
from ml.agentic_platform.sft.build_validation_dataset import (
    DEFAULT_CHUNKS_PATH,
    DEFAULT_MATERIALS_PATH,
    EXPECTED_PROFILE_COUNTS,
    EXPECTED_SPLIT_COUNTS,
    build_validation_dataset,
)
from ml.agentic_platform.sft.evaluate_router import (
    _evaluation_messages,
    _score,
    _strict_json,
)
from ml.agentic_platform.sft.export_llamafactory import export_llamafactory_dataset
from ml.agentic_platform.sft.spec import (
    ALLOWED_TOOLS,
    DatasetSpecError,
    audit_datasets,
    load_jsonl,
    load_public_corpus,
    validate_record,
)

pytestmark = pytest.mark.private_sft_corpus


def test_sft_tool_contract_matches_product_agent() -> None:
    assert ALLOWED_TOOLS == AgentToolLoopService.allowed_tools


def test_builds_exact_spec_validation_counts_without_split_leakage(tmp_path: Path) -> None:
    output_dir = tmp_path / "spec-validation"
    manifest = build_validation_dataset(
        output_dir=output_dir,
        generated_at="2026-07-31T00:00:00+00:00",
    )

    assert manifest["counts"] == EXPECTED_PROFILE_COUNTS
    assert manifest["split_counts"] == EXPECTED_SPLIT_COUNTS
    assert manifest["validation_passed"] is True
    assert "human_gold" in manifest["not_claimed_as"]

    router_path = output_dir / "router_tool_2b.jsonl"
    tutor_path = output_dir / "grounded_tutor_9b.jsonl"
    assert len(load_jsonl(router_path)) == 500
    assert len(load_jsonl(tutor_path)) == 300

    audit = audit_datasets(
        [router_path, tutor_path],
        materials_path=DEFAULT_MATERIALS_PATH,
        chunks_path=DEFAULT_CHUNKS_PATH,
        expected_profile_counts=EXPECTED_PROFILE_COUNTS,
        expected_split_counts=EXPECTED_SPLIT_COUNTS,
    )
    assert audit.passed is True
    assert audit.duplicate_pairs == []
    assert audit.material_split_leaks == {}
    assert audit.total_records == 800


def test_rejects_private_netdisk_content(tmp_path: Path) -> None:
    output_dir = tmp_path / "spec-validation"
    build_validation_dataset(
        output_dir=output_dir,
        generated_at="2026-07-31T00:00:00+00:00",
    )
    records = load_jsonl(output_dir / "router_tool_2b.jsonl")
    materials, chunks = load_public_corpus(
        materials_path=DEFAULT_MATERIALS_PATH,
        chunks_path=DEFAULT_CHUNKS_PATH,
    )
    record = copy.deepcopy(records[0])
    user_payload = json.loads(record["messages"][1]["content"])
    user_payload["current_user_query"] = "读取 https://pan.baidu.com/s/example?pwd=test"
    record["messages"][1]["content"] = json.dumps(user_payload, ensure_ascii=False)

    with pytest.raises(DatasetSpecError, match="forbidden content"):
        validate_record(record, materials=materials, chunks=chunks)


def test_rejects_material_split_leakage(tmp_path: Path) -> None:
    output_dir = tmp_path / "spec-validation"
    build_validation_dataset(
        output_dir=output_dir,
        generated_at="2026-07-31T00:00:00+00:00",
    )
    router_rows = load_jsonl(output_dir / "router_tool_2b.jsonl")
    first_public = next(row for row in router_rows if row["evidence_refs"])
    leaked = copy.deepcopy(first_public)
    leaked["example_id"] = "2b_9999"
    leaked["split"] = "test" if first_public["split"] != "test" else "train"
    leaked["messages"][1]["content"] = json.dumps(
        {
            **json.loads(leaked["messages"][1]["content"]),
            "conversation_context": "独立的合成泄漏检测样本。",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    with (output_dir / "router_tool_2b.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(leaked, ensure_ascii=False, sort_keys=True) + "\n")

    audit = audit_datasets(
        [
            output_dir / "router_tool_2b.jsonl",
            output_dir / "grounded_tutor_9b.jsonl",
        ],
        materials_path=DEFAULT_MATERIALS_PATH,
        chunks_path=DEFAULT_CHUNKS_PATH,
    )
    material_id = int(leaked["evidence_refs"][0]["material_id"])
    assert material_id in audit.material_split_leaks


def test_exports_llamafactory_sharegpt_splits(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    build_validation_dataset(
        output_dir=source_dir,
        generated_at="2026-07-31T00:00:00+00:00",
    )
    dataset_dir = tmp_path / "llamafactory"
    manifest = export_llamafactory_dataset(
        source_path=source_dir / "router_tool_2b.jsonl",
        dataset_dir=dataset_dir,
    )

    assert manifest["counts"] == {"train": 400, "validation": 50, "test": 50}
    assert manifest["assistant_only_loss"] is True
    dataset_info = json.loads((dataset_dir / "dataset_info.json").read_text())
    assert dataset_info["studyhub_router_2b_train"]["formatting"] == "sharegpt"
    rows = load_jsonl(dataset_dir / "router_tool_2b_train.jsonl")
    assert len(rows) == 400
    assert [message["role"] for message in rows[0]["messages"]] == [
        "system",
        "user",
        "assistant",
    ]


def test_router_evaluator_requires_bare_strict_json() -> None:
    valid = '{"mode":"final","answer":"无法执行写操作。"}'
    assert _strict_json(valid) == {
        "mode": "final",
        "answer": "无法执行写操作。",
    }
    assert _strict_json(f"<think>internal</think>{valid}") is None
    assert _strict_json(f"```json\n{valid}\n```") is None
    assert _strict_json(f"prefix {valid}") is None


def test_router_evaluator_scores_exact_tool_arguments() -> None:
    expected = {
        "mode": "tools",
        "actions": [
            {
                "name": "search_materials",
                "arguments": {"query": "高等数学", "limit": 5},
            }
        ],
    }
    exact = {
        "mode": "tools",
        "progress": "检索中",
        "task_context": {},
        "actions": [
            {
                "arguments": {"limit": 5, "query": "高等数学"},
                "name": "search_materials",
            }
        ],
    }
    wrong_limit = {
        "mode": "tools",
        "progress": "检索中",
        "task_context": {},
        "actions": [
            {
                "name": "search_materials",
                "arguments": {"query": "高等数学", "limit": 10},
            }
        ],
    }

    assert _score(expected, exact)["arguments_exact"] is True
    assert _score(expected, exact)["contract_valid"] is True
    assert _score(expected, wrong_limit)["tool_name_correct"] is True
    assert _score(expected, wrong_limit)["arguments_exact"] is False


def test_router_evaluator_rejects_invalid_tool_contract() -> None:
    expected = {
        "mode": "tools",
        "actions": [
            {
                "name": "search_materials",
                "arguments": {"query": "高等数学", "limit": 5},
            }
        ],
    }
    invalid = {
        "mode": "tools",
        "progress": "检索中",
        "task_context": {},
        "actions": [
            {
                "name": "search_materials",
                "arguments": {"query": "高等数学", "limit": 999},
            }
        ],
    }

    assert _score(expected, invalid)["tool_name_correct"] is True
    assert _score(expected, invalid)["contract_valid"] is False


def test_router_evaluator_can_replay_exact_production_contract(tmp_path: Path) -> None:
    output_dir = tmp_path / "spec-validation"
    build_validation_dataset(
        output_dir=output_dir,
        generated_at="2026-07-31T00:00:00+00:00",
    )
    record = load_jsonl(output_dir / "router_tool_2b.jsonl")[0]
    messages = _evaluation_messages(
        record,
        normalize_routing_state=True,
        production_contract=True,
    )
    payload = json.loads(messages[1]["content"])

    assert messages[0]["content"] == AGENT_TOOL_LOOP_SYSTEM_PROMPT
    expected_payload = json.loads(record["messages"][1]["content"])
    expected_payload["routing_state"] = build_agent_routing_state(expected_payload)
    assert payload == expected_payload
