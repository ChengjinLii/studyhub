from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RequestCreatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    course: str | None = Field(default=None, max_length=80)
    keyword: str | None = Field(default=None, max_length=300)
    budget: int | None = Field(default=None, ge=0)
    urgencyTier: str | None = Field(default=None, max_length=16)
    creatorFloor: int | None = Field(default=None, ge=0)
    previewRequirement: str | None = Field(default=None, max_length=255)
    school: str | None = Field(default=None, max_length=120)
    college: str | None = Field(default=None, max_length=120)
    major: str | None = Field(default=None, max_length=255)
    anonymous: bool | None = None


class RequestContributionCreatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    amount: int = Field(ge=1)
    deadlineTier: str | None = Field(default=None, max_length=16)


class RequestRespondPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str | None = Field(default=None, max_length=500)
    materialId: int | None = Field(default=None, ge=1)


class RequestAcceptPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    responseId: int = Field(ge=1)


class RequestPreviewViewPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    responseId: int = Field(ge=1)
    loadedCount: int | None = Field(default=0, ge=0)


class RequestDisputePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    responseId: int = Field(ge=1)
    reason: str = Field(min_length=10)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 10:
            raise ValueError("不收货理由需至少 10 个字")
        return normalized


class RequestArbitrationDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: str = Field(min_length=1, max_length=16)
    adminNote: str | None = Field(default=None, max_length=500)


class RequestContributionDeadlinePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    deadlineTier: str = Field(min_length=1, max_length=16)
