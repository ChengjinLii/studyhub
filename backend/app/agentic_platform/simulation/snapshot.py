"""Durable, hash-checked environment snapshots.

Snapshots contain the typed Agent state and compact references only.  They do
not embed raw model output, full PDF text, or secret-bearing provider state.
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.artifact import ArtifactRef
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.state import AgentTaskState


class EnvironmentKind(StrEnum):
    LIVE = "live"
    SNAPSHOT = "snapshot"
    SIMULATED = "simulated"


SnapshotMetadataValue = str | int | float | bool | None


class EnvironmentSnapshot(DomainModel):
    """A compact, self-verifying capture of a replayable environment state."""

    schema_version: str = "1.0"
    snapshot_id: str = Field(min_length=1, max_length=128)
    environment_kind: EnvironmentKind
    source: str = Field(min_length=1, max_length=128)
    task_state: AgentTaskState
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    metadata: dict[str, SnapshotMetadataValue] = Field(default_factory=dict)
    turn_index: int = Field(default=0, ge=0)
    initial_state_hash: str = Field(min_length=1, max_length=128)
    snapshot_hash: str = Field(min_length=1, max_length=128)
    captured_at: datetime | None = None

    @field_validator("snapshot_id", "source", "initial_state_hash", "snapshot_hash")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("artifact_refs")
    @classmethod
    def validate_unique_artifact_refs(cls, values: list[ArtifactRef]) -> list[ArtifactRef]:
        keys = [(reference.artifact_id, reference.version) for reference in values]
        if len(keys) != len(set(keys)):
            raise ValueError("snapshot artifact references must be unique by artifact ID and version")
        return values

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, metadata: dict[str, SnapshotMetadataValue]) -> dict[str, SnapshotMetadataValue]:
        for key, value in metadata.items():
            if not key.strip():
                raise ValueError("snapshot metadata keys must not be blank")
            if isinstance(value, str) and len(value) > 1_024:
                raise ValueError("snapshot metadata strings must be at most 1024 characters")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("snapshot metadata floats must be finite")
        return metadata

    @model_validator(mode="after")
    def validate_hashes(self) -> "EnvironmentSnapshot":
        if self.initial_state_hash != canonical_hash(self.task_state):
            raise ValueError("environment snapshot initial state hash does not match task state")
        if self.snapshot_hash != self.content_hash():
            raise ValueError("environment snapshot hash does not match snapshot content")
        return self

    @classmethod
    def capture(
        cls,
        task_state: AgentTaskState,
        *,
        environment_kind: EnvironmentKind,
        source: str,
        artifact_refs: list[ArtifactRef] | None = None,
        metadata: dict[str, SnapshotMetadataValue] | None = None,
        turn_index: int = 0,
        snapshot_id: str | None = None,
        captured_at: datetime | None = None,
    ) -> "EnvironmentSnapshot":
        """Create a snapshot whose IDs and hashes are deterministic by content.

        ``captured_at`` is retained for operations but intentionally excluded
        from the content hash, because it does not change the replayable state.
        """

        copied_state = task_state.model_copy(deep=True)
        copied_refs = [reference.model_copy(deep=True) for reference in artifact_refs or []]
        copied_metadata = dict(metadata or {})
        id_payload = {
            "schema_version": "1.0",
            "environment_kind": environment_kind.value,
            "source": source,
            "task_state": copied_state,
            "artifact_refs": copied_refs,
            "metadata": copied_metadata,
            "turn_index": turn_index,
        }
        resolved_snapshot_id = snapshot_id or f"snapshot_{canonical_hash(id_payload)[:40]}"
        hash_payload = {"snapshot_id": resolved_snapshot_id, **id_payload}
        return cls(
            snapshot_id=resolved_snapshot_id,
            environment_kind=environment_kind,
            source=source,
            task_state=copied_state,
            artifact_refs=copied_refs,
            metadata=copied_metadata,
            turn_index=turn_index,
            initial_state_hash=canonical_hash(copied_state),
            snapshot_hash=canonical_hash(hash_payload),
            captured_at=captured_at,
        )

    def content_hash(self) -> str:
        """Hash the replayable payload while deliberately excluding capture time."""

        return canonical_hash(
            {
                "snapshot_id": self.snapshot_id,
                "schema_version": self.schema_version,
                "environment_kind": self.environment_kind.value,
                "source": self.source,
                "task_state": self.task_state,
                "artifact_refs": self.artifact_refs,
                "metadata": self.metadata,
                "turn_index": self.turn_index,
            }
        )
