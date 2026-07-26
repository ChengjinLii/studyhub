from __future__ import annotations

from pydantic import Field, field_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.observation import EvidenceReference
from app.agentic_platform.domain.state import ConstraintState


class CheckConstraintsInput(DomainModel):
    constraints: list[ConstraintState] = Field(min_length=1, max_length=100)
    claimed_resolved_constraint_ids: list[str] = Field(default_factory=list)
    accepted_candidate_ids: list[str] = Field(default_factory=list)
    rejected_candidate_ids: list[str] = Field(default_factory=list)

    @field_validator(
        "claimed_resolved_constraint_ids",
        "accepted_candidate_ids",
        "rejected_candidate_ids",
    )
    @classmethod
    def validate_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("IDs must be unique")
        return values


class CheckConstraintsOutput(DomainModel):
    valid: bool
    resolved_constraint_ids: list[str] = Field(default_factory=list)
    unresolved_constraint_ids: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)


class CheckEvidenceInput(DomainModel):
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=100)
    required_claim_ids: list[str]

    @field_validator("required_claim_ids")
    @classmethod
    def validate_claim_ids(cls, claim_ids: list[str]) -> list[str]:
        if any(not claim_id.strip() for claim_id in claim_ids):
            raise ValueError("claim IDs must not be blank")
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim IDs must be unique")
        return claim_ids


class CheckEvidenceOutput(DomainModel):
    valid: bool
    supported_claim_ids: list[str] = Field(default_factory=list)
    unsupported_claim_ids: list[str] = Field(default_factory=list)
    invalid_evidence_ids: list[str] = Field(default_factory=list)


class CheckArtifactInput(DomainModel):
    artifact: dict[str, object] = Field(min_length=1)


class CheckArtifactOutput(DomainModel):
    valid: bool
    artifact_type: str = Field(min_length=1, max_length=128)
    artifact_id: str = Field(min_length=1, max_length=128)
    violations: list[str] = Field(default_factory=list)
