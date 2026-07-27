from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.agentic_platform.deepresearch.state import ResearchPacket, ResearchReport, ResearchTaskPacket
from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.plan import AgentPlan
from app.agentic_platform.domain.state import (
    AgentBudget,
    AgentTaskState,
    EnvironmentRef,
    GoalState,
    TerminalState,
    TerminalStatus,
    TriggerContext,
    TriggerType,
    UserInputRequest,
)
from app.agentic_platform.execution import AgentExecutionWorker, AgentRuntimeFactory
from app.agentic_platform.runtime.kernel import KernelRunNotFoundError, KernelRunResult, KernelRunStatus
from app.agentic_platform.subagents.deepresearch import DeepResearchSubAgentResult
from app.core.config import Settings
from app.models import Base
from app.models.agentic_runtime import (
    AgentArtifactRecord,
    AgentJobRecord,
    AgentJobStatus,
    AgentRunRecord,
    AgentRunStatus,
    AgentThreadRecord,
    AgentWaitRecord,
    AgentWaitStatus,
)
from app.repos.agentic_artifact_repo import AgentArtifactRepository
from app.repos.agentic_run_repo import AgentRunRepository
from app.services.worker_service import WorkerService


BASE_TIME = datetime(2026, 7, 27, 1, 0, tzinfo=UTC)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            AgentThreadRecord.__table__,
            AgentRunRecord.__table__,
            AgentJobRecord.__table__,
            AgentWaitRecord.__table__,
            AgentArtifactRecord.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as database_session:
        yield database_session
        database_session.rollback()
    engine.dispose()


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "agentic_platform_enabled": True,
        "agentic_execution_enabled": True,
        "agentic_execution_batch_size": 4,
        "agentic_execution_claim_ttl_seconds": 60,
        "agentic_execution_max_attempts": 3,
        "agentic_worker_retry_delay_seconds": 0,
    }
    defaults.update(overrides)
    return Settings(**defaults)


class _MemoryLock:
    provider_name = "test"

    def __init__(self) -> None:
        self.owners: dict[str, str] = {}
        self.deny = False

    def acquire(self, session: Session, *, lock_name: str, owner_token: str, ttl_seconds: int) -> bool:
        del session, ttl_seconds
        if self.deny:
            return False
        owner = self.owners.get(lock_name)
        if owner is not None and owner != owner_token:
            return False
        self.owners[lock_name] = owner_token
        return True

    def release(self, session: Session, *, lock_name: str, owner_token: str) -> None:
        del session
        if self.owners.get(lock_name) == owner_token:
            self.owners.pop(lock_name, None)

    def probe(self, *, deep: bool = False) -> dict[str, object]:
        del deep
        return {"status": "ok"}


def _synthetic_state(run_id: str) -> AgentTaskState:
    return AgentTaskState(
        thread_id=f"thread-{run_id}",
        run_id=run_id,
        admin_actor_id=3,
        trigger=TriggerContext(trigger_type=TriggerType.ADMIN_API, source="execution-worker-test"),
        goal=GoalState(goal_id=f"goal-{run_id}", statement="Finish the requested task."),
        plan=AgentPlan(
            plan_id=f"plan-{run_id}",
            version=1,
            objective="Finish the requested task.",
            created_by_policy_version="test-policy",
        ),
        environment=EnvironmentRef(
            snapshot_id=f"snapshot-{run_id}",
            snapshot_hash=canonical_hash({"run_id": run_id}),
            source="test",
        ),
        budget=AgentBudget(
            turns_remaining=4,
            skill_calls_remaining=4,
            context_tokens_remaining=4_000,
            cost_remaining=0.0,
            subagent_turns_remaining=4,
        ),
    )


class _Kernel:
    def __init__(self, run_id: str, *, status: KernelRunStatus = KernelRunStatus.COMPLETED, error: Exception | None = None) -> None:
        self.run_id = run_id
        self.status = status
        self.error = error
        self.start_calls = 0
        self.resume_calls: list[tuple[str, object, str | None]] = []
        self.cancel_calls: list[tuple[str, str]] = []
        self.closed = False

    async def get_result(self, run_id: str) -> KernelRunResult:
        del run_id
        raise KernelRunNotFoundError("fixture has no checkpoint before start")

    async def start(self, state: AgentTaskState) -> KernelRunResult:
        self.start_calls += 1
        if self.error is not None:
            raise self.error
        return self._result(state)

    async def resume(self, run_id: str, payload: object, *, wait_id: str | None = None) -> KernelRunResult:
        self.resume_calls.append((run_id, payload, wait_id))
        if self.error is not None:
            raise self.error
        return self._result(_synthetic_state(run_id))

    async def cancel(self, run_id: str, *, reason: str) -> KernelRunResult:
        self.cancel_calls.append((run_id, reason))
        return self._result(_synthetic_state(run_id), status=KernelRunStatus.CANCELLED)

    async def close(self) -> None:
        self.closed = True

    def _result(self, state: AgentTaskState, *, status: KernelRunStatus | None = None) -> KernelRunResult:
        result_status = status or self.status
        terminal = {
            KernelRunStatus.COMPLETED: TerminalState(status=TerminalStatus.COMPLETED, reason="fixture_completed"),
            KernelRunStatus.FAILED: TerminalState(status=TerminalStatus.FAILED, reason="fixture_failed"),
            KernelRunStatus.CANCELLED: TerminalState(status=TerminalStatus.CANCELLED, reason="fixture_cancelled"),
            KernelRunStatus.ABORTED: TerminalState(status=TerminalStatus.ABORTED, reason="fixture_aborted"),
        }.get(result_status)
        if result_status == KernelRunStatus.WAITING:
            result_state = state.model_copy(
                update={
                    "pending_user_request": UserInputRequest(
                        request_id=f"wait-{state.run_id}",
                        prompt="Continue?",
                    )
                }
            )
            pending_wait_id = f"wait-{state.run_id}"
        else:
            result_state = state.model_copy(update={"terminal": terminal})
            pending_wait_id = None
        return KernelRunResult(
            run_id=state.run_id,
            graph_thread_id=f"agent-run:{state.run_id}",
            status=result_status,
            state=result_state,
            state_hash=canonical_hash(result_state),
            checkpoint_ref=f"checkpoint://{state.run_id}",
            pending_wait_id=pending_wait_id,
        )


class _ResearchAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, task: ResearchTaskPacket) -> DeepResearchSubAgentResult:
        self.calls.append(task.task_id)
        trace = ArtifactRef(
            artifact_id=f"trace-{task.task_id}",
            artifact_type=ArtifactKind.OTHER,
            version=1,
            uri=f"artifact://trace/{task.task_id}",
            content_hash=canonical_hash({"task_id": task.task_id}),
            media_type="application/json",
            summary="Fixture trace",
        )
        return DeepResearchSubAgentResult(
            task_id=task.task_id,
            subagent_name="deep_research",
            parent_transition_id=task.parent_transition_id,
            summary="Fixture research completed.",
            artifact_refs=[trace],
            turns_used=1,
            research_packet=ResearchPacket(
                packet_id=f"packet-{task.task_id}",
                query=task.research_question,
                trace_ref=trace,
                confidence=0.8,
            ),
            research_report=ResearchReport(
                report_id=f"report-{task.task_id}",
                title="Fixture research report",
                research_question=task.research_question,
            ),
            terminal_reason="fixture_completed",
        )


def _create_run(
    session: Session,
    *,
    job_type: str = "agent_run.dispatch",
    payload: dict[str, object] | None = None,
    max_attempts: int = 3,
) -> tuple[AgentRunRecord, AgentJobRecord]:
    runs = AgentRunRepository()
    thread = runs.create_thread(session, admin_actor_id=3, title=f"Thread for {job_type}")
    run, _created = runs.create_or_get_run(
        session,
        thread_id=thread.id,
        admin_actor_id=3,
        user_id=None,
        trigger_type="admin_api",
        runtime_version="langgraph",
        policy_version="test-policy",
        environment_snapshot_id="test-snapshot-v1",
    )
    runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.QUEUED)
    job, _job_created = runs.create_or_get_job(
        session,
        run_id=run.id,
        job_type=job_type,
        payload=payload
        or {
            "schemaVersion": "1.0",
            "runKind": "agent_run",
            "goal": "Explain a testable concept.",
            "successCriteria": ["Produce a short answer."],
        },
        idempotency_key=f"{job_type}:{run.id}",
        max_attempts=max_attempts,
    )
    session.commit()
    return run, job


def _worker(settings: Settings, factory: AgentRuntimeFactory, lock: _MemoryLock | None = None) -> AgentExecutionWorker:
    return AgentExecutionWorker(settings, runtime_factory=factory, lock_provider=lock or _MemoryLock())


def test_dispatch_completes_and_persists_checkpoint(session: Session) -> None:
    run, job = _create_run(session)
    kernels: list[_Kernel] = []
    worker = _worker(
        _settings(),
        AgentRuntimeFactory(
            agent_kernel_builder=lambda record, payload: kernels.append(_Kernel(record.id)) or kernels[-1],
        ),
    )

    result = worker.run_once(session, worker_id="worker-dispatch", now=BASE_TIME)

    refreshed_run = session.get(AgentRunRecord, run.id)
    refreshed_job = session.get(AgentJobRecord, job.id)
    assert result.jobs_completed == 1
    assert refreshed_run is not None and refreshed_run.status == AgentRunStatus.COMPLETED.value
    assert refreshed_run.checkpoint_ref == f"checkpoint://{run.id}"
    assert refreshed_job is not None and refreshed_job.status == AgentJobStatus.COMPLETED.value
    assert len(kernels) == 1 and kernels[0].closed is True


def test_deep_research_dispatch_persists_packet_and_report(session: Session) -> None:
    research_agent = _ResearchAgent()
    payload = {
        "schemaVersion": "1.0",
        "runKind": "deep_research",
        "goal": "What is a confidence interval?",
        "successCriteria": [],
    }
    run, job = _create_run(session, job_type="deep_research.dispatch", payload=payload)
    task = ResearchTaskPacket(
        task_id=run.id,
        admin_actor_id=run.admin_actor_id,
        research_question="What is a confidence interval?",
    )
    payload["researchTask"] = task.model_dump(mode="json")
    job.payload_json = __import__("json").dumps(payload)
    session.commit()
    worker = _worker(
        _settings(),
        AgentRuntimeFactory(deep_research_agent_builder=lambda record, packet: research_agent),
    )

    result = worker.run_once(session, worker_id="worker-research", now=BASE_TIME)

    assert result.jobs_completed == 1
    assert research_agent.calls == [run.id]
    assert session.get(AgentRunRecord, run.id).status == AgentRunStatus.COMPLETED.value
    artifacts = list(
        session.scalars(
            select(AgentArtifactRecord)
            .where(AgentArtifactRecord.run_id == run.id)
            .where(AgentArtifactRecord.artifact_type.in_(("research_packet", "research_report")))
        )
    )
    assert {artifact.artifact_type for artifact in artifacts} == {"research_packet", "research_report"}
    assert session.get(AgentJobRecord, job.id).status == AgentJobStatus.COMPLETED.value


def test_resume_consumes_resolved_wait(session: Session) -> None:
    run, dispatch = _create_run(session)
    runs = AgentRunRepository()
    dispatch.status = AgentJobStatus.COMPLETED.value
    runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.RUNNING)
    runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.WAITING)
    wait, _created = runs.create_or_get_wait(
        session,
        run_id=run.id,
        wait_type="user_input",
        request_payload={"prompt": "Continue?"},
        idempotency_key=f"wait:{run.id}",
    )
    runs.resolve_wait(session, wait_id=wait.id, status=AgentWaitStatus.RESOLVED, resume_payload={"answer": "yes"})
    runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.QUEUED)
    job, _job_created = runs.create_or_get_job(
        session,
        run_id=run.id,
        job_type="agent_run.resume",
        payload={"schemaVersion": "1.0", "waitId": wait.id, "resume": {"answer": "yes"}},
        idempotency_key=f"resume:{run.id}",
        max_attempts=3,
    )
    session.commit()
    kernels: list[_Kernel] = []
    worker = _worker(
        _settings(),
        AgentRuntimeFactory(agent_kernel_builder=lambda record, payload: kernels.append(_Kernel(record.id)) or kernels[-1]),
    )

    result = worker.run_once(session, worker_id="worker-resume", now=BASE_TIME)

    assert result.jobs_completed == 1
    assert kernels[-1].resume_calls == [(run.id, {"answer": "yes"}, wait.id)]
    assert session.get(AgentRunRecord, run.id).status == AgentRunStatus.COMPLETED.value
    assert session.get(AgentJobRecord, job.id).status == AgentJobStatus.COMPLETED.value


def test_cancel_without_checkpoint_reaches_terminal_state(session: Session) -> None:
    run, _dispatch = _create_run(session)
    runs = AgentRunRepository()
    runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.CANCELLING)
    job, _job_created = runs.create_or_get_job(
        session,
        run_id=run.id,
        job_type="agent_run.cancel",
        payload={"schemaVersion": "1.0", "reason": "operator requested cancellation"},
        idempotency_key=f"cancel:{run.id}",
        max_attempts=3,
    )
    session.commit()
    worker = _worker(_settings(), AgentRuntimeFactory())

    result = worker.run_once(session, worker_id="worker-cancel", now=BASE_TIME)

    assert result.jobs_completed == 1
    assert session.get(AgentRunRecord, run.id).status == AgentRunStatus.CANCELLED.value
    assert session.get(AgentJobRecord, job.id).status == AgentJobStatus.COMPLETED.value


def test_duplicate_claim_does_not_execute_a_second_time(session: Session) -> None:
    run, _job = _create_run(session)
    starts: list[str] = []

    def build(record: AgentRunRecord, payload: dict[str, object]) -> _Kernel:
        del payload
        kernel = _Kernel(record.id)
        original_start = kernel.start

        async def start(state: AgentTaskState) -> KernelRunResult:
            starts.append(record.id)
            return await original_start(state)

        kernel.start = start  # type: ignore[method-assign]
        return kernel

    factory = AgentRuntimeFactory(agent_kernel_builder=build)
    first = _worker(_settings(), factory)
    second = _worker(_settings(), factory)
    assert first.run_once(session, worker_id="worker-one", now=BASE_TIME).jobs_completed == 1
    assert second.run_once(session, worker_id="worker-two", now=BASE_TIME).jobs_claimed == 0
    assert starts == [run.id]


def test_worker_restart_reclaims_stale_claim(session: Session) -> None:
    run, job = _create_run(session)
    runs = AgentRunRepository()
    claimed = runs.claim_next_job(
        session,
        job_types=("agent_run.dispatch",),
        claimed_by="worker-before-restart",
        claim_ttl_seconds=60,
        now=BASE_TIME,
    )
    assert claimed is not None and claimed.id == job.id
    session.commit()
    worker = _worker(_settings(agentic_execution_claim_ttl_seconds=60), AgentRuntimeFactory(agent_kernel_builder=lambda run, payload: _Kernel(run.id)))

    result = worker.run_once(session, worker_id="worker-after-restart", now=BASE_TIME + timedelta(seconds=61))

    assert result.jobs_completed == 1
    assert session.get(AgentJobRecord, job.id).attempts == 2
    assert session.get(AgentRunRecord, run.id).status == AgentRunStatus.COMPLETED.value


def test_second_run_lease_retries_without_writing_trajectory(session: Session) -> None:
    run, job = _create_run(session, max_attempts=2)
    lock = _MemoryLock()
    lock.deny = True
    worker = _worker(_settings(), AgentRuntimeFactory(agent_kernel_builder=lambda run, payload: _Kernel(run.id)), lock)

    result = worker.run_once(session, worker_id="worker-lease", now=BASE_TIME)

    refreshed = session.get(AgentJobRecord, job.id)
    assert result.lease_unavailable == 1
    assert result.jobs_retried == 1
    assert refreshed is not None and refreshed.status == AgentJobStatus.PENDING.value
    assert session.get(AgentRunRecord, run.id).status == AgentRunStatus.QUEUED.value


def test_timeout_retries_then_fails_at_max_attempts(session: Session) -> None:
    run, job = _create_run(session, max_attempts=2)
    factory = AgentRuntimeFactory(agent_kernel_builder=lambda record, payload: _Kernel(record.id, error=TimeoutError()))
    worker = _worker(_settings(agentic_execution_batch_size=1), factory)

    first = worker.run_once(session, worker_id="worker-timeout-one", now=BASE_TIME)
    second = worker.run_once(session, worker_id="worker-timeout-two", now=BASE_TIME + timedelta(seconds=1))

    assert first.jobs_retried == 1
    assert second.jobs_failed == 1
    refreshed = session.get(AgentJobRecord, job.id)
    assert refreshed is not None and refreshed.status == AgentJobStatus.FAILED.value
    assert refreshed.error_code == "agent_execution_timeout"
    assert session.get(AgentRunRecord, run.id).status == AgentRunStatus.FAILED.value


def test_storage_outage_retries_research_dispatch(session: Session) -> None:
    research_agent = _ResearchAgent()
    run, job = _create_run(session, job_type="deep_research.dispatch", max_attempts=2)
    payload = {
        "schemaVersion": "1.0",
        "runKind": "deep_research",
        "goal": "Research a bounded topic.",
        "successCriteria": [],
        "researchTask": ResearchTaskPacket(
            task_id=run.id,
            admin_actor_id=run.admin_actor_id,
            research_question="Research a bounded topic.",
        ).model_dump(mode="json"),
    }
    job.payload_json = __import__("json").dumps(payload)
    session.commit()
    worker = _worker(_settings(), AgentRuntimeFactory(deep_research_agent_builder=lambda record, packet: research_agent))

    class _UnavailableArtifacts:
        def create_next_version(self, *args: object, **kwargs: object) -> object:
            raise OSError("temporary storage outage")

    worker.handlers.artifacts = _UnavailableArtifacts()  # type: ignore[assignment]
    result = worker.run_once(session, worker_id="worker-storage", now=BASE_TIME)

    refreshed = session.get(AgentJobRecord, job.id)
    assert result.jobs_retried == 1
    assert refreshed is not None and refreshed.status == AgentJobStatus.PENDING.value
    assert refreshed.error_code == "agent_execution_storage_unavailable"


def test_feature_flag_disabled_claims_nothing(session: Session) -> None:
    _run, job = _create_run(session)
    worker = _worker(Settings(), AgentRuntimeFactory())

    result = worker.run_once(session, worker_id="worker-disabled", now=BASE_TIME)

    assert result.enabled is False
    assert session.get(AgentJobRecord, job.id).status == AgentJobStatus.PENDING.value


def test_twenty_fixture_dispatches_do_not_stick_or_cross_contaminate(session: Session) -> None:
    run_ids: list[str] = []
    for _ in range(20):
        run, _job = _create_run(session)
        run_ids.append(run.id)
    started_ids: list[str] = []

    def build(record: AgentRunRecord, payload: dict[str, object]) -> _Kernel:
        del payload
        kernel = _Kernel(record.id)
        original_start = kernel.start

        async def start(state: AgentTaskState) -> KernelRunResult:
            started_ids.append(state.run_id)
            return await original_start(state)

        kernel.start = start  # type: ignore[method-assign]
        return kernel

    worker = _worker(
        _settings(agentic_execution_batch_size=20),
        AgentRuntimeFactory(agent_kernel_builder=build),
    )

    result = worker.run_once(session, worker_id="worker-fixtures", now=BASE_TIME)

    statuses = list(session.scalars(select(AgentRunRecord.status).where(AgentRunRecord.id.in_(run_ids))))
    assert result.jobs_completed == 20
    assert set(statuses) == {AgentRunStatus.COMPLETED.value}
    assert set(started_ids) == set(run_ids)
    assert len(started_ids) == len(set(started_ids)) == 20


def test_worker_all_never_invokes_execution_plane() -> None:
    class _Lock:
        provider_name = "test"

        def acquire(self, session, *, lock_name, owner_token, ttl_seconds):
            return True

        def release(self, session, *, lock_name, owner_token):
            return None

        def probe(self, *, deep=False):
            return {"status": "ok"}

    class _Payout:
        def generate_pending_settlements(self, session):
            return 1

        def refresh_pending_transfers(self, session):
            return 1

    class _Requests:
        def run_request_maintenance(self, session):
            return {"maintained": 1}

        def run_scheduled_refunds(self, session):
            return {"refunded": 1}

    class _NeverRunExecution:
        def run_once(self, *args, **kwargs):
            raise AssertionError("all must not invoke the agentic execution worker")

    worker = WorkerService(
        Settings(),
        _Payout(),
        _Requests(),
        _Lock(),
        agentic_execution_worker=_NeverRunExecution(),
    )

    result = worker.run_named_job(object(), "all", owner_token="legacy-worker")

    assert set(result) == {"settlement", "requestMaintenance", "requestRefund", "payoutTransfer"}
