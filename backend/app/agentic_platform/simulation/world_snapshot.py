"""Frozen StudyHub world data used by deterministic snapshot rollouts.

The existing ``EnvironmentSnapshot`` captures Agent state.  This module adds a
separate, artifact-first snapshot of the *world* that a policy can query: a
time-split catalog, bounded PDF-page index, frozen permissions, and retriever
metadata.  No signed/download URL, future interaction, or live service handle
is present in the contract.
"""

from __future__ import annotations

import copy
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.artifact import ArtifactRef
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.state import AgentTaskState

from .clock import ClockState
from .snapshot import EnvironmentKind, EnvironmentSnapshot


class CatalogSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class SnapshotDataLeakageError(ValueError):
    """The requested snapshot would expose future or restricted live data."""


class SnapshotArtifactNotFoundError(LookupError):
    pass


class SnapshotMaterial(DomainModel):
    """Sanitized catalog row with only fields allowed in offline rollouts."""

    schema_version: str = "1.0"
    material_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    is_free: bool = True
    school: str | None = Field(default=None, max_length=120)
    college: str | None = Field(default=None, max_length=120)
    major: str | None = Field(default=None, max_length=255)
    course_category: str | None = Field(default=None, max_length=32)
    rating_avg: float = Field(default=0.0, ge=0.0)
    rating_count: int = Field(default=0, ge=0)
    download_count: int = Field(default=0, ge=0)
    quality_signals: list[str] = Field(default_factory=list, max_length=8)
    risk_signals: list[str] = Field(default_factory=list, max_length=8)
    observed_at: datetime

    @field_validator(
        "title",
        "description",
        "school",
        "college",
        "major",
        "course_category",
    )
    @classmethod
    def reject_blank_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("tags", "quality_signals", "risk_signals")
    @classmethod
    def validate_unique_terms(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("snapshot terms must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("snapshot terms must be unique")
        return values

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("snapshot observed_at must include a timezone")
        return value.astimezone(UTC)


class SnapshotCatalog(DomainModel):
    schema_version: str = "1.0"
    split: CatalogSplit
    items: list[SnapshotMaterial] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_material_ids(self) -> "SnapshotCatalog":
        ids = [item.material_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("snapshot catalog material IDs must be unique")
        return self


class SnapshotPdfPage(DomainModel):
    """Bounded page-level evidence index, never a raw PDF or signed URL."""

    schema_version: str = "1.0"
    material_id: int = Field(gt=0)
    page: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=120)
    excerpt: str | None = Field(default=None, max_length=700)
    question_types: list[str] = Field(default_factory=list, max_length=8)
    question_numbers: list[str] = Field(default_factory=list, max_length=12)
    source_type: str = Field(default="snapshot_pdf", min_length=1, max_length=64)
    solution_signals: list[str] = Field(default_factory=list, max_length=8)
    anchor_terms: list[str] = Field(default_factory=list, max_length=12)
    corrupt: bool = False

    @field_validator("title", "excerpt", "source_type")
    @classmethod
    def reject_blank_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_corruption_contract(self) -> "SnapshotPdfPage":
        if not self.corrupt and self.excerpt is None:
            raise ValueError("non-corrupt PDF pages require a bounded excerpt")
        return self


class SnapshotPdfPageIndex(DomainModel):
    schema_version: str = "1.0"
    pages: list[SnapshotPdfPage] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_pages(self) -> "SnapshotPdfPageIndex":
        keys = [(item.material_id, item.page) for item in self.pages]
        if len(keys) != len(set(keys)):
            raise ValueError("snapshot PDF page index must not duplicate material/page pairs")
        return self


class SnapshotPermissionRecord(DomainModel):
    schema_version: str = "1.0"
    material_id: int = Field(gt=0)
    allowed: bool
    reason_code: str = Field(default="snapshot_acl", min_length=1, max_length=128)

    @field_validator("reason_code")
    @classmethod
    def reject_blank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class SnapshotPermissionState(DomainModel):
    schema_version: str = "1.0"
    records: list[SnapshotPermissionRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_material_ids(self) -> "SnapshotPermissionState":
        ids = [item.material_id for item in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("permission records must be unique per material")
        return self


class SnapshotRetrieverEntry(DomainModel):
    schema_version: str = "1.0"
    material_id: int = Field(gt=0)
    terms: list[str] = Field(default_factory=list, max_length=48)

    @field_validator("terms")
    @classmethod
    def validate_terms(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("retriever terms must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("retriever terms must be unique")
        return values


class SnapshotRetrieverIndex(DomainModel):
    schema_version: str = "1.0"
    retriever_version: str = Field(min_length=1, max_length=128)
    entries: list[SnapshotRetrieverEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_material_ids(self) -> "SnapshotRetrieverIndex":
        ids = [item.material_id for item in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("retriever entries must be unique per material")
        return self


class WorldSnapshotArtifactStore(Protocol):
    def put_json(self, *, artifact_type: str, payload: object, summary: str) -> ArtifactRef:
        ...

    def get_json(self, reference: ArtifactRef) -> object:
        ...


class InMemoryWorldSnapshotArtifactStore:
    """Deterministic artifact adapter for fixtures and offline snapshot builds."""

    def __init__(self) -> None:
        self.payloads: dict[str, object] = {}

    def put_json(self, *, artifact_type: str, payload: object, summary: str) -> ArtifactRef:
        if not artifact_type.strip():
            raise ValueError("snapshot artifact type must not be blank")
        _assert_no_leakage(payload)
        content_hash = canonical_hash(payload, exclude_fields=())
        artifact_id = f"snapshot_artifact_{canonical_hash({'type': artifact_type, 'payload': payload}, exclude_fields=())[:40]}"
        self.payloads.setdefault(artifact_id, copy.deepcopy(payload))
        return ArtifactRef(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            version=1,
            uri=f"snapshot://artifact/{artifact_id}/v1",
            content_hash=content_hash,
            media_type="application/json",
            summary=summary[:1_024],
        )

    def get_json(self, reference: ArtifactRef) -> object:
        try:
            payload = self.payloads[reference.artifact_id]
        except KeyError as exc:
            raise SnapshotArtifactNotFoundError(reference.artifact_id) from exc
        if reference.content_hash != canonical_hash(payload, exclude_fields=()):
            raise SnapshotDataLeakageError("snapshot_artifact_hash_mismatch")
        return copy.deepcopy(payload)


class StudyHubWorldSnapshot(DomainModel):
    """Artifact-first frozen input to dynamic offline Agent execution."""

    schema_version: str = "1.0"
    snapshot_id: str = Field(min_length=1, max_length=128)
    catalog_ref: ArtifactRef
    pdf_page_index_ref: ArtifactRef
    permission_snapshot_ref: ArtifactRef
    retriever_snapshot_ref: ArtifactRef
    learner_state_ref: ArtifactRef | None = None
    user_simulator_state_ref: ArtifactRef | None = None
    clock_state: ClockState
    random_seed: int = Field(ge=0)
    source_commit_sha: str = Field(min_length=1, max_length=128)
    catalog_split: CatalogSplit
    catalog_cutoff_at: datetime
    snapshot_hash: str = Field(min_length=64, max_length=64)

    @field_validator("snapshot_id", "source_commit_sha", "snapshot_hash")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("catalog_cutoff_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("catalog cutoff must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_snapshot_hash_and_refs(self) -> "StudyHubWorldSnapshot":
        references = [
            self.catalog_ref,
            self.pdf_page_index_ref,
            self.permission_snapshot_ref,
            self.retriever_snapshot_ref,
            *([self.learner_state_ref] if self.learner_state_ref else []),
            *([self.user_simulator_state_ref] if self.user_simulator_state_ref else []),
        ]
        keys = [(item.artifact_id, item.version) for item in references]
        if len(keys) != len(set(keys)):
            raise ValueError("world snapshot artifact refs must be unique")
        if self.snapshot_hash != self.content_hash():
            raise ValueError("world snapshot hash does not match its content")
        return self

    @classmethod
    def create(
        cls,
        *,
        catalog_ref: ArtifactRef,
        pdf_page_index_ref: ArtifactRef,
        permission_snapshot_ref: ArtifactRef,
        retriever_snapshot_ref: ArtifactRef,
        learner_state_ref: ArtifactRef | None,
        user_simulator_state_ref: ArtifactRef | None,
        clock_state: ClockState,
        random_seed: int,
        source_commit_sha: str,
        catalog_split: CatalogSplit,
        catalog_cutoff_at: datetime,
        snapshot_id: str | None = None,
    ) -> "StudyHubWorldSnapshot":
        payload = {
            "schema_version": "1.0",
            "catalog_ref": catalog_ref,
            "pdf_page_index_ref": pdf_page_index_ref,
            "permission_snapshot_ref": permission_snapshot_ref,
            "retriever_snapshot_ref": retriever_snapshot_ref,
            "learner_state_ref": learner_state_ref,
            "user_simulator_state_ref": user_simulator_state_ref,
            "clock_state": clock_state,
            "random_seed": random_seed,
            "source_commit_sha": source_commit_sha,
            "catalog_split": catalog_split.value,
            "catalog_cutoff_at": catalog_cutoff_at,
        }
        resolved_id = snapshot_id or f"world_snapshot_{canonical_hash(payload, exclude_fields=())[:40]}"
        return cls(
            snapshot_id=resolved_id,
            **payload,
            snapshot_hash=canonical_hash({"snapshot_id": resolved_id, **payload}, exclude_fields=()),
        )

    def content_hash(self) -> str:
        return canonical_hash(
            {
                "snapshot_id": self.snapshot_id,
                "schema_version": self.schema_version,
                "catalog_ref": self.catalog_ref,
                "pdf_page_index_ref": self.pdf_page_index_ref,
                "permission_snapshot_ref": self.permission_snapshot_ref,
                "retriever_snapshot_ref": self.retriever_snapshot_ref,
                "learner_state_ref": self.learner_state_ref,
                "user_simulator_state_ref": self.user_simulator_state_ref,
                "clock_state": self.clock_state,
                "random_seed": self.random_seed,
                "source_commit_sha": self.source_commit_sha,
                "catalog_split": self.catalog_split.value,
                "catalog_cutoff_at": self.catalog_cutoff_at,
            },
            exclude_fields=(),
        )

    def as_environment_snapshot(self, task_state: AgentTaskState, *, turn_index: int = 0) -> EnvironmentSnapshot:
        """Bridge world data into the pre-existing open environment protocol."""

        return EnvironmentSnapshot.capture(
            task_state,
            environment_kind=EnvironmentKind.SNAPSHOT,
            source="studyhub_world_snapshot",
            artifact_refs=[
                self.catalog_ref,
                self.pdf_page_index_ref,
                self.permission_snapshot_ref,
                self.retriever_snapshot_ref,
                *([self.learner_state_ref] if self.learner_state_ref else []),
                *([self.user_simulator_state_ref] if self.user_simulator_state_ref else []),
            ],
            metadata={
                "world_snapshot_id": self.snapshot_id,
                "world_snapshot_hash": self.snapshot_hash,
                "catalog_split": self.catalog_split.value,
                "random_seed": self.random_seed,
            },
            turn_index=turn_index,
        )


class ResolvedStudyHubWorld(DomainModel):
    """Validated immutable payloads resolved from a world snapshot's refs."""

    schema_version: str = "1.0"
    snapshot: StudyHubWorldSnapshot
    catalog: SnapshotCatalog
    pdf_page_index: SnapshotPdfPageIndex
    permissions: SnapshotPermissionState
    retriever: SnapshotRetrieverIndex
    learner_state: object | None = None
    user_simulator_state: object | None = None

    @classmethod
    def resolve(
        cls,
        snapshot: StudyHubWorldSnapshot,
        artifact_store: WorldSnapshotArtifactStore,
    ) -> "ResolvedStudyHubWorld":
        catalog = SnapshotCatalog.model_validate(artifact_store.get_json(snapshot.catalog_ref))
        pages = SnapshotPdfPageIndex.model_validate(artifact_store.get_json(snapshot.pdf_page_index_ref))
        permissions = SnapshotPermissionState.model_validate(artifact_store.get_json(snapshot.permission_snapshot_ref))
        retriever = SnapshotRetrieverIndex.model_validate(artifact_store.get_json(snapshot.retriever_snapshot_ref))
        known_ids = {item.material_id for item in catalog.items}
        if catalog.split != snapshot.catalog_split:
            raise SnapshotDataLeakageError("catalog_split_mismatch")
        if any(item.observed_at > snapshot.catalog_cutoff_at for item in catalog.items):
            raise SnapshotDataLeakageError("catalog_contains_future_entry")
        if {item.material_id for item in permissions.records} != known_ids:
            raise SnapshotDataLeakageError("permission_snapshot_incomplete")
        for collection in (pages.pages, permissions.records, retriever.entries):
            if any(item.material_id not in known_ids for item in collection):
                raise SnapshotDataLeakageError("snapshot_references_material_outside_catalog")
        learner = artifact_store.get_json(snapshot.learner_state_ref) if snapshot.learner_state_ref else None
        simulator = artifact_store.get_json(snapshot.user_simulator_state_ref) if snapshot.user_simulator_state_ref else None
        _assert_no_leakage(learner)
        _assert_no_leakage(simulator)
        return cls(
            snapshot=snapshot.model_copy(deep=True),
            catalog=catalog,
            pdf_page_index=pages,
            permissions=permissions,
            retriever=retriever,
            learner_state=learner,
            user_simulator_state=simulator,
        )


class StudyHubWorldSnapshotBuilder:
    """Build a safe world snapshot after validating temporal/ACL boundaries."""

    def __init__(self, artifact_store: WorldSnapshotArtifactStore) -> None:
        self.artifact_store = artifact_store

    def build(
        self,
        *,
        catalog: SnapshotCatalog,
        pdf_page_index: SnapshotPdfPageIndex,
        permissions: SnapshotPermissionState,
        retriever: SnapshotRetrieverIndex,
        clock_state: ClockState,
        random_seed: int,
        source_commit_sha: str,
        catalog_cutoff_at: datetime,
        learner_state: object | None = None,
        user_simulator_state: object | None = None,
        snapshot_id: str | None = None,
    ) -> StudyHubWorldSnapshot:
        if catalog_cutoff_at.tzinfo is None:
            raise SnapshotDataLeakageError("catalog_cutoff_timezone_missing")
        cutoff = catalog_cutoff_at.astimezone(UTC)
        if any(item.observed_at > cutoff for item in catalog.items):
            raise SnapshotDataLeakageError("catalog_contains_future_entry")
        raw_payloads = [catalog, pdf_page_index, permissions, retriever, learner_state, user_simulator_state]
        for payload in raw_payloads:
            _assert_no_leakage(payload)
        catalog_ref = self.artifact_store.put_json(
            artifact_type="snapshot_catalog",
            payload=catalog.model_dump(mode="json"),
            summary=f"Frozen {catalog.split.value} StudyHub catalog",
        )
        page_ref = self.artifact_store.put_json(
            artifact_type="snapshot_pdf_page_index",
            payload=pdf_page_index.model_dump(mode="json"),
            summary="Frozen bounded PDF page evidence index",
        )
        permission_ref = self.artifact_store.put_json(
            artifact_type="snapshot_permissions",
            payload=permissions.model_dump(mode="json"),
            summary="Frozen material permission state",
        )
        retriever_ref = self.artifact_store.put_json(
            artifact_type="snapshot_retriever",
            payload=retriever.model_dump(mode="json"),
            summary=f"Frozen retriever index {retriever.retriever_version}",
        )
        learner_ref = (
            self.artifact_store.put_json(
                artifact_type="snapshot_learner_state",
                payload=learner_state,
                summary="Frozen sanitized learner state",
            )
            if learner_state is not None
            else None
        )
        simulator_ref = (
            self.artifact_store.put_json(
                artifact_type="snapshot_user_simulator_state",
                payload=user_simulator_state,
                summary="Frozen synthetic user simulator state",
            )
            if user_simulator_state is not None
            else None
        )
        return StudyHubWorldSnapshot.create(
            catalog_ref=catalog_ref,
            pdf_page_index_ref=page_ref,
            permission_snapshot_ref=permission_ref,
            retriever_snapshot_ref=retriever_ref,
            learner_state_ref=learner_ref,
            user_simulator_state_ref=simulator_ref,
            clock_state=clock_state,
            random_seed=random_seed,
            source_commit_sha=source_commit_sha,
            catalog_split=catalog.split,
            catalog_cutoff_at=cutoff,
            snapshot_id=snapshot_id,
        )


_FORBIDDEN_SNAPSHOT_KEY_PARTS = frozenset(
    {
        "download_url",
        "signed_url",
        "presigned_url",
        "restricted_download_url",
        "asset_url",
        "future_interactions",
        "future_hotness",
        "api_key",
        "access_token",
        "authorization",
        "cookie",
        "password",
        "secret",
    }
)
_FORBIDDEN_KEY_NORMALIZER = re.compile(r"[^a-z0-9]+")


def _assert_no_leakage(payload: object) -> None:
    """Reject known secret/future/download fields before artifact persistence."""

    if payload is None:
        return
    if isinstance(payload, DomainModel):
        payload = payload.model_dump(mode="python")
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = _FORBIDDEN_KEY_NORMALIZER.sub("_", str(key).lower()).strip("_")
            if normalized in _FORBIDDEN_SNAPSHOT_KEY_PARTS:
                raise SnapshotDataLeakageError(f"snapshot_forbidden_field:{normalized}")
            _assert_no_leakage(value)
    elif isinstance(payload, (list, tuple, set, frozenset)):
        for item in payload:
            _assert_no_leakage(item)
