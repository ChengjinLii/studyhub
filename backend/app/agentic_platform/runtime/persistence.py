from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agentic_platform.domain.decision import AgentDecision
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.state import AgentTaskState, TerminalStatus
from app.agentic_platform.persistence.state_machine import InvalidStatusTransition
from app.models.agentic_runtime import AgentRunStatus, AgentStepRecord, AgentStepStatus, AgentWaitRecord, AgentWaitStatus
from app.repos.agentic_run_repo import AgentRunRepository

from .interrupts import DuplicateResumeError
from .nodes import RuntimeMetadata


SessionFactory = Callable[[], Session]


class SqlAlchemyRuntimePersistence:
    """Durable run/step/wait summary adapter outside the serializable graph state."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        repository: AgentRunRepository | None = None,
        metadata: RuntimeMetadata | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.repository = repository or AgentRunRepository()
        self.metadata = metadata or RuntimeMetadata()

    async def ensure_run(self, state: AgentTaskState) -> None:
        def operation(session: Session) -> None:
            thread = self.repository.get_thread(session, state.thread_id)
            if thread is None:
                self.repository.create_thread(
                    session,
                    thread_id=state.thread_id,
                    admin_actor_id=state.admin_actor_id,
                    user_id=state.user_id,
                    title=state.goal.statement[:512],
                )
            run, _created = self.repository.create_or_get_run(
                session,
                thread_id=state.thread_id,
                run_id=state.run_id,
                admin_actor_id=state.admin_actor_id,
                user_id=state.user_id,
                trigger_type=state.trigger.trigger_type.value,
                trigger_ref=state.trigger.request_id or state.trigger.event_id,
                runtime_version=self.metadata.runtime_version,
                policy_version=self.metadata.policy_version,
                environment_snapshot_id=state.environment.snapshot_id,
                idempotency_key=f"runtime:{state.run_id}",
            )
            if AgentRunStatus(run.status) == AgentRunStatus.CREATED:
                self.repository.transition_run_status(session, run_id=state.run_id, target_status=AgentRunStatus.RUNNING)

        self._transaction(operation)

    async def begin_turn(self, state: AgentTaskState, *, turn_index: int, decision: AgentDecision) -> str | None:
        def operation(session: Session) -> str:
            key = f"turn:{state.run_id}:{turn_index}:{canonical_hash(decision)[:24]}"
            step, _created = self.repository.create_or_get_step(
                session,
                run_id=state.run_id,
                step_index=turn_index,
                node_name="policy",
                plan_step_id=decision.plan_step_id,
                subagent_name=decision.delegate_agent,
                idempotency_key=key,
            )
            if AgentStepStatus(step.status) in {AgentStepStatus.PENDING, AgentStepStatus.WAITING}:
                self.repository.transition_step_status(session, step_id=step.id, target_status=AgentStepStatus.RUNNING)
            self.repository.set_current_step(session, run_id=state.run_id, step_id=step.id)
            return step.id

        return self._transaction(operation)

    async def complete_turn(
        self,
        state: AgentTaskState,
        *,
        step_id: str | None,
        state_before_hash: str,
        state_after_hash: str,
        decision: AgentDecision,
        observation_ref,
        terminal: bool = False,
        waiting: bool = False,
    ) -> None:
        if step_id is None:
            return

        def operation(session: Session) -> None:
            self.repository.record_step_outcome(
                session,
                step_id=step_id,
                state_before_hash=state_before_hash,
                state_after_hash=state_after_hash,
                state_abstract_key=self._state_abstract_key(state),
                action_type=decision.action_type.value,
                skill_name=decision.skill_name,
                observation_ref=observation_ref.artifact_id if observation_ref is not None else None,
                artifact_refs=[artifact.model_dump(mode="json") for artifact in state.active_artifacts],
            )
            target = AgentStepStatus.WAITING if waiting else AgentStepStatus.COMPLETED
            step = session.get(AgentStepRecord, step_id)
            if step is None:
                raise ValueError(f"agent step not found: {step_id}")
            if not waiting and AgentStepStatus(step.status) == AgentStepStatus.WAITING:
                self.repository.transition_step_status(session, step_id=step_id, target_status=AgentStepStatus.RUNNING)
            self.repository.transition_step_status(session, step_id=step_id, target_status=target)
            if terminal:
                self.repository.set_current_step(session, run_id=state.run_id, step_id=None)

        self._transaction(operation)

    async def create_wait(
        self,
        state: AgentTaskState,
        *,
        step_id: str | None,
        wait_type: str,
        request_payload: dict[str, Any],
        idempotency_key: str,
    ) -> str | None:
        def operation(session: Session) -> str:
            record, _created = self.repository.create_or_get_wait(
                session,
                run_id=state.run_id,
                step_id=step_id,
                wait_type=wait_type,
                request_payload=request_payload,
                idempotency_key=idempotency_key,
            )
            return record.id

        return self._transaction(operation)

    async def resolve_wait(self, state: AgentTaskState, *, wait_id: str | None, payload: dict[str, Any]) -> None:
        if wait_id is None:
            return

        def operation(session: Session) -> None:
            try:
                self.repository.resolve_wait(session, wait_id=wait_id, status=AgentWaitStatus.RESOLVED, resume_payload=payload)
            except InvalidStatusTransition as exc:
                raise DuplicateResumeError(f"wait was already resolved: {wait_id}") from exc

        self._transaction(operation)

    async def mark_waiting(self, state: AgentTaskState) -> None:
        def operation(session: Session) -> None:
            run = self.repository.require_run(session, state.run_id)
            if AgentRunStatus(run.status) != AgentRunStatus.WAITING:
                self.repository.transition_run_status(session, run_id=state.run_id, target_status=AgentRunStatus.WAITING)

        self._transaction(operation)

    async def mark_running(self, state: AgentTaskState) -> None:
        def operation(session: Session) -> None:
            run = self.repository.require_run(session, state.run_id)
            current = AgentRunStatus(run.status)
            if current in {AgentRunStatus.CREATED, AgentRunStatus.QUEUED, AgentRunStatus.WAITING}:
                self.repository.transition_run_status(session, run_id=state.run_id, target_status=AgentRunStatus.RUNNING)

        self._transaction(operation)

    async def save_checkpoint(self, state: AgentTaskState, *, checkpoint_ref: str, state_hash: str) -> None:
        self._transaction(
            lambda session: self.repository.save_run_checkpoint(
                session,
                run_id=state.run_id,
                checkpoint_ref=checkpoint_ref,
                state_hash=state_hash,
            )
        )

    async def finish_run(self, state: AgentTaskState, *, terminal_status: TerminalStatus, reason: str) -> None:
        def operation(session: Session) -> None:
            target = {
                TerminalStatus.COMPLETED: AgentRunStatus.COMPLETED,
                TerminalStatus.CANCELLED: AgentRunStatus.CANCELLED,
                TerminalStatus.FAILED: AgentRunStatus.FAILED,
                TerminalStatus.ABORTED: AgentRunStatus.FAILED,
            }[terminal_status]
            run = self.repository.require_run(session, state.run_id)
            if AgentRunStatus(run.status) != target:
                self.repository.transition_run_status(
                    session,
                    run_id=state.run_id,
                    target_status=target,
                    terminal_reason=reason,
                )

        self._transaction(operation)

    async def request_cancel(self, run_id: str, *, reason: str) -> None:
        def operation(session: Session) -> None:
            run = self.repository.require_run(session, run_id)
            current = AgentRunStatus(run.status)
            if current in {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED, AgentRunStatus.CANCELLING}:
                return
            if current in {AgentRunStatus.QUEUED, AgentRunStatus.RUNNING, AgentRunStatus.WAITING}:
                self.repository.transition_run_status(
                    session,
                    run_id=run_id,
                    target_status=AgentRunStatus.CANCELLING,
                    terminal_reason=reason,
                )
            else:
                self.repository.transition_run_status(
                    session,
                    run_id=run_id,
                    target_status=AgentRunStatus.CANCELLED,
                    terminal_reason=reason,
                )
            pending_waits = session.scalars(
                select(AgentWaitRecord).where(
                    AgentWaitRecord.run_id == run_id,
                    AgentWaitRecord.status == AgentWaitStatus.PENDING.value,
                )
            )
            for wait in pending_waits:
                self.repository.resolve_wait(
                    session,
                    wait_id=wait.id,
                    status=AgentWaitStatus.CANCELLED,
                    resume_payload={"reason": reason},
                )

        self._transaction(operation)

    def _transaction(self, operation):
        session = self.session_factory()
        try:
            result = operation(session)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _state_abstract_key(state: AgentTaskState) -> str:
        return canonical_hash(
            {
                "plan": [(step.step_id, step.status.value) for step in state.plan.steps],
                "pending": bool(state.pending_user_request or state.pending_approval or state.pending_event),
                "terminal": state.terminal.status.value if state.terminal else None,
            }
        )
