from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.agentic_platform.domain.artifact import ArtifactKind
from app.agentic_platform.domain.decision import AgentActionType, AgentDecision, AgentOutput, ExpectedStateChange
from app.agentic_platform.domain.observation import Observation, ObservationSource
from app.agentic_platform.domain.state import AgentBudget, StateDelta, UserInputRequest
from app.agentic_platform.domain.transition import ExecutionError
from app.agentic_platform.policy.context_builder import ContextBuilder
from app.agentic_platform.policy.replay_policy import ReplayPolicy
from app.agentic_platform.runtime.checkpoint import RedisCheckpointAdapter, RuntimeCheckpointSnapshot, SQLiteCheckpointHandle
from app.agentic_platform.runtime.duplicate_detector import DuplicateActionDetector, NoStateDeltaDetector
from app.agentic_platform.runtime.interrupts import DuplicateResumeError, RunNotWaitingError
from app.agentic_platform.runtime.kernel import AgentKernel, KernelRunResult, KernelRunStatus
from app.agentic_platform.runtime.nodes import (
    ActionExecutionResult,
    InMemoryRuntimeArtifactStore,
    InMemoryRuntimeEventSink,
    InMemoryTransitionSink,
    RegistrySkillActionExecutor,
    RuntimeMetadata,
)
from app.agentic_platform.runtime.persistence import SqlAlchemyRuntimePersistence
from app.agentic_platform.runtime.routing import recursion_limit_for_state
from app.agentic_platform.skills.context import SkillExecutionContext, SkillExecutionMode
from app.agentic_platform.skills.executor import FixtureSkillExecutor
from app.agentic_platform.skills.registry import build_default_skill_registry
from app.models import Base
from app.models.agentic_runtime import AgentRunRecord, AgentStepRecord, AgentWaitRecord
from app.services.read_support import ROLE_ADMIN
from tests.agentic_platform.factories import agent_plan, artifact_ref, task_state


@dataclass
class ScriptedSkillExecutor:
    results: deque[ActionExecutionResult]
    calls: list[str] = field(default_factory=list)

    async def execute(self, state, decision, *, idempotency_key: str) -> ActionExecutionResult:
        del state
        self.calls.append(f"{decision.skill_name}:{idempotency_key}")
        return self.results.popleft().model_copy(deep=True)


def _decision(action_type: AgentActionType, *, plan_step_id: str | None = None, **payload: object) -> AgentDecision:
    return AgentDecision(
        action_type=action_type,
        plan_step_id=plan_step_id,
        rationale_summary=f"Select {action_type.value} for the current evidence.",
        expected_state_change=ExpectedStateChange(summary=f"Record the result of {action_type.value}."),
        **payload,
    )


def _skill_decision(step_id: str = "gather") -> AgentDecision:
    return _decision(
        AgentActionType.EXECUTE_SKILL,
        plan_step_id=step_id,
        skill_name="materials.search",
        arguments={"query": "calculus"},
    )


def _ask_decision() -> AgentDecision:
    return _decision(
        AgentActionType.ASK_USER,
        plan_step_id="review",
        user_request=UserInputRequest(request_id="ask-admin-1", prompt="Should the agent continue?", choices=["continue"]),
    )


def _final_decision() -> AgentDecision:
    return _decision(
        AgentActionType.FINALIZE,
        plan_step_id="review",
        final_output=AgentOutput(summary="The agent produced a reviewed recommendation.", user_visible=True),
    )


def _state_with_budget(*, turns: int = 24) -> object:
    state = task_state()
    return state.model_copy(
        update={
            "budget": AgentBudget(
                turns_remaining=turns,
                skill_calls_remaining=24,
                context_tokens_remaining=80_000,
                cost_remaining=50.0,
                subagent_turns_remaining=12,
            )
        }
    )


def _successful_execution(identifier: str, *, candidate: str) -> ActionExecutionResult:
    reference = artifact_ref(identifier, artifact_type=ArtifactKind.OBSERVATION)
    return ActionExecutionResult(
        state_delta=StateDelta(candidate_ids_to_add=[candidate], artifact_refs_to_add=[reference]),
        observation=Observation(
            observation_id=f"observation-{identifier}",
            source=ObservationSource.SKILL,
            summary=f"Collected evidence {identifier}.",
            artifact_ref=reference,
        ),
    )


def _revised_plan():
    return agent_plan().model_copy(update={"plan_id": "plan-2", "version": 2})


async def _kernel(
    *,
    policy: ReplayPolicy,
    skill_executor: ScriptedSkillExecutor,
    checkpoint,
    artifacts: InMemoryRuntimeArtifactStore | None = None,
    events: InMemoryRuntimeEventSink | None = None,
    transitions: InMemoryTransitionSink | None = None,
    persistence=None,
    redis_checkpoint_mirror=None,
) -> AgentKernel:
    return AgentKernel(
        policy=policy,
        context_builder=ContextBuilder(token_budget=4_000),
        skill_registry=build_default_skill_registry(),
        skill_action_executor=skill_executor,
        checkpointer=checkpoint,
        artifact_store=artifacts,
        event_sink=events,
        transition_sink=transitions,
        persistence=persistence,
        metadata=RuntimeMetadata(policy_version="runtime-test-policy-v1", model_id="replay-test"),
        redis_checkpoint_mirror=redis_checkpoint_mirror,
    )


def test_kernel_persists_interrupt_and_resumes_after_sqlite_process_restart(tmp_path) -> None:
    async def scenario() -> tuple[KernelRunResult, InMemoryTransitionSink, ScriptedSkillExecutor, ScriptedSkillExecutor, InMemoryRuntimeEventSink]:
        checkpoint_path = tmp_path / "runtime-checkpoints.sqlite3"
        artifacts = InMemoryRuntimeArtifactStore()
        events = InMemoryRuntimeEventSink()
        transitions = InMemoryTransitionSink()
        first_skills = ScriptedSkillExecutor(deque([_successful_execution("first", candidate="candidate-1")]))
        first_handle = await SQLiteCheckpointHandle.open(checkpoint_path)
        first_kernel = await _kernel(
            policy=ReplayPolicy(plans=[agent_plan()], decisions=[_skill_decision(), _ask_decision()]),
            skill_executor=first_skills,
            checkpoint=first_handle,
            artifacts=artifacts,
            events=events,
            transitions=transitions,
        )
        paused = await first_kernel.start(_state_with_budget())
        assert paused.status == KernelRunStatus.WAITING
        assert paused.pending_wait_id is not None
        await first_kernel.close()

        second_skills = ScriptedSkillExecutor(
            deque(
                [
                    _successful_execution("second", candidate="candidate-2"),
                    ActionExecutionResult(
                        error=ExecutionError(code="fixture_skill_failure", summary="Fixture Skill failed safely.", retryable=True)
                    ),
                ]
            )
        )
        second_handle = await SQLiteCheckpointHandle.open(checkpoint_path)
        second_kernel = await _kernel(
            policy=ReplayPolicy(
                plans=[_revised_plan()],
                decisions=[
                    _skill_decision(),
                    _decision(AgentActionType.REVIEW, plan_step_id="review"),
                    _decision(AgentActionType.REVISE_PLAN, plan_step_id="review"),
                    _skill_decision(),
                    _decision(AgentActionType.REVIEW, plan_step_id="review"),
                    _final_decision(),
                ],
            ),
            skill_executor=second_skills,
            checkpoint=second_handle,
            artifacts=artifacts,
            events=events,
            transitions=transitions,
        )
        completed = await second_kernel.resume(paused.run_id, "continue", wait_id=paused.pending_wait_id)
        await second_kernel.close()
        return completed, transitions, first_skills, second_skills, events

    completed, transitions, first_skills, second_skills, events = asyncio.run(scenario())

    assert completed.status == KernelRunStatus.COMPLETED
    assert completed.state.terminal is not None
    assert completed.state.plan.version == 2
    assert any(record.code == "fixture_skill_failure" for record in completed.state.failure_records)
    assert len(first_skills.calls) == 1  # The pre-pause Skill was not replayed after restart.
    assert len(second_skills.calls) == 2
    assert len(transitions.events) == 8
    assert len({event.state_after_hash for event in transitions.events}) == len(transitions.events)
    assert any(event.name.value == "run.waiting" for event in events.events)
    assert any(event.name.value == "run.completed" for event in events.events)


def test_kernel_double_resume_claims_only_one_wait() -> None:
    async def scenario() -> list[object]:
        from app.agentic_platform.runtime.checkpoint import InMemoryCheckpointHandle

        kernel = await _kernel(
            policy=ReplayPolicy(plans=[agent_plan()], decisions=[_ask_decision(), _final_decision()]),
            skill_executor=ScriptedSkillExecutor(deque()),
            checkpoint=InMemoryCheckpointHandle(),
        )
        paused = await kernel.start(_state_with_budget())
        assert paused.pending_wait_id is not None
        return list(
            await asyncio.gather(
                kernel.resume(paused.run_id, "continue", wait_id=paused.pending_wait_id),
                kernel.resume(paused.run_id, "continue", wait_id=paused.pending_wait_id),
                return_exceptions=True,
            )
        )

    results = asyncio.run(scenario())
    successful = [item for item in results if isinstance(item, KernelRunResult)]
    failures = [item for item in results if isinstance(item, Exception)]
    assert len(successful) == 1
    assert successful[0].status == KernelRunStatus.COMPLETED
    assert len(failures) == 1
    assert isinstance(failures[0], (RunNotWaitingError, DuplicateResumeError))


def test_budget_exhaustion_safely_terminates_without_a_fixed_replan_cap() -> None:
    async def scenario() -> KernelRunResult:
        from app.agentic_platform.runtime.checkpoint import InMemoryCheckpointHandle

        state = _state_with_budget(turns=0)
        kernel = await _kernel(
            policy=ReplayPolicy(),
            skill_executor=ScriptedSkillExecutor(deque()),
            checkpoint=InMemoryCheckpointHandle(),
        )
        return await kernel.start(state)

    result = asyncio.run(scenario())
    assert result.status == KernelRunStatus.ABORTED
    assert result.state.terminal is not None
    assert result.state.terminal.reason == "turns_exhausted"
    assert recursion_limit_for_state(_state_with_budget(turns=40)) > recursion_limit_for_state(_state_with_budget(turns=2))


def test_model_free_replay_does_not_consume_or_require_a_model_cost_budget() -> None:
    async def scenario() -> KernelRunResult:
        from app.agentic_platform.runtime.checkpoint import InMemoryCheckpointHandle

        state = _state_with_budget()
        state = state.model_copy(update={"budget": state.budget.model_copy(update={"cost_remaining": 0.0})})
        kernel = await _kernel(
            policy=ReplayPolicy(plans=[agent_plan()], decisions=[_final_decision()]),
            skill_executor=ScriptedSkillExecutor(deque()),
            checkpoint=InMemoryCheckpointHandle(),
        )
        return await kernel.start(state)

    result = asyncio.run(scenario())
    assert result.status == KernelRunStatus.COMPLETED


def test_cancel_routes_a_waiting_run_to_a_safe_terminal_state() -> None:
    async def scenario() -> KernelRunResult:
        from app.agentic_platform.runtime.checkpoint import InMemoryCheckpointHandle

        kernel = await _kernel(
            policy=ReplayPolicy(plans=[agent_plan()], decisions=[_ask_decision()]),
            skill_executor=ScriptedSkillExecutor(deque()),
            checkpoint=InMemoryCheckpointHandle(),
        )
        paused = await kernel.start(_state_with_budget())
        assert paused.status == KernelRunStatus.WAITING
        return await kernel.cancel(paused.run_id, reason="administrator stopped this run")

    result = asyncio.run(scenario())
    assert result.status == KernelRunStatus.CANCELLED
    assert result.state.terminal is not None
    assert result.state.terminal.reason == "administrator stopped this run"


def test_replay_state_hash_and_transitions_are_stable() -> None:
    async def run_once() -> tuple[str, list[str]]:
        from app.agentic_platform.runtime.checkpoint import InMemoryCheckpointHandle

        transitions = InMemoryTransitionSink()
        kernel = await _kernel(
            policy=ReplayPolicy(
                plans=[agent_plan()],
                decisions=[_decision(AgentActionType.REVIEW, plan_step_id="review"), _final_decision()],
            ),
            skill_executor=ScriptedSkillExecutor(deque()),
            checkpoint=InMemoryCheckpointHandle(),
            transitions=transitions,
        )
        result = await kernel.start(_state_with_budget())
        return result.state_hash, [event.canonical_hash() for event in transitions.events]

    first_hash, first_transitions = asyncio.run(run_once())
    second_hash, second_transitions = asyncio.run(run_once())
    assert first_hash == second_hash
    assert first_transitions == second_transitions


def test_finalizer_uses_the_replaceable_policy_finalizer_with_safe_decision_fallback() -> None:
    async def scenario() -> tuple[KernelRunResult, InMemoryRuntimeArtifactStore]:
        from app.agentic_platform.runtime.checkpoint import InMemoryCheckpointHandle

        artifacts = InMemoryRuntimeArtifactStore()
        kernel = await _kernel(
            policy=ReplayPolicy(
                plans=[agent_plan()],
                decisions=[_final_decision()],
                final_outputs=[AgentOutput(summary="Finalizer policy output", user_visible=True)],
            ),
            skill_executor=ScriptedSkillExecutor(deque()),
            checkpoint=InMemoryCheckpointHandle(),
            artifacts=artifacts,
        )
        return await kernel.start(_state_with_budget()), artifacts

    result, artifacts = asyncio.run(scenario())
    assert result.state.terminal is not None
    reference = result.state.terminal.final_artifact_ref
    assert reference is not None
    assert artifacts.payloads[reference.artifact_id]["summary"] == "Finalizer policy output"


def test_sqlalchemy_runtime_persistence_tracks_run_step_wait_and_checkpoint() -> None:
    async def scenario() -> tuple[str, list[str], list[str], str | None]:
        from app.agentic_platform.runtime.checkpoint import InMemoryCheckpointHandle

        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, future=True)
        persistence = SqlAlchemyRuntimePersistence(
            session_factory,
            metadata=RuntimeMetadata(policy_version="runtime-test-policy-v1", model_id="replay-test"),
        )
        kernel = await _kernel(
            policy=ReplayPolicy(plans=[agent_plan()], decisions=[_ask_decision(), _final_decision()]),
            skill_executor=ScriptedSkillExecutor(deque()),
            checkpoint=InMemoryCheckpointHandle(),
            persistence=persistence,
        )
        paused = await kernel.start(_state_with_budget())
        assert paused.pending_wait_id is not None
        completed = await kernel.resume(paused.run_id, "continue", wait_id=paused.pending_wait_id)
        with session_factory() as session:
            run = session.get(AgentRunRecord, completed.run_id)
            assert run is not None
            steps = list(session.scalars(select(AgentStepRecord).order_by(AgentStepRecord.step_index)))
            waits = list(session.scalars(select(AgentWaitRecord)))
            return run.status, [step.status for step in steps], [wait.status for wait in waits], run.checkpoint_ref

    run_status, step_statuses, wait_statuses, checkpoint_ref = asyncio.run(scenario())
    assert run_status == "completed"
    assert step_statuses == ["completed", "completed"]
    assert wait_statuses == ["resolved"]
    assert checkpoint_ref is not None and checkpoint_ref.startswith("langgraph-memory://")


def test_registry_skill_action_executor_uses_typed_fixture_output_and_artifact_store() -> None:
    async def scenario() -> ActionExecutionResult:
        registry = build_default_skill_registry()
        artifacts = InMemoryRuntimeArtifactStore()
        fixture_executor = FixtureSkillExecutor(registry)

        def context_factory(state, decision) -> SkillExecutionContext:
            del state, decision
            return SkillExecutionContext(
                admin_actor_id=3,
                role_mask=ROLE_ADMIN,
                permission_scopes=frozenset({"agentic.admin", "materials.read"}),
                mode=SkillExecutionMode.FIXTURE,
                fixture_outputs={
                    "materials.search": {
                        "query": "calculus",
                        "materials": [],
                        "retrieval_engine": "fixture",
                        "count": 0,
                    }
                },
            )

        adapter = RegistrySkillActionExecutor(
            registry=registry,
            executor=fixture_executor,
            context_factory=context_factory,
            artifact_store=artifacts,
        )
        return await adapter.execute(_state_with_budget(), _skill_decision(), idempotency_key="typed-fixture")

    result = asyncio.run(scenario())
    assert result.error is None
    assert result.observation is not None
    assert result.observation.artifact_ref.artifact_type == ArtifactKind.OBSERVATION
    assert len(result.state_delta.artifact_refs_to_add) == 1


def test_duplicate_and_no_state_delta_detectors_report_without_blocking_retries() -> None:
    decision = _skill_decision()
    detector = DuplicateActionDetector()
    first = detector.assess(decision, [])
    second = detector.assess(decision, [first.fingerprint])
    no_delta = NoStateDeltaDetector().assess(StateDelta(), has_observation=False)

    assert first.is_duplicate is False
    assert second.is_duplicate is True
    assert no_delta.has_no_state_delta is True
    assert no_delta.is_void_turn is True


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, name: str, value: str, ex: int | None = None) -> bool:
        del ex
        self.values[name] = value
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)


class FailingRedis:
    def set(self, name: str, value: str, ex: int | None = None) -> bool:
        del name, value, ex
        raise ConnectionError("fixture redis unavailable")

    def get(self, name: str) -> str | None:
        del name
        raise ConnectionError("fixture redis unavailable")


def test_redis_checkpoint_adapter_round_trips_a_safe_snapshot() -> None:
    adapter = RedisCheckpointAdapter(FakeRedis(), key_prefix="test:agentic")
    snapshot = RuntimeCheckpointSnapshot(
        graph_thread_id="agent-run:run-1",
        run_id="run-1",
        state_hash="state-hash",
        graph_state={"task_state": {"run_id": "run-1"}},
        next_nodes=["interrupt"],
    )

    reference = adapter.save(snapshot)
    loaded = adapter.load("agent-run:run-1")

    assert reference == "redis://test:agentic/agent-run:run-1"
    assert loaded == snapshot


def test_redis_checkpoint_mirror_failure_does_not_interrupt_a_durable_run() -> None:
    async def scenario() -> KernelRunResult:
        from app.agentic_platform.runtime.checkpoint import InMemoryCheckpointHandle

        kernel = await _kernel(
            policy=ReplayPolicy(plans=[agent_plan()], decisions=[_final_decision()]),
            skill_executor=ScriptedSkillExecutor(deque()),
            checkpoint=InMemoryCheckpointHandle(),
            redis_checkpoint_mirror=RedisCheckpointAdapter(FailingRedis(), key_prefix="test:agentic"),
        )
        result = await kernel.start(_state_with_budget())
        recovered = await kernel.get_result(result.run_id)
        await kernel.close()
        assert recovered.state_hash == result.state_hash
        return result

    result = asyncio.run(scenario())

    assert result.status == KernelRunStatus.COMPLETED
