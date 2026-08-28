from __future__ import annotations

from typing import Any

DATASET_SCHEMA_VERSION = "studyhub.agent-rl-dataset.v3"
PUBLIC_TASK_SCHEMA_VERSION = "studyhub.agent-rl-task.v3"
VERIFIER_SCHEMA_VERSION = "studyhub.reward-verifier.v3"

FAMILY_MIX = {
    "function_calling": 0.12,
    "rag_and_multihop": 0.18,
    "web": 0.12,
    "memory": 0.12,
    "cross_tool": 0.16,
    "recovery_and_acl": 0.12,
    "long_horizon_and_deep_research": 0.10,
    "direct_answer_and_abstention": 0.08,
}

BUDGET_TIERS = {
    "direct": {"max_model_turns": 3, "max_tool_calls": 1, "max_context_tokens": 4096},
    "short": {"max_model_turns": 6, "max_tool_calls": 4, "max_context_tokens": 8192},
    "extended": {"max_model_turns": 12, "max_tool_calls": 10, "max_context_tokens": 16384},
    "research": {"max_model_turns": 20, "max_tool_calls": 18, "max_context_tokens": 32768},
}

PUBLIC_FORBIDDEN_FIELDS = frozenset(
    {
        "answer",
        "answers",
        "acceptable_answers",
        "acceptable_semantic_answers",
        "claims",
        "contradiction_patterns",
        "expected_answer",
        "expected_answers",
        "expected_call",
        "expected_calls",
        "gold_query",
        "gold_source_ids",
        "gold_source_order",
        "gold_trajectory",
        "oracle_answer",
        "reference_actions",
        "rubric",
        "semantic_rubric",
        "state_assertions",
        "support_source_ids",
        "supporting_facts",
        "verifier",
    }
)

VERIFIER_FORBIDDEN_PATH_FIELDS = frozenset(
    {
        "expected_call",
        "expected_calls",
        "gold_query",
        "gold_source_order",
        "gold_trajectory",
        "reference_actions",
        "required_call_order",
        "required_tool_sequence",
    }
)


def _assert_no_fields(value: Any, forbidden: frozenset[str], *, path: str) -> None:
    if isinstance(value, dict):
        overlap = set(value) & forbidden
        if overlap:
            raise ValueError(f"forbidden fields at {path}: {sorted(overlap)}")
        for key, nested in value.items():
            _assert_no_fields(nested, forbidden, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_no_fields(nested, forbidden, path=f"{path}[{index}]")


def validate_public_task(value: dict[str, Any]) -> None:
    _assert_no_fields(value, PUBLIC_FORBIDDEN_FIELDS, path="$")
    if value.get("schema_version") != PUBLIC_TASK_SCHEMA_VERSION:
        raise ValueError("invalid public RL task schema")
    required = {
        "task_id",
        "goal",
        "initial_state",
        "available_tools",
        "hard_constraints",
        "environment_id",
        "budget_tier",
        "metadata",
    }
    missing = required - set(value)
    if missing:
        raise ValueError(f"public task missing fields: {sorted(missing)}")
    if value["task_id"] != value["environment_id"]:
        raise ValueError("task_id and environment_id must match")
    if value["budget_tier"] not in BUDGET_TIERS:
        raise ValueError(f"invalid budget tier: {value['budget_tier']}")
    if not str(value["goal"]).strip():
        raise ValueError("public task goal is empty")
    tools = list(map(str, value["available_tools"]))
    if len(tools) != len(set(tools)):
        raise ValueError("public task has duplicate tools")
    metadata = value["metadata"]
    if not isinstance(metadata, dict) or not metadata.get("verifier_id"):
        raise ValueError("public task requires an opaque verifier_id")


def validate_hidden_verifier(value: dict[str, Any]) -> None:
    _assert_no_fields(value, VERIFIER_FORBIDDEN_PATH_FIELDS, path="$")
    if value.get("schema_version") != VERIFIER_SCHEMA_VERSION:
        raise ValueError("invalid Reward v3 verifier schema")
    if not value.get("verifier_id") or value.get("verifier_id") != value.get("task_id"):
        raise ValueError("verifier_id and task_id must match")
    if value.get("family") not in FAMILY_MIX:
        raise ValueError(f"invalid Reward v3 family: {value.get('family')}")
    objective = value.get("objective")
    if not isinstance(objective, dict) or not objective.get("mode"):
        raise ValueError("Reward v3 verifier requires an objective")
    if "preferred_path" in value or "path_score" in value:
        raise ValueError("Reward v3 verifier must remain path agnostic")


def budget_for(tier: str) -> dict[str, int]:
    try:
        return dict(BUDGET_TIERS[tier])
    except KeyError as error:
        raise ValueError(f"invalid budget tier: {tier}") from error
