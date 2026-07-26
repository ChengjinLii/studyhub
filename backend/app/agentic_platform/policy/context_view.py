from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.plan import PlanStepStatus


class ContextPurpose(StrEnum):
    PLANNER = "planner"
    POLICY = "policy"
    FINALIZER = "finalizer"


class ContextConstraint(DomainModel):
    constraint_id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1_000)
    is_resolved: bool


class ContextMilestone(DomainModel):
    milestone_id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1_000)
    is_completed: bool


class ContextPlanStep(DomainModel):
    step_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    status: PlanStepStatus
    depends_on: list[str] = Field(default_factory=list)
    capability: str = Field(min_length=1, max_length=128)
    completion_check: str = Field(min_length=1, max_length=1_000)


class ContextCapability(DomainModel):
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1_000)
    side_effect: str = Field(min_length=1, max_length=32)
    requires_approval: bool
    input_model: str = Field(min_length=1, max_length=256)
    output_model: str = Field(min_length=1, max_length=256)


class ContextArtifactRef(DomainModel):
    """Safe artifact identity: intentionally excludes URI, hash, and body."""

    artifact_id: str = Field(min_length=1, max_length=128)
    artifact_type: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    summary: str | None = Field(default=None, max_length=512)


class ContextWorkingSet(DomainModel):
    candidate_ids: list[str] = Field(default_factory=list)
    accepted_ids: list[str] = Field(default_factory=list)
    rejected_ids: list[str] = Field(default_factory=list)
    evidence_artifacts: list[ContextArtifactRef] = Field(default_factory=list)


class ContextBudget(DomainModel):
    turns_remaining: int = Field(ge=0)
    skill_calls_remaining: int = Field(ge=0)
    context_tokens_remaining: int = Field(ge=0)
    cost_remaining: float = Field(ge=0.0)


class ContextView(DomainModel):
    """A bounded, secret-free model view for exactly one policy phase."""

    schema_version: str = "1.0"
    purpose: ContextPurpose
    thread_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    goal: str = Field(min_length=1, max_length=2_000)
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[ContextConstraint] = Field(default_factory=list)
    milestones: list[ContextMilestone] = Field(default_factory=list)
    plan_id: str = Field(min_length=1, max_length=128)
    plan_version: int = Field(ge=1)
    plan_steps: list[ContextPlanStep] = Field(default_factory=list)
    capabilities: list[ContextCapability] = Field(default_factory=list)
    capability_catalog_hash: str = Field(min_length=1, max_length=128)
    capability_count: int = Field(ge=0)
    working_set: ContextWorkingSet = Field(default_factory=ContextWorkingSet)
    active_artifacts: list[ContextArtifactRef] = Field(default_factory=list)
    observation_summaries: list[str] = Field(default_factory=list)
    budget: ContextBudget
    terminal_status: str | None = Field(default=None, max_length=32)
    token_budget: int = Field(gt=0)
    estimated_tokens: int = Field(ge=0)
    truncated: bool = False

    @field_validator("goal", "terminal_status")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("success_criteria", "observation_summaries")
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("context text values must not be blank")
        return values
