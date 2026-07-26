from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from ._base import DomainModel


class ArtifactKind(StrEnum):
    CONTEXT_VIEW = "context_view"
    RAW_MODEL_OUTPUT = "raw_model_output"
    OBSERVATION = "observation"
    RESEARCH_MEMORY = "research_memory"
    LEARNING_PROFILE = "learning_profile"
    LEARNING_PLAN = "learning_plan"
    PRACTICE_SET = "practice_set"
    MATERIAL_ANALYSIS = "material_analysis"
    DAILY_BRIEF = "daily_brief"
    EVIDENCE_LEDGER = "evidence_ledger"
    REPORT = "report"
    OTHER = "other"


class ArtifactRef(DomainModel):
    """A compact, versioned pointer to durable content.

    The referenced content belongs in the artifact store.  `summary` is capped
    so a transition cannot accidentally embed a raw model response or PDF text.
    """

    artifact_id: str = Field(min_length=1, max_length=128)
    artifact_type: ArtifactKind | str = ArtifactKind.OTHER
    version: int = Field(ge=1)
    uri: str = Field(min_length=1, max_length=2048)
    content_hash: str | None = Field(default=None, min_length=1, max_length=128)
    media_type: str | None = Field(default=None, max_length=128)
    summary: str | None = Field(default=None, max_length=1024)

    @field_validator("artifact_id", "uri", "content_hash", "media_type", "summary")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value
