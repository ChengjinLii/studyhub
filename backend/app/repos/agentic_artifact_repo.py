from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agentic_platform.domain.data_policy import TrainingDataPolicy
from app.models.agentic_runtime import AgentArtifactRecord


MAX_INLINE_ARTIFACT_JSON_BYTES = 64 * 1024


class ArtifactPayloadTooLargeError(ValueError):
    """Raised when an artifact payload should be stored behind an external URI."""


class ArtifactIdempotencyConflictError(ValueError):
    """Raised when a logical idempotency key is reused for different artifacts."""


def _new_id() -> str:
    return f"artifact_{uuid4().hex}"


def _require_nonblank(name: str, value: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value


def serialize_small_json(content: object | None) -> tuple[str | None, int | None]:
    if content is None:
        return None, None
    rendered = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    byte_length = len(rendered.encode("utf-8"))
    if byte_length > MAX_INLINE_ARTIFACT_JSON_BYTES:
        raise ArtifactPayloadTooLargeError(
            f"artifact inline JSON is {byte_length} bytes; use an external URI above {MAX_INLINE_ARTIFACT_JSON_BYTES} bytes"
        )
    return rendered, byte_length


class AgentArtifactRepository:
    """Stores versioned artifact metadata, keeping large bodies outside SQL."""

    def get(self, session: Session, artifact_id: str) -> AgentArtifactRecord | None:
        return session.get(AgentArtifactRecord, artifact_id)

    def get_latest(
        self,
        session: Session,
        *,
        thread_id: str,
        artifact_type: str,
        artifact_key: str,
    ) -> AgentArtifactRecord | None:
        return session.scalar(
            select(AgentArtifactRecord)
            .where(
                AgentArtifactRecord.thread_id == thread_id,
                AgentArtifactRecord.artifact_type == artifact_type,
                AgentArtifactRecord.artifact_key == artifact_key,
            )
            .order_by(AgentArtifactRecord.version.desc())
            .limit(1)
        )

    def find_by_idempotency_key(
        self,
        session: Session,
        *,
        thread_id: str,
        idempotency_key: str,
    ) -> AgentArtifactRecord | None:
        return session.scalar(
            select(AgentArtifactRecord).where(
                AgentArtifactRecord.thread_id == thread_id,
                AgentArtifactRecord.idempotency_key == idempotency_key,
            )
        )

    def create_next_version(
        self,
        session: Session,
        *,
        thread_id: str,
        admin_actor_id: int,
        artifact_type: str,
        artifact_key: str,
        content: object | None = None,
        external_uri: str | None = None,
        run_id: str | None = None,
        schema_version: str = "1.0",
        content_hash: str | None = None,
        media_type: str | None = None,
        idempotency_key: str | None = None,
        artifact_id: str | None = None,
        external_content_size_bytes: int | None = None,
        data_policy: TrainingDataPolicy | None = None,
    ) -> tuple[AgentArtifactRecord, bool]:
        _require_nonblank("thread_id", thread_id)
        _require_nonblank("artifact_type", artifact_type)
        _require_nonblank("artifact_key", artifact_key)
        _require_nonblank("schema_version", schema_version)
        if admin_actor_id <= 0:
            raise ValueError("admin_actor_id must be positive")
        if external_uri is not None:
            _require_nonblank("external_uri", external_uri)
        if external_content_size_bytes is not None and external_content_size_bytes < 0:
            raise ValueError("external_content_size_bytes must not be negative")
        if content is not None and external_content_size_bytes is not None:
            raise ValueError("external_content_size_bytes is only valid for external artifacts")
        if content is None and external_uri is None:
            raise ValueError("an artifact requires small JSON content or an external_uri")
        if content is None and external_uri is not None and external_content_size_bytes is None:
            raise ValueError("external artifacts require external_content_size_bytes")
        policy = (data_policy or TrainingDataPolicy.internal_eval_only()).model_copy(deep=True)
        content_json, content_size_bytes = serialize_small_json(content)
        if content is None:
            content_size_bytes = external_content_size_bytes

        if idempotency_key is not None:
            _require_nonblank("idempotency_key", idempotency_key)
            existing = self.find_by_idempotency_key(session, thread_id=thread_id, idempotency_key=idempotency_key)
            if existing is not None:
                self._assert_same_artifact_request(existing, artifact_type, artifact_key)
                return existing, False

        for _attempt in range(3):
            version = self._next_version(session, thread_id=thread_id, artifact_type=artifact_type, artifact_key=artifact_key)
            record = AgentArtifactRecord(
                id=artifact_id or _new_id(),
                thread_id=thread_id,
                run_id=run_id,
                admin_actor_id=admin_actor_id,
                artifact_type=artifact_type,
                artifact_key=artifact_key,
                version=version,
                schema_version=schema_version,
                content_json=content_json,
                external_uri=external_uri,
                content_hash=content_hash,
                media_type=media_type,
                content_size_bytes=content_size_bytes,
                idempotency_key=idempotency_key,
                training_allowed=policy.training_allowed,
                sensitivity=policy.sensitivity.value,
                license_class=policy.license_class.value,
                source_scope=policy.source_scope.value,
                contains_personal_data=policy.contains_personal_data,
                anonymization_version=policy.anonymization_version,
                retention_policy=policy.retention_policy,
            )
            try:
                with session.begin_nested():
                    session.add(record)
                    session.flush()
                return record, True
            except IntegrityError as exc:
                if idempotency_key is not None:
                    existing = self.find_by_idempotency_key(session, thread_id=thread_id, idempotency_key=idempotency_key)
                    if existing is not None:
                        self._assert_same_artifact_request(existing, artifact_type, artifact_key)
                        return existing, False
                if _attempt == 2:
                    raise exc
        raise RuntimeError("unreachable artifact version retry state")

    def decode_content(self, record: AgentArtifactRecord) -> object | None:
        return json.loads(record.content_json) if record.content_json is not None else None

    @staticmethod
    def _assert_same_artifact_request(
        existing: AgentArtifactRecord,
        artifact_type: str,
        artifact_key: str,
    ) -> None:
        if existing.artifact_type != artifact_type or existing.artifact_key != artifact_key:
            raise ArtifactIdempotencyConflictError("artifact idempotency key belongs to another logical artifact")

    @staticmethod
    def _next_version(
        session: Session,
        *,
        thread_id: str,
        artifact_type: str,
        artifact_key: str,
    ) -> int:
        current = session.scalar(
            select(func.max(AgentArtifactRecord.version)).where(
                AgentArtifactRecord.thread_id == thread_id,
                AgentArtifactRecord.artifact_type == artifact_type,
                AgentArtifactRecord.artifact_key == artifact_key,
            )
        )
        return int(current or 0) + 1
