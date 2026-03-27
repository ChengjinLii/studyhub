from __future__ import annotations

from pydantic import BaseModel, Field


class CommentCreatePayload(BaseModel):
    materialId: int = Field(ge=1)
    parentId: int | None = Field(default=None, ge=1)
    content: str = Field(min_length=1, max_length=2000)


class CommentUpdatePayload(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class CommentReportPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=255)
