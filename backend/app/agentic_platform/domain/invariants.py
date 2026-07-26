from __future__ import annotations

from collections.abc import Iterable

from .artifact import ArtifactRef
from .plan import PlanStep
from .state import AgentBudget, AgentTaskState, StateDelta, WorkingSet


def _artifact_key(artifact_ref: ArtifactRef) -> tuple[str, int]:
    return artifact_ref.artifact_id, artifact_ref.version


def _append_unique_artifacts(existing: list[ArtifactRef], additions: Iterable[ArtifactRef]) -> list[ArtifactRef]:
    result = list(existing)
    known = {_artifact_key(artifact_ref) for artifact_ref in result}
    for artifact_ref in additions:
        if _artifact_key(artifact_ref) not in known:
            result.append(artifact_ref)
            known.add(_artifact_key(artifact_ref))
    return result


def _append_unique_ids(existing: list[str], additions: Iterable[str]) -> list[str]:
    result = list(existing)
    known = set(result)
    for item_id in additions:
        if item_id not in known:
            result.append(item_id)
            known.add(item_id)
    return result


def _require_known_ids(label: str, requested_ids: Iterable[str], known_ids: set[str]) -> None:
    unknown_ids = set(requested_ids) - known_ids
    if unknown_ids:
        raise ValueError(f"delta references unknown {label} IDs: {sorted(unknown_ids)}")


def _consume_budget(budget: AgentBudget, delta: StateDelta) -> AgentBudget:
    consumption = delta.budget_consumption
    remaining = {
        "turns_remaining": budget.turns_remaining - consumption.turns,
        "skill_calls_remaining": budget.skill_calls_remaining - consumption.skill_calls,
        "context_tokens_remaining": budget.context_tokens_remaining - consumption.context_tokens,
        "cost_remaining": budget.cost_remaining - consumption.cost,
        "subagent_turns_remaining": budget.subagent_turns_remaining - consumption.subagent_turns,
    }
    if any(value < 0 for value in remaining.values()):
        raise ValueError("state delta would make the budget negative")
    return AgentBudget.model_validate(remaining)


def apply_state_delta(state: AgentTaskState, delta: StateDelta) -> AgentTaskState:
    """Return a validated successor state without mutating ``state``.

    This is the only domain-level mutation path.  A runtime can persist the old
    state hash, apply a delta, and then persist the successor hash confidently.
    """

    if state.terminal is not None:
        raise ValueError("cannot apply a state delta to a terminal state")

    constraint_ids = {constraint.constraint_id for constraint in state.constraints}
    milestone_ids = {milestone.milestone_id for milestone in state.milestones}
    effective_plan = delta.plan_update or state.plan
    step_ids = {step.step_id for step in effective_plan.steps}
    _require_known_ids("constraint", delta.resolved_constraint_ids, constraint_ids)
    _require_known_ids("constraint", delta.unresolved_constraint_ids, constraint_ids)
    _require_known_ids("milestone", delta.completed_milestone_ids, milestone_ids)
    _require_known_ids("plan step", delta.plan_step_status_updates, step_ids)

    successor = state.model_copy(deep=True)
    resolved_constraint_ids = set(delta.resolved_constraint_ids)
    unresolved_constraint_ids = set(delta.unresolved_constraint_ids)
    successor.constraints = [
        constraint.model_copy(
            update={
                "is_resolved": True
                if constraint.constraint_id in resolved_constraint_ids
                else False
                if constraint.constraint_id in unresolved_constraint_ids
                else constraint.is_resolved
            }
        )
        for constraint in successor.constraints
    ]
    completed_milestone_ids = set(delta.completed_milestone_ids)
    successor.milestones = [
        milestone.model_copy(
            update={
                "is_completed": True if milestone.milestone_id in completed_milestone_ids else milestone.is_completed
            }
        )
        for milestone in successor.milestones
    ]

    candidate_ids = [
        candidate_id
        for candidate_id in successor.working_set.candidate_ids
        if candidate_id not in set(delta.candidate_ids_to_remove)
    ]
    candidate_ids = _append_unique_ids(candidate_ids, delta.candidate_ids_to_add)
    successor.working_set = WorkingSet.model_validate(
        {
            "candidate_ids": candidate_ids,
            "accepted_ids": _append_unique_ids(successor.working_set.accepted_ids, delta.accepted_ids_to_add),
            "rejected_ids": _append_unique_ids(successor.working_set.rejected_ids, delta.rejected_ids_to_add),
            "evidence_refs": _append_unique_artifacts(successor.working_set.evidence_refs, delta.evidence_refs_to_add),
            "context_artifact_refs": successor.working_set.context_artifact_refs,
        }
    )

    successor.active_artifacts = _append_unique_artifacts(successor.active_artifacts, delta.artifact_refs_to_add)
    successor.failure_records = [*successor.failure_records, *delta.failure_records_to_add]
    successor.budget = _consume_budget(successor.budget, delta)

    status_updates = delta.plan_step_status_updates
    successor.plan = effective_plan.model_copy(
        update={
            "steps": [
                PlanStep.model_validate(
                    step.model_dump(mode="python")
                    | {"status": status_updates.get(step.step_id, step.status)}
                )
                for step in effective_plan.steps
            ]
        }
    )

    if delta.clear_pending_user_request:
        successor.pending_user_request = None
    if delta.clear_pending_approval:
        successor.pending_approval = None
    if delta.clear_pending_event:
        successor.pending_event = None
    if delta.pending_user_request is not None:
        successor.pending_user_request = delta.pending_user_request
        successor.pending_approval = None
        successor.pending_event = None
    if delta.pending_approval is not None:
        successor.pending_user_request = None
        successor.pending_approval = delta.pending_approval
        successor.pending_event = None
    if delta.pending_event is not None:
        successor.pending_user_request = None
        successor.pending_approval = None
        successor.pending_event = delta.pending_event
    if delta.last_transition_id is not None:
        successor.last_transition_id = delta.last_transition_id
    if delta.terminal is not None:
        successor.pending_user_request = None
        successor.pending_approval = None
        successor.pending_event = None
        successor.terminal = delta.terminal

    # model_validate re-runs all nested and cross-field invariants before the
    # runtime observes the next state.
    return AgentTaskState.model_validate(successor.model_dump(mode="python"))
