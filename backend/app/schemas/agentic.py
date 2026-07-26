from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _AdminAgenticPayload(BaseModel):
    """Strict transport boundary for the admin-only agentic control plane."""

    model_config = ConfigDict(extra="forbid")


class AgentRunCreatePayload(_AdminAgenticPayload):
    goal: str = Field(min_length=1, max_length=4_000)
    title: str | None = Field(default=None, max_length=512)
    threadId: str | None = Field(default=None, min_length=1, max_length=64)
    successCriteria: list[str] = Field(default_factory=list, max_length=24)
    idempotencyKey: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("goal", "title", "threadId", "idempotencyKey")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("successCriteria")
    @classmethod
    def validate_success_criteria(cls, values: list[str]) -> list[str]:
        normalized = [item.strip() for item in values]
        if any(not item for item in normalized):
            raise ValueError("success criteria must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("success criteria must be unique")
        return normalized


class DeepResearchCreatePayload(_AdminAgenticPayload):
    question: str = Field(min_length=1, max_length=4_000)
    title: str | None = Field(default=None, max_length=512)
    threadId: str | None = Field(default=None, min_length=1, max_length=64)
    successCriteria: list[str] = Field(default_factory=list, max_length=24)
    idempotencyKey: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("question", "title", "threadId", "idempotencyKey")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("successCriteria")
    @classmethod
    def validate_success_criteria(cls, values: list[str]) -> list[str]:
        normalized = [item.strip() for item in values]
        if any(not item for item in normalized):
            raise ValueError("success criteria must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("success criteria must be unique")
        return normalized


class AgentRunResumePayload(_AdminAgenticPayload):
    waitId: str = Field(min_length=1, max_length=64)
    resumeToken: str = Field(min_length=16, max_length=256)
    payload: Any = Field(default_factory=dict)

    @field_validator("waitId", "resumeToken")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("payload")
    @classmethod
    def bound_resume_payload(cls, value: Any) -> Any:
        try:
            rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be JSON-compatible") from exc
        if len(rendered.encode("utf-8")) > 16 * 1024:
            raise ValueError("payload must not exceed 16 KiB")
        return value


class AgentRunCancelPayload(_AdminAgenticPayload):
    reason: str = Field(default="cancelled_by_admin", min_length=1, max_length=1_000)

    @field_validator("reason")
    @classmethod
    def reject_blank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value
