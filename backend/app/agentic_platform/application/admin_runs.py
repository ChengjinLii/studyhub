from __future__ import annotations

import base64
from datetime import UTC, datetime
import hashlib
import hmac
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agentic_platform.deepresearch.state import ResearchSourceType, ResearchTaskPacket
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.runtime.interrupts import safe_resume_payload
from app.core.config import Settings
from app.models.agentic_runtime import (
    AgentArtifactRecord,
    AgentJobRecord,
    AgentRunRecord,
    AgentRunStatus,
    AgentStepRecord,
    AgentWaitRecord,
    AgentWaitStatus,
)
from app.repos.agentic_artifact_repo import AgentArtifactRepository
from app.repos.agentic_run_repo import AgentRunRepository, IdempotencyConflictError
from app.schemas.agentic import AgentRunCreatePayload, DeepResearchCreatePayload
from app.services.read_support import serialize_datetime

from .runtime_events import (
    RUNTIME_EVENT_ARTIFACT_TYPE,
    RuntimeEventStore,
    decode_json as _decode_json,
    safe_artifact_preview as _safe_artifact_preview,
    safe_public_value as _safe_public_value,
)


_SAFE_PREVIEW_ARTIFACT_TYPES = frozenset(
    {
        "research_packet",
        "research_report",
        "evidence_ledger",
        "research_memory",
        "learning_plan",
        "practice_set",
        "material_analysis",
        "daily_brief",
        "report",
    }
)


class AdminRunNotFoundError(LookupError):
    pass


class AdminRunConflictError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class ResumeTokenRejectedError(AdminRunConflictError):
    pass


class AgentResumeTokenCodec:
    """Stateless, signed resume grants; the wait row supplies one-time use."""

    _PREFIX = "ar1"

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("resume token signing secret must not be blank")
        self._secret = secret.encode("utf-8")

    def issue(self, *, wait_id: str, run_id: str, admin_actor_id: int) -> str:
        signature = self._signature(wait_id=wait_id, run_id=run_id, admin_actor_id=admin_actor_id)
        return f"{self._PREFIX}.{wait_id}.{signature}"

    def verify(self, token: str, *, wait_id: str, run_id: str, admin_actor_id: int) -> bool:
        expected = self.issue(wait_id=wait_id, run_id=run_id, admin_actor_id=admin_actor_id)
        return hmac.compare_digest(token, expected)

    def _signature(self, *, wait_id: str, run_id: str, admin_actor_id: int) -> str:
        material = f"{self._PREFIX}:{wait_id}:{run_id}:{admin_actor_id}".encode("utf-8")
        digest = hmac.new(self._secret, material, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class AdminAgentRunService:
    """Durable admin API boundary for agent runs.

    This is intentionally a control plane: it records a request and its queue
    job without inventing a policy decision or executing a model inline.  A
    worker can later bind the saved request to an AgentKernel/DeepResearchGraph
    using the same run and wait records.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        run_repository: AgentRunRepository | None = None,
        artifact_repository: AgentArtifactRepository | None = None,
    ) -> None:
        self.settings = settings
        self.runs = run_repository or AgentRunRepository()
        self.artifacts = artifact_repository or AgentArtifactRepository()
        self.events = RuntimeEventStore(self.artifacts)
        self.resume_tokens = AgentResumeTokenCodec(settings.jwt_secret)

    def create_run(self, session: Session, *, admin_actor_id: int, payload: AgentRunCreatePayload) -> dict[str, Any]:
        goal = _normalize_required(payload.goal, max_length=4_000)
        title = _normalize_optional(payload.title, max_length=512)
        return self._create(
            session,
            admin_actor_id=admin_actor_id,
            kind="agent_run",
            goal=goal,
            title=title,
            thread_id=payload.threadId,
            success_criteria=list(payload.successCriteria),
            idempotency_key=payload.idempotencyKey,
        )

    def create_deep_research(
        self,
        session: Session,
        *,
        admin_actor_id: int,
        payload: DeepResearchCreatePayload,
    ) -> dict[str, Any]:
        question = _normalize_required(payload.question, max_length=4_000)
        title = _normalize_optional(payload.title, max_length=512)
        return self._create(
            session,
            admin_actor_id=admin_actor_id,
            kind="deep_research",
            goal=question,
            title=title or f"Deep research · {question[:96]}",
            thread_id=payload.threadId,
            success_criteria=list(payload.successCriteria),
            idempotency_key=payload.idempotencyKey,
        )

    def list_runs(self, session: Session, *, limit: int = 30, status: str | None = None) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 100))
        stmt = select(AgentRunRecord).order_by(AgentRunRecord.created_at.desc(), AgentRunRecord.id.desc()).limit(safe_limit)
        if status:
            try:
                normalized_status = AgentRunStatus(status).value
            except ValueError as exc:
                raise AdminRunConflictError("Unknown agent run status.", code="INVALID_RUN_STATUS") from exc
            stmt = select(AgentRunRecord).where(AgentRunRecord.status == normalized_status).order_by(
                AgentRunRecord.created_at.desc(), AgentRunRecord.id.desc()
            ).limit(safe_limit)
        runs = list(session.scalars(stmt))
        return {
            "items": [self._serialize_run(session, run, include_details=False) for run in runs],
            "meta": {"limit": safe_limit, "total": len(runs)},
        }

    def get_run(self, session: Session, *, run_id: str) -> dict[str, Any]:
        run = self._require_run(session, run_id)
        return self._serialize_run(session, run, include_details=True)

    def list_events(self, session: Session, *, run_id: str, after_sequence: int = 0) -> dict[str, Any]:
        run = self._require_run(session, run_id)
        safe_after = max(0, after_sequence)
        return {
            "runId": run.id,
            "lastSequence": self.events.latest_sequence(session, run.id),
            "events": self.events.list_for_run(session, run.id, after_sequence=safe_after),
        }

    def resume(
        self,
        session: Session,
        *,
        run_id: str,
        wait_id: str,
        resume_token: str,
        payload: object,
    ) -> dict[str, Any]:
        try:
            run = self._require_run(session, run_id)
            wait = session.get(AgentWaitRecord, wait_id)
            if wait is None or wait.run_id != run.id:
                raise ResumeTokenRejectedError("The requested wait does not belong to this run.", code="WAIT_NOT_FOUND")
            if AgentWaitStatus(wait.status) != AgentWaitStatus.PENDING:
                raise ResumeTokenRejectedError("This resume token has already been used.", code="RESUME_TOKEN_ALREADY_USED")
            if AgentRunStatus(run.status) != AgentRunStatus.WAITING:
                raise ResumeTokenRejectedError("This run is not waiting for administrator input.", code="RUN_NOT_WAITING")
            if wait.expires_at is not None and wait.expires_at <= datetime.now(UTC):
                self.runs.resolve_wait(session, wait_id=wait.id, status=AgentWaitStatus.EXPIRED)
                raise ResumeTokenRejectedError("This resume token has expired.", code="RESUME_TOKEN_EXPIRED")
            if not self.resume_tokens.verify(
                resume_token,
                wait_id=wait.id,
                run_id=run.id,
                admin_actor_id=run.admin_actor_id,
            ):
                raise ResumeTokenRejectedError("The resume token is invalid.", code="INVALID_RESUME_TOKEN")

            safe_payload = safe_resume_payload(payload).model_dump(mode="json")
            self.runs.resolve_wait(
                session,
                wait_id=wait.id,
                status=AgentWaitStatus.RESOLVED,
                resume_payload=safe_payload,
            )
            self.runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.QUEUED)
            self.runs.create_or_get_job(
                session,
                run_id=run.id,
                job_type="agent_run.resume",
                payload={"schemaVersion": "1.0", "waitId": wait.id, "resume": safe_payload},
                idempotency_key=_job_idempotency_key(run.id, f"resume:{wait.id}"),
                max_attempts=self.settings.agentic_execution_max_attempts,
            )
            self.events.append(
                session,
                run=run,
                name="run.resumed",
                payload={"wait_id": wait.id, "wait_type": wait.wait_type, "status": AgentRunStatus.QUEUED.value},
                idempotency_key=f"resume:{wait.id}",
            )
            session.commit()
            return self._serialize_run(session, self._require_run(session, run.id), include_details=True)
        except Exception:
            session.rollback()
            raise

    def cancel(self, session: Session, *, run_id: str, reason: str) -> dict[str, Any]:
        try:
            run = self._require_run(session, run_id)
            normalized_reason = _normalize_required(reason, max_length=1_000)
            current = AgentRunStatus(run.status)
            if current in {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}:
                return self._serialize_run(session, run, include_details=True)
            if current == AgentRunStatus.CREATED:
                self.runs.transition_run_status(
                    session,
                    run_id=run.id,
                    target_status=AgentRunStatus.CANCELLED,
                    terminal_reason=normalized_reason,
                )
            elif current != AgentRunStatus.CANCELLING:
                self.runs.transition_run_status(
                    session,
                    run_id=run.id,
                    target_status=AgentRunStatus.CANCELLING,
                    terminal_reason=normalized_reason,
                )
            pending_waits = list(
                session.scalars(
                    select(AgentWaitRecord).where(
                        AgentWaitRecord.run_id == run.id,
                        AgentWaitRecord.status == AgentWaitStatus.PENDING.value,
                    )
                )
            )
            for wait in pending_waits:
                self.runs.resolve_wait(
                    session,
                    wait_id=wait.id,
                    status=AgentWaitStatus.CANCELLED,
                    resume_payload={"reason": normalized_reason},
                )
            self.runs.create_or_get_job(
                session,
                run_id=run.id,
                job_type="agent_run.cancel",
                payload={"schemaVersion": "1.0", "reason": normalized_reason},
                idempotency_key=_job_idempotency_key(run.id, "cancel"),
                max_attempts=self.settings.agentic_execution_max_attempts,
            )
            self.events.append(
                session,
                run=run,
                name="run.cancel_requested",
                payload={"reason": normalized_reason, "status": self._require_run(session, run.id).status},
                idempotency_key="cancel-requested",
            )
            session.commit()
            return self._serialize_run(session, self._require_run(session, run.id), include_details=True)
        except Exception:
            session.rollback()
            raise

    def list_artifacts(
        self,
        session: Session,
        *,
        run_id: str | None = None,
        artifact_type: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 100))
        stmt = select(AgentArtifactRecord).where(AgentArtifactRecord.artifact_type != RUNTIME_EVENT_ARTIFACT_TYPE)
        if run_id:
            self._require_run(session, run_id)
            stmt = stmt.where(AgentArtifactRecord.run_id == run_id)
        if artifact_type:
            stmt = stmt.where(AgentArtifactRecord.artifact_type == artifact_type)
        records = list(session.scalars(stmt.order_by(AgentArtifactRecord.created_at.desc(), AgentArtifactRecord.id.desc()).limit(safe_limit)))
        return {
            "items": [self._serialize_artifact(record) for record in records],
            "meta": {"limit": safe_limit, "total": len(records)},
        }

    def _create(
        self,
        session: Session,
        *,
        admin_actor_id: int,
        kind: str,
        goal: str,
        title: str | None,
        thread_id: str | None,
        success_criteria: list[str],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        try:
            request_hash = canonical_hash(
                {
                    "kind": kind,
                    "goal": goal,
                    "title": title,
                    "thread_id": thread_id,
                    "success_criteria": success_criteria,
                }
            )
            durable_idempotency_key = _durable_idempotency_key(admin_actor_id, idempotency_key) if idempotency_key else None
            if durable_idempotency_key:
                existing = self.runs.find_run_by_idempotency_key(session, durable_idempotency_key)
                if existing is not None:
                    if existing.trigger_ref != request_hash or existing.trigger_type != "admin_api":
                        raise AdminRunConflictError(
                            "This idempotency key belongs to a different agent run request.",
                            code="IDEMPOTENCY_CONFLICT",
                        )
                    return self._serialize_run(session, existing, include_details=True)

            if thread_id:
                thread = self.runs.require_thread(session, thread_id)
            else:
                thread = self.runs.create_thread(
                    session,
                    admin_actor_id=admin_actor_id,
                    title=title or goal[:512],
                )
            if thread.admin_actor_id != admin_actor_id:
                raise AdminRunConflictError("An agent thread belongs to a different administrator.", code="THREAD_OWNER_MISMATCH")

            run, created = self.runs.create_or_get_run(
                session,
                thread_id=thread.id,
                admin_actor_id=admin_actor_id,
                user_id=None,
                trigger_type="admin_api",
                trigger_ref=request_hash,
                runtime_version=self.settings.agentic_runtime,
                policy_version="agentic-policy-v1",
                environment_snapshot_id="admin-request-envelope-v1",
                idempotency_key=durable_idempotency_key,
            )
            if not created and run.trigger_ref != request_hash:
                raise AdminRunConflictError(
                    "This idempotency key belongs to a different agent run request.", code="IDEMPOTENCY_CONFLICT"
                )
            if created:
                self.runs.transition_run_status(session, run_id=run.id, target_status=AgentRunStatus.QUEUED)
            dispatch_payload = self._dispatch_payload(
                run=run,
                kind=kind,
                goal=goal,
                success_criteria=success_criteria,
            )
            self.runs.create_or_get_job(
                session,
                run_id=run.id,
                job_type=f"{kind}.dispatch",
                payload=dispatch_payload,
                idempotency_key=_job_idempotency_key(run.id, "dispatch"),
                max_attempts=self.settings.agentic_execution_max_attempts,
            )
            if created:
                self.events.append(
                    session,
                    run=run,
                    name="run.queued",
                    payload={"run_kind": kind, "shadow_mode": True, "status": AgentRunStatus.QUEUED.value},
                    idempotency_key="queued",
                )
            session.commit()
            return self._serialize_run(session, self._require_run(session, run.id), include_details=True)
        except IdempotencyConflictError as exc:
            session.rollback()
            raise AdminRunConflictError("Agent run idempotency conflict.", code="IDEMPOTENCY_CONFLICT") from exc
        except AdminRunConflictError:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise

    def _dispatch_payload(
        self,
        *,
        run: AgentRunRecord,
        kind: str,
        goal: str,
        success_criteria: list[str],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schemaVersion": "1.0",
            "runKind": kind,
            "goal": goal,
            "successCriteria": success_criteria,
            "shadowMode": True,
            "requestedAt": serialize_datetime(run.created_at),
        }
        if kind == "deep_research":
            allowed_sources = [ResearchSourceType.INTERNAL_MATERIAL]
            if self.settings.deep_research_web_enabled:
                allowed_sources.append(ResearchSourceType.WEB)
            if self.settings.deep_research_scholar_enabled:
                allowed_sources.append(ResearchSourceType.SCHOLAR)
            task = ResearchTaskPacket(
                task_id=run.id,
                admin_actor_id=run.admin_actor_id,
                research_question=goal,
                allowed_source_types=allowed_sources,
                max_turns=self.settings.agentic_max_turns,
                max_search_turns=self.settings.deep_research_max_search_turns,
                max_page_reads=self.settings.deep_research_max_page_reads,
                max_context_tokens=self.settings.agentic_max_context_tokens,
            )
            payload["researchTask"] = task.model_dump(mode="json")
        return payload

    def _serialize_run(self, session: Session, run: AgentRunRecord, *, include_details: bool) -> dict[str, Any]:
        dispatch = self._dispatch_for_run(session, run.id)
        steps = list(
            session.scalars(
                select(AgentStepRecord)
                .where(AgentStepRecord.run_id == run.id)
                .order_by(AgentStepRecord.step_index.asc(), AgentStepRecord.id.asc())
            )
        )
        waits = list(
            session.scalars(
                select(AgentWaitRecord)
                .where(AgentWaitRecord.run_id == run.id)
                .order_by(AgentWaitRecord.created_at.asc(), AgentWaitRecord.id.asc())
            )
        )
        artifacts = list(
            session.scalars(
                select(AgentArtifactRecord)
                .where(
                    AgentArtifactRecord.run_id == run.id,
                    AgentArtifactRecord.artifact_type != RUNTIME_EVENT_ARTIFACT_TYPE,
                )
                .order_by(AgentArtifactRecord.created_at.asc(), AgentArtifactRecord.id.asc())
            )
        )
        events = self.events.list_for_run(session, run.id) if include_details else []
        run_kind = dispatch.get("runKind") if isinstance(dispatch.get("runKind"), str) else "agent_run"
        result: dict[str, Any] = {
            "id": run.id,
            "threadId": run.thread_id,
            "adminActorId": run.admin_actor_id,
            "status": run.status,
            "runKind": run_kind,
            "goal": _safe_public_value(dispatch.get("goal")) if dispatch else None,
            "successCriteria": _safe_public_value(dispatch.get("successCriteria") or []) if dispatch else [],
            "shadowMode": bool(dispatch.get("shadowMode", True)) if dispatch else True,
            "trigger": {"type": run.trigger_type, "ref": run.trigger_ref},
            "runtime": {"version": run.runtime_version, "policyVersion": run.policy_version},
            "environmentSnapshotId": run.environment_snapshot_id,
            "currentStepId": run.current_step_id,
            "checkpointRef": run.checkpoint_ref,
            "stateHash": run.state_hash,
            "terminalReason": run.terminal_reason,
            "createdAt": serialize_datetime(run.created_at),
            "updatedAt": serialize_datetime(run.updated_at),
            "startedAt": serialize_datetime(run.started_at),
            "completedAt": serialize_datetime(run.completed_at),
            "canResume": AgentRunStatus(run.status) == AgentRunStatus.WAITING and any(
                AgentWaitStatus(wait.status) == AgentWaitStatus.PENDING for wait in waits
            ),
            "canCancel": AgentRunStatus(run.status)
            not in {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED},
            "latestEventSequence": self.events.latest_sequence(session, run.id),
        }
        if include_details:
            result.update(
                {
                    "steps": [self._serialize_step(step) for step in steps],
                    "waits": [self._serialize_wait(run, wait) for wait in waits],
                    "artifacts": [self._serialize_artifact(record) for record in artifacts],
                    "jobs": self._serialize_jobs(session, run.id),
                    "events": events,
                    "observability": self._observability(steps=steps, artifacts=artifacts, events=events),
                }
            )
        return result

    def _serialize_wait(self, run: AgentRunRecord, wait: AgentWaitRecord) -> dict[str, Any]:
        request = _decode_json(wait.request_json, fallback={})
        result = {
            "id": wait.id,
            "stepId": wait.step_id,
            "type": wait.wait_type,
            "status": wait.status,
            "request": _safe_public_value(request),
            "expiresAt": serialize_datetime(wait.expires_at),
            "resolvedAt": serialize_datetime(wait.resolved_at),
            "createdAt": serialize_datetime(wait.created_at),
        }
        if AgentWaitStatus(wait.status) == AgentWaitStatus.PENDING:
            result["resumeToken"] = self.resume_tokens.issue(
                wait_id=wait.id,
                run_id=run.id,
                admin_actor_id=run.admin_actor_id,
            )
        return result

    @staticmethod
    def _serialize_step(step: AgentStepRecord) -> dict[str, Any]:
        artifact_refs = _decode_json(step.artifact_refs_json, fallback=[])
        return {
            "id": step.id,
            "index": step.step_index,
            "node": step.node_name,
            "planStepId": step.plan_step_id,
            "subagent": step.subagent_name,
            "status": step.status,
            "actionType": step.action_type,
            "skillName": step.skill_name,
            "observationRef": step.observation_ref,
            "artifactRefs": _safe_public_value(artifact_refs),
            "stateBeforeHash": step.state_before_hash,
            "stateAfterHash": step.state_after_hash,
            "stateAbstractKey": step.state_abstract_key,
            "stateGroupKeyV2": step.state_group_key_v2,
            "errorCode": step.error_code,
            "startedAt": serialize_datetime(step.started_at),
            "completedAt": serialize_datetime(step.completed_at),
        }

    @staticmethod
    def _serialize_artifact(record: AgentArtifactRecord) -> dict[str, Any]:
        preview = None
        if record.artifact_type in _SAFE_PREVIEW_ARTIFACT_TYPES:
            preview = _safe_artifact_preview(record.content_json)
        return {
            "id": record.id,
            "threadId": record.thread_id,
            "runId": record.run_id,
            "artifactType": record.artifact_type,
            "artifactKey": record.artifact_key,
            "version": record.version,
            "schemaVersion": record.schema_version,
            "contentHash": record.content_hash,
            "externalUri": record.external_uri,
            "mediaType": record.media_type,
            "contentSizeBytes": record.content_size_bytes,
            "trainingAllowed": record.training_allowed,
            "sensitivity": record.sensitivity,
            "licenseClass": record.license_class,
            "sourceScope": record.source_scope,
            "containsPersonalData": record.contains_personal_data,
            "anonymizationVersion": record.anonymization_version,
            "retentionPolicy": record.retention_policy,
            "preview": preview,
            "createdAt": serialize_datetime(record.created_at),
        }

    @staticmethod
    def _serialize_jobs(session: Session, run_id: str) -> list[dict[str, Any]]:
        jobs = list(
            session.scalars(
                select(AgentJobRecord)
                .where(AgentJobRecord.run_id == run_id)
                .order_by(AgentJobRecord.created_at.asc(), AgentJobRecord.id.asc())
            )
        )
        return [
            {
                "id": job.id,
                "type": job.job_type,
                "status": job.status,
                "attempts": job.attempts,
                "maxAttempts": job.max_attempts,
                "errorCode": job.error_code,
                "scheduledAt": serialize_datetime(job.scheduled_at),
                "claimedAt": serialize_datetime(job.claimed_at),
                "completedAt": serialize_datetime(job.completed_at),
                "createdAt": serialize_datetime(job.created_at),
            }
            for job in jobs
        ]

    def _dispatch_for_run(self, session: Session, run_id: str) -> dict[str, Any]:
        job = session.scalar(
            select(AgentJobRecord)
            .where(
                AgentJobRecord.run_id == run_id,
                AgentJobRecord.job_type.in_(
                    ("agent_run.dispatch", "deep_research.dispatch", "proactive.material_analysis", "proactive.daily_brief")
                ),
            )
            .order_by(AgentJobRecord.created_at.asc(), AgentJobRecord.id.asc())
            .limit(1)
        )
        return _decode_json(job.payload_json, fallback={}) if job is not None else {}

    @staticmethod
    def _observability(
        *,
        steps: list[AgentStepRecord],
        artifacts: list[AgentArtifactRecord],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        plan = [
            {
                "planStepId": step.plan_step_id,
                "node": step.node_name,
                "status": step.status,
                "actionType": step.action_type,
            }
            for step in steps
            if step.plan_step_id is not None
        ]
        tools = [
            {"stepId": step.id, "skillName": step.skill_name, "status": step.status}
            for step in steps
            if step.skill_name is not None
        ]
        search_queries: list[dict[str, Any]] = []
        context_compressions: list[dict[str, Any]] = []
        verifier: list[dict[str, Any]] = []
        usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0, "cost": 0.0, "available": False}
        latency_ms: dict[str, float] = {}
        for event in events:
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            name = str(event.get("name") or "")
            if isinstance(payload.get("query"), str):
                search_queries.append({"sequence": event["sequence"], "query": payload["query"], "name": name})
            if name == "context.compressed":
                context_compressions.append({"sequence": event["sequence"], "payload": payload})
            if name.startswith("verifier."):
                verifier.append({"sequence": event["sequence"], "name": name, "payload": payload})
            raw_usage = payload.get("usage")
            if isinstance(raw_usage, dict):
                for source, target in (("input_tokens", "inputTokens"), ("output_tokens", "outputTokens"), ("total_tokens", "totalTokens")):
                    value = raw_usage.get(source)
                    if isinstance(value, int) and value >= 0:
                        usage[target] += value
                        usage["available"] = True
                cost = raw_usage.get("cost")
                if isinstance(cost, (int, float)) and cost >= 0:
                    usage["cost"] += float(cost)
                    usage["available"] = True
            raw_latency = payload.get("latency_ms")
            if isinstance(raw_latency, dict):
                for key, value in raw_latency.items():
                    if isinstance(key, str) and isinstance(value, (int, float)) and value >= 0:
                        latency_ms[key] = latency_ms.get(key, 0.0) + float(value)
        evidence_artifacts = [record for record in artifacts if record.artifact_type == "evidence_ledger"]
        return {
            "plan": plan,
            "steps": len(steps),
            "searchQueries": search_queries,
            "tools": tools,
            "evidenceGraph": {
                "artifactCount": len(evidence_artifacts),
                "nodes": [],
                "edges": [],
                "available": bool(evidence_artifacts),
            },
            "contextCompression": context_compressions,
            "verifier": verifier,
            "usage": usage,
            "latencyMs": latency_ms,
        }

    @staticmethod
    def _require_run(session: Session, run_id: str) -> AgentRunRecord:
        run = session.get(AgentRunRecord, run_id)
        if run is None:
            raise AdminRunNotFoundError(f"agent run not found: {run_id}")
        return run


def _normalize_required(value: str, *, max_length: int) -> str:
    normalized = " ".join(value.split()).strip()
    if not normalized:
        raise ValueError("value must not be blank")
    return normalized[:max_length]


def _normalize_optional(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    return _normalize_required(value, max_length=max_length)


def _durable_idempotency_key(admin_actor_id: int, source_key: str) -> str:
    return f"agentic:{admin_actor_id}:{canonical_hash({'key': source_key})[:48]}"


def _job_idempotency_key(run_id: str, purpose: str) -> str:
    return f"job:{canonical_hash({'run': run_id, 'purpose': purpose})[:56]}"
