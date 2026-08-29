"""Shared feasibility contract for controlled Agent RL tasks."""

from __future__ import annotations

from typing import Any

BUDGET_CONTRACT_SCHEMA = "studyhub.rl-budget-contract.v1"
RUNTIME_MAX_MODEL_TURNS = 6
CONTROLLED_TASK_MAX_TOOL_CALLS = 6


def make_budget_contract(
    *, reference_model_turns: int, required_tool_calls: int
) -> dict[str, Any]:
    if reference_model_turns < 1 or required_tool_calls < 1:
        raise ValueError("RL tasks require positive model-turn and tool-call budgets")
    return {
        "schema_version": BUDGET_CONTRACT_SCHEMA,
        "reference_model_turns": reference_model_turns,
        "required_tool_calls": required_tool_calls,
    }


def search_budget_contract(gold_source_ids: list[str]) -> dict[str, Any]:
    # One search, one read per required source, then one final model turn.
    required_tool_calls = 1 + len(set(gold_source_ids))
    return make_budget_contract(
        reference_model_turns=required_tool_calls + 1,
        required_tool_calls=required_tool_calls,
    )


def validate_task_budget(
    task: dict[str, Any], verifier: dict[str, Any]
) -> list[str]:
    """Return fail-closed budget-contract violations for one public/hidden pair."""

    failures: list[str] = []
    task_id = str(task.get("task_id", "<unknown>"))
    max_steps = int(task.get("max_steps", 0))
    max_tool_calls = int(task.get("max_tool_calls", -1))
    contract = verifier.get("budget_contract")
    if not isinstance(contract, dict):
        return [f"{task_id}: hidden verifier has no budget contract"]
    if contract.get("schema_version") != BUDGET_CONTRACT_SCHEMA:
        failures.append(f"{task_id}: unknown budget-contract schema")
    try:
        reference_model_turns = int(contract["reference_model_turns"])
        required_tool_calls = int(contract["required_tool_calls"])
    except (KeyError, TypeError, ValueError):
        return failures + [f"{task_id}: malformed budget contract"]

    family = str(verifier.get("family", ""))
    if family == "function_calling":
        expected_calls = verifier.get("expected_calls", [])
        expected_required_calls = len(expected_calls)
        if required_tool_calls != expected_required_calls:
            failures.append(f"{task_id}: function-call requirement mismatch")
        if expected_required_calls < 1:
            failures.append(f"{task_id}: function task has no expected call")
        # Calls in one assistant message may be parallel, but a final answer still
        # consumes another model turn.
        if not 2 <= reference_model_turns <= expected_required_calls + 1:
            failures.append(f"{task_id}: invalid function reference-turn count")
    else:
        expected = search_budget_contract(
            [str(item) for item in verifier.get("gold_source_ids", [])]
        )
        if required_tool_calls != expected["required_tool_calls"]:
            failures.append(f"{task_id}: search tool-call requirement mismatch")
        if reference_model_turns != expected["reference_model_turns"]:
            failures.append(f"{task_id}: search reference-turn requirement mismatch")

    if max_steps < 1 or max_steps > RUNTIME_MAX_MODEL_TURNS:
        failures.append(f"{task_id}: public model-turn budget exceeds runtime contract")
    if max_tool_calls < 1 or max_tool_calls > CONTROLLED_TASK_MAX_TOOL_CALLS:
        failures.append(f"{task_id}: public tool-call budget exceeds controlled contract")
    if max_tool_calls > max_steps:
        failures.append(f"{task_id}: tool-call budget exceeds public step budget")
    if reference_model_turns > min(max_steps, RUNTIME_MAX_MODEL_TURNS):
        failures.append(f"{task_id}: reference trajectory cannot finish within model turns")
    if required_tool_calls > min(max_tool_calls, CONTROLLED_TASK_MAX_TOOL_CALLS):
        failures.append(f"{task_id}: required tools cannot finish within tool budget")
    return failures
