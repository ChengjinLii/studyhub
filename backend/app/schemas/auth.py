from __future__ import annotations

from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, field_validator


class VerificationPurpose(str, Enum):
    REGISTER = "REGISTER"
    BIND = "BIND"
    RESET = "RESET"


class CaptchaResponsePayload(BaseModel):
    captchaId: str
    imageBase64: str


class VerificationSendResponsePayload(BaseModel):
    email: EmailStr
    expiresInSeconds: int
    resendAfterSeconds: int


class LoginRequestPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    identifier: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("identifier", "username", "email"),
    )
    password: str = Field(..., min_length=1)
    captchaId: str = Field(..., min_length=1)
    captchaCode: str = Field(..., min_length=1)
    rememberMe: bool | None = False


class RegisterRequestPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_\-\u4e00-\u9fa5]+$")
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=64)
    captchaId: str = Field(..., min_length=1)
    captchaCode: str = Field(..., min_length=1)

    @field_validator("username", "captchaId", "captchaCode", mode="before")
    @classmethod
    def strip_register_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class VerifyEmailRequestPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: EmailStr
    code: str = Field(..., min_length=4, max_length=10)
    purpose: VerificationPurpose = VerificationPurpose.REGISTER

    @field_validator("code", mode="before")
    @classmethod
    def strip_code(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PasswordChangeRequestPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    oldPassword: str = Field(..., min_length=1)
    newPassword: str = Field(..., min_length=6, max_length=64)


class ResetPasswordRequestPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    identifier: str = Field(..., min_length=1)
    newPassword: str = Field(..., min_length=6, max_length=64)
    captchaId: str | None = None
    captchaCode: str | None = Field(default=None, min_length=4, max_length=10)
    code: str | None = Field(default=None, min_length=4, max_length=10)


class BindEmailRequestPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: EmailStr
    code: str | None = Field(default=None, min_length=4, max_length=10)


class AuthUserPayload(BaseModel):
    id: int
    username: str
    email: str | None = None
    verified: bool
    nickname: str
    roleMask: int | None = None
    freeDownloadQuota: int | None = None
    emailPrivacy: bool | None = None


class AuthResponsePayload(BaseModel):
    token: str
    user: AuthUserPayload


class BindEmailResponsePayload(BaseModel):
    email: str | None = None
    verified: bool
