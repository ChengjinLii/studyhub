from __future__ import annotations

from datetime import date
import json
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator


class MaterialMutationBase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    description: str | None = None
    price: int | None = None
    school: str | None = None
    college: str | None = None
    major: str | None = None
    gradeType: str | None = None
    gradeValue: str | None = None
    generalCourse: bool | None = None
    courseCategory: str | None = None
    keywords: str | None = None
    tags: str | None = None
    deliveryMethod: str | None = None
    netdiskUrl: str | None = None
    netdiskPassword: str | None = None
    netdiskExpiredAt: date | None = None
    netdiskReminderAt: date | None = None
    previewWatermarkEnabled: bool | None = None
    previewSource: str | None = None
    customPreviewText: str | None = None
    copyrightOwner: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("标题不能为空")
        if len(normalized) > 80:
            raise ValueError("标题需在 80 个字符以内")
        return normalized

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) > 3000:
            raise ValueError("内容需在 3000 个字符以内")
        return value

    @field_validator("customPreviewText")
    @classmethod
    def validate_custom_preview_text(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) > 800:
            raise ValueError("自定义预览需在 800 个字符以内")
        return value

    @field_validator("copyrightOwner")
    @classmethod
    def validate_copyright_owner(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) > 8:
            raise ValueError("版权持有者需在 8 个字符以内")
        return value


class MaterialCreatePayload(MaterialMutationBase):
    price: int
    school: str
    requestId: int | None = None


class MaterialUpdatePayload(MaterialMutationBase):
    customPreviewClear: bool | None = None


class RatingPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rating: int

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("Input should be less than or equal to 5")
        return value


class ReviewPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rating: int
    comment: str | None = None

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("Input should be less than or equal to 5")
        return value


class BatchDownloadPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    materialIds: list[int]

    @field_validator("materialIds")
    @classmethod
    def validate_material_ids(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("materialIds 不能为空")
        return value


class MaterialViewPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    viewerToken: str | None = None

    @field_validator("viewerToken")
    @classmethod
    def validate_viewer_token(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) > 128:
            raise ValueError("viewerToken 过长")
        return value


def parse_payload_json(raw_payload: Any, schema: type[BaseModel]) -> BaseModel:
    if raw_payload is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少 payload")
    if hasattr(raw_payload, "file"):
        content = raw_payload.file.read()
        raw_text = content.decode("utf-8")
    elif isinstance(raw_payload, (str, bytes)):
        raw_text = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
    else:
        raw_text = json.dumps(raw_payload, ensure_ascii=False)
    return schema.model_validate_json(raw_text)
