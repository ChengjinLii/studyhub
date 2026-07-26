from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.state import AgentTaskState, BudgetConsumption, StateDelta


class BudgetExhaustionReason(StrEnum):
    TURNS = "turns_exhausted"
    SKILL_CALLS = "skill_calls_exhausted"
    CONTEXT_TOKENS = "context_tokens_exhausted"
    COST = "cost_exhausted"
    SUBAGENT_TURNS = "subagent_turns_exhausted"


class BudgetExhaustedError(RuntimeError):
    def __init__(self, reason: BudgetExhaustionReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


class BudgetGuard:
    """Applies explicit safety budgets without prescribing an agent workflow."""

    @staticmethod
    def policy_context_budget(state: AgentTaskState, configured_budget: int) -> int:
        if state.budget.turns_remaining <= 0:
            raise BudgetExhaustedError(BudgetExhaustionReason.TURNS)
        if state.budget.context_tokens_remaining <= 0:
            raise BudgetExhaustedError(BudgetExhaustionReason.CONTEXT_TOKENS)
        return min(configured_budget, state.budget.context_tokens_remaining)

    @staticmethod
    def assert_skill_available(state: AgentTaskState, *, estimated_cost: float) -> None:
        if state.budget.skill_calls_remaining <= 0:
            raise BudgetExhaustedError(BudgetExhaustionReason.SKILL_CALLS)
        if state.budget.cost_remaining < estimated_cost:
            raise BudgetExhaustedError(BudgetExhaustionReason.COST)

    @staticmethod
    def assert_subagent_available(state: AgentTaskState) -> None:
        if state.budget.subagent_turns_remaining <= 0:
            raise BudgetExhaustedError(BudgetExhaustionReason.SUBAGENT_TURNS)

    @staticmethod
    def model_turn_delta(*, context_tokens: int) -> StateDelta:
        return StateDelta(budget_consumption=BudgetConsumption(turns=1, context_tokens=context_tokens))

    @staticmethod
    def skill_call_delta(*, estimated_cost: float, context_tokens: int = 0) -> StateDelta:
        return StateDelta(
            budget_consumption=BudgetConsumption(
                skill_calls=1,
                cost=estimated_cost,
                context_tokens=context_tokens,
            )
        )

    @staticmethod
    def subagent_turn_delta(*, turns: int = 1) -> StateDelta:
        return StateDelta(budget_consumption=BudgetConsumption(subagent_turns=turns))


def merge_state_deltas(*deltas: StateDelta) -> StateDelta:
    """Merge compatible node effects into one auditable turn transition.

    A merge only combines declarative updates; conflicts remain errors rather
    than being silently resolved by orchestration code.
    """

    valid = [delta for delta in deltas if delta is not None]
    if not valid:
        return StateDelta()

    def unique(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(values))

    def unique_artifacts(field_name: str) -> list[object]:
        result: list[object] = []
        seen: set[tuple[object, object]] = set()
        for delta in valid:
            for artifact in getattr(delta, field_name):
                key = (artifact.artifact_id, artifact.version)
                if key not in seen:
                    result.append(artifact)
                    seen.add(key)
        return result

    def single(field_name: str):
        values = [getattr(delta, field_name) for delta in valid if getattr(delta, field_name) is not None]
        if not values:
            return None
        hashes = {canonical_hash(value) for value in values}
        if len(hashes) != 1:
            raise ValueError(f"conflicting state deltas for {field_name}")
        return values[0]

    step_updates: dict[str, object] = {}
    for delta in valid:
        for step_id, status in delta.plan_step_status_updates.items():
            existing = step_updates.get(step_id)
            if existing is not None and existing != status:
                raise ValueError(f"conflicting plan step status for {step_id}")
            step_updates[step_id] = status

    budget = BudgetConsumption(
        turns=sum(delta.budget_consumption.turns for delta in valid),
        skill_calls=sum(delta.budget_consumption.skill_calls for delta in valid),
        context_tokens=sum(delta.budget_consumption.context_tokens for delta in valid),
        cost=sum(delta.budget_consumption.cost for delta in valid),
        subagent_turns=sum(delta.budget_consumption.subagent_turns for delta in valid),
    )
    return StateDelta(
        plan_update=single("plan_update"),
        resolved_constraint_ids=unique(item for delta in valid for item in delta.resolved_constraint_ids),
        unresolved_constraint_ids=unique(item for delta in valid for item in delta.unresolved_constraint_ids),
        completed_milestone_ids=unique(item for delta in valid for item in delta.completed_milestone_ids),
        candidate_ids_to_add=unique(item for delta in valid for item in delta.candidate_ids_to_add),
        candidate_ids_to_remove=unique(item for delta in valid for item in delta.candidate_ids_to_remove),
        accepted_ids_to_add=unique(item for delta in valid for item in delta.accepted_ids_to_add),
        rejected_ids_to_add=unique(item for delta in valid for item in delta.rejected_ids_to_add),
        evidence_refs_to_add=unique_artifacts("evidence_refs_to_add"),
        artifact_refs_to_add=unique_artifacts("artifact_refs_to_add"),
        plan_step_status_updates=step_updates,
        budget_consumption=budget,
        failure_records_to_add=[record for delta in valid for record in delta.failure_records_to_add],
        pending_user_request=single("pending_user_request"),
        clear_pending_user_request=any(delta.clear_pending_user_request for delta in valid),
        pending_approval=single("pending_approval"),
        clear_pending_approval=any(delta.clear_pending_approval for delta in valid),
        pending_event=single("pending_event"),
        clear_pending_event=any(delta.clear_pending_event for delta in valid),
        last_transition_id=single("last_transition_id"),
        terminal=single("terminal"),
    )


def has_semantic_state_change(delta: StateDelta) -> bool:
    """Whether a delta changes business state, excluding bookkeeping budgets."""

    return any(
        (
            delta.plan_update is not None,
            delta.resolved_constraint_ids,
            delta.unresolved_constraint_ids,
            delta.completed_milestone_ids,
            delta.candidate_ids_to_add,
            delta.candidate_ids_to_remove,
            delta.accepted_ids_to_add,
            delta.rejected_ids_to_add,
            delta.evidence_refs_to_add,
            delta.artifact_refs_to_add,
            delta.plan_step_status_updates,
            delta.failure_records_to_add,
            delta.pending_user_request is not None,
            delta.clear_pending_user_request,
            delta.pending_approval is not None,
            delta.clear_pending_approval,
            delta.pending_event is not None,
            delta.clear_pending_event,
            delta.terminal is not None,
        )
    )
