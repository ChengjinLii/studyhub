from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from ._base import DOMAIN_SCHEMA_VERSION, DomainModel
from .artifact import ArtifactRef
from .decision import AgentDecision
from .hashing import canonical_model_hash
from .reward_facts import RewardFacts
from .state import StateDelta


class TokenRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    TOOL_OBSERVATION = "tool_observation"
    USER_SIMULATOR_OBSERVATION = "user_simulator_observation"
    ASSISTANT_ACTION = "assistant_action"
    ASSISTANT_FINAL = "assistant_final"


TRAINABLE_TOKEN_ROLES = frozenset({TokenRole.ASSISTANT_ACTION, TokenRole.ASSISTANT_FINAL})


class TokenRoleSpan(DomainModel):
    role: TokenRole
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    trainable: bool

    @model_validator(mode="after")
    def validate_span(self) -> "TokenRoleSpan":
        if self.end <= self.start:
            raise ValueError("token role span end must be greater than start")
        expected_trainable = self.role in TRAINABLE_TOKEN_ROLES
        if self.trainable != expected_trainable:
            raise ValueError(f"token role {self.role.value} has fixed trainable={expected_trainable}")
        return self


class VerifierResult(DomainModel):
    passed: bool
    summary: str = Field(min_length=1, max_length=4_000)
    failed_checks: list[str] = Field(default_factory=list)
    completed_milestone_ids: list[str] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("failed_checks", "completed_milestone_ids")
    @classmethod
    def validate_unique_nonblank_values(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("values must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("values must be unique")
        return values


class ModelUsage(DomainModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_total_tokens(self) -> "ModelUsage":
        minimum_total = self.input_tokens + self.output_tokens
        if self.total_tokens < minimum_total:
            raise ValueError("total tokens cannot be less than input plus output tokens")
        return self


class ExecutionError(DomainModel):
    code: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=2_000)
    retryable: bool = False
    safe_details_ref: ArtifactRef | None = None

    @field_validator("code", "summary")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class AgentTransitionEvent(DomainModel):
    schema_version: str = DOMAIN_SCHEMA_VERSION

    thread_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    transition_id: str = Field(min_length=1, max_length=128)
    parent_transition_id: str | None = Field(default=None, max_length=128)

    turn_index: int = Field(ge=0)
    plan_step_id: str | None = Field(default=None, max_length=128)
    subagent_name: str | None = Field(default=None, max_length=128)

    environment_snapshot_id: str = Field(min_length=1, max_length=128)
    state_before_hash: str = Field(min_length=1, max_length=128)
    state_after_hash: str = Field(min_length=1, max_length=128)
    state_abstract_key: str = Field(min_length=1, max_length=256)

    policy_version: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=256)
    model_revision: str | None = Field(default=None, max_length=256)

    prompt_template_hash: str = Field(min_length=1, max_length=128)
    skill_catalog_hash: str = Field(min_length=1, max_length=128)
    action_schema_hash: str = Field(min_length=1, max_length=128)

    context_view_ref: ArtifactRef
    raw_model_output_ref: ArtifactRef | None = None
    parsed_decision: AgentDecision

    observation_ref: ArtifactRef | None = None
    state_delta: StateDelta
    verifier_result: VerifierResult

    token_ids: list[int] | None = None
    token_logprobs: list[float] | None = None
    token_role_spans: list[TokenRoleSpan] = Field(default_factory=list)

    reward_facts: RewardFacts

    latency_ms: dict[str, float] = Field(default_factory=dict)
    usage: ModelUsage = Field(default_factory=ModelUsage)
    error: ExecutionError | None = None
    terminal_reason: str | None = Field(default=None, max_length=2_000)
    exported_at: datetime | None = None

    @field_validator(
        "thread_id",
        "run_id",
        "transition_id",
        "parent_transition_id",
        "plan_step_id",
        "subagent_name",
        "environment_snapshot_id",
        "state_before_hash",
        "state_after_hash",
        "state_abstract_key",
        "policy_version",
        "model_id",
        "model_revision",
        "prompt_template_hash",
        "skill_catalog_hash",
        "action_schema_hash",
        "terminal_reason",
    )
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("token_ids")
    @classmethod
    def validate_token_ids(cls, token_ids: list[int] | None) -> list[int] | None:
        if token_ids is not None and any(token_id < 0 for token_id in token_ids):
            raise ValueError("token IDs must be non-negative")
        return token_ids

    @field_validator("latency_ms")
    @classmethod
    def validate_latency(cls, latency_ms: dict[str, float]) -> dict[str, float]:
        if any(not key.strip() for key in latency_ms):
            raise ValueError("latency metric names must not be blank")
        if any(value < 0 for value in latency_ms.values()):
            raise ValueError("latency values must be non-negative")
        return latency_ms

    @model_validator(mode="after")
    def validate_token_trace(self) -> "AgentTransitionEvent":
        if self.token_logprobs is not None:
            if self.token_ids is None:
                raise ValueError("token logprobs require raw token IDs")
            if len(self.token_logprobs) != len(self.token_ids):
                raise ValueError("token logprobs must align with raw token IDs")
        if self.token_role_spans and self.token_ids is None:
            raise ValueError("token role spans require raw token IDs")
        if self.token_ids is not None and any(span.end > len(self.token_ids) for span in self.token_role_spans):
            raise ValueError("token role span exceeds raw token IDs")
        return self

    def canonical_hash(self) -> str:
        """Hash the durable transition while ignoring its trace-export timestamp."""

        return canonical_model_hash(self)
