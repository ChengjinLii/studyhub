from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BotSpeechUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enabled: bool
    message: str = Field(default="", max_length=120)
