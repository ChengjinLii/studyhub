from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from ._base import DomainModel


class PlanStepStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RetryPolicy(DomainModel):
    max_attempts: int = Field(default=1, ge=1, le=20)
    backoff_seconds: float = Field(default=0.0, ge=0.0, le=86_400.0)
    retryable_error_codes: list[str] = Field(default_factory=list)

    @field_validator("retryable_error_codes")
    @classmethod
    def validate_error_codes(cls, codes: list[str]) -> list[str]:
        if any(not code.strip() for code in codes):
            raise ValueError("retryable error codes must not be blank")
        if len(codes) != len(set(codes)):
            raise ValueError("retryable error codes must be unique")
        return codes


class PlanStep(DomainModel):
    step_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    status: PlanStepStatus = PlanStepStatus.PENDING
    depends_on: list[str] = Field(default_factory=list)
    capability: str = Field(min_length=1, max_length=128)
    completion_check: str = Field(min_length=1, max_length=1024)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    expected_artifacts: list[str] = Field(default_factory=list)

    @field_validator("step_id", "title", "capability", "completion_check")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("depends_on", "expected_artifacts")
    @classmethod
    def unique_nonblank_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("values must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("values must be unique")
        return values

    @model_validator(mode="after")
    def reject_self_dependency(self) -> "PlanStep":
        if self.step_id in self.depends_on:
            raise ValueError("a plan step cannot depend on itself")
        return self


class AgentPlan(DomainModel):
    plan_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    objective: str = Field(min_length=1, max_length=4_000)
    success_criteria: list[str] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list)
    created_by_policy_version: str = Field(min_length=1, max_length=128)

    @field_validator("plan_id", "objective", "created_by_policy_version")
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

    @model_validator(mode="after")
    def validate_dag(self) -> "AgentPlan":
        step_by_id = {step.step_id: step for step in self.steps}
        if len(step_by_id) != len(self.steps):
            raise ValueError("plan step IDs must be unique")

        missing_dependencies = {
            dependency
            for step in self.steps
            for dependency in step.depends_on
            if dependency not in step_by_id
        }
        if missing_dependencies:
            raise ValueError(f"plan contains unknown dependencies: {sorted(missing_dependencies)}")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("plan dependency graph contains a cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in step_by_id[step_id].depends_on:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step in self.steps:
            visit(step.step_id)
        return self
