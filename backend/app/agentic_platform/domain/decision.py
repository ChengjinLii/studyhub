from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from ._base import DOMAIN_SCHEMA_VERSION, DomainModel
from .artifact import ArtifactRef
from .state import ApprovalRequest, EventWait, UserInputRequest


class AgentActionType(StrEnum):
    CREATE_PLAN = "create_plan"
    REVISE_PLAN = "revise_plan"
    EXECUTE_SKILL = "execute_skill"
    DELEGATE = "delegate"
    ASK_USER = "ask_user"
    REQUEST_APPROVAL = "request_approval"
    WAIT_EVENT = "wait_event"
    WRITE_ARTIFACT = "write_artifact"
    MANAGE_CONTEXT = "manage_context"
    REVIEW = "review"
    FINALIZE = "finalize"
    ABORT = "abort"


class ExpectedStateChange(DomainModel):
    summary: str = Field(min_length=1, max_length=2_000)
    affected_constraint_ids: list[str] = Field(default_factory=list)
    affected_milestone_ids: list[str] = Field(default_factory=list)
    expected_artifact_types: list[str] = Field(default_factory=list)
    may_wait: bool = False

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("affected_constraint_ids", "affected_milestone_ids", "expected_artifact_types")
    @classmethod
    def validate_unique_nonblank_values(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("values must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("values must be unique")
        return values


class SubAgentTaskPacket(DomainModel):
    task_id: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=4_000)
    input_artifacts: list[ArtifactRef] = Field(default_factory=list)
    max_turns: int = Field(ge=1, le=100)
    max_skill_calls: int = Field(default=0, ge=0, le=1_000)

    @field_validator("task_id", "objective")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class AgentOutput(DomainModel):
    summary: str = Field(min_length=1, max_length=8_000)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    user_visible: bool = False

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class AgentDecision(DomainModel):
    """A validated atomic policy decision, never an unbounded ReAct message."""

    schema_version: str = DOMAIN_SCHEMA_VERSION
    action_type: AgentActionType
    plan_step_id: str | None = Field(default=None, max_length=128)
    rationale_summary: str = Field(min_length=1, max_length=2_000)
    expected_state_change: ExpectedStateChange

    skill_name: str | None = Field(default=None, max_length=128)
    arguments: dict[str, Any] | None = None

    delegate_agent: str | None = Field(default=None, max_length=128)
    task_packet: SubAgentTaskPacket | None = None

    user_request: UserInputRequest | None = None
    approval_request: ApprovalRequest | None = None
    event_wait: EventWait | None = None

    final_output: AgentOutput | None = None

    @field_validator("plan_step_id", "rationale_summary", "skill_name", "delegate_agent")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_action_payload(self) -> "AgentDecision":
        requirements: dict[AgentActionType, tuple[str, ...]] = {
            AgentActionType.EXECUTE_SKILL: ("skill_name", "arguments"),
            AgentActionType.DELEGATE: ("delegate_agent", "task_packet"),
            AgentActionType.ASK_USER: ("user_request",),
            AgentActionType.REQUEST_APPROVAL: ("approval_request",),
            AgentActionType.WAIT_EVENT: ("event_wait",),
            AgentActionType.FINALIZE: ("final_output",),
        }
        action_payload_fields = {
            "skill_name",
            "arguments",
            "delegate_agent",
            "task_packet",
            "user_request",
            "approval_request",
            "event_wait",
            "final_output",
        }
        required = set(requirements.get(self.action_type, ()))
        missing = [field_name for field_name in required if getattr(self, field_name) is None]
        if missing:
            raise ValueError(f"{self.action_type.value} requires: {', '.join(missing)}")

        unexpected = [
            field_name
            for field_name in action_payload_fields - required
            if getattr(self, field_name) is not None
        ]
        if unexpected:
            raise ValueError(f"{self.action_type.value} does not allow: {', '.join(sorted(unexpected))}")
        return self
