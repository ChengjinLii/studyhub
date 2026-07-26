from __future__ import annotations

from enum import StrEnum
from typing import Any

from langgraph.types import Command
from pydantic import Field

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.state import AgentTaskState, TerminalStatus
from app.agentic_platform.policy.base import AgentPolicy
from app.agentic_platform.policy.context_builder import ContextBuilder
from app.agentic_platform.skills.registry import SkillRegistry

from .checkpoint import InMemoryCheckpointHandle, RedisCheckpointAdapter, RuntimeCheckpointSnapshot
from .graph import build_agent_graph
from .interrupts import CancellationRegistry, DuplicateResumeError, ResumeCoordinator, RunNotWaitingError
from .nodes import (
    AgentGraphNodes,
    DefaultRuntimeCritic,
    DefaultRuntimeVerifier,
    InMemoryRuntimeArtifactStore,
    NullRuntimeEventSink,
    NullRuntimePersistence,
    NullTransitionSink,
    RuntimeArtifactStore,
    RuntimeCritic,
    RuntimeEventSink,
    RuntimeMetadata,
    RuntimePersistence,
    RuntimeVerifier,
    SkillActionExecutor,
    SubagentActionExecutor,
    TransitionSink,
    UnsupportedSubagentExecutor,
    dump_task_state,
)
from .routing import recursion_limit_for_state


class KernelRunStatus(StrEnum):
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABORTED = "aborted"


class KernelRunNotFoundError(LookupError):
    pass


class KernelRunAlreadyStartedError(RuntimeError):
    pass


class KernelRunResult(DomainModel):
    schema_version: str = "1.0"
    run_id: str = Field(min_length=1, max_length=128)
    graph_thread_id: str = Field(min_length=1, max_length=256)
    status: KernelRunStatus
    state: AgentTaskState
    state_hash: str = Field(min_length=1, max_length=128)
    checkpoint_ref: str = Field(min_length=1, max_length=2_048)
    pending_wait_id: str | None = Field(default=None, max_length=128)


class AgentKernel:
    """Persistent, interruptible scheduler around an open-ended AgentPolicy.

    The graph topology is fixed for auditability, but no business intent,
    Skill ordering, or replan count is encoded here.  The policy and registered
    capabilities choose the next atomic action subject only to explicit safety
    boundaries.
    """

    def __init__(
        self,
        *,
        policy: AgentPolicy,
        context_builder: ContextBuilder,
        skill_registry: SkillRegistry,
        skill_action_executor: SkillActionExecutor,
        checkpointer: Any | None = None,
        subagent_executor: SubagentActionExecutor | None = None,
        verifier: RuntimeVerifier | None = None,
        critic: RuntimeCritic | None = None,
        artifact_store: RuntimeArtifactStore | None = None,
        event_sink: RuntimeEventSink | None = None,
        transition_sink: TransitionSink | None = None,
        persistence: RuntimePersistence | None = None,
        metadata: RuntimeMetadata | None = None,
        redis_checkpoint_mirror: RedisCheckpointAdapter | None = None,
        resume_coordinator: ResumeCoordinator | None = None,
        cancellation_registry: CancellationRegistry | None = None,
    ) -> None:
        self.policy = policy
        self.context_builder = context_builder
        self.skill_registry = skill_registry
        self.checkpoint_handle = checkpointer or InMemoryCheckpointHandle()
        self.persistence = persistence or NullRuntimePersistence()
        self.redis_checkpoint_mirror = redis_checkpoint_mirror
        self.resume_coordinator = resume_coordinator or ResumeCoordinator()
        self.cancellation_registry = cancellation_registry or CancellationRegistry()
        self.metadata = metadata or RuntimeMetadata()
        self.nodes = AgentGraphNodes(
            policy=policy,
            context_builder=context_builder,
            skill_registry=skill_registry,
            skill_executor=skill_action_executor,
            subagent_executor=subagent_executor or UnsupportedSubagentExecutor(),
            verifier=verifier or DefaultRuntimeVerifier(),
            critic=critic or DefaultRuntimeCritic(),
            artifact_store=artifact_store or InMemoryRuntimeArtifactStore(),
            event_sink=event_sink or NullRuntimeEventSink(),
            transition_sink=transition_sink or NullTransitionSink(),
            persistence=self.persistence,
            cancellation_registry=self.cancellation_registry,
            metadata=self.metadata,
        )
        self.graph = build_agent_graph(self.nodes, checkpointer=self.checkpoint_handle.checkpointer)

    async def start(self, state: AgentTaskState) -> KernelRunResult:
        """Begin a new run; a reused run ID is rejected rather than overwritten."""

        if state.terminal is not None:
            raise ValueError("cannot start a terminal task state")
        async with self.resume_coordinator.hold(state.run_id):
            config = self._config_for_state(state)
            existing = await self.graph.aget_state(config)
            if existing.values:
                raise KernelRunAlreadyStartedError(f"agent run already has a checkpoint: {state.run_id}")
            await self.persistence.ensure_run(state)
            await self.graph.ainvoke(
                {
                    "task_state": dump_task_state(state),
                    "observation_summaries": [],
                    "action_fingerprints": [],
                    "turn_index": 0,
                    "event_sequence": 0,
                },
                config=config,
            )
            return await self._result_from_snapshot(state.run_id)

    async def resume(self, run_id: str, payload: object, *, wait_id: str | None = None) -> KernelRunResult:
        """Resume exactly the current interrupt, optionally pinning its wait id."""

        async with self.resume_coordinator.hold(run_id):
            snapshot = await self._require_snapshot(run_id)
            state = AgentTaskState.model_validate(snapshot.values["task_state"])
            current_wait_id = snapshot.values.get("pending_wait_id")
            if state.terminal is not None or not self._is_waiting(state):
                raise RunNotWaitingError(f"agent run is not waiting: {run_id}")
            if wait_id is not None and wait_id != current_wait_id:
                raise DuplicateResumeError(f"wait {wait_id} is no longer current for run {run_id}")
            await self.persistence.mark_running(state)
            await self.graph.ainvoke(Command(resume=payload), config=self._config_for_state(state))
            return await self._result_from_snapshot(run_id)

    async def cancel(self, run_id: str, *, reason: str = "cancelled_by_admin") -> KernelRunResult:
        """Request a safe terminal path; a dynamic interrupt is resumed only to cancel."""

        normalized_reason = " ".join(reason.split()).strip() or "cancelled_by_admin"
        async with self.resume_coordinator.hold(run_id):
            snapshot = await self._require_snapshot(run_id)
            state = AgentTaskState.model_validate(snapshot.values["task_state"])
            if state.terminal is not None:
                return await self._result_from_snapshot(run_id)
            self.cancellation_registry.request(run_id, reason=normalized_reason)
            await self.persistence.request_cancel(run_id, reason=normalized_reason)
            config = self._config_for_state(state)
            if self._is_waiting(state):
                await self.graph.ainvoke(Command(resume={"cancel": True}), config=config)
            else:
                await self.graph.ainvoke(None, config=config)
            return await self._result_from_snapshot(run_id)

    async def get_result(self, run_id: str) -> KernelRunResult:
        return await self._result_from_snapshot(run_id)

    async def close(self) -> None:
        close = getattr(self.checkpoint_handle, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    async def _require_snapshot(self, run_id: str):
        config = self._config_for_run_id(run_id, recursion_limit=64)
        snapshot = await self.graph.aget_state(config)
        if not snapshot.values or "task_state" not in snapshot.values:
            raise KernelRunNotFoundError(f"agent run checkpoint not found: {run_id}")
        return snapshot

    async def _result_from_snapshot(self, run_id: str) -> KernelRunResult:
        snapshot = await self._require_snapshot(run_id)
        state = AgentTaskState.model_validate(snapshot.values["task_state"])
        state_hash = canonical_hash(state)
        graph_thread_id = self._graph_thread_id(run_id)
        checkpoint_ref = self.checkpoint_handle.checkpoint_ref(graph_thread_id)
        await self.persistence.save_checkpoint(state, checkpoint_ref=checkpoint_ref, state_hash=state_hash)
        if self.redis_checkpoint_mirror is not None:
            self.redis_checkpoint_mirror.save(
                RuntimeCheckpointSnapshot(
                    graph_thread_id=graph_thread_id,
                    run_id=run_id,
                    state_hash=state_hash,
                    graph_state=dict(snapshot.values),
                    next_nodes=list(snapshot.next),
                )
            )
        return KernelRunResult(
            run_id=run_id,
            graph_thread_id=graph_thread_id,
            status=self._status_for_state(state),
            state=state,
            state_hash=state_hash,
            checkpoint_ref=checkpoint_ref,
            pending_wait_id=snapshot.values.get("pending_wait_id"),
        )

    @staticmethod
    def _is_waiting(state: AgentTaskState) -> bool:
        return any((state.pending_user_request, state.pending_approval, state.pending_event))

    @classmethod
    def _status_for_state(cls, state: AgentTaskState) -> KernelRunStatus:
        if state.terminal is None:
            if cls._is_waiting(state):
                return KernelRunStatus.WAITING
            raise RuntimeError("graph stopped without a terminal or waiting task state")
        return {
            TerminalStatus.COMPLETED: KernelRunStatus.COMPLETED,
            TerminalStatus.FAILED: KernelRunStatus.FAILED,
            TerminalStatus.CANCELLED: KernelRunStatus.CANCELLED,
            TerminalStatus.ABORTED: KernelRunStatus.ABORTED,
        }[state.terminal.status]

    def _config_for_state(self, state: AgentTaskState) -> dict[str, Any]:
        return self._config_for_run_id(state.run_id, recursion_limit=recursion_limit_for_state(state))

    def _config_for_run_id(self, run_id: str, *, recursion_limit: int) -> dict[str, Any]:
        return {
            "recursion_limit": recursion_limit,
            "configurable": {"thread_id": self._graph_thread_id(run_id)},
        }

    @staticmethod
    def _graph_thread_id(run_id: str) -> str:
        return f"agent-run:{run_id}"
