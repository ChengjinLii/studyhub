from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AdminCreateUserPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    nickname: str | None = Field(default=None, max_length=64)
    roleMask: int | None = None


class AdminUpdateRolePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    roleMask: int


class AdminCreateUserNotePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str = Field(min_length=1, max_length=1000)


class AdminMaterialBatchUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    materialIds: list[int]
    college: str | None = Field(default=None, max_length=120)
    major: str | None = Field(default=None, max_length=255)
    gradeValue: str | None = Field(default=None, max_length=64)
    courseCategory: str | None = Field(default=None, max_length=32)
    tags: str | None = None
    tagsMode: str | None = Field(default="replace", max_length=16)


class AdminMaterialBatchDeletePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    materialIds: list[int]
