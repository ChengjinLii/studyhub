import hashlib
import json
from pathlib import Path

import pytest

from scripts.data.build_runtime_sft_v3 import (
    _normalize_toolace,
    _wiki_component_assignments,
    benchmark_lock,
)
from scripts.data.select_runtime_sft_v3 import select_diverse_rows
from studyhub_agent.trajectory.runtime_sft import (
    make_record,
    tools_from_system,
    validate_runtime_trajectory,
)


def _toolace_system() -> str:
    tools = [
        {
            "name": "Search for Words in Title, Text, or URL",
            "description": "Search a document collection.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
        {
            "name": "Read Result",
            "description": "Read one result.",
            "parameters": {
                "type": "object",
                "properties": {"source_id": {"type": "string"}},
                "required": ["source_id"],
            },
        },
    ]
    return "Use the tools. Here is a list of functions in JSON format that you can invoke:" + json.dumps(tools)


def test_toolace_normalizer_preserves_recorded_multistep_observations() -> None:
    row = {
        "system": _toolace_system(),
        "conversations": [
            {"from": "user", "value": "Find and read the source."},
            {"from": "assistant", "value": '[Search for Words in Title, Text, or URL(query="StudyHub")]'},
            {
                "from": "tool",
                "value": json.dumps([{"name": "Search", "results": {"source_id": "doc-1"}}]),
            },
            {"from": "assistant", "value": '[Read Result(source_id="doc-1")]'},
            {
                "from": "tool",
                "value": json.dumps([{"name": "Read", "results": {"text": "evidence"}}]),
            },
            {"from": "assistant", "value": "The source says evidence."},
        ],
    }

    messages, tools = _normalize_toolace(row, index=7)

    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    assert len(tools) == 2
    assert messages[2]["tool_calls"][0]["function"]["name"] == "Search_for_Words_in_Title_Text_or_URL"
    assert messages[3]["tool_call_id"] == messages[2]["tool_calls"][0]["id"]
    assert messages[5]["tool_call_id"] == messages[4]["tool_calls"][0]["id"]
    record = make_record(
        record_id="toolace:test",
        group_id="toolace:test",
        source_dataset="toolace",
        source_id="test",
        task_family="open_function_calling",
        messages=messages,
        tools=tools,
        provenance={},
        capability_tags=["function_calling"],
        quality_tier="expert_complete",
    )
    assert validate_runtime_trajectory(record) == []


def test_toolace_normalizer_keeps_a_valid_action_only_tail() -> None:
    row = {
        "system": _toolace_system(),
        "conversations": [
            {"from": "user", "value": "Find the source."},
            {"from": "assistant", "value": '[Search for Words in Title, Text, or URL(query="StudyHub")]'},
        ],
    }

    messages, tools = _normalize_toolace(row, index=11)

    assert tools
    assert messages[-1]["tool_calls"]


def test_hermes_tool_parser_skips_the_empty_example_block() -> None:
    payload = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
    system = f"Signatures are within <tools> </tools>.\n<tools>{json.dumps(payload)}</tools>"

    assert tools_from_system(system) == payload


def test_2wiki_components_are_transitive_and_title_normalized() -> None:
    rows = [
        {
            "_id": "a",
            "supporting_facts": json.dumps([["Alpha Page", 0], ["Bridge Page", 1]]),
        },
        {
            "_id": "b",
            "supporting_facts": json.dumps([[" bridge   page ", 0], ["Gamma Page", 1]]),
        },
        {
            "_id": "c",
            "supporting_facts": json.dumps([["GAMMA PAGE", 0], ["Delta Page", 1]]),
        },
        {
            "_id": "isolated",
            "supporting_facts": json.dumps([["Independent Page", 0]]),
        },
    ]

    assignments = _wiki_component_assignments(rows)

    connected = {assignments[row_id] for row_id in ("a", "b", "c")}
    assert len(connected) == 1
    assert assignments["isolated"][0] != assignments["a"][0]


def test_diverse_selection_enforces_group_cap() -> None:
    rows = [
        {"id": "a", "group_id": "shared", "quality_tier": "expert_complete"},
        {"id": "b", "group_id": "shared", "quality_tier": "expert_complete"},
        {"id": "c", "group_id": "independent", "quality_tier": "expert_complete"},
    ]

    selected = select_diverse_rows(rows, 2, max_rows_per_group=1)

    assert len(selected) == 2
    assert len({row["group_id"] for row in selected}) == 2


def test_runtime_sft_benchmark_lock_fails_closed_on_inventory_drift(tmp_path: Path) -> None:
    inventory = tmp_path / "source-inventory.jsonl"
    inventory.write_text('{"material_id": 1}\n', encoding="utf-8")
    inventory_hash = hashlib.sha256(inventory.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "benchmark_version": "studyhub-agentbench-v2",
                "benchmark_revision": "2.0.0",
                "status": "FROZEN_FOR_BASELINE",
                "counts": {"development": 98},
                "hidden_files": {"source-inventory.jsonl": inventory_hash},
            }
        ),
        encoding="utf-8",
    )

    lock = benchmark_lock(manifest, inventory)
    assert lock["benchmark_tasks"] == 98

    inventory.write_text('{"material_id": 2}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="frozen manifest"):
        benchmark_lock(manifest, inventory)
