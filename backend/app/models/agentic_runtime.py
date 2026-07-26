from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AgentThreadStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class AgentRunStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class AgentWaitStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class AgentJobStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentOutboxStatus(StrEnum):
    """Durable delivery states for proactive trigger events.

    The outbox deliberately has its own state machine from AgentJob.  An event
    may be durably accepted before it is mapped to a runnable agent job, which
    makes a database commit or worker restart safe to recover from.
    """

    PENDING = "pending"
    CLAIMED = "claimed"
    DISPATCHED = "dispatched"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentThreadRecord(TimestampMixin, Base):
    __tablename__ = "agent_threads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_actor_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AgentThreadStatus.ACTIVE.value, index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    latest_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class AgentRunRecord(TimestampMixin, Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    admin_actor_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trigger_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    runtime_version: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    environment_snapshot_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AgentRunStatus.CREATED.value, index=True)
    current_step_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    checkpoint_ref: Mapped[str | None] = mapped_column(String(2_048), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    state_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentStepRecord(TimestampMixin, Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "step_index", name="uq_agent_steps_run_index"),
        UniqueConstraint("run_id", "idempotency_key", name="uq_agent_steps_run_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    node_name: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_step_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    subagent_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AgentStepStatus.PENDING.value, index=True)
    state_before_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state_after_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state_abstract_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    action_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skill_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    observation_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_refs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)


class AgentWaitRecord(TimestampMixin, Base):
    __tablename__ = "agent_waits"
    __table_args__ = (UniqueConstraint("run_id", "idempotency_key", name="uq_agent_waits_run_idempotency"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    wait_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AgentWaitStatus.PENDING.value, index=True)
    request_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentJobRecord(TimestampMixin, Base):
    __tablename__ = "agent_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AgentJobStatus.PENDING.value, index=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)


class AgentOutboxRecord(TimestampMixin, Base):
    """Transactional event outbox for the administrator-only proactive plane."""

    __tablename__ = "agent_outbox_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    admin_actor_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AgentOutboxStatus.PENDING.value, index=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)


class AgentArtifactRecord(TimestampMixin, Base):
    __tablename__ = "agent_artifacts"
    __table_args__ = (
        UniqueConstraint("thread_id", "artifact_type", "artifact_key", "version", name="uq_agent_artifacts_version"),
        UniqueConstraint("thread_id", "idempotency_key", name="uq_agent_artifacts_thread_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    admin_actor_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    artifact_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0")
    content_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_uri: Mapped[str | None] = mapped_column(String(2_048), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
