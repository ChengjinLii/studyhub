import json
from collections import Counter

from scripts.data.select_open_agentic_token_budget import (
    InventoryRow,
    load_inventory_cache,
    write_inventory_cache,
)
from studyhub_agent.trajectory.open_agentic import (
    iter_json_array,
    observation_has_error,
    parse_toolbench_record,
    parse_toolbench_tools,
)


def _toolbench_system() -> str:
    tools = [
        {
            "name": "lookup_user",
            "description": "Look up a user.",
            "parameters": {
                "type": "object",
                "properties": {"username": {"type": "string"}},
                "required": ["username"],
                "optional": [],
            },
        },
        {
            "name": "lookup_posts",
            "description": "Look up recent posts.",
            "parameters": {
                "type": "object",
                "properties": {"user_id": {"type": "string"}},
                "required": ["user_id"],
                "optional": [],
            },
        },
        {
            "name": "Finish",
            "description": "Finish the task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "return_type": {"type": "string"},
                    "final_answer": {"type": "string"},
                },
                "required": ["return_type"],
            },
        },
    ]
    return f"Specifically, you have access to the following APIs: {tools!r}"


def _toolbench_row() -> dict:
    return {
        "id": "Step 7: Find a user and their recent posts.",
        "conversations": [
            {"from": "system", "value": _toolbench_system()},
            {"from": "user", "value": "Find a user and their recent posts.\nBegin!\n"},
            {
                "from": "assistant",
                "value": 'Thought: first call.\nAction: lookup_user\nAction Input: {"username": "alice"}',
            },
            {"from": "function", "value": '{"error": "", "response": {"id": "u1"}}'},
            {
                "from": "assistant",
                "value": 'Thought: use the ID.\nAction: lookup_posts\nAction Input: {"user_id": "u1"}',
            },
            {"from": "function", "value": '{"error": "", "response": [{"title": "hello"}]}'},
            {
                "from": "assistant",
                "value": (
                    "Thought: done.\nAction: Finish\nAction Input: "
                    '{"return_type": "give_answer", "final_answer": "Alice posted hello."}'
                ),
            },
        ],
    }


def test_iter_json_array_streams_across_small_chunks(tmp_path) -> None:
    path = tmp_path / "rows.json"
    rows = [{"id": index, "text": "x" * 17} for index in range(5)]
    path.write_text(json.dumps(rows), encoding="utf-8")

    assert list(iter_json_array(path, chunk_size=13)) == rows


def test_parse_toolbench_tools_excludes_finish_and_optional_extension() -> None:
    tools = parse_toolbench_tools(_toolbench_system())

    assert [tool["function"]["name"] for tool in tools] == ["lookup_user", "lookup_posts"]
    assert "optional" not in tools[0]["function"]["parameters"]


def test_parse_toolbench_record_keeps_actions_observations_and_final_without_thought() -> None:
    record, reason = parse_toolbench_record(
        _toolbench_row(),
        revision="archive-sha256:test",
        license_name="Apache-2.0",
        source_url="https://github.com/OpenBMB/ToolBench",
        archive_sha256="abc",
    )

    assert reason == "accepted"
    assert record is not None
    assert record["policy_quality_tier"] == "A"
    assert record["behavior_tags"] == ["multi_tool", "multi_turn", "observation_conditioned"]
    assert record["tool_call_count"] == 2
    assert record["messages"][-1]["content"] == "Alice posted hello."
    assert all("Thought:" not in str(message.get("content", "")) for message in record["messages"])


def test_parse_toolbench_record_rejects_unresolved_failure() -> None:
    row = _toolbench_row()
    row["conversations"][5]["value"] = '{"error": "provider unavailable", "response": ""}'

    record, reason = parse_toolbench_record(
        row,
        revision="archive-sha256:test",
        license_name="Apache-2.0",
        source_url="https://github.com/OpenBMB/ToolBench",
        archive_sha256="abc",
    )

    assert record is None
    assert reason == "toolbench:unresolved_failure"


def test_empty_error_field_is_not_a_failed_observation() -> None:
    assert not observation_has_error('{"error": "", "response": {"ok": true}}')


def test_token_inventory_cache_is_lineage_bound(tmp_path) -> None:
    path = tmp_path / "inventory.jsonl"
    row = InventoryRow(
        record_id="row-1",
        position=0,
        split="train",
        source="source",
        source_family="hermes",
        group_id="group-1",
        total_tokens=20,
        assistant_tokens=5,
        behaviors=("multi_turn",),
        abstract_path="single-tool -> final",
        exact_path="tool -> final",
        quality_tier="A",
        stable_order="abc",
    )
    lineage = {"candidate_sha256": "candidate", "max_length": 8192}

    write_inventory_cache(path, [row], Counter(), lineage=lineage)

    loaded = load_inventory_cache(path, expected_lineage=lineage)
    assert loaded is not None
    assert loaded[0] == [row]
    assert load_inventory_cache(path, expected_lineage={"candidate_sha256": "other"}) is None
