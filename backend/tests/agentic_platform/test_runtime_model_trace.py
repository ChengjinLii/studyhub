from __future__ import annotations

import asyncio
from collections import deque

from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.domain.decision import AgentActionType, AgentDecision, AgentOutput, ExpectedStateChange
from app.agentic_platform.domain.plan import AgentPlan
from app.agentic_platform.domain.state import AgentBudget, AgentTaskState, StateDelta
from app.agentic_platform.domain.transition import ModelTurnPurpose, ModelUsage, TokenRole, TokenRoleSpan
from app.agentic_platform.policy.context_builder import ContextBuilder
from app.agentic_platform.policy.context_view import ContextPurpose, ContextView
from app.agentic_platform.policy.token_trace import TokenTraceSource
from app.agentic_platform.policy.turn_result import PolicyTurnResult
from app.agentic_platform.runtime.checkpoint import InMemoryCheckpointHandle
from app.agentic_platform.runtime.kernel import AgentKernel, KernelRunStatus
from app.agentic_platform.runtime.nodes import (
    ActionExecutionResult,
    InMemoryModelTurnSink,
    InMemoryTransitionSink,
    RuntimeMetadata,
)
from app.agentic_platform.simulation.trajectory import ModelIORecord
from app.agentic_platform.skills.registry import build_default_skill_registry
from tests.agentic_platform.factories import agent_plan, task_state


class LocalTokenPolicy:
    """Deterministic local-provider fixture with original token provenance."""

    def __init__(self, decisions: list[AgentDecision]) -> None:
        self._decisions = deque(decision.model_copy(deep=True) for decision in decisions)
        self._counter = 0

    async def create_plan(self, state: AgentTaskState, context: ContextView) -> PolicyTurnResult[AgentPlan]:
        del state
        assert context.purpose == ContextPurpose.PLANNER
        return self._turn(agent_plan(), context, ModelTurnPurpose.PLANNER)

    async def decide(self, state: AgentTaskState, context: ContextView) -> PolicyTurnResult[AgentDecision]:
        del state
        assert context.purpose == ContextPurpose.POLICY
        return self._turn(self._decisions.popleft(), context, ModelTurnPurpose.POLICY)

    async def finalize(self, state: AgentTaskState, context: ContextView) -> PolicyTurnResult[AgentOutput]:
        del state
        assert context.purpose == ContextPurpose.FINALIZER
        return self._turn(
            AgentOutput(summary="Token-preserving final answer.", user_visible=True),
            context,
            ModelTurnPurpose.FINALIZER,
        )

    def _turn(self, output, context: ContextView, purpose: ModelTurnPurpose):
        self._counter += 1
        if purpose == ModelTurnPurpose.FINALIZER:
            spans = [
                TokenRoleSpan(role=TokenRole.SYSTEM, start=0, end=1, trainable=False),
                TokenRoleSpan(role=TokenRole.USER, start=1, end=2, trainable=False),
                TokenRoleSpan(role=TokenRole.ASSISTANT_FINAL, start=2, end=5, trainable=True),
            ]
        else:
            spans = [
                TokenRoleSpan(role=TokenRole.SYSTEM, start=0, end=1, trainable=False),
                TokenRoleSpan(role=TokenRole.USER, start=1, end=2, trainable=False),
                TokenRoleSpan(role=TokenRole.TOOL_OBSERVATION, start=2, end=3, trainable=False),
                TokenRoleSpan(role=TokenRole.ASSISTANT_ACTION, start=3, end=5, trainable=True),
            ]
        token_ids = [self._counter * 100 + offset for offset in range(5)]
        return PolicyTurnResult(
            parsed_output=output,
            model_id="local-fixture-model",
            model_revision="fixture-r1",
            prompt_hash=f"prompt-{self._counter}",
            context_hash=f"context-{self._counter}",
            raw_model_output_ref=ArtifactRef(
                artifact_id=f"raw-model-{self._counter}",
                artifact_type=ArtifactKind.RAW_MODEL_OUTPUT,
                version=1,
                uri=f"artifact://restricted/raw-model-{self._counter}",
                content_hash=f"raw-hash-{self._counter}",
                summary="restricted fixture raw output",
            ),
            token_ids=token_ids,
            token_logprobs=[-0.1] * len(token_ids),
            token_role_spans=spans,
            usage=ModelUsage(input_tokens=3, output_tokens=2, total_tokens=5),
            latency_ms={"provider": 12.5},
            finish_reason="stop",
            provider_request_id=f"provider-{self._counter}",
            token_trace_source=TokenTraceSource.LOCAL,
            trainable=True,
        )


class OneObservationSkillExecutor:
    async def execute(self, state, decision, *, idempotency_key: str) -> ActionExecutionResult:
        del state, decision, idempotency_key
        return ActionExecutionResult(state_delta=StateDelta(candidate_ids_to_add=["fixture-candidate"]))


def _decision(action_type: AgentActionType, **payload: object) -> AgentDecision:
    return AgentDecision(
        action_type=action_type,
        plan_step_id="review",
        rationale_summary=f"Choose {action_type.value} with a concise rationale.",
        expected_state_change=ExpectedStateChange(summary="Record a bounded state change."),
        **payload,
    )


def _state() -> AgentTaskState:
    state = task_state()
    return state.model_copy(
        update={
            "budget": AgentBudget(
                turns_remaining=16,
                skill_calls_remaining=16,
                context_tokens_remaining=100_000,
                cost_remaining=10.0,
                subagent_turns_remaining=4,
            )
        }
    )


def test_local_token_model_turns_populate_transitions_and_all_model_io() -> None:
    async def scenario():
        decisions = [
            _decision(AgentActionType.EXECUTE_SKILL, skill_name="materials.search", arguments={"query": "calculus"}),
            *[_decision(AgentActionType.REVIEW) for _ in range(6)],
            _decision(
                AgentActionType.FINALIZE,
                final_output=AgentOutput(summary="Policy final output.", user_visible=True),
            ),
        ]
        transition_sink = InMemoryTransitionSink()
        model_turn_sink = InMemoryModelTurnSink()
        kernel = AgentKernel(
            policy=LocalTokenPolicy(decisions),
            context_builder=ContextBuilder(token_budget=8_000),
            skill_registry=build_default_skill_registry(),
            skill_action_executor=OneObservationSkillExecutor(),
            checkpointer=InMemoryCheckpointHandle(),
            transition_sink=transition_sink,
            model_turn_sink=model_turn_sink,
            metadata=RuntimeMetadata(
                policy_version="trace-fixture-policy-v1",
                model_id="fallback-never-used",
                trainable_turn_purposes=[
                    ModelTurnPurpose.PLANNER,
                    ModelTurnPurpose.POLICY,
                    ModelTurnPurpose.FINALIZER,
                ],
            ),
        )
        result = await kernel.start(_state())
        snapshot = await kernel.graph.aget_state({"configurable": {"thread_id": "agent-run:run-1"}})
        return result, transition_sink, model_turn_sink, snapshot.values

    result, transition_sink, model_turn_sink, graph_state = asyncio.run(scenario())

    assert result.status == KernelRunStatus.COMPLETED
    # 1 planner + 8 action-policy calls + 1 finalizer = 10 model turns.
    assert len(model_turn_sink.events) == 10
    assert [turn.turn_purpose for turn in model_turn_sink.events].count(ModelTurnPurpose.PLANNER) == 1
    assert [turn.turn_purpose for turn in model_turn_sink.events].count(ModelTurnPurpose.POLICY) == 8
    assert [turn.turn_purpose for turn in model_turn_sink.events].count(ModelTurnPurpose.FINALIZER) == 1
    assert all(turn.token_ids is not None for turn in model_turn_sink.events)
    assert all(turn.token_role_spans for turn in model_turn_sink.events)
    assert all(turn.usage.total_tokens > 0 for turn in model_turn_sink.events)
    assert all(turn.training_eligible for turn in model_turn_sink.events)

    policy_records = [ModelIORecord.from_model_turn(turn) for turn in model_turn_sink.events]
    assert all(len(record.trainable_token_mask) == len(record.token_ids or []) for record in policy_records)
    action_record = next(record for record in policy_records if record.turn_purpose == ModelTurnPurpose.POLICY)
    assert action_record.trainable_token_mask == [False, False, False, True, True]

    assert len(transition_sink.events) == 8
    assert all(event.model_id == "local-fixture-model" for event in transition_sink.events)
    assert all(event.model_revision == "fixture-r1" for event in transition_sink.events)
    assert all(event.raw_model_output_ref is not None for event in transition_sink.events)
    assert all(event.token_ids is not None for event in transition_sink.events)
    assert all(event.training_eligible for event in transition_sink.events)
    assert all(event.reward_facts.trainable for event in transition_sink.events)
    assert "parsed_output" not in graph_state["policy_turn_result"]
    assert "raw_content" not in graph_state["policy_turn_result"]
    assert graph_state["policy_turn_result"]["raw_model_output_ref"]["artifact_type"] == "raw_model_output"


def test_model_turn_without_local_tokens_is_retained_but_not_training_eligible() -> None:
    from app.agentic_platform.policy.replay_policy import ReplayPolicy

    async def scenario():
        model_turn_sink = InMemoryModelTurnSink()
        kernel = AgentKernel(
            policy=ReplayPolicy(
                plans=[agent_plan()],
                decisions=[
                    _decision(
                        AgentActionType.FINALIZE,
                        final_output=AgentOutput(summary="Finish safely.", user_visible=True),
                    )
                ],
            ),
            context_builder=ContextBuilder(token_budget=8_000),
            skill_registry=build_default_skill_registry(),
            skill_action_executor=OneObservationSkillExecutor(),
            checkpointer=InMemoryCheckpointHandle(),
            model_turn_sink=model_turn_sink,
        )
        await kernel.start(_state())
        return model_turn_sink.events

    turns = asyncio.run(scenario())

    assert turns
    assert all(turn.token_ids is None for turn in turns)
    assert all(turn.training_eligible is False for turn in turns)
    assert all(turn.quarantine_reason == "missing_student_tokenization" for turn in turns)
