from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import pytest

from app.agentic_platform.persistence import InvalidStatusTransition
from app.models import Base
from app.models.agentic_runtime import (
    AgentArtifactRecord,
    AgentJobStatus,
    AgentRunRecord,
    AgentRunStatus,
    AgentStepStatus,
    AgentWaitStatus,
)
from app.repos.agentic_artifact_repo import (
    MAX_INLINE_ARTIFACT_JSON_BYTES,
    AgentArtifactRepository,
    ArtifactPayloadTooLargeError,
)
from app.repos.agentic_run_repo import AgentRunRepository


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    runtime_tables = [
        table
        for name, table in Base.metadata.tables.items()
        if name in {"agent_threads", "agent_runs", "agent_steps", "agent_waits", "agent_jobs", "agent_artifacts"}
    ]
    Base.metadata.create_all(engine, tables=runtime_tables)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as database_session:
        yield database_session
        database_session.rollback()
    engine.dispose()


def _create_run(session: Session):
    repository = AgentRunRepository()
    thread = repository.create_thread(session, admin_actor_id=3, user_id=7, title="Persistence test")
    run, created = repository.create_or_get_run(
        session,
        thread_id=thread.id,
        admin_actor_id=3,
        user_id=7,
        trigger_type="admin_api",
        runtime_version="legacy",
        policy_version="test-policy-v1",
        environment_snapshot_id="snapshot-1",
        idempotency_key="run-request-1",
    )
    return repository, thread, run, created


def test_sqlite_runtime_records_and_run_idempotency(session: Session) -> None:
    repository, thread, run, created = _create_run(session)
    duplicate, duplicate_created = repository.create_or_get_run(
        session,
        thread_id=thread.id,
        admin_actor_id=3,
        user_id=7,
        trigger_type="admin_api",
        runtime_version="legacy",
        policy_version="test-policy-v1",
        environment_snapshot_id="snapshot-1",
        idempotency_key="run-request-1",
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate.id == run.id
    assert session.scalar(select(func.count()).select_from(AgentRunRecord)) == 1
    assert thread.latest_run_id == run.id


def test_run_and_step_state_machines_reject_illegal_transitions(session: Session) -> None:
    repository, _thread, run, _created = _create_run(session)

    repository.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.QUEUED)
    running = repository.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.RUNNING)
    assert running.started_at is not None
    with pytest.raises(InvalidStatusTransition, match="running -> created"):
        repository.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.CREATED)

    step, created = repository.create_or_get_step(
        session,
        run_id=run.id,
        step_index=0,
        node_name="policy",
        idempotency_key="step-0",
    )
    duplicate, duplicate_created = repository.create_or_get_step(
        session,
        run_id=run.id,
        step_index=0,
        node_name="policy",
        idempotency_key="step-0",
    )
    assert created is True
    assert duplicate_created is False
    assert duplicate.id == step.id
    with pytest.raises(InvalidStatusTransition, match="pending -> completed"):
        repository.transition_step_status(session, step_id=step.id, target_status=AgentStepStatus.COMPLETED)

    repository.transition_step_status(session, step_id=step.id, target_status=AgentStepStatus.RUNNING)
    completed_step = repository.transition_step_status(session, step_id=step.id, target_status=AgentStepStatus.COMPLETED)
    completed_run = repository.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.COMPLETED)
    assert completed_step.completed_at is not None
    assert completed_run.completed_at is not None
    with pytest.raises(InvalidStatusTransition, match="completed -> running"):
        repository.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.RUNNING)


def test_wait_and_job_records_are_durable_and_idempotent(session: Session) -> None:
    repository, _thread, run, _created = _create_run(session)
    wait, wait_created = repository.create_or_get_wait(
        session,
        run_id=run.id,
        wait_type="approval",
        request_payload={"approvalId": "approval-1"},
        idempotency_key="wait-1",
    )
    duplicate_wait, duplicate_wait_created = repository.create_or_get_wait(
        session,
        run_id=run.id,
        wait_type="approval",
        request_payload={"approvalId": "approval-1"},
        idempotency_key="wait-1",
    )
    resolved = repository.resolve_wait(session, wait_id=wait.id, status=AgentWaitStatus.RESOLVED, resume_payload={"approved": True})
    job, job_created = repository.create_or_get_job(
        session,
        run_id=run.id,
        job_type="resume_run",
        payload={"runId": run.id},
        idempotency_key="job-1",
    )
    claimed = repository.claim_job(session, job_id=job.id, claimed_by="worker-1")

    assert wait_created is True
    assert duplicate_wait_created is False
    assert duplicate_wait.id == wait.id
    assert resolved.status == AgentWaitStatus.RESOLVED.value
    assert resolved.resume_payload_json == '{"approved":true}'
    assert job_created is True
    assert claimed.status == AgentJobStatus.CLAIMED.value
    assert claimed.attempts == 1


def test_artifact_versions_increment_and_inline_content_stays_bounded(session: Session) -> None:
    artifacts = AgentArtifactRepository()
    first, first_created = artifacts.create_next_version(
        session,
        thread_id="thread-artifacts",
        admin_actor_id=3,
        artifact_type="research_report",
        artifact_key="weekly",
        content={"title": "Week 1"},
        idempotency_key="artifact-1",
    )
    duplicate, duplicate_created = artifacts.create_next_version(
        session,
        thread_id="thread-artifacts",
        admin_actor_id=3,
        artifact_type="research_report",
        artifact_key="weekly",
        content={"title": "Week 1"},
        idempotency_key="artifact-1",
    )
    second, second_created = artifacts.create_next_version(
        session,
        thread_id="thread-artifacts",
        admin_actor_id=3,
        artifact_type="research_report",
        artifact_key="weekly",
        content={"title": "Week 2"},
    )

    assert first_created is True
    assert duplicate_created is False
    assert duplicate.id == first.id
    assert second_created is True
    assert [first.version, second.version] == [1, 2]
    assert artifacts.decode_content(second) == {"title": "Week 2"}
    assert session.scalar(select(func.count()).select_from(AgentArtifactRecord)) == 2
    with pytest.raises(ArtifactPayloadTooLargeError):
        artifacts.create_next_version(
            session,
            thread_id="thread-artifacts",
            admin_actor_id=3,
            artifact_type="research_report",
            artifact_key="too-large",
            content={"payload": "x" * MAX_INLINE_ARTIFACT_JSON_BYTES},
        )
