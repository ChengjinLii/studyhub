from __future__ import annotations

import asyncio

from training.rl.environment_v3 import TrainingTaskEnvironmentV3
from training.rl.reward_v3 import INFRA_STATUS, REWARD_VERSION, evaluate_reward_v3


def _trace(*calls, read_sources=(), policy_errors=(), runtime_errors=()):
    return {
        "tool_calls": list(calls),
        "policy_errors": list(policy_errors),
        "environment_errors": [],
        "runtime_errors": list(runtime_errors),
        "discovered_source_ids": list(read_sources),
        "read_source_ids": list(read_sources),
        "fetched_urls": [],
        "denied_source_ids": [],
        "state_changes": [],
    }


def _verifier(**updates):
    value = {
        "schema_version": "studyhub.reward-verifier.v3",
        "verifier_id": "v",
        "task_id": "t",
        "family": "rag_and_multihop",
        "hard_constraints": {"max_tool_calls": 6},
        "objective": {"mode": "facts", "acceptable_answers": [["卷积", "convolution"]]},
        "claims": [
            {
                "claim_id": "answer",
                "required": True,
                "acceptable_semantic_answers": [["卷积", "convolution"]],
                "support_source_ids": ["train-src-a", "train-src-b"],
                "citation_required": True,
            }
        ],
        "semantic_rubric": {"requirements": []},
        "process": {"max_reasonable_tool_calls": 4, "target_evidence_gain_steps": 1},
        "thresholds": {"objective": 0.99, "grounding": 0.99, "semantic": 0.75},
    }
    value.update(updates)
    return value


def test_reward_v3_accepts_alternative_valid_search_paths() -> None:
    path_a = _trace(
        {
            "name": "knowledge_search",
            "arguments": {"query": "系统 卷积"},
            "ok": True,
            "returned_source_ids": ["train-src-a"],
        },
        {
            "name": "knowledge_read",
            "arguments": {"source_id": "train-src-a"},
            "ok": True,
            "returned_source_ids": ["train-src-a"],
        },
        read_sources=("train-src-a",),
    )
    path_b = _trace(
        {
            "name": "knowledge_search",
            "arguments": {"query": "线性时不变系统输出"},
            "ok": True,
            "returned_source_ids": ["train-src-b"],
        },
        {
            "name": "knowledge_read",
            "arguments": {"source_id": "train-src-b"},
            "ok": True,
            "returned_source_ids": ["train-src-b"],
        },
        read_sources=("train-src-b",),
    )

    first = evaluate_reward_v3(
        final_answer="输出由卷积得到。[train-src-a]",
        trace=path_a,
        final_state={},
        verifier=_verifier(),
    )
    second = evaluate_reward_v3(
        final_answer="The operation is convolution. [train-src-b]",
        trace=path_b,
        final_state={},
        verifier=_verifier(),
    )

    assert first.strict_success is True
    assert second.strict_success is True
    assert first.total == second.total
    assert first.diagnostics["reward_version"] == REWARD_VERSION
    assert first.diagnostics["gold_path_equality_used"] is False


def test_reward_v3_hard_gates_fabricated_citation() -> None:
    result = evaluate_reward_v3(
        final_answer="答案是卷积。[made-up-source]",
        trace=_trace(read_sources=("train-src-a",)),
        final_state={},
        verifier=_verifier(),
    )

    assert result.total == -1.0
    assert result.hard_gate_triggered is True
    assert "invalid_citation:made-up-source" in result.hard_gate_reasons


def test_reward_v3_does_not_treat_function_payload_brackets_as_citations() -> None:
    verifier = _verifier(
        family="function_calling",
        objective={"mode": "state", "state_assertions": []},
        claims=[],
    )
    result = evaluate_reward_v3(
        final_answer="Created resources [wallet_primary, wallet_backup].",
        trace=_trace(
            {"name": "create_wallet", "arguments": {}, "ok": True},
        ),
        final_state={},
        verifier=verifier,
    )

    assert result.strict_success is True
    assert result.hard_gate_triggered is False


def test_reward_v3_rejects_multiple_choice_keyword_stuffing() -> None:
    verifier = _verifier(
        family="direct_answer_and_abstention",
        objective={"mode": "facts", "acceptable_answers": [["C"]]},
        claims=[],
    )
    result = evaluate_reward_v3(
        final_answer="候选项包括 A、B、C、D，尚未作答。",
        trace=_trace(),
        final_state={},
        verifier=verifier,
    )

    assert result.strict_success is False
    assert result.objective_end_state == 0.0


def test_reward_v3_excludes_runtime_failures_from_policy_reward() -> None:
    result = evaluate_reward_v3(
        final_answer="provider failed",
        trace=_trace(runtime_errors=("context_budget_provider_rejection",)),
        final_state={},
        verifier=_verifier(),
    )

    assert result.status == INFRA_STATUS
    assert result.eligible_for_policy_update is False
    assert result.total == 0.0


def test_reward_v3_scores_end_state_without_gold_action_sequence() -> None:
    verifier = _verifier(
        family="state_function",
        objective={
            "mode": "state",
            "state_assertions": [
                {"path": "progress.卷积.status", "operator": "eq", "value": "review"},
                {"path": "bookmarks", "operator": "contains", "value": 42},
            ],
        },
        claims=[],
    )
    calls = (
        {"name": "material_bookmark_add", "arguments": {"material_id": 42}, "ok": True},
        {
            "name": "learning_progress_record",
            "arguments": {"topic": "卷积", "status": "review"},
            "ok": True,
        },
    )

    result = evaluate_reward_v3(
        final_answer="已保存书签并把卷积标记为复习。",
        trace=_trace(*calls),
        final_state={"bookmarks": [42], "progress": {"卷积": {"status": "review"}}},
        verifier=verifier,
    )

    assert result.strict_success is True
    assert result.objective_end_state == 1.0


def test_fixture_environment_v3_applies_verified_state_transition(tmp_path) -> None:
    environment = {
        "schema_version": "studyhub.rl-environment.v3",
        "environment_kind": "fixture",
        "task_id": "fixture-task",
        "initial_state": {"status": "pending"},
        "max_tool_calls": 2,
        "mutating_tools": ["set_status"],
        "tool_schemas": [
            {
                "name": "set_status",
                "description": "Set task status.",
                "parameters": {
                    "type": "object",
                    "properties": {"status": {"type": "string", "enum": ["done"]}},
                    "required": ["status"],
                    "additionalProperties": False,
                },
            }
        ],
        "fixture_routes": [
            {
                "name": "set_status",
                "arguments": {"status": "done"},
                "result": {"ok": True, "message": "updated"},
                "state_patch": {"status": "done"},
            }
        ],
    }
    runtime = TrainingTaskEnvironmentV3(environment, root=tmp_path)

    result = asyncio.run(runtime.execute("set_status", {"status": "done"}))

    assert '"ok": true' in result
    assert runtime.state_snapshot() == {"status": "done"}
    assert runtime.trace_dict()["tool_calls"][0]["ok"] is True
    assert runtime.mutating_tools == {"set_status"}


def test_replay_environment_v3_enforces_discovery_before_read(tmp_path) -> None:
    environment = {
        "schema_version": "studyhub.rl-environment.v3",
        "environment_kind": "replay",
        "task_id": "replay-task",
        "available_tools": ["knowledge_search", "knowledge_read"],
        "inline_documents": [
            {
                "source_id": "train-source-1",
                "material_id": 42,
                "title": "卷积复习",
                "text": "线性时不变系统的输出可由卷积计算。",
                "access_scope": "free",
            }
        ],
        "initial_state": {},
        "max_tool_calls": 4,
    }
    runtime = TrainingTaskEnvironmentV3(environment, root=tmp_path)

    denied = asyncio.run(runtime.execute("knowledge_read", {"source_id": "train-source-1"}))
    searched = asyncio.run(runtime.execute("knowledge_search", {"query": "线性时不变", "limit": 5}))
    read = asyncio.run(runtime.execute("knowledge_read", {"source_id": "train-source-1"}))

    assert "source_not_discovered" in denied
    assert "train-source-1" in searched
    assert "线性时不变" in read
