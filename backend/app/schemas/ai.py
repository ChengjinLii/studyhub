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


class AiImageAttachmentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, max_length=120)
    mimeType: str = Field(min_length=1, max_length=64)
    dataUrl: str = Field(min_length=1, max_length=1_100_000)
    sizeBytes: int = Field(ge=1, le=786_432)

    @field_validator("mimeType")
    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("仅支持 PNG、JPG 或 WEBP 图片")
        return normalized

    @field_validator("dataUrl")
    @classmethod
    def validate_data_url(cls, value: str) -> str:
        if not value.startswith("data:image/") or ";base64," not in value[:80]:
            raise ValueError("图片必须使用 base64 data URL")
        return value


class AiRecommendRequestPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = Field(min_length=1)
    contextQuery: str | None = Field(default=None, max_length=1200)
    filters: dict[str, Any] | None = None
    imageAttachments: list[AiImageAttachmentPayload] = Field(default_factory=list)

    @field_validator("imageAttachments")
    @classmethod
    def validate_image_attachments(cls, value: list[AiImageAttachmentPayload]) -> list[AiImageAttachmentPayload]:
        return value[:1]


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
