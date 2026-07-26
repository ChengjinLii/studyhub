from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.state import UserInputRequest


class AskAdminInput(DomainModel):
    request_id: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=4_000)
    choices: list[str] = Field(default_factory=list, max_length=12)
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


class AskAdminOutput(DomainModel):
    request: UserInputRequest
