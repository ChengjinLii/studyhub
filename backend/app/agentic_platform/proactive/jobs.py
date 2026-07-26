from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agentic_platform.application.runtime_events import RuntimeEventStore, decode_json
from app.agentic_platform.deepresearch.evidence import evidence_from_internal_pdf
from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.proactive.intervention_policy import (
    DailyBriefJobPayload,
    MaterialAnalysisJobPayload,
    parse_proactive_job_payload,
)
from app.agentic_platform.subagents.curator import ContentCuratorAgent, ContentCuratorTaskPacket, DailyBriefTaskPacket
from app.core.config import Settings
from app.learning_artifacts.services import LearningArtifactService
from app.models.agentic_runtime import AgentArtifactRecord, AgentJobRecord, AgentJobStatus, AgentRunStatus
from app.repos.agentic_artifact_repo import AgentArtifactRepository
from app.repos.agentic_run_repo import AgentJobLeaseLostError, AgentRunRepository
from app.repos.material_repo import MaterialRepository
from app.services.material_pdf_evidence_service import MaterialPdfEvidenceService
from app.services.read_support import DEFAULT_OUTPUT_TIMEZONE

from .dispatcher import ProactiveDispatcher
from .outbox import AgentOutboxLeaseLostError, AgentOutboxRepository
from .triggers import ProactiveTriggerService


_DAILY_BRIEF_SOURCE_TYPES = frozenset({"material_analysis", "learning_plan", "practice_set"})


class ProactiveJobExecutionError(RuntimeError):
    def __init__(self, code: str, *, recoverable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.recoverable = recoverable


@dataclass(frozen=True, slots=True)
class ProactiveJobExecutionResult:
    summary: str
    artifact_ref: ArtifactRef | None


class ProactiveAgentWorker:
    """Executes PR10 Shadow jobs after a separate Worker process claims them.

    This class deliberately handles queue durability, leases, retries and
    artifact acceptance only.  It is not a hard-coded replacement for the
    general AgentKernel: later policy/runtime adapters can add job handlers
    without changing the transactional outbox protocol.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        triggers: ProactiveTriggerService | None = None,
        dispatcher: ProactiveDispatcher | None = None,
        outbox_repository: AgentOutboxRepository | None = None,
        run_repository: AgentRunRepository | None = None,
        artifact_repository: AgentArtifactRepository | None = None,
        material_repository: MaterialRepository | None = None,
        pdf_evidence_service: MaterialPdfEvidenceService,
        learning_artifacts: LearningArtifactService | None = None,
        curator: ContentCuratorAgent | None = None,
        events: RuntimeEventStore | None = None,
    ) -> None:
        self.settings = settings
        self.outbox = outbox_repository or AgentOutboxRepository()
        self.runs = run_repository or AgentRunRepository()
        self.artifacts = artifact_repository or AgentArtifactRepository()
        self.triggers = triggers or ProactiveTriggerService(settings, outbox_repository=self.outbox)
        self.events = events or RuntimeEventStore(self.artifacts)
        self.dispatcher = dispatcher or ProactiveDispatcher(
            settings,
            run_repository=self.runs,
            outbox_repository=self.outbox,
            events=self.events,
        )
        self.materials = material_repository or MaterialRepository()
        self.pdf_evidence = pdf_evidence_service
        self.learning_artifacts = learning_artifacts or LearningArtifactService(self.artifacts)
        self.curator = curator or ContentCuratorAgent()

    def is_enabled(self) -> bool:
        return self.triggers.is_enabled()

    def run_once(
        self,
        session: Session,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        if not self.is_enabled():
            return {
                "enabled": False,
                "reason": "proactive_shadow_mode_disabled",
                "dailyBriefEventCreated": False,
                "outboxDispatched": 0,
                "outboxFailed": 0,
                "jobsCompleted": 0,
                "jobsRetried": 0,
                "jobsFailed": 0,
            }

        current = now or datetime.now(UTC)
        daily_due = self.triggers.enqueue_daily_brief_due(
            session,
            for_date=current.astimezone(DEFAULT_OUTPUT_TIMEZONE).date(),
        )
        session.commit()
        metrics: dict[str, Any] = {
            "enabled": True,
            "dailyBriefEventCreated": bool(daily_due and daily_due[1]),
            "outboxDispatched": 0,
            "outboxFailed": 0,
            "jobsCompleted": 0,
            "jobsRetried": 0,
            "jobsFailed": 0,
        }
        batch_size = max(1, int(self.settings.agentic_worker_batch_size))
        for _ in range(batch_size):
            claimed_event = self.outbox.claim_next(
                session,
                claimed_by=worker_id,
                claim_ttl_seconds=self.settings.agentic_worker_claim_ttl_seconds,
                now=current,
            )
            if claimed_event is None:
                break
            # Commit the lease before dispatch so a killed worker can be
            # recovered by a later process rather than losing the event.
            session.commit()
            try:
                self.dispatcher.dispatch(session, event=claimed_event)
                self.outbox.mark_dispatched(session, event_id=claimed_event.id, claimed_by=worker_id)
                session.commit()
                metrics["outboxDispatched"] += 1
            except Exception:  # noqa: BLE001 - store only a stable error code, never raw failures.
                session.rollback()
                try:
                    result = self.outbox.retry_or_fail(
                        session,
                        event_id=claimed_event.id,
                        claimed_by=worker_id,
                        error_code="proactive_dispatch_failed",
                        retry_at=self._retry_at(current),
                    )
                    session.commit()
                    if result.status == "failed":
                        metrics["outboxFailed"] += 1
                except AgentOutboxLeaseLostError:
                    session.rollback()

        # A same-cycle material event is useful source input for today's brief.
        # This is queue ordering only; it does not prescribe an agent's internal
        # reasoning or action sequence.
        for job_types in (("proactive.material_analysis",), ("proactive.daily_brief",)):
            for _ in range(batch_size):
                claimed_job = self.runs.claim_next_job(
                    session,
                    job_types=job_types,
                    claimed_by=worker_id,
                    claim_ttl_seconds=self.settings.agentic_worker_claim_ttl_seconds,
                    now=current,
                )
                if claimed_job is None:
                    break
                session.commit()
                self._run_claimed_job(session, job=claimed_job, worker_id=worker_id, now=current, metrics=metrics)
        return metrics

    def _run_claimed_job(
        self,
        session: Session,
        *,
        job: AgentJobRecord,
        worker_id: str,
        now: datetime,
        metrics: dict[str, Any],
    ) -> None:
        try:
            run = self._prepare_claimed_job(session, job=job, worker_id=worker_id)
            session.commit()
            execution = self._execute_job(session, job=job, run_id=run.id)
            run = self.runs.require_run(session, run.id)
            if AgentRunStatus(run.status) == AgentRunStatus.CANCELLING:
                self.runs.cancel_job(session, job_id=job.id, claimed_by=worker_id, error_code="run_cancelled")
                self.runs.transition_run_status(
                    session,
                    run_id=run.id,
                    target_status=AgentRunStatus.CANCELLED,
                    terminal_reason="cancelled_by_admin",
                )
                self.events.append(
                    session,
                    run=run,
                    name="run.cancelled",
                    payload={"shadow_mode": True},
                    idempotency_key=f"job-cancelled:{job.id}",
                )
                session.commit()
                return
            self.runs.complete_job(session, job_id=job.id, claimed_by=worker_id)
            if AgentRunStatus(run.status) == AgentRunStatus.RUNNING:
                self.runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.COMPLETED)
            if execution.artifact_ref is not None:
                self.events.append(
                    session,
                    run=run,
                    name="artifact.created",
                    payload={
                        "artifact_type": execution.artifact_ref.artifact_type,
                        "artifact_id": execution.artifact_ref.artifact_id,
                        "shadow_mode": True,
                    },
                    idempotency_key=f"artifact:{job.id}",
                )
            self.events.append(
                session,
                run=run,
                name="run.completed",
                payload={
                    "shadow_mode": True,
                    "artifact_created": execution.artifact_ref is not None,
                    "summary": execution.summary,
                },
                idempotency_key=f"job-completed:{job.id}",
            )
            session.commit()
            metrics["jobsCompleted"] += 1
        except AgentJobLeaseLostError:
            session.rollback()
        except ProactiveJobExecutionError as exc:
            self._retry_or_fail_job(
                session,
                job=job,
                worker_id=worker_id,
                now=now,
                error_code=exc.code,
                retryable=exc.recoverable,
                metrics=metrics,
            )
        except Exception:  # noqa: BLE001 - no raw exception bodies enter event/artifact storage.
            self._retry_or_fail_job(
                session,
                job=job,
                worker_id=worker_id,
                now=now,
                error_code="proactive_execution_failed",
                retryable=True,
                metrics=metrics,
            )

    def _prepare_claimed_job(self, session: Session, *, job: AgentJobRecord, worker_id: str):
        if not job.run_id:
            raise ProactiveJobExecutionError("proactive_job_missing_run", recoverable=False)
        run = self.runs.require_run(session, job.run_id)
        status = AgentRunStatus(run.status)
        if status == AgentRunStatus.CANCELLING:
            self.runs.cancel_job(session, job_id=job.id, claimed_by=worker_id, error_code="run_cancelled")
            self.runs.transition_run_status(
                session,
                run_id=run.id,
                target_status=AgentRunStatus.CANCELLED,
                terminal_reason="cancelled_by_admin",
            )
            session.commit()
            raise AgentJobLeaseLostError(f"run cancelled before proactive job execution: {job.id}")
        if status in {AgentRunStatus.CANCELLED, AgentRunStatus.COMPLETED, AgentRunStatus.FAILED}:
            self.runs.cancel_job(session, job_id=job.id, claimed_by=worker_id, error_code="run_not_runnable")
            session.commit()
            raise AgentJobLeaseLostError(f"run is terminal before proactive job execution: {job.id}")
        if status == AgentRunStatus.CREATED:
            self.runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.QUEUED)
            status = AgentRunStatus.QUEUED
        if status == AgentRunStatus.QUEUED:
            run = self.runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.RUNNING)
        elif status != AgentRunStatus.RUNNING:
            raise ProactiveJobExecutionError("proactive_run_not_runnable", recoverable=False)
        self.events.append(
            session,
            run=run,
            name="run.started",
            payload={"shadow_mode": True, "job_type": job.job_type, "attempt": job.attempts},
            idempotency_key=f"job-started:{job.id}:{job.attempts}",
        )
        return run

    def _execute_job(self, session: Session, *, job: AgentJobRecord, run_id: str) -> ProactiveJobExecutionResult:
        envelope = decode_json(job.payload_json, fallback={})
        try:
            payload = parse_proactive_job_payload(envelope)
        except ValueError as exc:
            raise ProactiveJobExecutionError("invalid_proactive_job_payload", recoverable=False) from exc
        run = self.runs.require_run(session, run_id)
        if isinstance(payload, MaterialAnalysisJobPayload):
            return self._execute_material_analysis(session, run=run, job=job, payload=payload)
        if isinstance(payload, DailyBriefJobPayload):
            return self._execute_daily_brief(session, run=run, job=job, payload=payload)
        raise ProactiveJobExecutionError("unsupported_proactive_job", recoverable=False)

    def _execute_material_analysis(
        self,
        session: Session,
        *,
        run,
        job: AgentJobRecord,
        payload: MaterialAnalysisJobPayload,
    ) -> ProactiveJobExecutionResult:
        material = self.materials.get_material(session, payload.material_id)
        if material is None:
            raise ProactiveJobExecutionError("material_not_found", recoverable=False)
        try:
            pages = self.pdf_evidence.collect_for_material(
                material,
                payload.material_title,
                cacheable=bool(getattr(material, "is_free", True)),
                max_results=max(1, min(int(self.settings.ai_agent_pdf_evidence_max_pages), 100)),
            )
        except Exception as exc:  # noqa: BLE001 - mapped to a stable retry code above.
            raise ProactiveJobExecutionError("pdf_evidence_unavailable", recoverable=True) from exc
        evidence = [evidence_from_internal_pdf(page) for page in pages]
        if not evidence:
            # No fabricated artifact is preferable to a learner-facing-looking
            # analysis without provenance.  A transient storage/parser issue can
            # be retried by the durable job lease.
            raise ProactiveJobExecutionError("no_authorized_pdf_evidence", recoverable=True)
        result = _run_async(
            self.curator.run(
                ContentCuratorTaskPacket(
                    task_id=job.id,
                    admin_actor_id=run.admin_actor_id,
                    parent_transition_id=run.id,
                    material_id=payload.material_id,
                    material_title=material.title,
                    evidence=evidence,
                )
            )
        )
        persisted = self.learning_artifacts.persist(
            session,
            self.learning_artifacts.accept(result.material_analysis),
            thread_id=run.thread_id,
            run_id=run.id,
            admin_actor_id=run.admin_actor_id,
            artifact_key=f"material-analysis:{payload.material_id}",
            idempotency_key=f"proactive-artifact:{job.id}",
        )
        return ProactiveJobExecutionResult(summary=result.summary, artifact_ref=persisted.artifact_ref)

    def _execute_daily_brief(
        self,
        session: Session,
        *,
        run,
        job: AgentJobRecord,
        payload: DailyBriefJobPayload,
    ) -> ProactiveJobExecutionResult:
        source_artifacts = self._daily_brief_sources(session, admin_actor_id=run.admin_actor_id)
        if not source_artifacts:
            return ProactiveJobExecutionResult(
                summary="No accepted learning artifacts were available for this administrator date.",
                artifact_ref=None,
            )
        try:
            result = _run_async(
                self.curator.create_daily_brief(
                    DailyBriefTaskPacket(
                        task_id=job.id,
                        admin_actor_id=run.admin_actor_id,
                        parent_transition_id=run.id,
                        for_date=datetime.fromisoformat(payload.for_date).date(),
                        preview_summaries=[
                            f"Review accepted {reference.artifact_type} artifact version {reference.version}."
                            for reference in source_artifacts
                        ],
                        source_artifacts=source_artifacts,
                    )
                )
            )
        except ValueError as exc:
            raise ProactiveJobExecutionError("invalid_daily_brief_date", recoverable=False) from exc
        persisted = self.learning_artifacts.persist(
            session,
            self.learning_artifacts.accept(result.daily_brief),
            thread_id=run.thread_id,
            run_id=run.id,
            admin_actor_id=run.admin_actor_id,
            artifact_key=f"daily-brief:{payload.for_date}",
            idempotency_key=f"proactive-artifact:{job.id}",
        )
        return ProactiveJobExecutionResult(summary=result.summary, artifact_ref=persisted.artifact_ref)

    def _daily_brief_sources(self, session: Session, *, admin_actor_id: int) -> list[ArtifactRef]:
        records = list(
            session.scalars(
                select(AgentArtifactRecord)
                .where(
                    AgentArtifactRecord.admin_actor_id == admin_actor_id,
                    AgentArtifactRecord.artifact_type.in_(sorted(_DAILY_BRIEF_SOURCE_TYPES)),
                )
                .order_by(AgentArtifactRecord.created_at.desc(), AgentArtifactRecord.id.desc())
            )
        )
        references: list[ArtifactRef] = []
        seen_keys: set[tuple[str, str]] = set()
        for record in records:
            source_key = (record.artifact_type, record.artifact_key)
            if source_key in seen_keys:
                continue
            seen_keys.add(source_key)
            try:
                artifact_kind: ArtifactKind | str = ArtifactKind(record.artifact_type)
            except ValueError:
                artifact_kind = ArtifactKind.OTHER
            references.append(
                ArtifactRef(
                    artifact_id=record.id,
                    artifact_type=artifact_kind,
                    version=record.version,
                    uri=record.external_uri or f"artifact://agentic/{record.id}/v{record.version}",
                    content_hash=record.content_hash,
                    media_type=record.media_type or "application/json",
                    summary=f"Validated {record.artifact_type} artifact version {record.version}",
                )
            )
            if len(references) >= 12:
                break
        return references

    def _retry_or_fail_job(
        self,
        session: Session,
        *,
        job: AgentJobRecord,
        worker_id: str,
        now: datetime,
        error_code: str,
        retryable: bool,
        metrics: dict[str, Any],
    ) -> None:
        session.rollback()
        try:
            result = self.runs.retry_or_fail_job(
                session,
                job_id=job.id,
                claimed_by=worker_id,
                error_code=error_code,
                retry_at=self._retry_at(now),
                retryable=retryable,
            )
            run = self.runs.require_run(session, job.run_id or "")
            if AgentJobStatus(result.status) == AgentJobStatus.FAILED:
                current_status = AgentRunStatus(run.status)
                if current_status in {AgentRunStatus.QUEUED, AgentRunStatus.RUNNING, AgentRunStatus.CANCELLING}:
                    self.runs.transition_run_status(
                        session,
                        run_id=run.id,
                        target_status=AgentRunStatus.FAILED,
                        terminal_reason=error_code,
                    )
                self.events.append(
                    session,
                    run=run,
                    name="run.failed",
                    payload={"shadow_mode": True, "error_code": error_code},
                    idempotency_key=f"job-failed:{job.id}",
                )
                metrics["jobsFailed"] += 1
            else:
                self.events.append(
                    session,
                    run=run,
                    name="run.retry_scheduled",
                    payload={"shadow_mode": True, "error_code": error_code, "attempt": result.attempts},
                    idempotency_key=f"job-retry:{job.id}:{result.attempts}",
                )
                metrics["jobsRetried"] += 1
            session.commit()
        except AgentJobLeaseLostError:
            session.rollback()

    def _retry_at(self, now: datetime) -> datetime:
        delay_seconds = max(0, int(self.settings.agentic_worker_retry_delay_seconds))
        # Even an explicitly zero-delay test/dev setting should be reclaimed by
        # a subsequent poll, not burned through repeatedly in one batch loop.
        return now + timedelta(seconds=delay_seconds, microseconds=1 if delay_seconds == 0 else 0)


def _run_async(awaitable):
    """Worker entrypoints are synchronous; keep async subagents at the edge."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("ProactiveAgentWorker must run from the dedicated synchronous worker process")
