from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.plan import RetryPolicy

from .context import SkillExecutionContext


InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class IdempotencyMode(StrEnum):
    PURE = "pure"
    KEYED = "keyed"
    NON_IDEMPOTENT = "non_idempotent"


class ObservationTrainingRole(StrEnum):
    VISIBLE_MASKED = "visible_masked"
    VISIBLE_TRAINABLE = "visible_trainable"
    HIDDEN = "hidden"


class SkillCost(DomainModel):
    fixed_cost: float = Field(default=0.0, ge=0.0)
    per_item_cost: float = Field(default=0.0, ge=0.0)
    estimated_context_tokens: int = Field(default=0, ge=0)


class SkillSpec(DomainModel):
    name: str = Field(min_length=3, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=2_000)

    input_model: str = Field(min_length=1, max_length=256)
    output_model: str = Field(min_length=1, max_length=256)

    side_effect: Literal["none", "read", "write", "external"]
    permission_scopes: list[str] = Field(default_factory=list)
    requires_approval: bool = False

    timeout_seconds: float = Field(gt=0.0, le=300.0)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    idempotency: IdempotencyMode = IdempotencyMode.PURE

    observation_training_role: ObservationTrainingRole = ObservationTrainingRole.VISIBLE_MASKED
    environment_adapter: str = Field(min_length=1, max_length=128)
    reward_hooks: list[str] = Field(default_factory=list)
    cost_model: SkillCost = Field(default_factory=SkillCost)

    @field_validator("name", "version", "description", "input_model", "output_model", "environment_adapter")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("permission_scopes", "reward_hooks")
    @classmethod
    def validate_unique_nonblank_values(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("values must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("values must be unique")
        return values


class BaseSkill(ABC, Generic[InputT, OutputT]):
    """A single typed capability; orchestration belongs to the runtime, not here."""

    spec: SkillSpec
    input_model: type[InputT]
    output_model: type[OutputT]

    @abstractmethod
    async def execute(self, context: SkillExecutionContext, payload: InputT) -> OutputT:
        """Execute one bounded capability call and return only typed output."""
