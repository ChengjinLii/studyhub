from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BatchFilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    sizeBytes: int = Field(gt=0, le=50 * 1024 * 1024)
    contentType: str = Field(default="application/octet-stream", max_length=128)

    @field_validator("name")
    @classmethod
    def filename_only(cls, value: str) -> str:
        if any(char in value for char in ("/", "\\", "\x00", "\r", "\n")) or value in {".", ".."}:
            raise ValueError("文件名不能包含路径或控制字符")
        return value


class BatchCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    submissionId: str = Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")
    deliveryMethod: Literal["FILE", "NETDISK"]
    publicationIntent: Literal["FREE", "PAID", "CONTACT"]
    pricingNote: str = Field(default="", max_length=2000)
    note: str = Field(default="", max_length=2000)
    netdiskUrl: str = Field(default="", max_length=2048)
    netdiskPassword: str = Field(default="", max_length=64)
    consent: Literal[True]
    files: list[BatchFilePayload] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def valid_delivery(self):
        if self.deliveryMethod == "FILE":
            if not self.files or self.netdiskUrl or self.netdiskPassword:
                raise ValueError("请选择文件，文件投稿不包含网盘链接")
            if sum(item.sizeBytes for item in self.files) > 100 * 1024 * 1024:
                raise ValueError("每批文件总大小不能超过 100MB")
        else:
            parts = urlsplit(self.netdiskUrl)
            if self.files or parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                raise ValueError("请填写有效的 HTTP/HTTPS 网盘链接")
        return self


class BatchReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    itemIds: list[int] = Field(min_length=1, max_length=20)
    action: Literal["REVIEW", "RETURN", "REJECT"]
    reason: str = Field(min_length=1, max_length=500)


class BatchAmendPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    note: str = Field(min_length=1, max_length=2000)
    pricingNote: str | None = Field(default=None, max_length=2000)
    publicationIntent: Literal["FREE", "PAID", "CONTACT"] | None = None
    netdiskUrl: str | None = Field(default=None, max_length=2048)
    netdiskPassword: str | None = Field(default=None, max_length=64)

    @field_validator("netdiskUrl")
    @classmethod
    def http_link(cls, value: str | None) -> str | None:
        if value is not None:
            parts = urlsplit(value)
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                raise ValueError("请填写有效的 HTTP/HTTPS 网盘链接")
        return value


class BatchPublishPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    publicationId: str = Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")
    itemIds: list[int] = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=3000)
    school: str = Field(min_length=1, max_length=120)
    courseCategory: Literal["GENERAL", "MAJOR", "SKILL"]
    college: str = Field(default="", max_length=120)
    major: str = Field(default="", max_length=255)
    tags: str = Field(default="", max_length=1000)
    price: int = Field(ge=0, le=1000000, strict=True)
    pricingConfirmed: bool = False
    confirmationNote: str = Field(default="", max_length=1000)


class BatchAccessPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    permissions: list[Literal["read", "review", "publish", "cleanup"]] = Field(default_factory=lambda: ["read"], min_length=1, max_length=4)
