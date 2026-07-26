from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from ._base import DOMAIN_SCHEMA_VERSION, DomainModel
from .artifact import ArtifactRef
from .plan import AgentPlan, PlanStepStatus


class TriggerType(StrEnum):
    ADMIN_API = "admin_api"
    SCHEDULE = "schedule"
    INTERNAL_EVENT = "internal_event"
    RESUME = "resume"
    MANUAL_RETRY = "manual_retry"


class TriggerContext(DomainModel):
    trigger_type: TriggerType
    source: str = Field(min_length=1, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    event_id: str | None = Field(default=None, max_length=128)
    business_time: datetime | None = None

    @field_validator("source", "request_id", "event_id")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class GoalState(DomainModel):
    goal_id: str = Field(min_length=1, max_length=128)
    statement: str = Field(min_length=1, max_length=4_000)
    success_criteria: list[str] = Field(default_factory=list)

    @field_validator("goal_id", "statement")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("success_criteria")
    @classmethod
    def validate_success_criteria(cls, criteria: list[str]) -> list[str]:
        if any(not criterion.strip() for criterion in criteria):
            raise ValueError("success criteria must not be blank")
        if len(criteria) != len(set(criteria)):
            raise ValueError("success criteria must be unique")
        return criteria


class ConstraintState(DomainModel):
    constraint_id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2_000)
    is_resolved: bool = False
    resolution_summary: str | None = Field(default=None, max_length=2_000)

    @field_validator("constraint_id", "description", "resolution_summary")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class MilestoneState(DomainModel):
    milestone_id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2_000)
    is_completed: bool = False

    @field_validator("milestone_id", "description")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class WorkingSet(DomainModel):
    """The compact, mutable-by-delta portion of an agent's working context."""

    candidate_ids: list[str] = Field(default_factory=list)
    accepted_ids: list[str] = Field(default_factory=list)
    rejected_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[ArtifactRef] = Field(default_factory=list)
    context_artifact_refs: list[ArtifactRef] = Field(default_factory=list)

    @field_validator("candidate_ids", "accepted_ids", "rejected_ids")
    @classmethod
    def validate_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("IDs must be unique")
        return values

    @model_validator(mode="after")
    def reject_accepted_rejected_conflicts(self) -> "WorkingSet":
        conflicts = set(self.accepted_ids) & set(self.rejected_ids)
        if conflicts:
            raise ValueError(f"accepted and rejected IDs conflict: {sorted(conflicts)}")
        return self


class EnvironmentRef(DomainModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    snapshot_hash: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=128)
    captured_at: datetime | None = None

    @field_validator("snapshot_id", "snapshot_hash", "source")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class AgentBudget(DomainModel):
    turns_remaining: int = Field(ge=0)
    skill_calls_remaining: int = Field(ge=0)
    context_tokens_remaining: int = Field(ge=0)
    cost_remaining: float = Field(ge=0.0)
    subagent_turns_remaining: int = Field(default=0, ge=0)


class BudgetConsumption(DomainModel):
    turns: int = Field(default=0, ge=0)
    skill_calls: int = Field(default=0, ge=0)
    context_tokens: int = Field(default=0, ge=0)
    cost: float = Field(default=0.0, ge=0.0)
    subagent_turns: int = Field(default=0, ge=0)


class UserInputRequest(DomainModel):
    request_id: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=4_000)
    choices: list[str] = Field(default_factory=list)
    required: bool = True
    expires_at: datetime | None = None

    @field_validator("request_id", "prompt")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("choices")
    @classmethod
    def validate_choices(cls, choices: list[str]) -> list[str]:
        if any(not choice.strip() for choice in choices):
            raise ValueError("choices must not be blank")
        if len(choices) != len(set(choices)):
            raise ValueError("choices must be unique")
        return choices


class ApprovalRequest(DomainModel):
    approval_id: str = Field(min_length=1, max_length=128)
    action_summary: str = Field(min_length=1, max_length=4_000)
    risk_level: str = Field(default="medium", min_length=1, max_length=32)
    expires_at: datetime | None = None

    @field_validator("approval_id", "action_summary", "risk_level")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class EventWait(DomainModel):
    event_name: str = Field(min_length=1, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)
    timeout_at: datetime | None = None

    @field_validator("event_name", "correlation_id")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class TerminalStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABORTED = "aborted"


class TerminalState(DomainModel):
    status: TerminalStatus
    reason: str = Field(min_length=1, max_length=2_000)
    final_artifact_ref: ArtifactRef | None = None

    @field_validator("reason")
    @classmethod
    def reject_blank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class FailureRecord(DomainModel):
    failure_id: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=2_000)
    recoverable: bool = False

    @field_validator("failure_id", "code", "summary")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class AgentTaskState(DomainModel):
    schema_version: str = DOMAIN_SCHEMA_VERSION

    thread_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    user_id: int | None = Field(default=None, gt=0)
    admin_actor_id: int = Field(gt=0)

    trigger: TriggerContext
    goal: GoalState
    constraints: list[ConstraintState] = Field(default_factory=list)
    milestones: list[MilestoneState] = Field(default_factory=list)

    plan: AgentPlan
    working_set: WorkingSet = Field(default_factory=WorkingSet)

    learner_ref: ArtifactRef | None = None
    research_memory_ref: ArtifactRef | None = None
    active_artifacts: list[ArtifactRef] = Field(default_factory=list)

    environment: EnvironmentRef
    budget: AgentBudget

    pending_user_request: UserInputRequest | None = None
    pending_approval: ApprovalRequest | None = None
    pending_event: EventWait | None = None

    last_transition_id: str | None = Field(default=None, max_length=128)
    terminal: TerminalState | None = None
    failure_records: list[FailureRecord] = Field(default_factory=list)

    @field_validator("thread_id", "run_id", "last_transition_id")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_wait_and_terminal_state(self) -> "AgentTaskState":
        pending_count = sum(
            request is not None
            for request in (self.pending_user_request, self.pending_approval, self.pending_event)
        )
        if pending_count > 1:
            raise ValueError("only one pending user, approval, or event wait is allowed")
        if self.terminal is not None and pending_count:
            raise ValueError("a terminal state cannot retain a pending wait")
        return self

    @model_validator(mode="after")
    def validate_unique_state_ids(self) -> "AgentTaskState":
        for label, values in (
            ("constraint", [constraint.constraint_id for constraint in self.constraints]),
            ("milestone", [milestone.milestone_id for milestone in self.milestones]),
            ("failure", [failure.failure_id for failure in self.failure_records]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} IDs must be unique")
        return self


class StateDelta(DomainModel):
    """A declarative, runtime-applied change to :class:`AgentTaskState`."""

    # Planning remains a domain transition rather than a graph-local mutation.
    # This lets an open-ended policy create or revise a DAG without adding a
    # graph node for each business workflow.
    plan_update: AgentPlan | None = None

    resolved_constraint_ids: list[str] = Field(default_factory=list)
    unresolved_constraint_ids: list[str] = Field(default_factory=list)
    completed_milestone_ids: list[str] = Field(default_factory=list)

    candidate_ids_to_add: list[str] = Field(default_factory=list)
    candidate_ids_to_remove: list[str] = Field(default_factory=list)
    accepted_ids_to_add: list[str] = Field(default_factory=list)
    rejected_ids_to_add: list[str] = Field(default_factory=list)

    evidence_refs_to_add: list[ArtifactRef] = Field(default_factory=list)
    artifact_refs_to_add: list[ArtifactRef] = Field(default_factory=list)
    plan_step_status_updates: dict[str, PlanStepStatus] = Field(default_factory=dict)
    budget_consumption: BudgetConsumption = Field(default_factory=BudgetConsumption)
    failure_records_to_add: list[FailureRecord] = Field(default_factory=list)

    pending_user_request: UserInputRequest | None = None
    clear_pending_user_request: bool = False
    pending_approval: ApprovalRequest | None = None
    clear_pending_approval: bool = False
    pending_event: EventWait | None = None
    clear_pending_event: bool = False

    last_transition_id: str | None = Field(default=None, max_length=128)
    terminal: TerminalState | None = None

    @field_validator(
        "resolved_constraint_ids",
        "unresolved_constraint_ids",
        "completed_milestone_ids",
        "candidate_ids_to_add",
        "candidate_ids_to_remove",
        "accepted_ids_to_add",
        "rejected_ids_to_add",
    )
    @classmethod
    def validate_id_list(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("IDs must be unique")
        return values

    @field_validator("plan_step_status_updates")
    @classmethod
    def validate_plan_step_updates(cls, updates: dict[str, PlanStepStatus]) -> dict[str, PlanStepStatus]:
        if any(not step_id.strip() for step_id in updates):
            raise ValueError("plan step IDs must not be blank")
        return updates

    @field_validator("last_transition_id")
    @classmethod
    def reject_blank_transition_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_conflicts(self) -> "StateDelta":
        conflict_sets = (
            ("resolved and unresolved constraints", self.resolved_constraint_ids, self.unresolved_constraint_ids),
            ("candidate add and remove", self.candidate_ids_to_add, self.candidate_ids_to_remove),
            ("accepted and rejected", self.accepted_ids_to_add, self.rejected_ids_to_add),
        )
        for label, left, right in conflict_sets:
            overlap = set(left) & set(right)
            if overlap:
                raise ValueError(f"{label} conflict: {sorted(overlap)}")

        waits = (
            self.pending_user_request,
            self.pending_approval,
            self.pending_event,
        )
        if sum(wait is not None for wait in waits) > 1:
            raise ValueError("a delta may set only one pending wait")
        if self.pending_user_request is not None and self.clear_pending_user_request:
            raise ValueError("cannot set and clear pending user request together")
        if self.pending_approval is not None and self.clear_pending_approval:
            raise ValueError("cannot set and clear pending approval together")
        if self.pending_event is not None and self.clear_pending_event:
            raise ValueError("cannot set and clear pending event together")
        if self.terminal is not None and any(wait is not None for wait in waits):
            raise ValueError("a terminal delta cannot set a pending wait")
        return self
