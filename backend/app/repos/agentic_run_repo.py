from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agentic_platform.persistence.state_machine import (
    InvalidStatusTransition,
    assert_run_status_transition,
    assert_step_status_transition,
)
from app.models.agentic_runtime import (
    AgentJobRecord,
    AgentJobStatus,
    AgentRunRecord,
    AgentRunStatus,
    AgentStepRecord,
    AgentStepStatus,
    AgentThreadRecord,
    AgentThreadStatus,
    AgentWaitRecord,
    AgentWaitStatus,
)


class AgentRuntimeNotFoundError(LookupError):
    """Raised when a requested durable agent-runtime record does not exist."""


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused for a different logical action."""


class AgentJobLeaseLostError(RuntimeError):
    """A stale worker attempted to update a job reclaimed by another worker."""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _require_nonblank(name: str, value: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value


def _json_dumps(payload: object | None) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class AgentRunRepository:
    """Repository for durable thread/run/step/wait/job metadata.

    The repository deliberately stores status values as strings in SQL so the
    tables remain portable between SQLite and MySQL; transitions are validated
    before every update by the domain-owned state machines.
    """

    def create_thread(
        self,
        session: Session,
        *,
        admin_actor_id: int,
        user_id: int | None = None,
        title: str | None = None,
        thread_id: str | None = None,
    ) -> AgentThreadRecord:
        if admin_actor_id <= 0:
            raise ValueError("admin_actor_id must be positive")
        if user_id is not None and user_id <= 0:
            raise ValueError("user_id must be positive when provided")
        if title is not None:
            _require_nonblank("title", title)
        record = AgentThreadRecord(
            id=thread_id or _new_id("thread"),
            admin_actor_id=admin_actor_id,
            user_id=user_id,
            title=title,
            status=AgentThreadStatus.ACTIVE.value,
        )
        session.add(record)
        session.flush()
        return record

    def create_or_get_thread(
        self,
        session: Session,
        *,
        admin_actor_id: int,
        user_id: int | None = None,
        title: str | None = None,
        thread_id: str,
    ) -> tuple[AgentThreadRecord, bool]:
        """Create a stable worker-owned thread once, including after a crash.

        Proactive dispatchers derive ``thread_id`` from the durable outbox ID.
        A duplicate delivery can therefore resume the same thread instead of
        manufacturing a second logical run.
        """

        _require_nonblank("thread_id", thread_id)
        existing = self.get_thread(session, thread_id)
        if existing is not None:
            self._assert_same_thread_request(existing, admin_actor_id=admin_actor_id, user_id=user_id)
            return existing, False
        try:
            with session.begin_nested():
                record = self.create_thread(
                    session,
                    admin_actor_id=admin_actor_id,
                    user_id=user_id,
                    title=title,
                    thread_id=thread_id,
                )
            return record, True
        except IntegrityError as exc:
            existing = self.get_thread(session, thread_id)
            if existing is None:
                raise exc
            self._assert_same_thread_request(existing, admin_actor_id=admin_actor_id, user_id=user_id)
            return existing, False

    def get_thread(self, session: Session, thread_id: str) -> AgentThreadRecord | None:
        return session.get(AgentThreadRecord, thread_id)

    def require_thread(self, session: Session, thread_id: str) -> AgentThreadRecord:
        record = self.get_thread(session, thread_id)
        if record is None:
            raise AgentRuntimeNotFoundError(f"agent thread not found: {thread_id}")
        return record

    def create_or_get_run(
        self,
        session: Session,
        *,
        thread_id: str,
        admin_actor_id: int,
        user_id: int | None,
        trigger_type: str,
        runtime_version: str,
        policy_version: str,
        environment_snapshot_id: str,
        idempotency_key: str | None = None,
        trigger_ref: str | None = None,
        checkpoint_ref: str | None = None,
        run_id: str | None = None,
    ) -> tuple[AgentRunRecord, bool]:
        _require_nonblank("thread_id", thread_id)
        _require_nonblank("trigger_type", trigger_type)
        _require_nonblank("runtime_version", runtime_version)
        _require_nonblank("policy_version", policy_version)
        _require_nonblank("environment_snapshot_id", environment_snapshot_id)
        if admin_actor_id <= 0:
            raise ValueError("admin_actor_id must be positive")
        if user_id is not None and user_id <= 0:
            raise ValueError("user_id must be positive when provided")
        if idempotency_key is not None:
            _require_nonblank("idempotency_key", idempotency_key)
            existing = self.find_run_by_idempotency_key(session, idempotency_key)
            if existing is not None:
                self._assert_same_run_request(existing, thread_id, admin_actor_id, trigger_type)
                return existing, False

        thread = self.require_thread(session, thread_id)
        if thread.admin_actor_id != admin_actor_id:
            raise ValueError("run admin_actor_id must match its thread")
        if thread.user_id != user_id:
            raise ValueError("run user_id must match its thread")

        record = AgentRunRecord(
            id=run_id or _new_id("run"),
            thread_id=thread_id,
            admin_actor_id=admin_actor_id,
            user_id=user_id,
            trigger_type=trigger_type,
            trigger_ref=trigger_ref,
            runtime_version=runtime_version,
            policy_version=policy_version,
            environment_snapshot_id=environment_snapshot_id,
            checkpoint_ref=checkpoint_ref,
            idempotency_key=idempotency_key,
            status=AgentRunStatus.CREATED.value,
        )
        try:
            with session.begin_nested():
                session.add(record)
                session.flush()
        except IntegrityError as exc:
            if idempotency_key is None:
                raise
            existing = self.find_run_by_idempotency_key(session, idempotency_key)
            if existing is None:
                raise exc
            self._assert_same_run_request(existing, thread_id, admin_actor_id, trigger_type)
            return existing, False

        thread.latest_run_id = record.id
        session.flush()
        return record, True

    def get_run(self, session: Session, run_id: str) -> AgentRunRecord | None:
        return session.get(AgentRunRecord, run_id)

    def require_run(self, session: Session, run_id: str) -> AgentRunRecord:
        record = self.get_run(session, run_id)
        if record is None:
            raise AgentRuntimeNotFoundError(f"agent run not found: {run_id}")
        return record

    def find_run_by_idempotency_key(self, session: Session, idempotency_key: str) -> AgentRunRecord | None:
        return session.scalar(select(AgentRunRecord).where(AgentRunRecord.idempotency_key == idempotency_key))

    def transition_run_status(
        self,
        session: Session,
        *,
        run_id: str,
        target_status: AgentRunStatus | str,
        terminal_reason: str | None = None,
    ) -> AgentRunRecord:
        record = self.require_run(session, run_id)
        target = AgentRunStatus(target_status)
        assert_run_status_transition(record.status, target)
        now = datetime.now(UTC)
        record.status = target.value
        if target == AgentRunStatus.RUNNING and record.started_at is None:
            record.started_at = now
        if target in {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}:
            record.completed_at = now
            record.terminal_reason = terminal_reason
        session.flush()
        return record

    def save_run_checkpoint(
        self,
        session: Session,
        *,
        run_id: str,
        checkpoint_ref: str,
        state_hash: str,
    ) -> AgentRunRecord:
        _require_nonblank("checkpoint_ref", checkpoint_ref)
        _require_nonblank("state_hash", state_hash)
        record = self.require_run(session, run_id)
        record.checkpoint_ref = checkpoint_ref
        record.state_hash = state_hash
        session.flush()
        return record

    def set_current_step(self, session: Session, *, run_id: str, step_id: str | None) -> AgentRunRecord:
        record = self.require_run(session, run_id)
        if step_id is not None:
            _require_nonblank("step_id", step_id)
            step = session.get(AgentStepRecord, step_id)
            if step is None or step.run_id != run_id:
                raise AgentRuntimeNotFoundError(f"agent step does not belong to run: {step_id}")
        record.current_step_id = step_id
        session.flush()
        return record

    def create_or_get_step(
        self,
        session: Session,
        *,
        run_id: str,
        step_index: int,
        node_name: str,
        plan_step_id: str | None = None,
        subagent_name: str | None = None,
        idempotency_key: str | None = None,
        step_id: str | None = None,
    ) -> tuple[AgentStepRecord, bool]:
        self.require_run(session, run_id)
        if step_index < 0:
            raise ValueError("step_index must be non-negative")
        _require_nonblank("node_name", node_name)
        if idempotency_key is not None:
            _require_nonblank("idempotency_key", idempotency_key)
            existing = self.find_step_by_idempotency_key(session, run_id, idempotency_key)
            if existing is not None:
                self._assert_same_step_request(existing, step_index, node_name)
                return existing, False
        else:
            existing = self.find_step_by_index(session, run_id, step_index)
            if existing is not None:
                self._assert_same_step_request(existing, step_index, node_name)
                return existing, False

        record = AgentStepRecord(
            id=step_id or _new_id("step"),
            run_id=run_id,
            step_index=step_index,
            node_name=node_name,
            plan_step_id=plan_step_id,
            subagent_name=subagent_name,
            idempotency_key=idempotency_key,
            status=AgentStepStatus.PENDING.value,
        )
        try:
            with session.begin_nested():
                session.add(record)
                session.flush()
        except IntegrityError as exc:
            existing = (
                self.find_step_by_idempotency_key(session, run_id, idempotency_key)
                if idempotency_key is not None
                else self.find_step_by_index(session, run_id, step_index)
            )
            if existing is None:
                raise exc
            self._assert_same_step_request(existing, step_index, node_name)
            return existing, False
        return record, True

    def find_step_by_index(self, session: Session, run_id: str, step_index: int) -> AgentStepRecord | None:
        return session.scalar(
            select(AgentStepRecord).where(AgentStepRecord.run_id == run_id, AgentStepRecord.step_index == step_index)
        )

    def find_step_by_idempotency_key(
        self,
        session: Session,
        run_id: str,
        idempotency_key: str,
    ) -> AgentStepRecord | None:
        return session.scalar(
            select(AgentStepRecord).where(
                AgentStepRecord.run_id == run_id,
                AgentStepRecord.idempotency_key == idempotency_key,
            )
        )

    def transition_step_status(
        self,
        session: Session,
        *,
        step_id: str,
        target_status: AgentStepStatus | str,
        error_code: str | None = None,
    ) -> AgentStepRecord:
        record = session.get(AgentStepRecord, step_id)
        if record is None:
            raise AgentRuntimeNotFoundError(f"agent step not found: {step_id}")
        target = AgentStepStatus(target_status)
        assert_step_status_transition(record.status, target)
        now = datetime.now(UTC)
        record.status = target.value
        if target == AgentStepStatus.RUNNING and record.started_at is None:
            record.started_at = now
        if target in {AgentStepStatus.COMPLETED, AgentStepStatus.FAILED, AgentStepStatus.SKIPPED, AgentStepStatus.CANCELLED}:
            record.completed_at = now
            record.error_code = error_code
        session.flush()
        return record

    def record_step_outcome(
        self,
        session: Session,
        *,
        step_id: str,
        state_before_hash: str,
        state_after_hash: str,
        state_abstract_key: str,
        action_type: str,
        skill_name: str | None = None,
        observation_ref: str | None = None,
        artifact_refs: object | None = None,
    ) -> AgentStepRecord:
        for name, value in (
            ("state_before_hash", state_before_hash),
            ("state_after_hash", state_after_hash),
            ("state_abstract_key", state_abstract_key),
            ("action_type", action_type),
        ):
            _require_nonblank(name, value)
        if skill_name is not None:
            _require_nonblank("skill_name", skill_name)
        if observation_ref is not None:
            _require_nonblank("observation_ref", observation_ref)
        record = session.get(AgentStepRecord, step_id)
        if record is None:
            raise AgentRuntimeNotFoundError(f"agent step not found: {step_id}")
        record.state_before_hash = state_before_hash
        record.state_after_hash = state_after_hash
        record.state_abstract_key = state_abstract_key
        record.action_type = action_type
        record.skill_name = skill_name
        record.observation_ref = observation_ref
        record.artifact_refs_json = _json_dumps(artifact_refs)
        session.flush()
        return record

    def create_or_get_wait(
        self,
        session: Session,
        *,
        run_id: str,
        wait_type: str,
        request_payload: object | None,
        step_id: str | None = None,
        idempotency_key: str | None = None,
        expires_at: datetime | None = None,
        wait_id: str | None = None,
    ) -> tuple[AgentWaitRecord, bool]:
        self.require_run(session, run_id)
        _require_nonblank("wait_type", wait_type)
        if idempotency_key is not None:
            _require_nonblank("idempotency_key", idempotency_key)
            existing = session.scalar(
                select(AgentWaitRecord).where(
                    AgentWaitRecord.run_id == run_id,
                    AgentWaitRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return existing, False
        record = AgentWaitRecord(
            id=wait_id or _new_id("wait"),
            run_id=run_id,
            step_id=step_id,
            wait_type=wait_type,
            request_json=_json_dumps(request_payload),
            idempotency_key=idempotency_key,
            expires_at=expires_at,
            status=AgentWaitStatus.PENDING.value,
        )
        try:
            with session.begin_nested():
                session.add(record)
                session.flush()
        except IntegrityError as exc:
            if idempotency_key is None:
                raise
            existing = session.scalar(
                select(AgentWaitRecord).where(
                    AgentWaitRecord.run_id == run_id,
                    AgentWaitRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                raise exc
            return existing, False
        return record, True

    def resolve_wait(
        self,
        session: Session,
        *,
        wait_id: str,
        status: AgentWaitStatus | str,
        resume_payload: object | None = None,
    ) -> AgentWaitRecord:
        record = session.get(AgentWaitRecord, wait_id)
        if record is None:
            raise AgentRuntimeNotFoundError(f"agent wait not found: {wait_id}")
        target = AgentWaitStatus(status)
        current = AgentWaitStatus(record.status)
        if current != target and (current != AgentWaitStatus.PENDING or target == AgentWaitStatus.PENDING):
            raise InvalidStatusTransition(f"invalid wait status transition: {current.value} -> {target.value}")
        record.status = target.value
        if target != AgentWaitStatus.PENDING:
            record.resolved_at = datetime.now(UTC)
            record.resume_payload_json = _json_dumps(resume_payload)
        session.flush()
        return record

    def create_or_get_job(
        self,
        session: Session,
        *,
        job_type: str,
        payload: object | None,
        idempotency_key: str | None = None,
        run_id: str | None = None,
        scheduled_at: datetime | None = None,
        max_attempts: int = 1,
        job_id: str | None = None,
    ) -> tuple[AgentJobRecord, bool]:
        _require_nonblank("job_type", job_type)
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if run_id is not None:
            self.require_run(session, run_id)
        if idempotency_key is not None:
            _require_nonblank("idempotency_key", idempotency_key)
            existing = session.scalar(select(AgentJobRecord).where(AgentJobRecord.idempotency_key == idempotency_key))
            if existing is not None:
                if existing.job_type != job_type or existing.run_id != run_id:
                    raise IdempotencyConflictError("agent job idempotency key belongs to another logical job")
                return existing, False
        record = AgentJobRecord(
            id=job_id or _new_id("job"),
            run_id=run_id,
            job_type=job_type,
            payload_json=_json_dumps(payload),
            idempotency_key=idempotency_key,
            scheduled_at=scheduled_at,
            max_attempts=max_attempts,
            status=AgentJobStatus.PENDING.value,
        )
        try:
            with session.begin_nested():
                session.add(record)
                session.flush()
        except IntegrityError as exc:
            if idempotency_key is None:
                raise
            existing = session.scalar(select(AgentJobRecord).where(AgentJobRecord.idempotency_key == idempotency_key))
            if existing is None:
                raise exc
            if existing.job_type != job_type or existing.run_id != run_id:
                raise IdempotencyConflictError("agent job idempotency key belongs to another logical job")
            return existing, False
        return record, True

    def claim_job(self, session: Session, *, job_id: str, claimed_by: str) -> AgentJobRecord:
        _require_nonblank("claimed_by", claimed_by)
        record = session.get(AgentJobRecord, job_id)
        if record is None:
            raise AgentRuntimeNotFoundError(f"agent job not found: {job_id}")
        if AgentJobStatus(record.status) != AgentJobStatus.PENDING:
            raise InvalidStatusTransition(f"invalid job status transition: {record.status} -> {AgentJobStatus.CLAIMED.value}")
        record.status = AgentJobStatus.CLAIMED.value
        record.claimed_by = claimed_by
        record.claimed_at = datetime.now(UTC)
        record.attempts += 1
        session.flush()
        return record

    def claim_next_job(
        self,
        session: Session,
        *,
        job_types: set[str] | frozenset[str] | list[str] | tuple[str, ...],
        claimed_by: str,
        claim_ttl_seconds: int,
        now: datetime | None = None,
    ) -> AgentJobRecord | None:
        """Atomically lease one due or abandoned job from the supported types.

        Claims intentionally use a short-lived lease rather than an in-memory
        worker flag.  If a worker process dies after its claim is committed, a
        later worker can reclaim the job after ``claim_ttl_seconds``.
        """

        _require_nonblank("claimed_by", claimed_by)
        normalized_types = sorted({value.strip() for value in job_types if value and value.strip()})
        if not normalized_types:
            return None
        if claim_ttl_seconds <= 0:
            raise ValueError("claim_ttl_seconds must be positive")
        claimed_now = now or datetime.now(UTC)
        stale_before = claimed_now - timedelta(seconds=claim_ttl_seconds)
        due = and_(
            AgentJobRecord.status == AgentJobStatus.PENDING.value,
            or_(AgentJobRecord.scheduled_at.is_(None), AgentJobRecord.scheduled_at <= claimed_now),
        )
        stale = and_(
            AgentJobRecord.status == AgentJobStatus.CLAIMED.value,
            or_(AgentJobRecord.claimed_at.is_(None), AgentJobRecord.claimed_at <= stale_before),
        )
        candidates = list(
            session.scalars(
                select(AgentJobRecord)
                .where(AgentJobRecord.job_type.in_(normalized_types), or_(due, stale))
                .order_by(AgentJobRecord.scheduled_at.asc(), AgentJobRecord.created_at.asc(), AgentJobRecord.id.asc())
                .limit(max(8, len(normalized_types) * 4))
            )
        )
        for candidate in candidates:
            claimable = or_(
                and_(
                    AgentJobRecord.status == AgentJobStatus.PENDING.value,
                    or_(AgentJobRecord.scheduled_at.is_(None), AgentJobRecord.scheduled_at <= claimed_now),
                ),
                and_(
                    AgentJobRecord.status == AgentJobStatus.CLAIMED.value,
                    or_(AgentJobRecord.claimed_at.is_(None), AgentJobRecord.claimed_at <= stale_before),
                ),
            )
            result = session.execute(
                update(AgentJobRecord)
                .where(AgentJobRecord.id == candidate.id, claimable)
                .values(
                    status=AgentJobStatus.CLAIMED.value,
                    claimed_by=claimed_by,
                    claimed_at=claimed_now,
                    attempts=AgentJobRecord.attempts + 1,
                    error_code=None,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount == 1:
                session.expire(candidate)
                claimed = session.get(AgentJobRecord, candidate.id)
                if claimed is not None:
                    return claimed
        return None

    def complete_job(self, session: Session, *, job_id: str, claimed_by: str) -> AgentJobRecord:
        return self._finish_claimed_job(
            session,
            job_id=job_id,
            claimed_by=claimed_by,
            target_status=AgentJobStatus.COMPLETED,
            error_code=None,
            scheduled_at=None,
        )

    def cancel_job(self, session: Session, *, job_id: str, claimed_by: str, error_code: str | None = None) -> AgentJobRecord:
        return self._finish_claimed_job(
            session,
            job_id=job_id,
            claimed_by=claimed_by,
            target_status=AgentJobStatus.CANCELLED,
            error_code=error_code,
            scheduled_at=None,
        )

    def retry_or_fail_job(
        self,
        session: Session,
        *,
        job_id: str,
        claimed_by: str,
        error_code: str,
        retry_at: datetime | None,
        retryable: bool = True,
    ) -> AgentJobRecord:
        _require_nonblank("claimed_by", claimed_by)
        _require_nonblank("error_code", error_code)
        record = self.require_job(session, job_id)
        if AgentJobStatus(record.status) != AgentJobStatus.CLAIMED or record.claimed_by != claimed_by:
            raise AgentJobLeaseLostError(f"agent job lease was lost: {job_id}")
        target = AgentJobStatus.PENDING if retryable and record.attempts < record.max_attempts else AgentJobStatus.FAILED
        return self._finish_claimed_job(
            session,
            job_id=job_id,
            claimed_by=claimed_by,
            target_status=target,
            error_code=error_code,
            scheduled_at=retry_at if target == AgentJobStatus.PENDING else None,
        )

    def require_job(self, session: Session, job_id: str) -> AgentJobRecord:
        record = session.get(AgentJobRecord, job_id)
        if record is None:
            raise AgentRuntimeNotFoundError(f"agent job not found: {job_id}")
        return record

    def _finish_claimed_job(
        self,
        session: Session,
        *,
        job_id: str,
        claimed_by: str,
        target_status: AgentJobStatus,
        error_code: str | None,
        scheduled_at: datetime | None,
    ) -> AgentJobRecord:
        _require_nonblank("claimed_by", claimed_by)
        record = self.require_job(session, job_id)
        finished_at = datetime.now(UTC)
        values: dict[str, object] = {
            "status": target_status.value,
            "error_code": error_code,
            "scheduled_at": scheduled_at,
            "claimed_by": None,
            "claimed_at": None,
        }
        if target_status in {AgentJobStatus.COMPLETED, AgentJobStatus.FAILED, AgentJobStatus.CANCELLED}:
            values["completed_at"] = finished_at
        else:
            values["completed_at"] = None
        result = session.execute(
            update(AgentJobRecord)
            .where(
                AgentJobRecord.id == job_id,
                AgentJobRecord.status == AgentJobStatus.CLAIMED.value,
                AgentJobRecord.claimed_by == claimed_by,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise AgentJobLeaseLostError(f"agent job lease was lost: {job_id}")
        session.expire(record)
        refreshed = session.get(AgentJobRecord, job_id)
        if refreshed is None:
            raise AgentRuntimeNotFoundError(f"agent job not found: {job_id}")
        return refreshed

    @staticmethod
    def _assert_same_run_request(
        existing: AgentRunRecord,
        thread_id: str,
        admin_actor_id: int,
        trigger_type: str,
    ) -> None:
        if (
            existing.thread_id != thread_id
            or existing.admin_actor_id != admin_actor_id
            or existing.trigger_type != trigger_type
        ):
            raise IdempotencyConflictError("agent run idempotency key belongs to another logical run")

    @staticmethod
    def _assert_same_thread_request(existing: AgentThreadRecord, *, admin_actor_id: int, user_id: int | None) -> None:
        if existing.admin_actor_id != admin_actor_id or existing.user_id != user_id:
            raise IdempotencyConflictError("agent thread ID belongs to another logical thread")

    @staticmethod
    def _assert_same_step_request(existing: AgentStepRecord, step_index: int, node_name: str) -> None:
        if existing.step_index != step_index or existing.node_name != node_name:
            raise IdempotencyConflictError("agent step idempotency key belongs to another logical step")
