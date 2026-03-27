from __future__ import annotations

from pydantic import BaseModel, Field


class ReportCreatePayload(BaseModel):
    targetType: str = Field(min_length=1, max_length=32)
    targetId: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=255)


class AdminReportUpdatePayload(BaseModel):
    status: str | None = Field(default=None, max_length=32)
    adminNote: str | None = Field(default=None, max_length=500)
    restoreTarget: bool | None = None
