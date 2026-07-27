from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from enum import StrEnum
from typing import Any, Protocol

from langgraph.types import Command, interrupt
from pydantic import Field, field_validator

from app.agentic_platform.domain import DomainModel, apply_state_delta
from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.domain.data_policy import TrainingDataPolicy
from app.agentic_platform.domain.decision import AgentActionType, AgentDecision, AgentOutput
from app.agentic_platform.domain.hashing import canonical_hash, json_schema_hash
from app.agentic_platform.domain.observation import Observation, ObservationSource
from app.agentic_platform.domain.reward_facts import RewardFacts
from app.agentic_platform.domain.state import AgentTaskState, FailureRecord, StateDelta, TerminalState, TerminalStatus
from app.agentic_platform.domain.state_abstract import state_group_key_v2
from app.agentic_platform.domain.transition import (
    AgentTransitionEvent,
    ExecutionError,
    ModelTurnEvent,
    ModelTurnPurpose,
    VerifierResult,
)
from app.agentic_platform.policy.base import AgentPolicy
from app.agentic_platform.policy.context_builder import ContextBuilder
from app.agentic_platform.policy.context_view import ContextPurpose, ContextView
from app.agentic_platform.policy.turn_result import PolicyTurnResult, unwrap_policy_output
from app.agentic_platform.skills.context import SkillExecutionContext
from app.agentic_platform.skills.executor import SkillExecutionError, SkillExecutor
from app.agentic_platform.skills.registry import SkillRegistry

from .budget import BudgetExhaustedError, BudgetGuard, merge_state_deltas
from .duplicate_detector import DuplicateActionDetector, NoStateDeltaDetector
from .interrupts import CancellationRegistry, safe_resume_payload
from .routing import KernelRoute, route_for_action


class RuntimeEventName(StrEnum):
    RUN_STARTED = "run.started"
    PLAN_CREATED = "plan.created"
    PLAN_REVISED = "plan.revised"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    SKILL_STARTED = "skill.started"
    SKILL_COMPLETED = "skill.completed"
    SUBAGENT_STARTED = "subagent.started"
    SUBAGENT_COMPLETED = "subagent.completed"
    CONTEXT_COMPRESSED = "context.compressed"
    ARTIFACT_CREATED = "artifact.created"
    USER_INPUT_REQUIRED = "user_input.required"
    APPROVAL_REQUIRED = "approval.required"
    RUN_WAITING = "run.waiting"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


class RuntimeEvent(DomainModel):
    schema_version: str = "1.0"
    name: RuntimeEventName
    thread_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class RuntimeEventSink(Protocol):
    async def emit(self, event: RuntimeEvent) -> None:
        ...


class TransitionSink(Protocol):
    async def emit(self, event: AgentTransitionEvent) -> None:
        ...


class ModelTurnSink(Protocol):
    """Records every successful model invocation, including non-action turns."""

    async def emit_model_turn(self, event: ModelTurnEvent) -> None:
        ...


class InMemoryRuntimeEventSink:
    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    async def emit(self, event: RuntimeEvent) -> None:
        self.events.append(event.model_copy(deep=True))


class InMemoryTransitionSink:
    def __init__(self) -> None:
        self.events: list[AgentTransitionEvent] = []
        self._hashes_by_id: dict[str, str] = {}

    async def emit(self, event: AgentTransitionEvent) -> None:
        event_hash = event.canonical_hash()
        existing = self._hashes_by_id.get(event.transition_id)
        if existing is not None:
            if existing != event_hash:
                raise ValueError(f"transition id collision: {event.transition_id}")
            return
        self._hashes_by_id[event.transition_id] = event_hash
        self.events.append(event.model_copy(deep=True))


class InMemoryModelTurnSink:
    def __init__(self) -> None:
        self.events: list[ModelTurnEvent] = []
        self._hashes_by_id: dict[str, str] = {}

    async def emit_model_turn(self, event: ModelTurnEvent) -> None:
        event_hash = canonical_hash(event)
        existing = self._hashes_by_id.get(event.model_turn_id)
        if existing is not None:
            if existing != event_hash:
                raise ValueError(f"model turn id collision: {event.model_turn_id}")
            return
        self._hashes_by_id[event.model_turn_id] = event_hash
        self.events.append(event.model_copy(deep=True))


class NullRuntimeEventSink:
    async def emit(self, event: RuntimeEvent) -> None:
        del event


class NullTransitionSink:
    async def emit(self, event: AgentTransitionEvent) -> None:
        del event


class NullModelTurnSink:
    async def emit_model_turn(self, event: ModelTurnEvent) -> None:
        del event


class RuntimeArtifactStore(Protocol):
    async def store_json(
        self,
        state: AgentTaskState,
        *,
        artifact_type: ArtifactKind | str,
        artifact_key: str,
        payload: object,
        summary: str,
        idempotency_key: str,
    ) -> ArtifactRef:
        ...


class InMemoryRuntimeArtifactStore:
    """Artifact-first test adapter with idempotency and monotonically versioned refs."""

    def __init__(self) -> None:
        self.payloads: dict[str, object] = {}
        self._by_idempotency: dict[tuple[str, str], ArtifactRef] = {}
        self._versions: dict[tuple[str, str, str], int] = {}

    async def store_json(
        self,
        state: AgentTaskState,
        *,
        artifact_type: ArtifactKind | str,
        artifact_key: str,
        payload: object,
        summary: str,
        idempotency_key: str,
    ) -> ArtifactRef:
        idempotency = (state.thread_id, idempotency_key)
        existing = self._by_idempotency.get(idempotency)
        if existing is not None:
            return existing.model_copy(deep=True)
        kind = str(artifact_type)
        version_key = (state.thread_id, kind, artifact_key)
        version = self._versions.get(version_key, 0) + 1
        self._versions[version_key] = version
        content_hash = canonical_hash(payload)
        artifact_id = f"artifact_{content_hash[:24]}_{version}"
        reference = ArtifactRef(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            version=version,
            uri=f"artifact://agentic/{artifact_id}/v{version}",
            content_hash=content_hash,
            media_type="application/json",
            summary=summary[:1_024],
        )
        self.payloads[artifact_id] = payload
        self._by_idempotency[idempotency] = reference.model_copy(deep=True)
        return reference


class ActionExecutionResult(DomainModel):
    state_delta: StateDelta = Field(default_factory=StateDelta)
    observation: Observation | None = None
    verifier_result: VerifierResult | None = None
    reward_facts: RewardFacts = Field(default_factory=RewardFacts)
    error: ExecutionError | None = None
    estimated_cost: float = Field(default=0.0, ge=0.0)
    subagent_turns_used: int = Field(default=0, ge=0)


class PostVerificationRoute(StrEnum):
    POLICY = "policy"
    PLANNER = "planner"
    CRITIC = "critic"
    FINALIZER = "finalizer"


class VerificationOutcome(DomainModel):
    state_delta: StateDelta = Field(default_factory=StateDelta)
    result: VerifierResult
    next_route: PostVerificationRoute = PostVerificationRoute.POLICY


class SkillActionExecutor(Protocol):
    async def execute(self, state: AgentTaskState, decision: AgentDecision, *, idempotency_key: str) -> ActionExecutionResult:
        ...


class SubagentActionExecutor(Protocol):
    async def execute(self, state: AgentTaskState, decision: AgentDecision, *, idempotency_key: str) -> ActionExecutionResult:
        ...


class ParentTransitionAwareSubagentExecutor(Protocol):
    """Optional extension for delegates that emit their own child trajectory."""

    async def execute_with_parent_transition(
        self,
        state: AgentTaskState,
        decision: AgentDecision,
        *,
        idempotency_key: str,
        parent_transition_id: str,
    ) -> ActionExecutionResult:
        ...


class RuntimeVerifier(Protocol):
    async def verify(
        self,
        state: AgentTaskState,
        decision: AgentDecision,
        execution: ActionExecutionResult,
    ) -> VerificationOutcome:
        ...


class RuntimeCritic(Protocol):
    async def critique(
        self,
        state: AgentTaskState,
        decision: AgentDecision,
        verification: VerificationOutcome,
    ) -> VerificationOutcome:
        ...


class DefaultRuntimeVerifier:
    async def verify(
        self,
        state: AgentTaskState,
        decision: AgentDecision,
        execution: ActionExecutionResult,
    ) -> VerificationOutcome:
        del state, decision
        result = execution.verifier_result or VerifierResult(
            passed=execution.error is None,
            summary="Action completed." if execution.error is None else execution.error.summary,
        )
        return VerificationOutcome(result=result)


class DefaultRuntimeCritic:
    async def critique(
        self,
        state: AgentTaskState,
        decision: AgentDecision,
        verification: VerificationOutcome,
    ) -> VerificationOutcome:
        del state, decision
        return verification.model_copy(deep=True, update={"next_route": PostVerificationRoute.POLICY})


class UnsupportedSubagentExecutor:
    async def execute(self, state: AgentTaskState, decision: AgentDecision, *, idempotency_key: str) -> ActionExecutionResult:
        del state, decision, idempotency_key
        return ActionExecutionResult(
            error=ExecutionError(
                code="subagent_not_configured",
                summary="No subagent adapter is configured for this runtime.",
                retryable=False,
            )
        )


SkillContextFactory = Callable[[AgentTaskState, AgentDecision], SkillExecutionContext]


class RegistrySkillActionExecutor:
    """Executes any currently registered Skill without central tool sequencing."""

    def __init__(
        self,
        *,
        registry: SkillRegistry,
        executor: SkillExecutor,
        context_factory: SkillContextFactory,
        artifact_store: RuntimeArtifactStore,
    ) -> None:
        self.registry = registry
        self.executor = executor
        self.context_factory = context_factory
        self.artifact_store = artifact_store

    async def execute(self, state: AgentTaskState, decision: AgentDecision, *, idempotency_key: str) -> ActionExecutionResult:
        if decision.skill_name is None or decision.arguments is None:
            raise ValueError("execute_skill decisions require skill_name and arguments")
        try:
            skill = self.registry.get(decision.skill_name)
            context = self.context_factory(state, decision)
            if context.idempotency_key is None:
                context = replace(context, idempotency_key=idempotency_key)
            result = await self.executor.execute(
                skill_name=decision.skill_name,
                arguments=decision.arguments,
                context=context,
            )
            reference = await self.artifact_store.store_json(
                state,
                artifact_type=ArtifactKind.OBSERVATION,
                artifact_key=f"skill:{decision.skill_name}",
                payload=result.output.model_dump(mode="json"),
                summary=f"Typed output from Skill {decision.skill_name}",
                idempotency_key=f"observation:{idempotency_key}",
            )
            observation = Observation(
                observation_id=f"observation_{canonical_hash({'run': state.run_id, 'key': idempotency_key})[:24]}",
                source=ObservationSource.SKILL,
                summary=f"Skill {decision.skill_name} completed with {result.output.__class__.__name__}.",
                artifact_ref=reference,
            )
            return ActionExecutionResult(
                state_delta=StateDelta(artifact_refs_to_add=[reference]),
                observation=observation,
                estimated_cost=result.estimated_cost,
            )
        except Exception as exc:  # noqa: BLE001 - converted to a safe structured runtime outcome.
            retryable = isinstance(exc, SkillExecutionError) and exc.retryable
            code = exc.code if isinstance(exc, SkillExecutionError) else "skill_execution_error"
            return ActionExecutionResult(
                error=ExecutionError(code=code, summary=f"Skill {decision.skill_name} failed.", retryable=retryable)
            )


class RuntimePersistence(Protocol):
    async def ensure_run(self, state: AgentTaskState) -> None:
        ...

    async def begin_turn(self, state: AgentTaskState, *, turn_index: int, decision: AgentDecision) -> str | None:
        ...

    async def complete_turn(
        self,
        state: AgentTaskState,
        *,
        step_id: str | None,
        state_before_hash: str,
        state_after_hash: str,
        decision: AgentDecision,
        observation_ref: ArtifactRef | None,
        terminal: bool = False,
        waiting: bool = False,
    ) -> None:
        ...

    async def create_wait(
        self,
        state: AgentTaskState,
        *,
        step_id: str | None,
        wait_type: str,
        request_payload: dict[str, Any],
        idempotency_key: str,
    ) -> str | None:
        ...

    async def resolve_wait(self, state: AgentTaskState, *, wait_id: str | None, payload: dict[str, Any]) -> None:
        ...

    async def mark_waiting(self, state: AgentTaskState) -> None:
        ...

    async def mark_running(self, state: AgentTaskState) -> None:
        ...

    async def save_checkpoint(self, state: AgentTaskState, *, checkpoint_ref: str, state_hash: str) -> None:
        ...

    async def finish_run(self, state: AgentTaskState, *, terminal_status: TerminalStatus, reason: str) -> None:
        ...

    async def request_cancel(self, run_id: str, *, reason: str) -> None:
        ...


class NullRuntimePersistence:
    async def ensure_run(self, state: AgentTaskState) -> None:
        del state

    async def begin_turn(self, state: AgentTaskState, *, turn_index: int, decision: AgentDecision) -> str | None:
        del state, decision
        return f"step-turn-{turn_index}"

    async def complete_turn(
        self,
        state: AgentTaskState,
        *,
        step_id: str | None,
        state_before_hash: str,
        state_after_hash: str,
        decision: AgentDecision,
        observation_ref: ArtifactRef | None,
        terminal: bool = False,
        waiting: bool = False,
    ) -> None:
        del state, step_id, state_before_hash, state_after_hash, decision, observation_ref, terminal, waiting

    async def create_wait(
        self,
        state: AgentTaskState,
        *,
        step_id: str | None,
        wait_type: str,
        request_payload: dict[str, Any],
        idempotency_key: str,
    ) -> str | None:
        del state, step_id, wait_type, request_payload
        return f"wait-{canonical_hash(idempotency_key)[:24]}"

    async def resolve_wait(self, state: AgentTaskState, *, wait_id: str | None, payload: dict[str, Any]) -> None:
        del state, wait_id, payload

    async def mark_waiting(self, state: AgentTaskState) -> None:
        del state

    async def mark_running(self, state: AgentTaskState) -> None:
        del state

    async def save_checkpoint(self, state: AgentTaskState, *, checkpoint_ref: str, state_hash: str) -> None:
        del state, checkpoint_ref, state_hash

    async def finish_run(self, state: AgentTaskState, *, terminal_status: TerminalStatus, reason: str) -> None:
        del state, terminal_status, reason

    async def request_cancel(self, run_id: str, *, reason: str) -> None:
        del run_id, reason


class RuntimeMetadata(DomainModel):
    runtime_version: str = Field(default="agent-kernel-v1", min_length=1, max_length=128)
    policy_version: str = Field(default="policy-v1", min_length=1, max_length=128)
    model_id: str = Field(default="policy-adapter", min_length=1, max_length=256)
    model_revision: str | None = Field(default=None, max_length=256)
    trainable_turn_purposes: list[ModelTurnPurpose] = Field(
        default_factory=lambda: [ModelTurnPurpose.POLICY, ModelTurnPurpose.FINALIZER]
    )
    data_policy: TrainingDataPolicy = Field(default_factory=TrainingDataPolicy.internal_eval_only)

    @field_validator("trainable_turn_purposes")
    @classmethod
    def _validate_trainable_turn_purposes(cls, values: list[ModelTurnPurpose]) -> list[ModelTurnPurpose]:
        if len(values) != len(set(values)):
            raise ValueError("trainable turn purposes must be unique")
        return values


def dump_task_state(state: AgentTaskState) -> dict[str, Any]:
    return state.model_dump(mode="json")


def load_task_state(graph_state: Mapping[str, Any]) -> AgentTaskState:
    try:
        raw = graph_state["task_state"]
    except KeyError as exc:
        raise ValueError("graph state has no task_state") from exc
    return AgentTaskState.model_validate(raw)


def load_stored_state(value: object) -> AgentTaskState:
    return AgentTaskState.model_validate(value)


def load_decision(graph_state: Mapping[str, Any]) -> AgentDecision:
    try:
        raw = graph_state["decision"]
    except KeyError as exc:
        raise ValueError("graph state has no decision") from exc
    return AgentDecision.model_validate(raw)


def load_delta(graph_state: Mapping[str, Any], field_name: str = "turn_delta") -> StateDelta:
    return StateDelta.model_validate(graph_state.get(field_name) or {})


def load_artifact_ref(graph_state: Mapping[str, Any], field_name: str) -> ArtifactRef:
    try:
        raw = graph_state[field_name]
    except KeyError as exc:
        raise ValueError(f"graph state has no {field_name}") from exc
    return ArtifactRef.model_validate(raw)


class AgentGraphNodes:
    """Low-level StateGraph nodes; all business choices stay in supplied adapters."""

    def __init__(
        self,
        *,
        policy: AgentPolicy,
        context_builder: ContextBuilder,
        skill_registry: SkillRegistry,
        skill_executor: SkillActionExecutor,
        subagent_executor: SubagentActionExecutor,
        verifier: RuntimeVerifier,
        critic: RuntimeCritic,
        artifact_store: RuntimeArtifactStore,
        event_sink: RuntimeEventSink,
        transition_sink: TransitionSink,
        model_turn_sink: ModelTurnSink,
        persistence: RuntimePersistence,
        cancellation_registry: CancellationRegistry,
        metadata: RuntimeMetadata,
    ) -> None:
        self.policy = policy
        self.context_builder = context_builder
        self.skill_registry = skill_registry
        self.skill_executor = skill_executor
        self.subagent_executor = subagent_executor
        self.verifier = verifier
        self.critic = critic
        self.artifact_store = artifact_store
        self.event_sink = event_sink
        self.transition_sink = transition_sink
        self.model_turn_sink = model_turn_sink
        self.persistence = persistence
        self.cancellation_registry = cancellation_registry
        self.metadata = metadata
        self.duplicate_detector = DuplicateActionDetector()
        self.no_delta_detector = NoStateDeltaDetector()

    async def bootstrap(self, graph_state: Mapping[str, Any]) -> Command:
        state = load_task_state(graph_state)
        cancellation = self.cancellation_registry.requested_reason(state.run_id)
        if cancellation:
            return self._terminate(cancellation, TerminalStatus.CANCELLED)
        await self.persistence.mark_running(state)
        sequence = await self._emit(graph_state, state, RuntimeEventName.RUN_STARTED, {"runtime_version": self.metadata.runtime_version})
        return Command(update={"event_sequence": sequence}, goto="planner")

    async def planner(self, graph_state: Mapping[str, Any]) -> Command:
        state = load_task_state(graph_state)
        cancellation = self.cancellation_registry.requested_reason(state.run_id)
        if cancellation:
            return self._terminate(cancellation, TerminalStatus.CANCELLED)
        try:
            builder = self._budgeted_builder(state)
            context = builder.build_planner_context(state, self.skill_registry.list())
            context_ref = await self._store_context_view(
                state,
                context=context,
                artifact_key="planner-context",
                turn_index=int(graph_state.get("turn_index", 0)),
            )
            planner_turn = self._coerce_policy_turn(
                await self.policy.create_plan(state, context),
                context=context,
                purpose=ContextPurpose.PLANNER,
            )
            plan = planner_turn.parsed_output
            delta = merge_state_deltas(
                StateDelta(plan_update=plan),
                BudgetGuard.model_turn_delta(context_tokens=context.estimated_tokens),
            )
            successor = apply_state_delta(state, delta)
            await self._emit_standalone_model_turn(
                state_before=state,
                state_after=successor,
                context_ref=context_ref,
                turn=planner_turn,
                purpose=ModelTurnPurpose.PLANNER,
                turn_index=int(graph_state.get("turn_index", 0)),
                state_delta=delta,
            )
        except BudgetExhaustedError as exc:
            return self._terminate(exc.reason.value, TerminalStatus.ABORTED)
        except ValueError as exc:
            return self._terminate(f"planner_context_unavailable:{exc}", TerminalStatus.ABORTED)
        except Exception as exc:  # noqa: BLE001 - converted to a safe terminal outcome.
            return self._terminate(f"planner_failed:{exc.__class__.__name__}", TerminalStatus.FAILED)

        event_name = RuntimeEventName.PLAN_CREATED if plan.version <= 1 else RuntimeEventName.PLAN_REVISED
        sequence = await self._emit(
            graph_state,
            successor,
            event_name,
            {"plan_id": plan.plan_id, "plan_version": plan.version, "capability_count": context.capability_count},
        )
        update: dict[str, Any] = {
            "task_state": dump_task_state(successor),
            "planner_turn_result": planner_turn.runtime_metadata(),
            "observation_summaries": self._append_summary(
                graph_state,
                f"Plan {plan.plan_id} version {plan.version} is available for policy selection.",
            ),
            "event_sequence": sequence,
        }
        if context.truncated:
            update["event_sequence"] = await self._emit(
                {**graph_state, **update},
                successor,
                RuntimeEventName.CONTEXT_COMPRESSED,
                {"purpose": "planner", "token_budget": context.token_budget},
            )
        return Command(update=update, goto="policy")

    async def policy_node(self, graph_state: Mapping[str, Any]) -> Command:
        state_before = load_task_state(graph_state)
        cancellation = self.cancellation_registry.requested_reason(state_before.run_id)
        if cancellation:
            return self._terminate(cancellation, TerminalStatus.CANCELLED)
        try:
            builder = self._budgeted_builder(state_before)
            context = builder.build_policy_context(
                state_before,
                self.skill_registry.list(),
                observation_summaries=graph_state.get("observation_summaries", []),
            )
            context_ref = await self._store_context_view(
                state_before,
                context=context,
                artifact_key="policy-context",
                turn_index=int(graph_state.get("turn_index", 0)),
            )
            policy_turn = self._coerce_policy_turn(
                await self.policy.decide(state_before, context),
                context=context,
                purpose=ContextPurpose.POLICY,
            )
            decision = policy_turn.parsed_output
            assessment = self.duplicate_detector.assess(decision, list(graph_state.get("action_fingerprints", [])))
            base_delta = BudgetGuard.model_turn_delta(context_tokens=context.estimated_tokens)
            state_after_decision = apply_state_delta(state_before, base_delta)
        except BudgetExhaustedError as exc:
            return self._terminate(exc.reason.value, TerminalStatus.ABORTED)
        except ValueError as exc:
            return self._terminate(f"policy_context_unavailable:{exc}", TerminalStatus.ABORTED)
        except Exception as exc:  # noqa: BLE001 - an adapter failure must not leak its raw details.
            return self._terminate(f"policy_failed:{exc.__class__.__name__}", TerminalStatus.FAILED)

        turn_index = int(graph_state.get("turn_index", 0))
        step_id = await self.persistence.begin_turn(state_before, turn_index=turn_index, decision=decision)
        sequence = await self._emit(
            graph_state,
            state_after_decision,
            RuntimeEventName.STEP_STARTED,
            {"turn_index": turn_index, "action_type": decision.action_type.value, "plan_step_id": decision.plan_step_id},
        )
        update: dict[str, Any] = {
            "task_state": dump_task_state(state_after_decision),
            "decision": decision.model_dump(mode="json"),
            "turn_state_before": dump_task_state(state_before),
            "turn_delta": base_delta.model_dump(mode="json"),
            "turn_index": turn_index + 1,
            "current_step_id": step_id,
            "context_ref": context_ref.model_dump(mode="json"),
            "context_catalog_hash": context.capability_catalog_hash,
            "policy_turn_result": policy_turn.runtime_metadata(),
            "action_fingerprints": [*graph_state.get("action_fingerprints", []), assessment.fingerprint],
            "duplicate_action": assessment.is_duplicate,
            "event_sequence": sequence,
        }
        if context.truncated:
            update["event_sequence"] = await self._emit(
                {**graph_state, **update},
                state_after_decision,
                RuntimeEventName.CONTEXT_COMPRESSED,
                {"purpose": "policy", "token_budget": context.token_budget},
            )

        next_route = route_for_action(decision.action_type)
        if next_route == KernelRoute.PLANNER:
            return await self._complete_immediate_turn(
                graph_state,
                update,
                state_before,
                decision,
                base_delta,
                context_ref,
                goto="planner",
            )
        if decision.action_type in {AgentActionType.ASK_USER, AgentActionType.REQUEST_APPROVAL, AgentActionType.WAIT_EVENT}:
            return await self._create_wait(graph_state, update, state_before, decision, base_delta, context_ref)
        if next_route == KernelRoute.FINALIZER:
            status = TerminalStatus.COMPLETED if decision.action_type == AgentActionType.FINALIZE else TerminalStatus.ABORTED
            reason = "policy_finalize" if status == TerminalStatus.COMPLETED else "policy_abort"
            update["termination_status"] = status.value
            update["termination_reason"] = reason
            return await self._complete_immediate_turn(
                graph_state,
                update,
                state_before,
                decision,
                base_delta,
                context_ref,
                goto="finalizer",
            )
        if next_route == KernelRoute.SKILL_EXECUTOR:
            return Command(update=update, goto="skill_executor")
        if next_route == KernelRoute.SUBAGENT_EXECUTOR:
            return Command(update=update, goto="subagent_executor")

        # REVIEW, WRITE_ARTIFACT and MANAGE_CONTEXT remain dynamically handled
        # by verifier/critic adapters rather than becoming scripted graph paths.
        update["execution"] = ActionExecutionResult().model_dump(mode="json")
        return Command(update=update, goto="verifier")

    async def skill_executor_node(self, graph_state: Mapping[str, Any]) -> Command:
        state = load_task_state(graph_state)
        decision = load_decision(graph_state)
        cancellation = self.cancellation_registry.requested_reason(state.run_id)
        if cancellation:
            return self._terminate(cancellation, TerminalStatus.CANCELLED)
        try:
            if decision.skill_name is None:
                raise ValueError("execute_skill decision has no skill_name")
            skill = self.skill_registry.get(decision.skill_name)
            BudgetGuard.assert_skill_available(state, estimated_cost=skill.spec.cost_model.fixed_cost)
            sequence = await self._emit(
                graph_state,
                state,
                RuntimeEventName.SKILL_STARTED,
                {"skill_name": decision.skill_name, "plan_step_id": decision.plan_step_id},
            )
            execution = await self.skill_executor.execute(
                state,
                decision,
                idempotency_key=self._turn_idempotency_key(graph_state, decision),
            )
            action_delta = merge_state_deltas(
                execution.state_delta,
                BudgetGuard.skill_call_delta(
                    estimated_cost=execution.estimated_cost,
                    context_tokens=skill.spec.cost_model.estimated_context_tokens,
                ),
                self._failure_delta(graph_state, execution.error),
            )
            successor = apply_state_delta(state, action_delta)
        except BudgetExhaustedError as exc:
            return self._terminate(exc.reason.value, TerminalStatus.ABORTED)
        except Exception as exc:  # noqa: BLE001
            execution = ActionExecutionResult(
                error=ExecutionError(code="skill_node_failed", summary="Skill execution node failed.", retryable=False)
            )
            action_delta = self._failure_delta(graph_state, execution.error)
            successor = apply_state_delta(state, action_delta)
            sequence = int(graph_state.get("event_sequence", 0))

        sequence = await self._emit(
            {**graph_state, "event_sequence": sequence},
            successor,
            RuntimeEventName.SKILL_COMPLETED,
            {
                "skill_name": decision.skill_name,
                "success": execution.error is None,
                "observation_id": execution.observation.observation_id if execution.observation else None,
            },
        )
        return Command(
            update={
                "task_state": dump_task_state(successor),
                "turn_delta": merge_state_deltas(load_delta(graph_state), action_delta).model_dump(mode="json"),
                "execution": execution.model_dump(mode="json"),
                "observation_summaries": self._append_summary(
                    graph_state,
                    execution.observation.summary if execution.observation else "Skill execution produced no observation.",
                ),
                "event_sequence": sequence,
            },
            goto="verifier",
        )

    async def subagent_executor_node(self, graph_state: Mapping[str, Any]) -> Command:
        state = load_task_state(graph_state)
        decision = load_decision(graph_state)
        cancellation = self.cancellation_registry.requested_reason(state.run_id)
        if cancellation:
            return self._terminate(cancellation, TerminalStatus.CANCELLED)
        try:
            BudgetGuard.assert_subagent_available(state)
            sequence = await self._emit(
                graph_state,
                state,
                RuntimeEventName.SUBAGENT_STARTED,
                {"subagent_name": decision.delegate_agent, "plan_step_id": decision.plan_step_id},
            )
            state_before = load_stored_state(graph_state.get("turn_state_before"))
            parent_transition_id = self._transition_id(graph_state, state_before, decision)
            execute_with_parent = getattr(self.subagent_executor, "execute_with_parent_transition", None)
            if callable(execute_with_parent):
                execution = await execute_with_parent(
                    state,
                    decision,
                    idempotency_key=self._turn_idempotency_key(graph_state, decision),
                    parent_transition_id=parent_transition_id,
                )
            else:
                execution = await self.subagent_executor.execute(
                    state,
                    decision,
                    idempotency_key=self._turn_idempotency_key(graph_state, decision),
                )
            consumed_turns = max(1, execution.subagent_turns_used)
            action_delta = merge_state_deltas(
                execution.state_delta,
                BudgetGuard.subagent_turn_delta(turns=consumed_turns),
                self._failure_delta(graph_state, execution.error),
            )
            successor = apply_state_delta(state, action_delta)
        except BudgetExhaustedError as exc:
            return self._terminate(exc.reason.value, TerminalStatus.ABORTED)
        except Exception:  # noqa: BLE001
            execution = ActionExecutionResult(
                error=ExecutionError(code="subagent_node_failed", summary="Subagent execution node failed.", retryable=False)
            )
            action_delta = self._failure_delta(graph_state, execution.error)
            successor = apply_state_delta(state, action_delta)
            sequence = int(graph_state.get("event_sequence", 0))

        sequence = await self._emit(
            {**graph_state, "event_sequence": sequence},
            successor,
            RuntimeEventName.SUBAGENT_COMPLETED,
            {"subagent_name": decision.delegate_agent, "success": execution.error is None},
        )
        return Command(
            update={
                "task_state": dump_task_state(successor),
                "turn_delta": merge_state_deltas(load_delta(graph_state), action_delta).model_dump(mode="json"),
                "execution": execution.model_dump(mode="json"),
                "observation_summaries": self._append_summary(
                    graph_state,
                    execution.observation.summary if execution.observation else "Subagent execution completed.",
                ),
                "event_sequence": sequence,
            },
            goto="verifier",
        )

    async def interrupt_node(self, graph_state: Mapping[str, Any]) -> Command:
        state = load_task_state(graph_state)
        cancellation = self.cancellation_registry.requested_reason(state.run_id)
        if cancellation:
            return self._terminate(cancellation, TerminalStatus.CANCELLED)
        decision = load_decision(graph_state)
        pending = state.pending_user_request or state.pending_approval
        if pending is None:
            return Command(goto="policy")
        payload = self._interrupt_payload(graph_state, state, pending_kind="user_input" if state.pending_user_request else "approval")
        resumed = interrupt(payload)
        safe_payload = safe_resume_payload(resumed)
        clear_delta = StateDelta(
            clear_pending_user_request=state.pending_user_request is not None,
            clear_pending_approval=state.pending_approval is not None,
        )
        successor = apply_state_delta(state, clear_delta)
        await self.persistence.resolve_wait(
            successor,
            wait_id=graph_state.get("pending_wait_id"),
            payload=safe_payload.model_dump(mode="json"),
        )
        await self.persistence.mark_running(successor)
        await self.persistence.complete_turn(
            successor,
            step_id=graph_state.get("current_step_id"),
            state_before_hash=canonical_hash(load_stored_state(graph_state.get("turn_state_before"))),
            state_after_hash=canonical_hash(successor),
            decision=decision,
            observation_ref=None,
        )
        return Command(
            update={
                "task_state": dump_task_state(successor),
                "pending_wait_id": None,
                "observation_summaries": self._append_summary(
                    graph_state,
                    f"Administrator responded: {safe_payload.summary}",
                ),
            },
            goto="policy",
        )

    async def event_wait_node(self, graph_state: Mapping[str, Any]) -> Command:
        state = load_task_state(graph_state)
        cancellation = self.cancellation_registry.requested_reason(state.run_id)
        if cancellation:
            return self._terminate(cancellation, TerminalStatus.CANCELLED)
        decision = load_decision(graph_state)
        if state.pending_event is None:
            return Command(goto="policy")
        payload = self._interrupt_payload(graph_state, state, pending_kind="event")
        resumed = interrupt(payload)
        safe_payload = safe_resume_payload(resumed)
        successor = apply_state_delta(state, StateDelta(clear_pending_event=True))
        await self.persistence.resolve_wait(
            successor,
            wait_id=graph_state.get("pending_wait_id"),
            payload=safe_payload.model_dump(mode="json"),
        )
        await self.persistence.mark_running(successor)
        await self.persistence.complete_turn(
            successor,
            step_id=graph_state.get("current_step_id"),
            state_before_hash=canonical_hash(load_stored_state(graph_state.get("turn_state_before"))),
            state_after_hash=canonical_hash(successor),
            decision=decision,
            observation_ref=None,
        )
        return Command(
            update={
                "task_state": dump_task_state(successor),
                "pending_wait_id": None,
                "observation_summaries": self._append_summary(graph_state, f"Event arrived: {safe_payload.summary}"),
            },
            goto="policy",
        )

    async def verifier_node(self, graph_state: Mapping[str, Any]) -> Command:
        state = load_task_state(graph_state)
        decision = load_decision(graph_state)
        cancellation = self.cancellation_registry.requested_reason(state.run_id)
        if cancellation:
            return self._terminate(cancellation, TerminalStatus.CANCELLED)
        execution = ActionExecutionResult.model_validate(graph_state.get("execution") or {})
        try:
            verification = await self.verifier.verify(state, decision, execution)
            base_delta = merge_state_deltas(load_delta(graph_state), verification.state_delta)
            if verification.next_route == PostVerificationRoute.CRITIC:
                successor = apply_state_delta(load_stored_state(graph_state.get("turn_state_before")), base_delta)
                return Command(
                    update={
                        "task_state": dump_task_state(successor),
                        "turn_delta": base_delta.model_dump(mode="json"),
                        "verifier_result": verification.result.model_dump(mode="json"),
                        "execution": execution.model_dump(mode="json"),
                    },
                    goto="critic",
                )
            return await self._complete_turn(
                graph_state,
                state_before=load_stored_state(graph_state.get("turn_state_before")),
                state_current=state,
                decision=decision,
                delta=base_delta,
                context_ref=load_artifact_ref(graph_state, "context_ref"),
                execution=execution,
                verifier_result=verification.result,
                goto=verification.next_route.value,
            )
        except Exception:  # noqa: BLE001
            failure = ExecutionError(code="verifier_failed", summary="Verifier node failed.", retryable=False)
            execution = execution.model_copy(update={"error": execution.error or failure})
            return await self._complete_turn(
                graph_state,
                state_before=load_stored_state(graph_state.get("turn_state_before")),
                state_current=state,
                decision=decision,
                delta=merge_state_deltas(load_delta(graph_state), self._failure_delta(graph_state, failure)),
                context_ref=load_artifact_ref(graph_state, "context_ref"),
                execution=execution,
                verifier_result=VerifierResult(passed=False, summary="Verifier execution failed."),
                goto="policy",
            )

    async def critic_node(self, graph_state: Mapping[str, Any]) -> Command:
        state = load_task_state(graph_state)
        decision = load_decision(graph_state)
        execution = ActionExecutionResult.model_validate(graph_state.get("execution") or {})
        prior = VerificationOutcome(
            result=VerifierResult.model_validate(graph_state.get("verifier_result") or {"passed": True, "summary": "No verifier result."})
        )
        try:
            outcome = await self.critic.critique(state, decision, prior)
        except Exception:  # noqa: BLE001
            outcome = VerificationOutcome(result=VerifierResult(passed=False, summary="Critic execution failed."))
        return await self._complete_turn(
            graph_state,
            state_before=load_stored_state(graph_state.get("turn_state_before")),
            state_current=state,
            decision=decision,
            delta=merge_state_deltas(load_delta(graph_state), outcome.state_delta),
            context_ref=load_artifact_ref(graph_state, "context_ref"),
            execution=execution,
            verifier_result=outcome.result,
            goto=outcome.next_route.value,
        )

    async def finalizer_node(self, graph_state: Mapping[str, Any]) -> Command:
        state = load_task_state(graph_state)
        decision_raw = graph_state.get("decision")
        decision = AgentDecision.model_validate(decision_raw) if decision_raw else None
        status = TerminalStatus(graph_state.get("termination_status", TerminalStatus.COMPLETED.value))
        reason = str(graph_state.get("termination_reason") or "finalized")
        finalizer_turn: PolicyTurnResult[Any] | None = None
        if status != TerminalStatus.COMPLETED:
            output = AgentOutput(summary=f"Agent run ended safely: {reason}", user_visible=True)
        else:
            try:
                builder = self._budgeted_builder(state)
                context = builder.build_final_context(state)
                context_ref = await self._store_context_view(
                    state,
                    context=context,
                    artifact_key="finalizer-context",
                    turn_index=int(graph_state.get("turn_index", 0)),
                )
                finalizer_turn = self._coerce_policy_turn(
                    await self.policy.finalize(state, context),
                    context=context,
                    purpose=ContextPurpose.FINALIZER,
                )
                output = finalizer_turn.parsed_output
                await self._emit_standalone_model_turn(
                    state_before=state,
                    state_after=state,
                    context_ref=context_ref,
                    turn=finalizer_turn,
                    purpose=ModelTurnPurpose.FINALIZER,
                    turn_index=int(graph_state.get("turn_index", 0)),
                )
            except Exception:  # noqa: BLE001
                output = (
                    decision.final_output
                    if decision is not None and decision.final_output is not None
                    else AgentOutput(summary="Agent run completed; final output requires review.", user_visible=True)
                )
        update: dict[str, Any] = {
            "final_output": output.model_dump(mode="json"),
            "termination_status": status.value,
            "termination_reason": reason,
        }
        if finalizer_turn is not None:
            update["finalizer_turn_result"] = finalizer_turn.runtime_metadata()
        return Command(
            update=update,
            goto="artifact_persist",
        )

    async def artifact_persist_node(self, graph_state: Mapping[str, Any]) -> Command:
        state = load_task_state(graph_state)
        status = TerminalStatus(graph_state.get("termination_status", TerminalStatus.COMPLETED.value))
        reason = str(graph_state.get("termination_reason") or "finalized")
        output = AgentOutput.model_validate(graph_state.get("final_output"))
        reference = await self.artifact_store.store_json(
            state,
            artifact_type=ArtifactKind.OTHER,
            artifact_key="agent-final-output",
            payload=output.model_dump(mode="json"),
            summary="Administrator-visible agent final output",
            idempotency_key=f"final:{state.run_id}:{status.value}",
        )
        successor = apply_state_delta(
            state,
            StateDelta(
                artifact_refs_to_add=[reference],
                terminal=TerminalState(status=status, reason=reason, final_artifact_ref=reference),
            ),
        )
        await self.persistence.finish_run(successor, terminal_status=status, reason=reason)
        event_name = RuntimeEventName.RUN_COMPLETED if status == TerminalStatus.COMPLETED else RuntimeEventName.RUN_FAILED
        sequence = await self._emit(
            graph_state,
            successor,
            RuntimeEventName.ARTIFACT_CREATED,
            {"artifact_id": reference.artifact_id, "artifact_type": str(reference.artifact_type)},
        )
        sequence = await self._emit(
            {**graph_state, "event_sequence": sequence},
            successor,
            event_name,
            {"terminal_status": status.value, "reason": reason},
        )
        self.cancellation_registry.clear(successor.run_id)
        return Command(update={"task_state": dump_task_state(successor), "event_sequence": sequence}, goto="__end__")

    async def _create_wait(
        self,
        graph_state: Mapping[str, Any],
        update: dict[str, Any],
        state_before: AgentTaskState,
        decision: AgentDecision,
        base_delta: StateDelta,
        context_ref: ArtifactRef,
    ) -> Command:
        if decision.action_type == AgentActionType.ASK_USER:
            assert decision.user_request is not None
            wait_delta = StateDelta(pending_user_request=decision.user_request)
            wait_type = "user_input"
            event_name = RuntimeEventName.USER_INPUT_REQUIRED
            request_payload = {
                "request_id": decision.user_request.request_id,
                "prompt": decision.user_request.prompt,
                "choices": decision.user_request.choices,
            }
            goto = "interrupt"
        elif decision.action_type == AgentActionType.REQUEST_APPROVAL:
            assert decision.approval_request is not None
            wait_delta = StateDelta(pending_approval=decision.approval_request)
            wait_type = "approval"
            event_name = RuntimeEventName.APPROVAL_REQUIRED
            request_payload = {
                "approval_id": decision.approval_request.approval_id,
                "action_summary": decision.approval_request.action_summary,
                "risk_level": decision.approval_request.risk_level,
            }
            goto = "interrupt"
        else:
            assert decision.event_wait is not None
            wait_delta = StateDelta(pending_event=decision.event_wait)
            wait_type = "event"
            event_name = RuntimeEventName.RUN_WAITING
            request_payload = {
                "event_name": decision.event_wait.event_name,
                "correlation_id": decision.event_wait.correlation_id,
            }
            goto = "event_wait"

        delta = merge_state_deltas(base_delta, wait_delta)
        state_with_wait = apply_state_delta(state_before, delta)
        wait_key = f"wait:{state_before.run_id}:{self._turn_idempotency_key(graph_state, decision)}"
        wait_id = await self.persistence.create_wait(
            state_with_wait,
            step_id=update.get("current_step_id"),
            wait_type=wait_type,
            request_payload=request_payload,
            idempotency_key=wait_key,
        )
        await self.persistence.mark_waiting(state_with_wait)
        update.update(
            {
                "task_state": dump_task_state(state_with_wait),
                "turn_delta": delta.model_dump(mode="json"),
                "pending_wait_id": wait_id,
            }
        )
        update["event_sequence"] = await self._emit(
            {**graph_state, **update},
            state_with_wait,
            event_name,
            request_payload,
        )
        update["event_sequence"] = await self._emit(
            {**graph_state, **update},
            state_with_wait,
            RuntimeEventName.RUN_WAITING,
            {"wait_type": wait_type},
        )
        return await self._complete_immediate_turn(
            graph_state,
            update,
            state_before,
            decision,
            delta,
            context_ref,
            goto=goto,
            wait_turn=True,
        )

    async def _complete_immediate_turn(
        self,
        graph_state: Mapping[str, Any],
        update: dict[str, Any],
        state_before: AgentTaskState,
        decision: AgentDecision,
        delta: StateDelta,
        context_ref: ArtifactRef,
        *,
        goto: str,
        wait_turn: bool = False,
    ) -> Command:
        effective_graph_state = {**graph_state, **update}
        state_current = AgentTaskState.model_validate(update["task_state"])
        execution = ActionExecutionResult()
        verification = VerifierResult(passed=True, summary="Action is awaiting external input." if wait_turn else "Action accepted.")
        return await self._complete_turn(
            effective_graph_state,
            state_before=state_before,
            state_current=state_current,
            decision=decision,
            delta=delta,
            context_ref=context_ref,
            execution=execution,
            verifier_result=verification,
            goto=goto,
            update=update,
            terminal=goto == "finalizer",
            waiting=wait_turn,
        )

    async def _complete_turn(
        self,
        graph_state: Mapping[str, Any],
        *,
        state_before: AgentTaskState,
        state_current: AgentTaskState,
        decision: AgentDecision,
        delta: StateDelta,
        context_ref: ArtifactRef,
        execution: ActionExecutionResult,
        verifier_result: VerifierResult,
        goto: str,
        update: dict[str, Any] | None = None,
        terminal: bool = False,
        waiting: bool = False,
    ) -> Command:
        transition_id = self._transition_id(graph_state, state_before, decision)
        complete_delta = merge_state_deltas(delta, StateDelta(last_transition_id=transition_id))
        # `state_current` may already include part of the delta (e.g. a Skill
        # outcome). Reapplying the full merged delta from the immutable source
        # prevents order-dependent in-place mutation.
        successor = apply_state_delta(state_before, complete_delta)
        no_delta = self.no_delta_detector.assess(complete_delta, has_observation=execution.observation is not None)
        reward_facts = execution.reward_facts.model_copy(
            update={
                "duplicate_action": bool(graph_state.get("duplicate_action", False)),
                "void_turn": no_delta.is_void_turn,
                "tool_cost": execution.estimated_cost,
                "context_tokens": load_delta(graph_state).budget_consumption.context_tokens,
                "user_questions": 1 if decision.action_type == AgentActionType.ASK_USER else 0,
            }
        )
        policy_turn = self._turn_from_graph(
            graph_state,
            field_name="policy_turn_result",
            parsed_output=decision,
            context_ref=context_ref,
            purpose=ContextPurpose.POLICY,
        )
        training_eligible, quarantine_reason = self._training_status(
            policy_turn,
            purpose=ModelTurnPurpose.POLICY,
        )
        reward_facts = reward_facts.model_copy(
            update={
                "trainable": training_eligible,
                "quarantine_reason": quarantine_reason,
            }
        )
        state_group = self._state_group_key_v2(successor)
        event = AgentTransitionEvent(
            thread_id=successor.thread_id,
            run_id=successor.run_id,
            transition_id=transition_id,
            parent_transition_id=state_before.last_transition_id,
            turn_index=max(0, int(graph_state.get("turn_index", 1)) - 1),
            plan_step_id=decision.plan_step_id,
            subagent_name=decision.delegate_agent,
            environment_snapshot_id=successor.environment.snapshot_id,
            state_before_hash=canonical_hash(state_before),
            state_after_hash=canonical_hash(successor),
            state_abstract_key=state_group,
            state_group_key_v2=state_group,
            policy_version=self.metadata.policy_version,
            model_id=policy_turn.model_id,
            model_revision=policy_turn.model_revision,
            model_turn_id=self._model_turn_id(
                state_before,
                turn_index=max(0, int(graph_state.get("turn_index", 1)) - 1),
                purpose=ModelTurnPurpose.POLICY,
                turn=policy_turn,
            ),
            turn_purpose=ModelTurnPurpose.POLICY,
            prompt_template_hash=policy_turn.prompt_hash,
            skill_catalog_hash=str(graph_state.get("context_catalog_hash") or "unavailable-catalog-hash"),
            action_schema_hash=json_schema_hash(AgentDecision),
            context_view_ref=context_ref,
            raw_model_output_ref=policy_turn.raw_model_output_ref,
            parsed_decision=decision,
            observation_ref=execution.observation.artifact_ref if execution.observation else None,
            state_delta=complete_delta,
            verifier_result=verifier_result,
            reward_facts=reward_facts,
            token_ids=list(policy_turn.token_ids) if policy_turn.token_ids is not None else None,
            token_logprobs=list(policy_turn.token_logprobs) if policy_turn.token_logprobs is not None else None,
            token_role_spans=[span.model_copy(deep=True) for span in policy_turn.token_role_spans],
            usage=policy_turn.usage.model_copy(deep=True),
            latency_ms=dict(policy_turn.latency_ms),
            finish_reason=policy_turn.finish_reason,
            provider_request_id=policy_turn.provider_request_id,
            training_eligible=training_eligible,
            quarantine_reason=quarantine_reason,
            data_policy=self.metadata.data_policy.model_copy(deep=True),
            error=execution.error,
            terminal_reason=str((update or graph_state).get("termination_reason")) if terminal else None,
        )
        await self.transition_sink.emit(event)
        await self.model_turn_sink.emit_model_turn(event.model_turn_event())
        await self.persistence.complete_turn(
            successor,
            step_id=(update or graph_state).get("current_step_id"),
            state_before_hash=event.state_before_hash,
            state_after_hash=event.state_after_hash,
            decision=decision,
            observation_ref=event.observation_ref,
            terminal=terminal,
            waiting=waiting,
        )
        sequence = await self._emit(
            {**graph_state, **(update or {})},
            successor,
            RuntimeEventName.STEP_COMPLETED,
            {"transition_id": transition_id, "completed": True, "next": goto},
        )
        final_update = dict(update or {})
        final_update.update(
            {
                "task_state": dump_task_state(successor),
                "turn_delta": complete_delta.model_dump(mode="json"),
                "verifier_result": verifier_result.model_dump(mode="json"),
                "execution": execution.model_dump(mode="json"),
                "event_sequence": sequence,
            }
        )
        return Command(update=final_update, goto=goto)

    def _coerce_policy_turn(
        self,
        value: object,
        *,
        context: ContextView,
        purpose: ContextPurpose,
    ) -> PolicyTurnResult[Any]:
        """Accept the structured contract while keeping older adapters usable.

        The fallback is intentionally non-trainable and clearly marked as
        missing local tokenization.  It does not invent model IDs, token IDs,
        or hidden content, and therefore keeps an open policy integration from
        becoming silently eligible for RL data.
        """

        if isinstance(value, PolicyTurnResult):
            return value
        parsed_output = unwrap_policy_output(value)
        context_hash = canonical_hash(context)
        return PolicyTurnResult(
            parsed_output=parsed_output,
            model_id=self.metadata.model_id,
            model_revision=self.metadata.model_revision,
            prompt_hash=canonical_hash(
                {
                    "runtime_version": self.metadata.runtime_version,
                    "policy_version": self.metadata.policy_version,
                    "purpose": purpose.value,
                    "context_hash": context_hash,
                    "compatibility_adapter": True,
                }
            ),
            context_hash=context_hash,
            trainable=False,
        )

    def _turn_from_graph(
        self,
        graph_state: Mapping[str, Any],
        *,
        field_name: str,
        parsed_output: object,
        context_ref: ArtifactRef,
        purpose: ContextPurpose,
    ) -> PolicyTurnResult[Any]:
        raw = graph_state.get(field_name)
        if isinstance(raw, Mapping):
            try:
                return PolicyTurnResult.model_validate({**raw, "parsed_output": parsed_output})
            except Exception:  # noqa: BLE001 - old checkpoints remain non-trainable rather than unreadable.
                pass
        context_hash = canonical_hash(context_ref)
        return PolicyTurnResult(
            parsed_output=parsed_output,
            model_id=self.metadata.model_id,
            model_revision=self.metadata.model_revision,
            prompt_hash=canonical_hash(
                {
                    "runtime_version": self.metadata.runtime_version,
                    "policy_version": self.metadata.policy_version,
                    "purpose": purpose.value,
                    "context_ref": context_hash,
                    "compatibility_checkpoint": True,
                }
            ),
            context_hash=context_hash,
            trainable=False,
        )

    async def _store_context_view(
        self,
        state: AgentTaskState,
        *,
        context: ContextView,
        artifact_key: str,
        turn_index: int,
    ) -> ArtifactRef:
        return await self.artifact_store.store_json(
            state,
            artifact_type=ArtifactKind.CONTEXT_VIEW,
            artifact_key=artifact_key,
            payload=context.model_dump(mode="json"),
            summary=f"Secret-free {context.purpose.value} context view",
            idempotency_key=(
                f"context:{context.purpose.value}:{state.run_id}:{turn_index}:{canonical_hash(context)[:24]}"
            ),
        )

    def _training_status(
        self,
        turn: PolicyTurnResult[Any],
        *,
        purpose: ModelTurnPurpose,
    ) -> tuple[bool, str | None]:
        if turn.token_ids is None:
            return False, "missing_student_tokenization"
        if not turn.token_role_spans:
            return False, "missing_token_role_spans"
        if not turn.trainable:
            return False, "non_trainable_token_trace"
        if purpose not in self.metadata.trainable_turn_purposes:
            return False, None
        if not any(span.trainable for span in turn.token_role_spans):
            return False, "missing_trainable_assistant_span"
        return True, None

    @staticmethod
    def _model_turn_id(
        state: AgentTaskState,
        *,
        turn_index: int,
        purpose: ModelTurnPurpose,
        turn: PolicyTurnResult[Any],
    ) -> str:
        return "model_turn_" + canonical_hash(
            {
                "run_id": state.run_id,
                "turn_index": turn_index,
                "purpose": purpose.value,
                "prompt_hash": turn.prompt_hash,
                "context_hash": turn.context_hash,
            }
        )[:40]

    async def _emit_standalone_model_turn(
        self,
        *,
        state_before: AgentTaskState,
        state_after: AgentTaskState,
        context_ref: ArtifactRef,
        turn: PolicyTurnResult[Any],
        purpose: ModelTurnPurpose,
        turn_index: int,
        state_delta: StateDelta | None = None,
    ) -> None:
        training_eligible, quarantine_reason = self._training_status(turn, purpose=purpose)
        state_group = self._state_group_key_v2(state_after)
        await self.model_turn_sink.emit_model_turn(
            ModelTurnEvent(
                model_turn_id=self._model_turn_id(
                    state_before,
                    turn_index=turn_index,
                    purpose=purpose,
                    turn=turn,
                ),
                thread_id=state_before.thread_id,
                run_id=state_before.run_id,
                turn_index=turn_index,
                turn_purpose=purpose,
                environment_snapshot_id=state_after.environment.snapshot_id,
                state_before_hash=canonical_hash(state_before),
                state_after_hash=canonical_hash(state_after),
                state_abstract_key=state_group,
                state_group_key_v2=state_group,
                policy_version=self.metadata.policy_version,
                model_id=turn.model_id,
                model_revision=turn.model_revision,
                prompt_template_hash=turn.prompt_hash,
                context_view_ref=context_ref,
                raw_model_output_ref=turn.raw_model_output_ref,
                state_delta=state_delta,
                token_ids=list(turn.token_ids) if turn.token_ids is not None else None,
                token_logprobs=list(turn.token_logprobs) if turn.token_logprobs is not None else None,
                token_role_spans=[span.model_copy(deep=True) for span in turn.token_role_spans],
                usage=turn.usage.model_copy(deep=True),
                latency_ms=dict(turn.latency_ms),
                finish_reason=turn.finish_reason,
                provider_request_id=turn.provider_request_id,
                training_eligible=training_eligible,
                quarantine_reason=quarantine_reason,
                data_policy=self.metadata.data_policy.model_copy(deep=True),
            )
        )

    def _budgeted_builder(self, state: AgentTaskState) -> ContextBuilder:
        return ContextBuilder(token_budget=BudgetGuard.policy_context_budget(state, self.context_builder.token_budget))

    def _terminate(self, reason: str, status: TerminalStatus) -> Command:
        return Command(update={"termination_reason": reason[:2_000], "termination_status": status.value}, goto="finalizer")

    async def _emit(
        self,
        graph_state: Mapping[str, Any],
        state: AgentTaskState,
        name: RuntimeEventName,
        payload: dict[str, Any],
    ) -> int:
        sequence = int(graph_state.get("event_sequence", 0)) + 1
        await self.event_sink.emit(
            RuntimeEvent(
                name=name,
                thread_id=state.thread_id,
                run_id=state.run_id,
                sequence=sequence,
                payload=payload,
            )
        )
        return sequence

    @staticmethod
    def _append_summary(graph_state: Mapping[str, Any], summary: str) -> list[str]:
        normalized = " ".join(summary.split()).strip()
        return [*graph_state.get("observation_summaries", []), normalized[:1_000] or "[empty observation]"]

    @staticmethod
    def _turn_idempotency_key(graph_state: Mapping[str, Any], decision: AgentDecision) -> str:
        return canonical_hash(
            {
                "turn_index": graph_state.get("turn_index", 0),
                "decision": DuplicateActionDetector.fingerprint(decision),
            }
        )

    @staticmethod
    def _transition_id(graph_state: Mapping[str, Any], state_before: AgentTaskState, decision: AgentDecision) -> str:
        return f"transition_{canonical_hash({'run': state_before.run_id, 'turn': graph_state.get('turn_index', 0), 'before': canonical_hash(state_before), 'decision': DuplicateActionDetector.fingerprint(decision)})[:40]}"

    @staticmethod
    def _state_abstract_key(state: AgentTaskState) -> str:
        return state_group_key_v2(state)

    @staticmethod
    def _state_group_key_v2(state: AgentTaskState) -> str:
        return state_group_key_v2(state)

    @staticmethod
    def _failure_delta(graph_state: Mapping[str, Any], error: ExecutionError | None) -> StateDelta:
        if error is None:
            return StateDelta()
        prefix = canonical_hash({"turn": graph_state.get("turn_index", 0), "code": error.code})[:24]
        return StateDelta(
            failure_records_to_add=[
                FailureRecord(
                    failure_id=f"failure_{prefix}",
                    code=error.code,
                    summary=error.summary,
                    recoverable=error.retryable,
                )
            ]
        )

    @staticmethod
    def _interrupt_payload(graph_state: Mapping[str, Any], state: AgentTaskState, *, pending_kind: str) -> dict[str, Any]:
        if pending_kind == "user_input":
            assert state.pending_user_request is not None
            return {
                "wait_id": graph_state.get("pending_wait_id"),
                "kind": pending_kind,
                "request_id": state.pending_user_request.request_id,
                "prompt": state.pending_user_request.prompt,
                "choices": state.pending_user_request.choices,
            }
        if pending_kind == "approval":
            assert state.pending_approval is not None
            return {
                "wait_id": graph_state.get("pending_wait_id"),
                "kind": pending_kind,
                "approval_id": state.pending_approval.approval_id,
                "action_summary": state.pending_approval.action_summary,
                "risk_level": state.pending_approval.risk_level,
            }
        assert state.pending_event is not None
        return {
            "wait_id": graph_state.get("pending_wait_id"),
            "kind": pending_kind,
            "event_name": state.pending_event.event_name,
            "correlation_id": state.pending_event.correlation_id,
        }
