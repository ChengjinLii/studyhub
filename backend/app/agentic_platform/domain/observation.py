from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from ._base import DomainModel
from .artifact import ArtifactRef


class ObservationSource(StrEnum):
    SKILL = "skill"
    USER = "user"
    SYSTEM = "system"
    SUBAGENT = "subagent"
    VERIFIER = "verifier"


class EvidenceReference(DomainModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    source_uri: str = Field(min_length=1, max_length=2048)
    page: int | None = Field(default=None, gt=0)
    excerpt_ref: ArtifactRef | None = None
    claim_ids: list[str] = Field(default_factory=list)

    @field_validator("evidence_id", "source_uri")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("claim_ids")
    @classmethod
    def validate_claim_ids(cls, claim_ids: list[str]) -> list[str]:
        if any(not claim_id.strip() for claim_id in claim_ids):
            raise ValueError("claim IDs must not be blank")
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim IDs must be unique")
        return claim_ids


class Observation(DomainModel):
    """A bounded observation whose full payload is stored as an artifact."""

    observation_id: str = Field(min_length=1, max_length=128)
    source: ObservationSource
    summary: str = Field(min_length=1, max_length=4_000)
    artifact_ref: ArtifactRef
    evidence: list[EvidenceReference] = Field(default_factory=list)
    recoverable_error_code: str | None = Field(default=None, max_length=128)

    @field_validator("observation_id", "summary", "recoverable_error_code")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


EvidenceRef = EvidenceReference
