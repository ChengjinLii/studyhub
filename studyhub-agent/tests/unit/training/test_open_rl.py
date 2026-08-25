from __future__ import annotations

import asyncio
import json

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
