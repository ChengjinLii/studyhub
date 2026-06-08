from __future__ import annotations

import base64
import binascii
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AGENT_IMAGE_MAX_BYTES = 786_432
AGENT_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}


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
    sizeBytes: int = Field(ge=1, le=AGENT_IMAGE_MAX_BYTES)

    @field_validator("mimeType")
    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in AGENT_IMAGE_MIME_TYPES:
            raise ValueError("仅支持 PNG、JPG 或 WEBP 图片")
        return normalized

    @field_validator("dataUrl")
    @classmethod
    def validate_data_url(cls, value: str) -> str:
        _decode_image_data_url(value)
        return value

    @model_validator(mode="after")
    def validate_data_url_matches_mime_type(self) -> "AiImageAttachmentPayload":
        media_type, decoded_size = _decode_image_data_url(self.dataUrl)
        if media_type != self.mimeType:
            raise ValueError("图片 MIME 与 data URL 不一致")
        if decoded_size != self.sizeBytes:
            raise ValueError("图片大小与 data URL 不一致")
        return self


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


def _decode_image_data_url(value: str) -> tuple[str, int]:
    header, separator, encoded = value.partition(",")
    normalized_header = header.strip().lower()
    if separator != "," or not normalized_header.startswith("data:") or not normalized_header.endswith(";base64"):
        raise ValueError("图片必须使用 base64 data URL")
    media_type = normalized_header.removeprefix("data:").removesuffix(";base64")
    if media_type not in AGENT_IMAGE_MIME_TYPES:
        raise ValueError("仅支持 PNG、JPG 或 WEBP 图片")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("图片必须使用有效 base64 data URL") from exc
    if not decoded:
        raise ValueError("图片内容不能为空")
    if len(decoded) > AGENT_IMAGE_MAX_BYTES:
        raise ValueError("图片不能超过 768KB")
    return media_type, len(decoded)
