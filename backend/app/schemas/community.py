from __future__ import annotations

from pydantic import BaseModel, Field


class FeedbackPayload(BaseModel):
    type: str = Field(min_length=1, max_length=32)
    page: str | None = Field(default=None, max_length=255)
    content: str = Field(min_length=1)
    contact: str | None = Field(default=None, max_length=255)


class VolunteerPayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    schoolMajorGrade: str = Field(min_length=1, max_length=255)
    skills: list[str] | None = None
    timeCommitment: str | None = Field(default=None, max_length=64)
    portfolioUrl: str | None = Field(default=None, max_length=512)
    intro: str = Field(min_length=1)
    contact: str | None = Field(default=None, max_length=255)


class UpdateStatusPayload(BaseModel):
    status: str = Field(min_length=1, max_length=32)
