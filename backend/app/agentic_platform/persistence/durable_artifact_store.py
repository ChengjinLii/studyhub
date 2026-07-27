"""Durable, artifact-first storage for agent execution.

The runtime deliberately stores only compact :class:`ArtifactRef` values in
graph state and transitions.  Small JSON documents live in ``agent_artifacts``
while larger documents are committed to an immutable external blob before the
metadata row is written.  This keeps a retry recoverable without ever placing a
large model response, context, or observation in a shared transition file.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy.orm import Session

from app.agentic_platform.deepresearch.state import DeepResearchState
from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.domain.data_policy import TrainingDataPolicy
from app.agentic_platform.domain.hashing import canonical_hash, canonical_json
from app.agentic_platform.domain.state import AgentTaskState
from app.agentic_platform.policy.context_view import ContextPurpose
from app.models.agentic_runtime import AgentArtifactRecord
from app.repos.agentic_artifact_repo import AgentArtifactRepository, MAX_INLINE_ARTIFACT_JSON_BYTES


SessionFactory = Callable[[], Session]


class DurableArtifactStoreError(RuntimeError):
    """A safe, stable storage failure exposed to the execution worker."""


class ArtifactIdempotencyPayloadConflictError(DurableArtifactStoreError):
    """A retry key was reused with bytes different from its first request."""


class ArtifactBlobStore(Protocol):
    """External immutable blob target used for artifacts above the SQL limit."""

    def put_bytes(self, *, key: str, content: bytes) -> str:
        """Write ``content`` atomically and return a non-public storage URI."""


class LocalFilesystemArtifactBlobStore:
    """Local external artifact store with fsync + atomic rename semantics."""

    provider_name = "local_fs"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def put_bytes(self, *, key: str, content: bytes) -> str:
        target = self._target_for_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        expected_hash = _sha256(content)
        if target.exists():
            if _sha256_file(target) != expected_hash:
                raise DurableArtifactStoreError("artifact_blob_key_collision")
            return target.resolve().as_uri()

        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            # ``replace`` is atomic when both files live in the same directory.
            os.replace(temporary, target)
            _fsync_directory(target.parent)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return target.resolve().as_uri()

    def _target_for_key(self, key: str) -> Path:
        normalized = key.strip().replace("\\", "/").lstrip("/")
        if not normalized or ".." in Path(normalized).parts:
            raise ValueError("artifact blob key is invalid")
        root = self.root.resolve()
        target = (root / normalized).resolve()
        if root not in target.parents:
            raise ValueError("artifact blob key escapes its configured root")
        return target


class OssArtifactBlobStore:
    """OSS adapter that stages bytes locally before uploading an immutable key.

    OSS does not expose a filesystem-style rename.  The content-addressed key
    is therefore uploaded only after a locally fsynced temporary file exists;
    a failed upload never creates the metadata row that would reference it.
    """

    provider_name = "oss"

    def __init__(self, *, provider, staging_root: str | Path) -> None:
        self.provider = provider
        self.staging_root = Path(staging_root)

    def put_bytes(self, *, key: str, content: bytes) -> str:
        self.staging_root.mkdir(parents=True, exist_ok=True)
        temporary = self.staging_root / f".{uuid4().hex}.upload.tmp"
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(self.staging_root)
            # The provider's key builder keeps this namespace separate from
            # material uploads while retaining the configured OSS prefix.
            object_key = self.provider._build_relative_key(self.staging_root, Path(key))  # noqa: SLF001
            with temporary.open("rb") as handle:
                self.provider._bucket().put_object(object_key, handle)  # noqa: SLF001
            bucket = str(self.provider.settings.oss_bucket or "").strip()
            if not bucket:
                raise DurableArtifactStoreError("oss_bucket_missing")
            return f"oss://{bucket}/{object_key}"
        finally:
            temporary.unlink(missing_ok=True)


class DurableArtifactStore:
    """SQL metadata + inline/external JSON adapter for ``AgentTaskState``.

    The object also implements ``RawModelOutputStore``.  Raw outputs remain in
    a restricted artifact and are never copied into model I/O or transition
    payloads.
    """

    schema_version = "1.0"

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        blob_store: ArtifactBlobStore,
        repository: AgentArtifactRepository | None = None,
        inline_max_bytes: int = MAX_INLINE_ARTIFACT_JSON_BYTES,
    ) -> None:
        if inline_max_bytes <= 0 or inline_max_bytes > MAX_INLINE_ARTIFACT_JSON_BYTES:
            raise ValueError("inline_max_bytes must be within the repository inline JSON limit")
        self.session_factory = session_factory
        self.blob_store = blob_store
        self.repository = repository or AgentArtifactRepository()
        self.inline_max_bytes = inline_max_bytes

    async def store_json(
        self,
        state: AgentTaskState,
        *,
        artifact_type: ArtifactKind | str,
        artifact_key: str,
        payload: object,
        summary: str,
        idempotency_key: str,
        data_policy: TrainingDataPolicy | None = None,
    ) -> ArtifactRef:
        return self.store_json_for_owner(
            thread_id=state.thread_id,
            run_id=state.run_id,
            admin_actor_id=state.admin_actor_id,
            artifact_type=artifact_type,
            artifact_key=artifact_key,
            payload=payload,
            summary=summary,
            idempotency_key=idempotency_key,
            data_policy=data_policy,
        )

    async def store(
        self,
        *,
        state: AgentTaskState,
        purpose: ContextPurpose,
        raw_content: str,
        model_id: str,
        prompt_hash: str,
    ) -> ArtifactRef:
        """Persist restricted raw model output without exposing it in events."""

        return await self.store_json(
            state,
            artifact_type=ArtifactKind.RAW_MODEL_OUTPUT,
            artifact_key=f"raw-model-{purpose.value}",
            payload={
                "schema_version": self.schema_version,
                "purpose": purpose.value,
                "model_id": model_id,
                "prompt_hash": prompt_hash,
                "raw_content": raw_content,
            },
            summary=f"Restricted {purpose.value} model output",
            idempotency_key=f"raw-model:{purpose.value}:{prompt_hash}",
        )

    def store_json_for_owner(
        self,
        *,
        thread_id: str,
        run_id: str | None,
        admin_actor_id: int,
        artifact_type: ArtifactKind | str,
        artifact_key: str,
        payload: object,
        summary: str,
        idempotency_key: str,
        data_policy: TrainingDataPolicy | None = None,
    ) -> ArtifactRef:
        """Synchronous implementation shared by main and research adapters."""

        rendered = canonical_json(payload, exclude_fields=())
        content = rendered.encode("utf-8")
        content_hash = _sha256(content)
        artifact_type_value = _artifact_type_value(artifact_type)
        schema_version = _payload_schema_version(payload)
        policy = (data_policy or TrainingDataPolicy.internal_eval_only()).model_copy(deep=True)

        session = self.session_factory()
        try:
            existing = self.repository.find_by_idempotency_key(
                session,
                thread_id=thread_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                self._assert_existing_matches(
                    existing,
                    artifact_type=artifact_type_value,
                    artifact_key=artifact_key,
                    content_hash=content_hash,
                    data_policy=policy,
                )
                return self._reference_for_record(existing, artifact_type=artifact_type, summary=summary)

            external_uri: str | None = None
            inline_content: object | None = payload
            external_content_size_bytes: int | None = None
            if len(content) > self.inline_max_bytes:
                external_uri = self.blob_store.put_bytes(
                    key=self._external_key(
                        thread_id=thread_id,
                        run_id=run_id,
                        idempotency_key=idempotency_key,
                        content_hash=content_hash,
                    ),
                    content=content,
                )
                inline_content = None
                external_content_size_bytes = len(content)

            record, _created = self.repository.create_next_version(
                session,
                thread_id=thread_id,
                run_id=run_id,
                admin_actor_id=admin_actor_id,
                artifact_type=artifact_type_value,
                artifact_key=artifact_key,
                content=inline_content,
                external_uri=external_uri,
                external_content_size_bytes=external_content_size_bytes,
                schema_version=schema_version,
                content_hash=content_hash,
                media_type="application/json",
                idempotency_key=idempotency_key,
                data_policy=policy,
            )
            self._assert_existing_matches(
                record,
                artifact_type=artifact_type_value,
                artifact_key=artifact_key,
                content_hash=content_hash,
                data_policy=policy,
            )
            session.commit()
            return self._reference_for_record(record, artifact_type=artifact_type, summary=summary)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _assert_existing_matches(
        record: AgentArtifactRecord,
        *,
        artifact_type: str,
        artifact_key: str,
        content_hash: str,
        data_policy: TrainingDataPolicy,
    ) -> None:
        if record.artifact_type != artifact_type or record.artifact_key != artifact_key:
            raise ArtifactIdempotencyPayloadConflictError("artifact_idempotency_logical_target_conflict")
        if not record.content_hash or record.content_hash != content_hash:
            raise ArtifactIdempotencyPayloadConflictError("artifact_idempotency_payload_conflict")
        stored_policy = TrainingDataPolicy(
            training_allowed=record.training_allowed,
            sensitivity=record.sensitivity,
            license_class=record.license_class,
            source_scope=record.source_scope,
            contains_personal_data=record.contains_personal_data,
            anonymization_version=record.anonymization_version,
            retention_policy=record.retention_policy,
        )
        if stored_policy != data_policy:
            raise ArtifactIdempotencyPayloadConflictError("artifact_idempotency_data_policy_conflict")

    @staticmethod
    def _reference_for_record(
        record: AgentArtifactRecord,
        *,
        artifact_type: ArtifactKind | str,
        summary: str,
    ) -> ArtifactRef:
        uri = record.external_uri or f"artifact://agentic/{record.id}/v{record.version}"
        return ArtifactRef(
            artifact_id=record.id,
            artifact_type=artifact_type,
            version=record.version,
            uri=uri,
            content_hash=record.content_hash,
            media_type=record.media_type or "application/json",
            summary=summary[:1_024],
        )

    @staticmethod
    def _external_key(*, thread_id: str, run_id: str | None, idempotency_key: str, content_hash: str) -> str:
        # These are hashes rather than user-provided IDs, so an object key is
        # path-safe and cannot disclose a goal/request in a storage listing.
        thread_hash = canonical_hash(thread_id)[:24]
        run_hash = canonical_hash(run_id or "standalone")[:24]
        request_hash = canonical_hash(idempotency_key)[:24]
        return f"agentic-platform/blobs/{thread_hash}/{run_hash}/{content_hash}-{request_hash}.json"


class DurableResearchArtifactStore:
    """Bind the research graph's artifact protocol to a durable parent run."""

    def __init__(
        self,
        backend: DurableArtifactStore,
        *,
        thread_id: str,
        run_id: str,
        admin_actor_id: int,
    ) -> None:
        self.backend = backend
        self.thread_id = thread_id
        self.run_id = run_id
        self.admin_actor_id = admin_actor_id

    async def store_json(
        self,
        state: DeepResearchState,
        *,
        artifact_type: ArtifactKind | str,
        artifact_key: str,
        payload: object,
        summary: str,
        idempotency_key: str,
        data_policy: TrainingDataPolicy | None = None,
    ) -> ArtifactRef:
        if state.task.admin_actor_id != self.admin_actor_id:
            raise DurableArtifactStoreError("research_artifact_owner_mismatch")
        task_hash = canonical_hash(state.task.task_id)[:16]
        return self.backend.store_json_for_owner(
            thread_id=self.thread_id,
            run_id=self.run_id,
            admin_actor_id=self.admin_actor_id,
            artifact_type=artifact_type,
            artifact_key=f"research-{task_hash}-{artifact_key}"[:128],
            payload=payload,
            summary=summary,
            idempotency_key=f"research:{task_hash}:{idempotency_key}"[:128],
            data_policy=data_policy,
        )


class DurableResearchTraceStore:
    """Persist the report trace through the same artifact contract as context."""

    def __init__(self, artifact_store: DurableResearchArtifactStore) -> None:
        self.artifact_store = artifact_store

    async def store(self, state: DeepResearchState, entries: list[object]) -> ArtifactRef:
        payload = [entry.model_dump(mode="json") if hasattr(entry, "model_dump") else entry for entry in entries]
        return await self.artifact_store.store_json(
            state,
            artifact_type=ArtifactKind.OTHER,
            artifact_key="research-trace",
            payload=payload,
            summary=f"Structured DeepResearch trace for task {state.task.task_id}",
            idempotency_key=f"research-trace:{canonical_hash(payload)[:32]}",
        )


def _artifact_type_value(value: ArtifactKind | str) -> str:
    return value.value if isinstance(value, ArtifactKind) else str(value)


def _payload_schema_version(payload: object) -> str:
    if isinstance(payload, dict):
        value = payload.get("schema_version", payload.get("schemaVersion"))
        if isinstance(value, str) and value.strip():
            return value[:64]
    value = getattr(payload, "schema_version", None)
    return value[:64] if isinstance(value, str) and value.strip() else "1.0"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65_536), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    """Persist the directory entry after ``os.replace`` where supported."""

    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
