from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class AccountUpdateRequestPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nickname: str | None = None
    emailPrivacy: bool | None = None
    signature: str | None = None
    school: str | None = None
    college: str | None = None
    major: str | None = None
    gradeStages: list[str] | None = None

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) > 24:
            raise ValueError("昵称长度不能超过 24 个字符")
        return value

    @field_validator("signature")
    @classmethod
    def validate_signature(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) > 300:
            raise ValueError("个性签名长度不能超过 300 个字符")
        return value

    @field_validator("school")
    @classmethod
    def validate_school(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) > 120:
            raise ValueError("学校长度不能超过 120 个字符")
        return value

    @field_validator("college")
    @classmethod
    def validate_college(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) > 120:
            raise ValueError("学院长度不能超过 120 个字符")
        return value

    @field_validator("major")
    @classmethod
    def validate_major(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) > 120:
            raise ValueError("专业长度不能超过 120 个字符")
        return value

    @field_validator("gradeStages")
    @classmethod
    def validate_grade_stages(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) > 7:
            raise ValueError("年级/阶段最多选择 7 项")
        return value


class AccountProfilePayload(BaseModel):
    id: int
    username: str
    nickname: str
    signature: str | None = None
    school: str | None = None
    college: str | None = None
    major: str | None = None
    gradeStages: list[str]
    email: str | None = None
    emailPrivacy: bool | None = None
    avatar: str | None = None
    payoutQrUrl: str | None = None
    legendaryContributorUntil: str | None = None
    purchaseCount: int
    saleCount: int
