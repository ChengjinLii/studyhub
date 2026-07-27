"""Stable, privacy-bounded state groups for trajectory analysis.

``state_hash`` remains the exact replay identity.  The group key deliberately
contains only generic progress features: it must never depend on a goal ID,
plan-step ID, prompt text, artifact ID, or other per-run identifier.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from ._base import DomainModel
from .hashing import canonical_hash
from .plan import PlanStepStatus
from .state import AgentTaskState


class StateGroupFeatures(DomainModel):
    """Non-identifying features used for GiGPO/evaluation stratification."""

    schema_version: str = "2.0"
    task_family: str = Field(min_length=1, max_length=64)
    plan_step_type: str = Field(min_length=1, max_length=64)
    resolved_constraint_types: tuple[str, ...] = ()
    candidate_count_bucket: str = Field(min_length=1, max_length=32)
    evidence_coverage_bucket: str = Field(min_length=1, max_length=32)
    last_observation_type: str | None = Field(default=None, max_length=64)
    failure_type: str | None = Field(default=None, max_length=64)
    remaining_budget_bucket: str = Field(min_length=1, max_length=32)
    cold_start_stage: str | None = Field(default=None, max_length=64)

    @field_validator(
        "task_family",
        "plan_step_type",
        "candidate_count_bucket",
        "evidence_coverage_bucket",
        "last_observation_type",
        "failure_type",
        "remaining_budget_bucket",
        "cold_start_stage",
    )
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("state group values must not be blank")
        return value

    @field_validator("resolved_constraint_types")
    @classmethod
    def validate_constraint_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("resolved constraint types must not be blank")
        if tuple(sorted(set(values))) != values:
            raise ValueError("resolved constraint types must be sorted and unique")
        return values


def state_group_features(state: AgentTaskState) -> StateGroupFeatures:
    """Extract safe grouping features without classifying the user's intent.

    ``ConstraintState`` does not carry a typed taxonomy today.  We therefore
    retain the generic ``constraint`` label when one or more constraints are
    resolved instead of inferring a category from private natural-language
    descriptions.
    """

    active_step = next(
        (
            step
            for step in state.plan.steps
            if step.status in {PlanStepStatus.READY, PlanStepStatus.IN_PROGRESS, PlanStepStatus.PENDING}
        ),
        None,
    )
    return StateGroupFeatures(
        task_family=state.trigger.trigger_type.value,
        plan_step_type=_plan_step_type(active_step.capability if active_step is not None else None),
        resolved_constraint_types=("constraint",) if any(item.is_resolved for item in state.constraints) else (),
        candidate_count_bucket=_count_bucket(len(state.working_set.candidate_ids)),
        evidence_coverage_bucket=_evidence_coverage_bucket(state),
        last_observation_type=_last_observation_type(state),
        failure_type=_failure_type(state),
        remaining_budget_bucket=_budget_bucket(state.budget.turns_remaining),
        cold_start_stage=_cold_start_stage(state),
    )


def state_group_key_v2(state: AgentTaskState) -> str:
    """Hash ``StateGroupFeatures`` into a non-identifying grouping key."""

    return "sgv2_" + canonical_hash(state_group_features(state), exclude_fields=())


def state_abstract_key(state: AgentTaskState) -> str:
    """Backward-compatible alias for the safe ``state_group_key_v2``.

    Historical callers use this name in a schema field.  New persisted rows
    additionally write ``state_group_key_v2`` explicitly.
    """

    return state_group_key_v2(state)


def _plan_step_type(capability: str | None) -> str:
    if not capability:
        return "no_active_step"
    namespace = capability.split(".", 1)[0].strip().lower()
    return namespace if namespace in {"materials", "research", "validation", "interaction", "plan"} else "other"


def _count_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 4:
        return "2_4"
    if value <= 9:
        return "5_9"
    return "10_plus"


def _evidence_coverage_bucket(state: AgentTaskState) -> str:
    if not state.constraints:
        return "not_applicable"
    resolved = sum(item.is_resolved for item in state.constraints)
    if resolved == 0:
        return "none"
    if resolved == len(state.constraints):
        return "complete"
    return "partial"


def _last_observation_type(state: AgentTaskState) -> str | None:
    if state.working_set.evidence_refs:
        return "evidence"
    if not state.active_artifacts:
        return None
    latest = state.active_artifacts[-1].artifact_type
    value = getattr(latest, "value", latest)
    return "observation" if value == "observation" else "artifact"


def _failure_type(state: AgentTaskState) -> str | None:
    if not state.failure_records:
        return None
    return "recoverable" if state.failure_records[-1].recoverable else "non_recoverable"


def _budget_bucket(turns_remaining: int) -> str:
    if turns_remaining == 0:
        return "exhausted"
    if turns_remaining == 1:
        return "one_turn"
    if turns_remaining <= 3:
        return "two_to_three"
    if turns_remaining <= 7:
        return "four_to_seven"
    return "eight_plus"


def _cold_start_stage(state: AgentTaskState) -> str | None:
    if state.last_transition_id is not None:
        return None
    if state.working_set.candidate_ids or state.working_set.evidence_refs or state.active_artifacts:
        return "seeded"
    return "cold_start"
