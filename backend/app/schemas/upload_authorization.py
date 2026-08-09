from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


UploadFileRole = Literal["MATERIAL", "PREVIEW", "CUSTOM_PREVIEW"]


class UploadFileDescriptorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: UploadFileRole
    name: str = Field(..., min_length=1, max_length=255)
    sizeBytes: int = Field(..., ge=0)
    contentType: str = Field(default="", max_length=128)

    @field_validator("name", "contentType", mode="before")
    @classmethod
    def strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class MaterialUploadAuthorizationRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submissionId: str = Field(..., pattern=r"^[A-Za-z0-9_-]{16,64}$")
    files: list[UploadFileDescriptorPayload] = Field(default_factory=list, max_length=16)


class MaterialUploadAuthorizationResponsePayload(BaseModel):
    uploadToken: str
    expiresInSeconds: int
    remainingDailySubmissions: int
    remainingDailyBytes: int
