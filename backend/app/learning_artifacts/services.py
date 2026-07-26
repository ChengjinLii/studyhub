from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import Field, ValidationError

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.domain.hashing import canonical_hash
from app.models.agentic_runtime import AgentArtifactRecord
from app.repos.agentic_artifact_repo import AgentArtifactRepository

from .schemas import LearningArtifact, LearningArtifactType, artifact_identifier, validate_learning_artifact


class ArtifactAcceptanceError(ValueError):
    """A parent runtime attempted to persist an unaccepted artifact candidate."""


class ArtifactReview(DomainModel):
    schema_version: str = "1.0"
    artifact_type: str = Field(min_length=1, max_length=128)
    artifact_id: str = Field(min_length=1, max_length=128)
    accepted: bool
    rationale_summary: str = Field(min_length=1, max_length=2_000)
    candidate_hash: str | None = Field(default=None, max_length=128)
    validation_error_codes: list[str] = Field(default_factory=list, max_length=32)


@dataclass(frozen=True, slots=True)
class AcceptedLearningArtifact:
    """An in-memory handoff from parent acceptance to the persistence boundary."""

    artifact: LearningArtifact
    review: ArtifactReview


class PersistedLearningArtifact(DomainModel):
    schema_version: str = "1.0"
    artifact_ref: ArtifactRef
    created: bool
    review: ArtifactReview


class LearningArtifactService:
    """Parent-owned validation and versioning boundary for sub-agent artifacts.

    Sub-agents produce typed candidates only.  This service is the first place
    where a candidate can become a durable AgentArtifactRecord, after schema
    and provenance checks have succeeded.
    """

    def __init__(self, repository: AgentArtifactRepository | None = None) -> None:
        self.repository = repository or AgentArtifactRepository()

    def review(self, candidate: LearningArtifact | dict[str, object]) -> ArtifactReview:
        try:
            artifact = validate_learning_artifact(candidate)
        except (ValidationError, ValueError):
            return ArtifactReview(
                artifact_type=self._raw_type(candidate),
                artifact_id=self._raw_id(candidate),
                accepted=False,
                rationale_summary="Artifact candidate failed strict schema or provenance validation.",
                validation_error_codes=["invalid_artifact"],
            )
        payload_hash = canonical_hash(artifact)
        return ArtifactReview(
            artifact_type=artifact.artifact_type.value,
            artifact_id=artifact_identifier(artifact),
            accepted=True,
            rationale_summary="Artifact candidate is schema-valid and evidence-provenanced for parent acceptance.",
            candidate_hash=payload_hash,
        )

    def accept(self, candidate: LearningArtifact | dict[str, object]) -> AcceptedLearningArtifact:
        try:
            artifact = validate_learning_artifact(candidate)
        except (ValidationError, ValueError) as exc:
            raise ArtifactAcceptanceError("artifact candidate was rejected") from exc
        review = self.review(artifact)
        if not review.accepted:
            raise ArtifactAcceptanceError("artifact candidate was rejected")
        return AcceptedLearningArtifact(artifact=artifact, review=review)

    def persist(
        self,
        session: Any,
        accepted: AcceptedLearningArtifact,
        *,
        thread_id: str,
        admin_actor_id: int,
        artifact_key: str,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> PersistedLearningArtifact:
        if not accepted.review.accepted:
            raise ArtifactAcceptanceError("artifact must be accepted before persistence")
        if accepted.review.candidate_hash != canonical_hash(accepted.artifact):
            raise ArtifactAcceptanceError("accepted artifact payload no longer matches its reviewed hash")
        record, created = self.repository.create_next_version(
            session,
            thread_id=thread_id,
            admin_actor_id=admin_actor_id,
            artifact_type=accepted.artifact.artifact_type.value,
            artifact_key=artifact_key,
            content=accepted.artifact.model_dump(mode="json"),
            run_id=run_id,
            schema_version=accepted.artifact.schema_version,
            content_hash=accepted.review.candidate_hash,
            media_type="application/json",
            idempotency_key=idempotency_key,
        )
        if not created and record.content_hash != accepted.review.candidate_hash:
            raise ArtifactAcceptanceError("idempotency key already belongs to a different accepted artifact payload")
        return PersistedLearningArtifact(
            artifact_ref=self._reference_for_record(record, accepted.artifact.artifact_type),
            created=created,
            review=accepted.review,
        )

    @staticmethod
    def _reference_for_record(record: AgentArtifactRecord, artifact_type: LearningArtifactType) -> ArtifactRef:
        kind = ArtifactKind(artifact_type.value)
        return ArtifactRef(
            artifact_id=record.id,
            artifact_type=kind,
            version=record.version,
            uri=record.external_uri or f"artifact://agentic/{record.id}/v{record.version}",
            content_hash=record.content_hash,
            media_type=record.media_type or "application/json",
            summary=f"Validated {artifact_type.value} version {record.version}",
        )

    @staticmethod
    def _raw_type(candidate: object) -> str:
        if isinstance(candidate, dict):
            value = candidate.get("artifact_type")
            if isinstance(value, str) and value.strip():
                return value[:128]
        return "unknown"

    @staticmethod
    def _raw_id(candidate: object) -> str:
        if isinstance(candidate, dict):
            for field_name in ("plan_id", "practice_set_id", "analysis_id", "brief_id"):
                value = candidate.get(field_name)
                if isinstance(value, str) and value.strip():
                    return value[:128]
        return "unidentified"
