from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agentic_platform.application.runtime_events import decode_json
from app.agentic_platform.deepresearch.state import ResearchTaskPacket
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.plan import AgentPlan
from app.agentic_platform.domain.state import AgentBudget, AgentTaskState, EnvironmentRef, GoalState, TriggerContext, TriggerType
from app.agentic_platform.runtime.kernel import AgentKernel, KernelRunNotFoundError, KernelRunResult
from app.core.config import Settings
from app.models.agentic_runtime import AgentJobRecord, AgentRunRecord, AgentWaitRecord, AgentWaitStatus
from app.repos.agentic_artifact_repo import AgentArtifactRepository
from app.repos.agentic_run_repo import AgentRunRepository

from .errors import AgentExecutionError, AgentExecutionPayloadError
from .factory import AgentRuntimeFactory


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    kind: str
    kernel_result: KernelRunResult | None = None
    summary: str | None = None
    artifacts_created: int = 0


class AgentExecutionJobHandlers:
    """Typed handlers only; queue leases and status finalization stay in Worker."""

    def __init__(
        self,
        settings: Settings,
        *,
        runtime_factory: AgentRuntimeFactory,
        run_repository: AgentRunRepository | None = None,
        artifact_repository: AgentArtifactRepository | None = None,
    ) -> None:
        self.settings = settings
        self.factory = runtime_factory
        self.runs = run_repository or AgentRunRepository()
        self.artifacts = artifact_repository or AgentArtifactRepository()

    async def execute(self, session: Session, *, job: AgentJobRecord, run: AgentRunRecord) -> JobExecutionResult:
        if job.job_type == "agent_run.dispatch":
            return await self._dispatch_agent_run(job=job, run=run)
        if job.job_type == "agent_run.resume":
            return await self._resume_agent_run(session, job=job, run=run)
        if job.job_type == "agent_run.cancel":
            return await self._cancel_agent_run(job=job, run=run)
        if job.job_type == "deep_research.dispatch":
            return await self._dispatch_deep_research(session, job=job, run=run)
        raise AgentExecutionPayloadError("unsupported_agent_execution_job")

    async def _dispatch_agent_run(self, *, job: AgentJobRecord, run: AgentRunRecord) -> JobExecutionResult:
        payload = _require_mapping(decode_json(job.payload_json, fallback={}))
        if payload.get("runKind") != "agent_run":
            raise AgentExecutionPayloadError()
        state = self._initial_state(run=run, payload=payload)
        kernel = await self.factory.build_agent_kernel(run=run, dispatch_payload=payload)
        try:
            result = await self._start_or_recover(
                kernel,
                state,
                checkpoint_expected=bool(run.checkpoint_ref),
            )
            return JobExecutionResult(kind="agent_run", kernel_result=result)
        finally:
            await _close_if_supported(kernel)

    async def _resume_agent_run(self, session: Session, *, job: AgentJobRecord, run: AgentRunRecord) -> JobExecutionResult:
        payload = _require_mapping(decode_json(job.payload_json, fallback={}))
        wait_id = payload.get("waitId")
        if not isinstance(wait_id, str) or not wait_id.strip() or "resume" not in payload:
            raise AgentExecutionPayloadError()
        wait = session.get(AgentWaitRecord, wait_id)
        if wait is None or wait.run_id != run.id or AgentWaitStatus(wait.status) != AgentWaitStatus.RESOLVED:
            raise AgentExecutionPayloadError("agent_resume_wait_not_resolved")
        kernel = await self.factory.build_agent_kernel(run=run, dispatch_payload=payload)
        try:
            result = await kernel.resume(run.id, payload["resume"], wait_id=wait_id)
            return JobExecutionResult(kind="agent_run", kernel_result=result)
        finally:
            await _close_if_supported(kernel)

    async def _cancel_agent_run(self, *, job: AgentJobRecord, run: AgentRunRecord) -> JobExecutionResult:
        payload = _require_mapping(decode_json(job.payload_json, fallback={}))
        reason = payload.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise AgentExecutionPayloadError()
        # A queued job can be cancelled before it produced a checkpoint. The
        # worker handles that durable no-checkpoint path without requiring a
        # provider/runtime factory.
        if not run.checkpoint_ref:
            return JobExecutionResult(kind="cancel", summary="cancelled_before_checkpoint")
        kernel = await self.factory.build_agent_kernel(run=run, dispatch_payload=payload)
        try:
            try:
                result = await kernel.cancel(run.id, reason=reason)
            except KernelRunNotFoundError:
                return JobExecutionResult(kind="cancel", summary="cancelled_before_checkpoint")
            return JobExecutionResult(kind="cancel", kernel_result=result)
        finally:
            await _close_if_supported(kernel)

    async def _dispatch_deep_research(
        self,
        session: Session,
        *,
        job: AgentJobRecord,
        run: AgentRunRecord,
    ) -> JobExecutionResult:
        payload = _require_mapping(decode_json(job.payload_json, fallback={}))
        if payload.get("runKind") != "deep_research":
            raise AgentExecutionPayloadError()
        raw_task = _require_mapping(payload.get("researchTask"))
        try:
            task = ResearchTaskPacket.model_validate(raw_task)
        except Exception as exc:  # noqa: BLE001 - worker records a stable schema error only.
            raise AgentExecutionPayloadError("invalid_research_task_packet") from exc
        if task.task_id != run.id or task.admin_actor_id != run.admin_actor_id:
            raise AgentExecutionPayloadError("research_task_run_mismatch")
        agent = await self.factory.build_deep_research_agent(run=run, research_task=task)
        try:
            result = await agent.run(task)
        finally:
            await _close_if_supported(agent)
        persisted_count = await self.factory.persist_deep_research_result(
            run=run,
            result=result,
            idempotency_key=job.id,
        )
        if persisted_count is None:
            # Bounded fixture factories used by legacy tests do not have the
            # R5 durable artifact adapter. Production factories always take
            # the branch above, including external storage for large packets.
            packet = result.research_packet.model_dump(mode="json")
            report = result.research_report.model_dump(mode="json")
            self.artifacts.create_next_version(
                session,
                thread_id=run.thread_id,
                run_id=run.id,
                admin_actor_id=run.admin_actor_id,
                artifact_type="research_packet",
                artifact_key=f"deep-research:{run.id}:packet",
                content=packet,
                schema_version=result.research_packet.schema_version,
                content_hash=canonical_hash(packet),
                media_type="application/json",
                idempotency_key=f"deep-research-packet:{job.id}",
            )
            self.artifacts.create_next_version(
                session,
                thread_id=run.thread_id,
                run_id=run.id,
                admin_actor_id=run.admin_actor_id,
                artifact_type="research_report",
                artifact_key=f"deep-research:{run.id}:report",
                content=report,
                schema_version="1.0",
                content_hash=canonical_hash(report),
                media_type="application/json",
                idempotency_key=f"deep-research-report:{job.id}",
            )
            persisted_count = 2
        return JobExecutionResult(
            kind="deep_research",
            summary=result.summary,
            artifacts_created=persisted_count,
        )

    def _initial_state(self, *, run: AgentRunRecord, payload: dict[str, object]) -> AgentTaskState:
        goal = payload.get("goal")
        criteria = payload.get("successCriteria", [])
        if not isinstance(goal, str) or not goal.strip() or not isinstance(criteria, list):
            raise AgentExecutionPayloadError()
        if any(not isinstance(item, str) or not item.strip() for item in criteria):
            raise AgentExecutionPayloadError()
        environment = EnvironmentRef(
            snapshot_id=run.environment_snapshot_id,
            snapshot_hash=canonical_hash(
                {
                    "snapshot_id": run.environment_snapshot_id,
                    "run_id": run.id,
                    "thread_id": run.thread_id,
                }
            ),
            source="admin_request_envelope",
        )
        return AgentTaskState(
            thread_id=run.thread_id,
            run_id=run.id,
            user_id=run.user_id,
            admin_actor_id=run.admin_actor_id,
            trigger=TriggerContext(
                trigger_type=TriggerType.ADMIN_API,
                source="agent_execution_worker",
                request_id=f"run:{run.id}",
            ),
            goal=GoalState(goal_id=f"goal:{run.id}", statement=goal, success_criteria=list(criteria)),
            plan=AgentPlan(
                plan_id=f"bootstrap:{run.id}",
                version=1,
                objective=goal,
                success_criteria=list(criteria),
                created_by_policy_version=run.policy_version,
            ),
            environment=environment,
            budget=AgentBudget(
                turns_remaining=self.settings.agentic_max_turns,
                skill_calls_remaining=self.settings.agentic_max_skill_calls,
                context_tokens_remaining=self.settings.agentic_max_context_tokens,
                cost_remaining=0.0,
                subagent_turns_remaining=self.settings.agentic_max_turns,
            ),
        )

    @staticmethod
    async def _start_or_recover(
        kernel: AgentKernel,
        state: AgentTaskState,
        *,
        checkpoint_expected: bool,
    ) -> KernelRunResult:
        get_result = getattr(kernel, "get_result", None)
        if get_result is not None:
            try:
                return await get_result(state.run_id)
            except KernelRunNotFoundError:
                if checkpoint_expected:
                    raise AgentExecutionError("agent_execution_checkpoint_unavailable", retryable=True) from None
        return await kernel.start(state)


def _require_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AgentExecutionPayloadError()
    return {str(key): item for key, item in value.items()}


async def _close_if_supported(value: object) -> None:
    close = getattr(value, "close", None)
    if close is None:
        return
    result = close()
    if isinstance(result, Awaitable):
        await result
