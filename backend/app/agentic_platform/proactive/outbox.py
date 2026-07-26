from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agentic_runtime import AgentOutboxRecord, AgentOutboxStatus


MAX_OUTBOX_PAYLOAD_BYTES = 16 * 1024


class AgentOutboxNotFoundError(LookupError):
    pass


class AgentOutboxIdempotencyConflictError(ValueError):
    pass


class AgentOutboxLeaseLostError(RuntimeError):
    pass


def _new_id() -> str:
    return f"outbox_{uuid4().hex}"


def _require_nonblank(name: str, value: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value


def _serialize_payload(payload: object) -> str:
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(rendered.encode("utf-8")) > MAX_OUTBOX_PAYLOAD_BYTES:
        raise ValueError("proactive outbox payload exceeds 16 KiB")
    return rendered


class AgentOutboxRepository:
    """Portable transactional-outbox repository with reclaimable leases."""

    def enqueue(
        self,
        session: Session,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        admin_actor_id: int,
        payload: object,
        idempotency_key: str,
        max_attempts: int,
        available_at: datetime | None = None,
    ) -> tuple[AgentOutboxRecord, bool]:
        for name, value in (
            ("event_type", event_type),
            ("aggregate_type", aggregate_type),
            ("aggregate_id", aggregate_id),
            ("idempotency_key", idempotency_key),
        ):
            _require_nonblank(name, value)
        if admin_actor_id <= 0:
            raise ValueError("admin_actor_id must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        existing = self.find_by_idempotency_key(session, idempotency_key=idempotency_key)
        if existing is not None:
            self._assert_same_event_request(existing, event_type, aggregate_type, aggregate_id, admin_actor_id)
            return existing, False
        record = AgentOutboxRecord(
            id=_new_id(),
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            admin_actor_id=admin_actor_id,
            payload_json=_serialize_payload(payload),
            idempotency_key=idempotency_key,
            available_at=available_at,
            max_attempts=max_attempts,
            status=AgentOutboxStatus.PENDING.value,
        )
        try:
            with session.begin_nested():
                session.add(record)
                session.flush()
            return record, True
        except IntegrityError as exc:
            existing = self.find_by_idempotency_key(session, idempotency_key=idempotency_key)
            if existing is None:
                raise exc
            self._assert_same_event_request(existing, event_type, aggregate_type, aggregate_id, admin_actor_id)
            return existing, False

    def get(self, session: Session, event_id: str) -> AgentOutboxRecord | None:
        return session.get(AgentOutboxRecord, event_id)

    def require(self, session: Session, event_id: str) -> AgentOutboxRecord:
        record = self.get(session, event_id)
        if record is None:
            raise AgentOutboxNotFoundError(f"agent outbox event not found: {event_id}")
        return record

    def find_by_idempotency_key(self, session: Session, *, idempotency_key: str) -> AgentOutboxRecord | None:
        return session.scalar(select(AgentOutboxRecord).where(AgentOutboxRecord.idempotency_key == idempotency_key))

    def decode_payload(self, record: AgentOutboxRecord) -> object:
        if not record.payload_json:
            return {}
        try:
            return json.loads(record.payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("proactive outbox payload is invalid JSON") from exc

    def claim_next(
        self,
        session: Session,
        *,
        claimed_by: str,
        claim_ttl_seconds: int,
        now: datetime | None = None,
    ) -> AgentOutboxRecord | None:
        _require_nonblank("claimed_by", claimed_by)
        if claim_ttl_seconds <= 0:
            raise ValueError("claim_ttl_seconds must be positive")
        claimed_now = now or datetime.now(UTC)
        stale_before = claimed_now - timedelta(seconds=claim_ttl_seconds)
        due = and_(
            AgentOutboxRecord.status == AgentOutboxStatus.PENDING.value,
            or_(AgentOutboxRecord.available_at.is_(None), AgentOutboxRecord.available_at <= claimed_now),
        )
        stale = and_(
            AgentOutboxRecord.status == AgentOutboxStatus.CLAIMED.value,
            or_(AgentOutboxRecord.claimed_at.is_(None), AgentOutboxRecord.claimed_at <= stale_before),
        )
        candidates = list(
            session.scalars(
                select(AgentOutboxRecord)
                .where(or_(due, stale))
                .order_by(AgentOutboxRecord.available_at.asc(), AgentOutboxRecord.created_at.asc(), AgentOutboxRecord.id.asc())
                .limit(16)
            )
        )
        for candidate in candidates:
            claimable = or_(
                and_(
                    AgentOutboxRecord.status == AgentOutboxStatus.PENDING.value,
                    or_(AgentOutboxRecord.available_at.is_(None), AgentOutboxRecord.available_at <= claimed_now),
                ),
                and_(
                    AgentOutboxRecord.status == AgentOutboxStatus.CLAIMED.value,
                    or_(AgentOutboxRecord.claimed_at.is_(None), AgentOutboxRecord.claimed_at <= stale_before),
                ),
            )
            result = session.execute(
                update(AgentOutboxRecord)
                .where(AgentOutboxRecord.id == candidate.id, claimable)
                .values(
                    status=AgentOutboxStatus.CLAIMED.value,
                    claimed_by=claimed_by,
                    claimed_at=claimed_now,
                    attempts=AgentOutboxRecord.attempts + 1,
                    error_code=None,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount == 1:
                session.expire(candidate)
                claimed = session.get(AgentOutboxRecord, candidate.id)
                if claimed is not None:
                    return claimed
        return None

    def mark_dispatched(self, session: Session, *, event_id: str, claimed_by: str) -> AgentOutboxRecord:
        return self._finish_claimed(
            session,
            event_id=event_id,
            claimed_by=claimed_by,
            target_status=AgentOutboxStatus.DISPATCHED,
            error_code=None,
            available_at=None,
        )

    def retry_or_fail(
        self,
        session: Session,
        *,
        event_id: str,
        claimed_by: str,
        error_code: str,
        retry_at: datetime | None,
        retryable: bool = True,
    ) -> AgentOutboxRecord:
        _require_nonblank("error_code", error_code)
        record = self.require(session, event_id)
        if AgentOutboxStatus(record.status) != AgentOutboxStatus.CLAIMED or record.claimed_by != claimed_by:
            raise AgentOutboxLeaseLostError(f"agent outbox lease was lost: {event_id}")
        target = AgentOutboxStatus.PENDING if retryable and record.attempts < record.max_attempts else AgentOutboxStatus.FAILED
        return self._finish_claimed(
            session,
            event_id=event_id,
            claimed_by=claimed_by,
            target_status=target,
            error_code=error_code,
            available_at=retry_at if target == AgentOutboxStatus.PENDING else None,
        )

    def _finish_claimed(
        self,
        session: Session,
        *,
        event_id: str,
        claimed_by: str,
        target_status: AgentOutboxStatus,
        error_code: str | None,
        available_at: datetime | None,
    ) -> AgentOutboxRecord:
        _require_nonblank("claimed_by", claimed_by)
        record = self.require(session, event_id)
        dispatched_at = datetime.now(UTC) if target_status == AgentOutboxStatus.DISPATCHED else None
        result = session.execute(
            update(AgentOutboxRecord)
            .where(
                AgentOutboxRecord.id == event_id,
                AgentOutboxRecord.status == AgentOutboxStatus.CLAIMED.value,
                AgentOutboxRecord.claimed_by == claimed_by,
            )
            .values(
                status=target_status.value,
                error_code=error_code,
                available_at=available_at,
                claimed_by=None,
                claimed_at=None,
                dispatched_at=dispatched_at,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise AgentOutboxLeaseLostError(f"agent outbox lease was lost: {event_id}")
        session.expire(record)
        refreshed = session.get(AgentOutboxRecord, event_id)
        if refreshed is None:
            raise AgentOutboxNotFoundError(f"agent outbox event not found: {event_id}")
        return refreshed

    @staticmethod
    def _assert_same_event_request(
        existing: AgentOutboxRecord,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        admin_actor_id: int,
    ) -> None:
        if (
            existing.event_type != event_type
            or existing.aggregate_type != aggregate_type
            or existing.aggregate_id != aggregate_id
            or existing.admin_actor_id != admin_actor_id
        ):
            raise AgentOutboxIdempotencyConflictError("outbox idempotency key belongs to another logical event")
