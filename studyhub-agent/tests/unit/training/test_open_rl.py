from __future__ import annotations

import asyncio
import json

from scripts.data.build_open_rl_tasks import parse_toolace_trajectory
from training.rl.frozen_environment import FrozenTaskEnvironment
from training.rl.reward_v2 import evaluate_reward_v2


def test_fixture_environment_enforces_tool_budget() -> None:
    environment = {
        "tools": [
            {
                "name": "lookup_value",
                "description": "Look up a frozen value.",
                "capability": "function_call",
                "parameters": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
            }
        ],
        "documents": [],
    }
    fixture = {
        "routes": [
            {
                "name": "lookup_value",
                "arguments": {"key": "alpha"},
                "result": "42",
            }
        ]
    }
    runtime = FrozenTaskEnvironment(environment, fixture, max_tool_calls=1)

    first = json.loads(asyncio.run(runtime.execute("lookup_value", {"key": "alpha"})))
    second = json.loads(asyncio.run(runtime.execute("lookup_value", {"key": "alpha"})))

    assert first == {
        "content": "42",
        "fixture_match": True,
        "ok": True,
        "tool": "lookup_value",
    }
    assert second == {"error": "tool_call_budget_exhausted", "max_tool_calls": 1}
    assert len(runtime.trace.tool_calls) == 2
    assert runtime.trace.invalid_tool_calls == 1


def test_fixture_environment_rejects_unmatched_arguments() -> None:
    environment = {
        "tools": [
            {
                "name": "lookup_value",
                "description": "Look up a frozen value.",
                "capability": "function_call",
                "parameters": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
            }
        ],
        "documents": [],
    }
    fixture = {
        "routes": [
            {
                "name": "lookup_value",
                "arguments": {"key": "alpha"},
                "result": "42",
            }
        ]
    }
    runtime = FrozenTaskEnvironment(environment, fixture, max_tool_calls=2)

    result = json.loads(asyncio.run(runtime.execute("lookup_value", {"key": "beta"})))

    assert result == {
        "error": "fixture_route_not_found",
        "fixture_match": False,
        "ok": False,
        "tool": "lookup_value",
    }
    assert runtime.trace.invalid_tool_calls == 1
    assert runtime.trace.error_codes == ["fixture_route_not_found"]


def test_grounded_reward_uses_hidden_evidence_and_valid_citation() -> None:
    source_id = "src-0123456789ab"
    environment = {
        "tools": [
            {
                "name": "knowledge_search_test",
                "description": "Search the frozen corpus.",
                "capability": "knowledge_search",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "knowledge_read_test",
                "description": "Read a frozen source.",
                "capability": "knowledge_read",
                "parameters": {
                    "type": "object",
                    "properties": {"source_id": {"type": "string"}},
                    "required": ["source_id"],
                },
            },
        ],
        "documents": [
            {
                "source_id": source_id,
                "title": "Frozen evidence",
                "text": "The verified answer is forty two.",
            }
        ],
    }
    runtime = FrozenTaskEnvironment(environment, max_tool_calls=4)
    asyncio.run(runtime.execute("knowledge_search_test", {"query": "verified answer"}))
    asyncio.run(runtime.execute("knowledge_read_test", {"source_id": source_id}))

    result = evaluate_reward_v2(
        final_answer=f"The answer is forty two [{source_id}].",
        trace=runtime.trace,
        verifier={
            "family": "evidence_grounding",
            "expected_answers": ["forty two"],
            "gold_source_ids": [source_id],
            "citations_required": True,
        },
        max_tool_calls=4,
    )

    assert result.task_success == 1.0
    assert result.evidence == 1.0
    assert result.citation == 1.0
    assert result.tool_quality == 1.0
    assert not result.violations
    assert result.total > 0.8


def test_read_requires_source_to_be_discovered_by_search() -> None:
    source_id = "src-0123456789ab"
    environment = {
        "tools": [
            {
                "name": "knowledge_search_test",
                "description": "Search the frozen corpus.",
                "capability": "knowledge_search",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "knowledge_read_test",
                "description": "Read a frozen source.",
                "capability": "knowledge_read",
                "parameters": {"type": "object", "properties": {}},
            },
        ],
        "documents": [{"source_id": source_id, "title": "Evidence", "text": "forty two"}],
    }
    runtime = FrozenTaskEnvironment(environment, max_tool_calls=3)

    rejected = json.loads(asyncio.run(runtime.execute("knowledge_read_test", {"source_id": source_id})))
    asyncio.run(runtime.execute("knowledge_search_test", {"query": "forty two"}))
    accepted = json.loads(asyncio.run(runtime.execute("knowledge_read_test", {"source_id": source_id})))

    assert rejected == {"error": "source_not_discovered", "source_id": source_id}
    assert accepted["source_id"] == source_id
    assert runtime.trace.read_source_ids == {source_id}
    assert runtime.trace.error_codes == ["source_not_discovered"]


def test_function_reward_requires_a_final_answer() -> None:
    runtime = FrozenTaskEnvironment(
        {
            "tools": [
                {
                    "name": "lookup_value",
                    "description": "Look up a frozen value.",
                    "capability": "function_call",
                    "parameters": {
                        "type": "object",
                        "properties": {"key": {"type": "string"}},
                        "required": ["key"],
                    },
                }
            ],
            "documents": [],
        },
        {
            "routes": [
                {
                    "name": "lookup_value",
                    "arguments": {"key": "alpha"},
                    "result": "42",
                }
            ]
        },
        max_tool_calls=2,
    )
    asyncio.run(runtime.execute("lookup_value", {"key": "alpha"}))

    result = evaluate_reward_v2(
        final_answer="",
        trace=runtime.trace,
        verifier={
            "family": "function_calling",
            "expected_calls": [{"name": "lookup_value", "arguments": {"key": "alpha"}}],
            "expected_answers": ["42"],
        },
        max_tool_calls=2,
    )

    assert result.function_call_quality == 1.0
    assert result.answer_quality == -1.0
    assert result.task_success == 0.4
    assert result.total <= 0.0
    assert "empty_final_answer" in result.violations


def test_invalid_citation_is_a_hard_gate() -> None:
    source_id = "src-0123456789ab"
    runtime = FrozenTaskEnvironment(
        {"tools": [], "documents": []},
        max_tool_calls=1,
    )
    runtime.trace.tool_calls.append({"name": "knowledge_read", "arguments": {}})
    runtime.trace.read_source_ids.add(source_id)

    result = evaluate_reward_v2(
        final_answer="forty two [src-ffffffffffff]",
        trace=runtime.trace,
        verifier={
            "family": "evidence_grounding",
            "expected_answers": ["forty two"],
            "gold_source_ids": [source_id],
            "citations_required": True,
        },
        max_tool_calls=1,
    )

    assert result.total == -1.0
    assert result.hard_gate_triggered is True
    assert "invalid_citation" in result.violations


def test_toolace_parser_keeps_all_tool_rounds_and_only_the_final_answer() -> None:
    conversations = [
        {"from": "user", "value": "Plan an outdoor party."},
        {"from": "assistant", "value": '[weather(city="Paris")]'},
        {"from": "tool", "value": '[{"name":"weather","results":{"dry":true}}]'},
        {"from": "assistant", "value": "[layout(tables=5)]"},
        {"from": "tool", "value": '[{"name":"layout","results":{"status":"ok"}}]'},
        {"from": "assistant", "value": "The weather is dry and the layout is ready."},
    ]

    parsed = parse_toolace_trajectory(conversations, ["weather", "layout"])

    assert parsed is not None
    user_request, calls, responses, final = parsed
    assert user_request == "Plan an outdoor party."
    assert [call["original_name"] for call in calls] == ["weather", "layout"]
    assert [response["original_name"] for response in responses] == ["weather", "layout"]
    assert final == "The weather is dry and the layout is ready."
