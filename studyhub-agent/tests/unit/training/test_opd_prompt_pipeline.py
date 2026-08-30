import json
from pathlib import Path

from scripts.data.build_opd_prompt_pool_v1 import (
    stratified_probe,
    validate_candidate,
    validate_environment,
)
from scripts.data.select_opd_training_pool_v1 import family_scores, task_priority
from scripts.train.run_opd_policy_probe import aggregate


def task(
    task_id: str, *, family: str = "rag_and_multihop", tools: list[str] | None = None
) -> dict:
    return {
        "schema_version": "studyhub.agent-rl-task.v3",
        "task_id": task_id,
        "goal": f"Find supported evidence for {task_id}.",
        "initial_state": {},
        "available_tools": tools or ["knowledge_search", "knowledge_read"],
        "hard_constraints": {
            "hidden_oracle_access": False,
            "respect_acl": True,
            "no_cross_user_memory": True,
            "citations_must_be_observed": True,
            "max_tool_calls": 4,
        },
        "environment_id": task_id,
        "budget_tier": "short",
        "metadata": {
            "family": family,
            "source_dataset": "unit",
            "source_group_id": f"group-{task_id}",
            "split": "train",
            "verifier_id": task_id,
            "oracle_fields_exposed": False,
        },
    }


def verifier(task_id: str, *, family: str = "rag_and_multihop") -> dict:
    return {
        "schema_version": "studyhub.reward-verifier.v3",
        "verifier_id": task_id,
        "task_id": task_id,
        "family": family,
        "objective": {"mode": "facts", "acceptable_answers": [["supported"]]},
        "claims": [],
        "semantic_rubric": {"requirements": []},
        "process": {},
        "hard_constraints": {"max_tool_calls": 4},
        "thresholds": {"objective": 0.99, "grounding": 0.99, "semantic": 0.75},
    }


def environment(task_id: str, tools: list[str]) -> dict:
    return {
        "schema_version": "studyhub.rl-environment.v3",
        "task_id": task_id,
        "environment_kind": "replay",
        "available_tools": tools,
    }


def test_candidate_rejects_redundant_web_alias() -> None:
    row = task("legacy-web", family="web", tools=["web_search", "web_fetch"])
    failures = validate_candidate(
        row,
        verifier("legacy-web", family="web"),
        blocked_task_ids=set(),
        blocked_groups=set(),
        blocked_prompt_hashes=set(),
        blocked_prompt_terms_by_size={},
    )

    assert "legacy_redundant_tool" in failures


def test_environment_requires_exact_task_tool_surface() -> None:
    row = task("tool-contract")
    failures = validate_environment(
        row,
        verifier("tool-contract"),
        environment("tool-contract", ["knowledge_search"]),
    )

    assert failures == ["tool_surface_mismatch"]


def test_probe_is_deterministic_and_family_stratified() -> None:
    rows = [task(f"rag-{index}") for index in range(8)] + [
        task(f"direct-{index}", family="direct_answer_and_abstention", tools=[])
        for index in range(2)
    ]

    first = stratified_probe(rows, 5, 7)
    second = stratified_probe(rows, 5, 7)

    assert [row["task_id"] for row in first] == [row["task_id"] for row in second]
    assert {row["metadata"]["family"] for row in first} == {
        "rag_and_multihop",
        "direct_answer_and_abstention",
    }


def test_probe_aggregate_separates_infra() -> None:
    rows = [
        {
            "family": "rag_and_multihop",
            "status": "SCORED",
            "strict_success": True,
            "diagnostic_score": 0.8,
            "tool_validity": 1.0,
        },
        {
            "family": "rag_and_multihop",
            "status": "INFRA_EXCLUDED",
            "strict_success": False,
            "diagnostic_score": 0.0,
            "tool_validity": 0.0,
        },
    ]

    result = aggregate(rows)

    assert result["tasks"] == 2
    assert result["scored"] == 1
    assert result["infra_excluded"] == 1
    assert result["strict_success_rate"] == 1.0


def test_teacher_only_task_has_priority_over_unevaluated_family_fill() -> None:
    teacher = {
        "observed": {
            "family": "rag_and_multihop",
            "strict_success": True,
            "diagnostic_score": 0.9,
        }
    }
    student = {
        "observed": {
            "family": "rag_and_multihop",
            "strict_success": False,
            "diagnostic_score": 0.2,
        }
    }
    scores = family_scores(teacher, student)
    observed = {
        "task_id": "observed",
        "metadata": {"family": "rag_and_multihop"},
    }
    unseen = {
        "task_id": "unseen",
        "metadata": {"family": "rag_and_multihop"},
    }
    assert task_priority(
        observed,
        teacher=teacher,
        student=student,
        family=scores,
        seed=1,
    ) < task_priority(
        unseen,
        teacher=teacher,
        student=student,
        family=scores,
        seed=1,
    )
