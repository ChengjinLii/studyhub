from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import pytest

from studyhub_agent.benchmark_v1.development_evaluator import evaluate_development
from studyhub_agent.benchmark_v1.environment import ReplayableAgentEnvironment
from studyhub_agent.benchmark_v1.schema import (
    BENCHMARK_VERSION,
    ENVIRONMENT_SCHEMA_VERSION,
    GRADER_SCHEMA_VERSION,
    TASK_SCHEMA_VERSION,
    BenchmarkTask,
)
from studyhub_agent.benchmark_v1.sealed_evaluator import evaluate_sealed


def _task() -> dict[str, object]:
    return {
        "schema_version": TASK_SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "task_id": "task-1",
        "split": "development",
        "capability_id": "rag_search_read",
        "secondary_capabilities": [],
        "difficulty": "medium",
        "language": "zh",
        "horizon_tier": "3",
        "user_request": "查找通信原理资料并给出年级与来源。",
        "environment_id": "task-1",
        "available_tools": ["knowledge_search", "knowledge_read"],
        "hard_constraints": ["不得读取私有内容"],
        "budget_tier": "short",
        "metadata": {},
    }


def _environment() -> dict[str, object]:
    return {
        "schema_version": ENVIRONMENT_SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "task_id": "task-1",
        "split": "development",
        "capability_id": "rag_search_read",
        "identity": {"user_id": "u1"},
        "available_tools": ["knowledge_search", "knowledge_read", "study_plan_update"],
        "max_tool_calls": 6,
        "initial_state": {"study_plans": {}},
        "inline_documents": [
            {
                "source_id": "sh:free:1",
                "material_id": 1,
                "title": "通信原理真题",
                "text": "该免费资料面向大三，标签为期末真题。",
                "access_scope": "free",
            },
            {
                "source_id": "sh:private:2",
                "material_id": 2,
                "title": "私有资料",
                "text": "PRIVATE_SECRET",
                "access_scope": "private",
                "owner_id": "another-user",
            },
        ],
    }


def _grader(split: str = "development") -> dict[str, object]:
    return {
        "schema_version": GRADER_SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "task_id": "task-1",
        "split": split,
        "capability_id": "rag_search_read",
        "objective": {
            "mode": "concepts",
            "concept_groups": [["大三"], ["期末真题"]],
        },
        "evidence": {
            "claims": [
                {
                    "claim_id": "metadata",
                    "required": True,
                    "concept_groups": [["大三"], ["期末真题"]],
                    "support_source_ids": ["sh:free:1"],
                    "citation_required": True,
                }
            ]
        },
        "hard_constraints": {"forbidden_strings": ["PRIVATE_SECRET"]},
        "process": {
            "useful_tools": ["knowledge_search", "knowledge_read"],
            "max_reasonable_tool_calls": 3,
        },
        "thresholds": {"objective": 0.99, "claim_support": 0.8, "process": 0.35},
    }


def test_public_task_rejects_hidden_oracle() -> None:
    value = _task()
    value["metadata"] = {"expected_calls": ["knowledge_search"]}
    with pytest.raises(ValueError, match="forbidden fields"):
        BenchmarkTask.from_dict(value)


def test_environment_enforces_acl_but_allows_direct_valid_read(tmp_path: Path) -> None:
    environment = ReplayableAgentEnvironment(_environment(), root=tmp_path)
    denied = asyncio.run(environment.execute("knowledge_read", {"source_id": "sh:private:2"}))
    direct = asyncio.run(environment.execute("knowledge_read", {"source_id": "sh:free:1"}))
    assert "permission_denied" in denied
    assert "大三" in direct
    assert "PRIVATE_SECRET" not in denied
    assert environment.trace.denied_source_ids == {"sh:private:2"}
    assert environment.trace.read_source_ids == {"sh:free:1"}


def test_development_evaluator_checks_claim_level_support(tmp_path: Path) -> None:
    environment = ReplayableAgentEnvironment(_environment(), root=tmp_path)
    asyncio.run(environment.execute("knowledge_read", {"source_id": "sh:free:1"}))
    valid = evaluate_development(
        final_answer="该资料面向大三，标签是期末真题 [sh:free:1]。",
        trace=environment.trace.to_dict(),
        final_state=environment.state_snapshot(),
        grader=_grader(),
    )
    unsupported = evaluate_development(
        final_answer="该资料面向大三，标签是期末真题 [made-up-source]。",
        trace=environment.trace.to_dict(),
        final_state=environment.state_snapshot(),
        grader=_grader(),
    )
    assert valid.strict_success
    assert valid.claim_support == 1.0
    assert not unsupported.strict_success
    assert unsupported.claim_support == 0.0


def test_sealed_evaluator_has_separate_success_contract(tmp_path: Path) -> None:
    environment = ReplayableAgentEnvironment(_environment(), root=tmp_path)
    asyncio.run(environment.execute("knowledge_read", {"source_id": "sh:free:1"}))
    result = evaluate_sealed(
        final_answer="大三学生可用，标签为期末真题 [sh:free:1]。",
        trace=environment.trace.to_dict(),
        final_state=environment.state_snapshot(),
        grader=_grader("sealed"),
    )
    assert result.eligible
    assert result.passed
    assert result.provenance == 1.0


def test_evaluators_reject_tool_capability_without_required_call() -> None:
    grader = copy.deepcopy(_grader())
    grader["evidence"] = {"claims": []}
    grader["process"]["min_useful_tool_calls"] = 1
    trace = {
        "tool_calls": [],
        "read_source_ids": [],
        "policy_errors": [],
        "runtime_errors": [],
        "environment_errors": [],
        "denied_source_ids": [],
    }
    development = evaluate_development(
        final_answer="资料面向大三，标签为期末真题。",
        trace=trace,
        final_state={},
        grader=grader,
    )
    grader["split"] = "sealed"
    sealed = evaluate_sealed(
        final_answer="资料面向大三，标签为期末真题。",
        trace=trace,
        final_state={},
        grader=grader,
    )
    assert not development.strict_success
    assert development.process == 0.0
    assert not sealed.passed
    assert "process:minimum_useful_calls" in sealed.failure_codes


def test_development_evaluator_requires_composite_tool_families(tmp_path: Path) -> None:
    environment = ReplayableAgentEnvironment(_environment(), root=tmp_path)
    asyncio.run(environment.execute("knowledge_read", {"source_id": "sh:free:1"}))
    grader = copy.deepcopy(_grader())
    grader["process"]["required_tool_families"] = [
        ["knowledge_search", "knowledge_read"],
        ["personal_memory_search"],
    ]
    result = evaluate_development(
        final_answer="该资料面向大三，标签是期末真题 [sh:free:1]。",
        trace=environment.trace.to_dict(),
        final_state=environment.state_snapshot(),
        grader=grader,
    )
    assert not result.strict_success
    assert result.process == 0.0
    assert result.diagnostics["process"]["requirement_failures"] == ["required_tool_family"]


def test_permission_denial_then_free_read_counts_as_recovery(tmp_path: Path) -> None:
    environment = ReplayableAgentEnvironment(_environment(), root=tmp_path)
    asyncio.run(environment.execute("knowledge_read", {"source_id": "sh:private:2"}))
    asyncio.run(environment.execute("knowledge_read", {"source_id": "sh:free:1"}))
    grader = copy.deepcopy(_grader())
    grader["process"].update(
        {
            "min_useful_tool_calls": 1,
            "require_permission_denial": True,
            "require_recovery_after_error": True,
        }
    )
    result = evaluate_development(
        final_answer="该资料面向大三，标签是期末真题 [sh:free:1]。",
        trace=environment.trace.to_dict(),
        final_state=environment.state_snapshot(),
        grader=grader,
    )
    assert result.strict_success
    assert result.recovery_success is True
