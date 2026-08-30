from __future__ import annotations

import json

import pytest

from studyhub_agent.eval.protocol_holdout import (
    build_protocol_items,
    classify_chat_completion,
    score_protocol_item,
    select_protocol_rows,
    summarize_protocol_results,
    wire_messages,
)


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Call {name}",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }


def _row(row_id: str = "row-1") -> dict:
    return {
        "id": row_id,
        "split": "protocol_holdout",
        "source_dataset": "fixture",
        "source_family": "hermes",
        "quality_tier": "expert_recorded_complete",
        "tools": [_tool("lookup")],
        "messages": [
            {"role": "system", "content": "Use tools."},
            {"role": "user", "content": "Find alpha."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": {"query": "alpha"}},
                    }
                ],
            },
            {
                "role": "tool",
                "name": "lookup",
                "tool_call_id": "call-1",
                "content": '{"result":"alpha"}',
            },
            {"role": "assistant", "content": "Alpha was found."},
            {"role": "user", "content": "Find beta."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-2",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": {"query": "beta"}},
                    }
                ],
            },
            {
                "role": "tool",
                "name": "lookup",
                "tool_call_id": "call-2",
                "content": '{"result":"beta"}',
            },
            {"role": "assistant", "content": "Beta was found."},
        ],
    }


def _payload(*, content: str = "", calls: list[dict] | None = None, reasoning: str = "") -> dict:
    message = {"content": content, "tool_calls": calls or []}
    if reasoning:
        message["reasoning_content"] = reasoning
    return {"choices": [{"finish_reason": "tool_calls" if calls else "stop", "message": message}]}


def _call(name: str = "lookup", arguments: str = '{"query":"alpha"}') -> dict:
    return {"id": "generated-1", "type": "function", "function": {"name": name, "arguments": arguments}}


def test_build_items_preserves_gold_prefix_without_leaking_target() -> None:
    items = build_protocol_items([_row()])

    assert [item.expected_kind for item in items] == ["tool_call", "continuation", "tool_call", "final"]
    assert items[0].expected_tool_names == ("lookup",)
    assert items[0].prefix_messages[-1]["role"] == "user"
    assert items[1].prefix_messages[-1]["role"] == "tool"
    assert items[1].observation_conditioned is True
    assert items[-1].prefix_messages[-1]["role"] == "tool"
    assert all(message.get("content") != "Beta was found." for message in items[-1].prefix_messages)


def test_wire_messages_serializes_structured_arguments() -> None:
    item = build_protocol_items([_row()])[-1]
    messages = wire_messages(item.prefix_messages)
    call = messages[2]["tool_calls"][0]

    assert json.loads(call["function"]["arguments"]) == {"query": "alpha"}


def test_valid_native_tool_call_passes_protocol() -> None:
    response = classify_chat_completion(_payload(calls=[_call()]), allowed_tool_names={"lookup"})
    item = build_protocol_items([_row()])[0]
    scored = score_protocol_item(item, response)

    assert response["response_kind"] == "tool_call"
    assert response["protocol_valid"] is True
    assert scored["target_pass"] is True
    assert scored["exact_tool_name_match"] is True


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (_payload(calls=[_call(arguments="not-json")]), "invalid arguments"),
        (_payload(calls=[_call(name="unknown")]), "unknown tool"),
        (_payload(content="I will call it", calls=[_call()]), "same-turn text and tool"),
        (
            _payload(
                calls=[_call()],
                reasoning='<tool_call><function=lookup>{"query":"alpha"}</function></tool_call>',
            ),
            "tool markup in reasoning",
        ),
    ],
)
def test_ambiguous_or_unparseable_tool_outputs_fail(payload: dict, reason: str) -> None:
    response = classify_chat_completion(payload, allowed_tool_names={"lookup"})
    scored = score_protocol_item(build_protocol_items([_row()])[0], response)

    assert scored["target_pass"] is False, reason


def test_final_requires_visible_text_without_tool_calls() -> None:
    final_item = build_protocol_items([_row()])[-1]
    text = score_protocol_item(
        final_item,
        classify_chat_completion(_payload(content="Answer"), allowed_tool_names={"lookup"}),
    )
    empty = score_protocol_item(
        final_item,
        classify_chat_completion(_payload(), allowed_tool_names={"lookup"}),
    )

    assert text["target_pass"] is True
    assert empty["target_pass"] is False


def test_deterministic_row_selection_is_order_independent() -> None:
    rows = [_row(f"row-{index}") for index in range(10)]
    left = select_protocol_rows(rows, max_rows=4, seed=7)
    right = select_protocol_rows(list(reversed(rows)), max_rows=4, seed=7)

    assert [row["id"] for row in left] == [row["id"] for row in right]


def test_summary_enforces_frozen_thresholds_and_complete_coverage() -> None:
    items = build_protocol_items([_row()])
    rows = []
    for item in items:
        payload = _payload(calls=[_call()]) if item.expected_kind == "tool_call" else _payload(content="Answer")
        rows.append(
            {
                **score_protocol_item(
                    item,
                    classify_chat_completion(payload, allowed_tool_names={"lookup"}),
                ),
                "status": "SCORED",
            }
        )
    passed = summarize_protocol_results(
        rows,
        expected_items=4,
        expected_rows=1,
        tool_call_parse_minimum=0.9,
        final_nonempty_minimum=0.95,
        observation_mask_pass=True,
    )
    incomplete = summarize_protocol_results(
        rows[:-1],
        expected_items=4,
        expected_rows=1,
        tool_call_parse_minimum=0.9,
        final_nonempty_minimum=0.95,
        observation_mask_pass=True,
    )

    assert passed["status"] == "PASS_SFT1_PROTOCOL_HOLDOUT"
    assert all(passed["gates"].values())
    assert incomplete["status"] == "INCOMPLETE_PROTOCOL_HOLDOUT_INFRA"


def test_non_protocol_rows_fail_closed() -> None:
    row = _row()
    row["split"] = "train"
    with pytest.raises(ValueError, match="non-protocol"):
        build_protocol_items([row])
