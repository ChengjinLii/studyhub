from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BotSpeechUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enabled: bool
    message: str = Field(default="", max_length=120)


class BotSpeechMessagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)

    message: str = Field(min_length=1, max_length=120)
    display_style: Literal["STANDARD", "EMPHASIS", "TYPEWRITER"] = Field(default="STANDARD", alias="displayStyle")
    display_duration_seconds: int = Field(default=8, ge=0, le=60, alias="displayDurationSeconds")
    priority: int = Field(default=50, ge=0, le=100)
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    publish: bool = False

    @model_validator(mode="after")
    def validate_schedule(self) -> "BotSpeechMessagePayload":
        if (
            self.starts_at is not None
            and self.ends_at is not None
            and self.ends_at.timestamp() <= self.starts_at.timestamp()
        ):
            raise ValueError("结束时间必须晚于开始时间")
        return self
