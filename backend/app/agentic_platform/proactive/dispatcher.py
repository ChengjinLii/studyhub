from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agentic_platform.application.runtime_events import RuntimeEventStore
from app.agentic_platform.domain.hashing import canonical_hash
from app.core.config import Settings
from app.models.agentic_runtime import AgentOutboxRecord, AgentRunRecord, AgentRunStatus
from app.repos.agentic_run_repo import AgentRunRepository

from .intervention_policy import ShadowIntervention, ShadowInterventionPolicy
from .outbox import AgentOutboxRepository
from .triggers import trigger_from_outbox


@dataclass(frozen=True, slots=True)
class ProactiveDispatchResult:
    run: AgentRunRecord
    job_id: str
    created_run: bool
    created_job: bool
    intervention: ShadowIntervention


class ProactiveDispatcher:
    """Turns a claimed outbox event into one durable, replayable AgentJob."""

    def __init__(
        self,
        settings: Settings,
        *,
        run_repository: AgentRunRepository | None = None,
        outbox_repository: AgentOutboxRepository | None = None,
        policy: ShadowInterventionPolicy | None = None,
        events: RuntimeEventStore | None = None,
    ) -> None:
        self.settings = settings
        self.runs = run_repository or AgentRunRepository()
        self.outbox = outbox_repository or AgentOutboxRepository()
        self.policy = policy or ShadowInterventionPolicy()
        self.events = events or RuntimeEventStore()

    def dispatch(self, session: Session, *, event: AgentOutboxRecord) -> ProactiveDispatchResult:
        trigger = trigger_from_outbox(event, self.outbox)
        intervention = self.policy.decide(trigger)
        stable_key = canonical_hash({"outbox_event_id": event.id})[:40]
        thread, _thread_created = self.runs.create_or_get_thread(
            session,
            thread_id=f"thread_proactive_{stable_key}",
            admin_actor_id=trigger.admin_actor_id,
            title=intervention.title,
        )
        run, created_run = self.runs.create_or_get_run(
            session,
            thread_id=thread.id,
            admin_actor_id=trigger.admin_actor_id,
            user_id=None,
            trigger_type="proactive_event",
            trigger_ref=event.id,
            runtime_version=self.settings.agentic_runtime,
            policy_version=self.policy.version,
            environment_snapshot_id="proactive-shadow-v1",
            idempotency_key=f"proactive:run:{stable_key}",
        )
        if created_run:
            self.runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.QUEUED)
        job, created_job = self.runs.create_or_get_job(
            session,
            run_id=run.id,
            job_type=intervention.job_type,
            payload={
                "schemaVersion": "1.0",
                "runKind": intervention.run_kind,
                "goal": intervention.goal,
                "successCriteria": intervention.success_criteria,
                "shadowMode": True,
                "proactive": intervention.payload.model_dump(mode="json"),
            },
            idempotency_key=f"proactive:job:{stable_key}",
            max_attempts=self.settings.agentic_worker_max_attempts,
        )
        if created_run:
            self.events.append(
                session,
                run=run,
                name="run.queued",
                payload={
                    "run_kind": intervention.run_kind,
                    "shadow_mode": True,
                    "trigger_type": trigger.event_type.value,
                    "status": AgentRunStatus.QUEUED.value,
                },
                idempotency_key="proactive-queued",
            )
        return ProactiveDispatchResult(
            run=run,
            job_id=job.id,
            created_run=created_run,
            created_job=created_job,
            intervention=intervention,
        )
