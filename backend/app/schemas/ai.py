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
    contextQuery: str | None = Field(default=None, max_length=1200)
    filters: dict[str, Any] | None = None


class AiMemoryPreferencePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool


class AiFeedbackPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hook: str = Field(min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=500)
    selectedMaterialIds: list[int] = Field(default_factory=list)

    @field_validator("selectedMaterialIds")
    @classmethod
    def validate_selected_material_ids(cls, value: list[int]) -> list[int]:
        deduped: list[int] = []
        for item in value:
            material_id = int(item)
            if material_id <= 0 or material_id in deduped:
                continue
            deduped.append(material_id)
            if len(deduped) >= 10:
                break
        return deduped
