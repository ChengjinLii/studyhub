from __future__ import annotations

from pydantic import BaseModel, Field


class NotificationCreatePayload(BaseModel):
    userId: int | None = Field(default=None, ge=1)
    message: str = Field(min_length=1)
