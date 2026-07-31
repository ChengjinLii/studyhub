from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.agentic_platform.application.runtime_events import RuntimeEventStore
from app.agentic_platform.persistence.run_lease import RunLease, RunLeaseLostError
from app.agentic_platform.runtime.kernel import KernelRunStatus
from app.core.config import Settings
from app.models.agentic_runtime import AgentJobRecord, AgentJobStatus, AgentRunRecord, AgentRunStatus
from app.providers.lock import LockProvider
from app.repos.agentic_artifact_repo import AgentArtifactRepository
from app.repos.agentic_run_repo import AgentJobLeaseLostError, AgentRunRepository

from .errors import AgentExecutionError, AgentExecutionLeaseError, classify_execution_error
from .factory import AgentRuntimeFactory
from .job_handlers import AgentExecutionJobHandlers, JobExecutionResult


EXECUTION_JOB_TYPES = frozenset(
    {
        "agent_run.dispatch",
        "deep_research.dispatch",
        "agent_run.resume",
        "agent_run.cancel",
    }
)


@dataclass(frozen=True, slots=True)
class AgentExecutionWorkerResult:
    enabled: bool
    jobs_claimed: int = 0
    jobs_completed: int = 0
    jobs_cancelled: int = 0
    jobs_retried: int = 0
    jobs_failed: int = 0
    lease_unavailable: int = 0
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "jobsClaimed": self.jobs_claimed,
            "jobsCompleted": self.jobs_completed,
            "jobsCancelled": self.jobs_cancelled,
            "jobsRetried": self.jobs_retried,
            "jobsFailed": self.jobs_failed,
            "leaseUnavailable": self.lease_unavailable,
            **({"reason": self.reason} if self.reason else {}),
        }


class AgentExecutionWorker:
    """Consume administrator-created Agent jobs outside the FastAPI process.

    Job claims provide crash recovery. A second run-scoped lock prevents two
    worker processes from concurrently writing the same checkpoint/trajectory.
    This worker intentionally knows no policy action sequence.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        runtime_factory: AgentRuntimeFactory,
        lock_provider: LockProvider,
        run_repository: AgentRunRepository | None = None,
        artifact_repository: AgentArtifactRepository | None = None,
        events: RuntimeEventStore | None = None,
    ) -> None:
        self.settings = settings
        self.runs = run_repository or AgentRunRepository()
        self.artifacts = artifact_repository or AgentArtifactRepository()
        self.events = events or RuntimeEventStore(self.artifacts)
        self.lock_provider = lock_provider
        self.handlers = AgentExecutionJobHandlers(
            settings,
            runtime_factory=runtime_factory,
            run_repository=self.runs,
            artifact_repository=self.artifacts,
        )

    def run_once(
        self,
        session: Session,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> AgentExecutionWorkerResult:
        if not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        if not self.settings.agentic_execution_enabled:
            return AgentExecutionWorkerResult(enabled=False, reason="agentic_execution_disabled")

        current = now or datetime.now(UTC)
        metrics = _MutableWorkerMetrics()
        for _ in range(max(1, int(self.settings.agentic_execution_batch_size))):
            job = self.runs.claim_next_job(
                session,
                job_types=EXECUTION_JOB_TYPES,
                claimed_by=worker_id,
                claim_ttl_seconds=self.settings.agentic_execution_claim_ttl_seconds,
                now=current,
            )
            if job is None:
                break
            session.commit()
            metrics.jobs_claimed += 1
            self._run_claimed_job(session, job=job, worker_id=worker_id, now=current, metrics=metrics)
        return metrics.freeze()

    def _run_claimed_job(
        self,
        session: Session,
        *,
        job: AgentJobRecord,
        worker_id: str,
        now: datetime,
        metrics: "_MutableWorkerMetrics",
    ) -> None:
        if not job.run_id:
            self._retry_or_fail(
                session,
                job=job,
                worker_id=worker_id,
                now=now,
                error=AgentExecutionError("agent_execution_job_missing_run", retryable=False),
                metrics=metrics,
            )
            return

        lease = RunLease(
            self.lock_provider,
            session,
            run_id=job.run_id,
            owner_token=f"agent-execution:{worker_id}:{job.id}:{job.attempts}",
            ttl_seconds=self.settings.agentic_execution_claim_ttl_seconds,
        )
        if not lease.acquire():
            metrics.lease_unavailable += 1
            self._retry_or_fail(
                session,
                job=job,
                worker_id=worker_id,
                now=now,
                error=AgentExecutionLeaseError(),
                metrics=metrics,
            )
            return

        try:
            run = self._prepare_run(session, job=job, worker_id=worker_id)
            if run is None:
                metrics.jobs_cancelled += 1
                return
            session.commit()
            heartbeat_bind = session.get_bind()
            result = _run_async(
                lease.run_with_heartbeat(
                    self.handlers.execute(session, job=job, run=run),
                    ownership_check=lambda: self._renew_job_claim(
                        heartbeat_bind,
                        job_id=job.id,
                        worker_id=worker_id,
                    ),
                )
            )
            session.expire_all()
            refreshed_run = self.runs.require_run(session, run.id)
            self._persist_result_status(session, run=refreshed_run, result=result)
            refreshed_run = self.runs.require_run(session, run.id)
            self.runs.complete_job(session, job_id=job.id, claimed_by=worker_id)
            self.events.append(
                session,
                run=refreshed_run,
                name="run.execution_completed",
                payload={
                    "job_type": job.job_type,
                    "job_attempt": job.attempts,
                    "result_kind": result.kind,
                    "artifacts_created": result.artifacts_created,
                },
                idempotency_key=f"execution-completed:{job.id}:{job.attempts}",
            )
            session.commit()
            metrics.jobs_completed += 1
        except AgentJobLeaseLostError:
            session.rollback()
        except RunLeaseLostError:
            metrics.lease_unavailable += 1
            self._retry_or_fail(
                session,
                job=job,
                worker_id=worker_id,
                now=now,
                error=AgentExecutionLeaseError("agent_execution_lease_lost"),
                metrics=metrics,
            )
        except Exception as exc:  # noqa: BLE001 - error details stay out of durable admin artifacts.
            self._retry_or_fail(
                session,
                job=job,
                worker_id=worker_id,
                now=now,
                error=classify_execution_error(exc),
                metrics=metrics,
            )
        finally:
            lease.release()

    def _renew_job_claim(self, bind: Any, *, job_id: str, worker_id: str) -> bool:
        with Session(bind=bind, expire_on_commit=False) as heartbeat_session:
            try:
                renewed = self.runs.renew_job_claim(
                    heartbeat_session,
                    job_id=job_id,
                    claimed_by=worker_id,
                )
                heartbeat_session.commit()
                return renewed
            except Exception:
                heartbeat_session.rollback()
                raise

    def _prepare_run(self, session: Session, *, job: AgentJobRecord, worker_id: str) -> AgentRunRecord | None:
        assert job.run_id is not None
        run = self.runs.require_run(session, job.run_id)
        status = AgentRunStatus(run.status)
        if status in {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}:
            if job.job_type == "agent_run.cancel" and status == AgentRunStatus.CANCELLED:
                return run
            self.runs.cancel_job(session, job_id=job.id, claimed_by=worker_id, error_code="run_not_runnable")
            session.commit()
            return None

        if job.job_type == "agent_run.cancel":
            if status != AgentRunStatus.CANCELLING:
                if status in {AgentRunStatus.QUEUED, AgentRunStatus.RUNNING, AgentRunStatus.WAITING}:
                    self.runs.transition_run_status(
                        session,
                        run_id=run.id,
                        target_status=AgentRunStatus.CANCELLING,
                        terminal_reason="cancelled_by_admin",
                    )
                elif status == AgentRunStatus.CREATED:
                    self.runs.transition_run_status(
                        session,
                        run_id=run.id,
                        target_status=AgentRunStatus.CANCELLED,
                        terminal_reason="cancelled_by_admin",
                    )
            return self.runs.require_run(session, run.id)

        if status == AgentRunStatus.CANCELLING:
            self.runs.cancel_job(session, job_id=job.id, claimed_by=worker_id, error_code="run_cancelling")
            self.runs.transition_run_status(
                session,
                run_id=run.id,
                target_status=AgentRunStatus.CANCELLED,
                terminal_reason="cancelled_by_admin",
            )
            session.commit()
            return None
        if status == AgentRunStatus.CREATED:
            self.runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.QUEUED)
            status = AgentRunStatus.QUEUED
        if status == AgentRunStatus.QUEUED:
            run = self.runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.RUNNING)
        elif status == AgentRunStatus.WAITING:
            raise ValueError("agent execution job cannot run while its run is waiting")
        elif status != AgentRunStatus.RUNNING:
            raise ValueError("agent execution run is not runnable")
        self.events.append(
            session,
            run=run,
            name="run.execution_started",
            payload={"job_type": job.job_type, "job_attempt": job.attempts},
            idempotency_key=f"execution-started:{job.id}:{job.attempts}",
        )
        return run

    def _persist_result_status(self, session: Session, *, run: AgentRunRecord, result: JobExecutionResult) -> None:
        if result.kind == "deep_research":
            self._transition_if_needed(session, run=run, target=AgentRunStatus.COMPLETED, reason=result.summary)
            return
        if result.kind == "cancel" and result.kernel_result is None:
            self._transition_if_needed(
                session,
                run=run,
                target=AgentRunStatus.CANCELLED,
                reason=result.summary or "cancelled_by_admin",
            )
            return
        kernel_result = result.kernel_result
        if kernel_result is None:
            raise ValueError("agent execution produced no kernel result")
        self.runs.save_run_checkpoint(
            session,
            run_id=run.id,
            checkpoint_ref=kernel_result.checkpoint_ref,
            state_hash=kernel_result.state_hash,
        )
        target = {
            KernelRunStatus.WAITING: AgentRunStatus.WAITING,
            KernelRunStatus.COMPLETED: AgentRunStatus.COMPLETED,
            KernelRunStatus.FAILED: AgentRunStatus.FAILED,
            KernelRunStatus.ABORTED: AgentRunStatus.FAILED,
            KernelRunStatus.CANCELLED: AgentRunStatus.CANCELLED,
        }[kernel_result.status]
        reason = kernel_result.state.terminal.reason if kernel_result.state.terminal is not None else None
        self._transition_if_needed(session, run=run, target=target, reason=reason)

    def _transition_if_needed(
        self,
        session: Session,
        *,
        run: AgentRunRecord,
        target: AgentRunStatus,
        reason: str | None = None,
    ) -> None:
        current = AgentRunStatus(run.status)
        if current == target:
            return
        if current == AgentRunStatus.QUEUED and target in {
            AgentRunStatus.WAITING,
            AgentRunStatus.COMPLETED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }:
            self.runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.RUNNING)
            run = self.runs.require_run(session, run.id)
        self.runs.transition_run_status(session, run_id=run.id, target_status=target, terminal_reason=reason)

    def _retry_or_fail(
        self,
        session: Session,
        *,
        job: AgentJobRecord,
        worker_id: str,
        now: datetime,
        error,
        metrics: "_MutableWorkerMetrics",
    ) -> None:
        session.rollback()
        try:
            result = self.runs.retry_or_fail_job(
                session,
                job_id=job.id,
                claimed_by=worker_id,
                error_code=error.code,
                # Do not reclaim the same failed lease again in this batch.
                # A zero-configured legacy retry delay still means the next
                # worker poll, rather than a tight local replay loop.
                retry_at=now + timedelta(seconds=max(1, int(self.settings.agentic_worker_retry_delay_seconds))),
                retryable=error.retryable,
            )
            if result.status == AgentJobStatus.FAILED.value and job.run_id:
                run = self.runs.require_run(session, job.run_id)
                if AgentRunStatus(run.status) not in {
                    AgentRunStatus.COMPLETED,
                    AgentRunStatus.FAILED,
                    AgentRunStatus.CANCELLED,
                }:
                    self._transition_if_needed(session, run=run, target=AgentRunStatus.FAILED, reason=error.code)
                self.events.append(
                    session,
                    run=self.runs.require_run(session, job.run_id),
                    name="run.execution_failed",
                    payload={"job_type": job.job_type, "error_code": error.code, "job_attempt": job.attempts},
                    idempotency_key=f"execution-failed:{job.id}:{job.attempts}",
                )
                metrics.jobs_failed += 1
            else:
                if job.run_id:
                    run = self.runs.require_run(session, job.run_id)
                    self.events.append(
                        session,
                        run=run,
                        name="run.execution_retry_scheduled",
                        payload={"job_type": job.job_type, "error_code": error.code, "job_attempt": job.attempts},
                        idempotency_key=f"execution-retry:{job.id}:{job.attempts}",
                    )
                metrics.jobs_retried += 1
            session.commit()
        except AgentJobLeaseLostError:
            session.rollback()


@dataclass(slots=True)
class _MutableWorkerMetrics:
    jobs_claimed: int = 0
    jobs_completed: int = 0
    jobs_cancelled: int = 0
    jobs_retried: int = 0
    jobs_failed: int = 0
    lease_unavailable: int = 0

    def freeze(self) -> AgentExecutionWorkerResult:
        return AgentExecutionWorkerResult(enabled=True, **asdict(self))


def _run_async(awaitable):
    """Dedicated worker entrypoint; fail fast if embedded in an active event loop."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("AgentExecutionWorker.run_once must run outside an active event loop")
