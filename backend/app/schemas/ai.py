from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AiChatMessagePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1)


class AiChatRequestPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messages: list[AiChatMessagePayload]
    maxTokens: int | None = 1024
    temperature: float | None = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, value: list[AiChatMessagePayload]) -> list[AiChatMessagePayload]:
        if not value:
            raise ValueError("messages 不能为空")
        return value


class AiRecommendRequestPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = Field(min_length=1)
    filters: dict[str, Any] | None = None
