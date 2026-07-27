from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field

from app.agentic_platform.deepresearch.domain_router import ResearchDomainRouter
from app.agentic_platform.deepresearch.graph import DeepResearchGraph
from app.agentic_platform.deepresearch.policy import ModelResearchPolicy, ReplayResearchPolicy
from app.agentic_platform.deepresearch.state import (
    EvidenceRecord,
    ResearchActionType,
    ResearchContextAction,
    ResearchDecision,
    ResearchSourceRef,
    ResearchSourceType,
    ResearchTaskPacket,
)
from app.agentic_platform.deepresearch.transition import (
    InMemoryResearchArtifactStore,
    InMemoryResearchChildTransitionSink,
    ResearchRuntimeMetadata,
)
from app.agentic_platform.domain.decision import AgentActionType, AgentDecision, AgentOutput, ExpectedStateChange, SubAgentTaskPacket
from app.agentic_platform.domain.state import StateDelta
from app.agentic_platform.domain.transition import ModelTurnPurpose, ModelUsage, TokenRole, TokenRoleSpan
from app.agentic_platform.policy.model_provider import AgentModelResponse
from app.agentic_platform.policy.context_builder import ContextBuilder
from app.agentic_platform.policy.replay_policy import ReplayPolicy
from app.agentic_platform.policy.token_trace import TokenTraceSource
from app.agentic_platform.runtime.checkpoint import InMemoryCheckpointHandle
from app.agentic_platform.runtime.kernel import AgentKernel
from app.agentic_platform.runtime.nodes import ActionExecutionResult, InMemoryTransitionSink
from app.agentic_platform.skills.registry import build_default_skill_registry
from app.agentic_platform.subagents.deepresearch import research_task_from_parent_decision
from tests.agentic_platform.factories import agent_plan, task_state


@dataclass
class FixtureResearchEnvironment:
    sources_by_query: dict[str, list[ResearchSourceRef]] = field(default_factory=dict)
    evidence_by_sources: dict[tuple[str, ...], deque[list[EvidenceRecord]]] = field(default_factory=dict)

    async def search_internal(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        del limit
        return [source.model_copy(deep=True) for source in self.sources_by_query.get(query, [])]

    async def read_internal(self, source_ids: list[str], query: str, *, page_limit: int) -> list[EvidenceRecord]:
        del query, page_limit
        values = self.evidence_by_sources[tuple(source_ids)].popleft()
        return [evidence.model_copy(deep=True) for evidence in values]

    async def search_web(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        del query, limit
        return []

    async def read_web(self, source_ids: list[str], query: str) -> list[EvidenceRecord]:
        del source_ids, query
        return []

    async def search_scholar(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        del query, limit
        return []


def _task() -> ResearchTaskPacket:
    return ResearchTaskPacket(
        task_id="research-child-transitions",
        admin_actor_id=3,
        research_question="What does the course conclude about sampling rates?",
        allowed_source_types=[ResearchSourceType.INTERNAL_MATERIAL],
        max_turns=32,
        max_search_turns=8,
        max_page_reads=8,
        max_context_tokens=32_000,
        parent_transition_id="transition_delegate_parent_1",
    )


def _decision(action: ResearchActionType, **payload: object) -> ResearchDecision:
    return ResearchDecision(
        action_type=action,
        rationale_summary=f"Choose {action.value} for the research objective.",
        **payload,
    )


def _source() -> ResearchSourceRef:
    return ResearchSourceRef(
        source_id="material:1",
        source_type=ResearchSourceType.INTERNAL_MATERIAL,
        title="Sampling lecture notes",
        source_uri="studyhub://materials/1",
        material_id=1,
        reliability=0.9,
        access_scope="admin:materials.read",
    )


def _evidence() -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id="evidence-1",
        source_type=ResearchSourceType.INTERNAL_PDF,
        source_uri="studyhub://materials/1/pages/3",
        title="Sampling lecture notes",
        material_id=1,
        page=3,
        excerpt="The course requires sampling at least twice the highest frequency.",
        reliability=0.9,
        access_scope="admin:materials.read",
    )


def test_deep_research_emits_ordered_child_transitions_for_an_open_policy_path() -> None:
    async def scenario():
        environment = FixtureResearchEnvironment(
            sources_by_query={"sampling theorem": [_source()]},
            evidence_by_sources={("material:1",): deque([[_evidence()]])},
        )
        sink = InMemoryResearchChildTransitionSink()
        artifacts = InMemoryResearchArtifactStore()
        graph = DeepResearchGraph(
            policy=ReplayResearchPolicy(
                decisions=[
                    _decision(ResearchActionType.SEARCH_INTERNAL, query="too vague"),
                    _decision(ResearchActionType.SEARCH_INTERNAL, query="sampling theorem"),
                    _decision(ResearchActionType.READ_INTERNAL, source_ids=["material:1"]),
                    _decision(
                        ResearchActionType.EXTRACT_CLAIMS,
                        claim_candidates=["The course requires sampling at least twice the highest frequency."],
                    ),
                    _decision(ResearchActionType.CROSS_VALIDATE),
                    _decision(ResearchActionType.MANAGE_CONTEXT, context_action=ResearchContextAction.COMPRESS),
                    _decision(ResearchActionType.WRITE_REPORT),
                    _decision(ResearchActionType.VALIDATE_REPORT),
                    _decision(ResearchActionType.FINALIZE),
                ]
            ),
            router=ResearchDomainRouter(environment),
            transition_sink=sink,
            artifact_store=artifacts,
            metadata=ResearchRuntimeMetadata(
                policy_version="research-fixture-policy-v1",
                skill_catalog_hash="research-fixture-skill-catalog-v1",
                retriever_version="research-fixture-retriever-v1",
                environment_snapshot_id="research-fixture-snapshot-v1",
                environment_snapshot_hash="research-fixture-snapshot-hash-v1",
            ),
        )
        result = await graph.run(_task())
        return result, sink.events, artifacts.payloads

    result, events, artifact_payloads = asyncio.run(scenario())

    assert len(events) >= 9
    assert result.child_transition_count == len(events)
    assert all(event.parent_transition_id == "transition_delegate_parent_1" for event in events)
    assert all(event.subagent_name == "deep_research" for event in events)
    assert all(event.policy_version == "research-fixture-policy-v1" for event in events)
    assert all(event.skill_catalog_hash == "research-fixture-skill-catalog-v1" for event in events)
    assert all(event.retriever_version == "research-fixture-retriever-v1" for event in events)
    assert all(event.environment_snapshot_id == "research-fixture-snapshot-v1" for event in events)
    assert all(event.environment_snapshot_hash == "research-fixture-snapshot-hash-v1" for event in events)
    assert [event.sequence_in_subagent for event in events] == list(range(len(events)))
    assert events[0].previous_child_transition_id is None
    assert [event.previous_child_transition_id for event in events[1:]] == [
        event.child_transition_id for event in events[:-1]
    ]
    assert {event.node_name for event in events} >= {"planner", "policy", "executor", "finalizer"}

    model_purposes = {event.model_turn.turn_purpose for event in events if event.model_turn is not None}
    assert {
        ModelTurnPurpose.RESEARCH_PLANNER,
        ModelTurnPurpose.RESEARCH_POLICY,
        ModelTurnPurpose.RESEARCH_FINALIZER,
    } <= model_purposes
    replay_model_turns = [event.model_turn for event in events if event.model_turn is not None]
    assert all(turn.token_ids is None for turn in replay_model_turns)
    assert all(turn.training_eligible is False for turn in replay_model_turns)
    assert all(turn.quarantine_reason == "missing_student_tokenization" for turn in replay_model_turns)
    assert all(turn.policy_version == "research-fixture-policy-v1" for turn in replay_model_turns)
    assert all(turn.skill_catalog_hash == "research-fixture-skill-catalog-v1" for turn in replay_model_turns)
    assert all(turn.retriever_version == "research-fixture-retriever-v1" for turn in replay_model_turns)

    search_events = [
        event
        for event in events
        if event.node_name == "executor" and event.parsed_decision is not None
        and event.parsed_decision.action_type == ResearchActionType.SEARCH_INTERNAL
    ]
    assert len(search_events) == 2
    assert all(event.observation_ref is not None and event.observation is not None for event in search_events)
    assert search_events[0].observation.result_count == 0
    assert search_events[1].observation.result_count == 1
    assert search_events[1].reward_facts.search_query_novelty == 1.0

    read_event = next(
        event
        for event in events
        if event.node_name == "executor" and event.parsed_decision is not None
        and event.parsed_decision.action_type == ResearchActionType.READ_INTERNAL
    )
    assert read_event.observation_ref is not None
    assert read_event.observation is not None
    assert read_event.observation.evidence_count == 1
    assert read_event.reward_facts.evidence_added == 1
    assert read_event.reward_facts.trainable is False
    observation_payloads = [
        payload for payload in artifact_payloads.values() if isinstance(payload, dict) and "action_type" in payload
    ]
    assert observation_payloads
    assert all("excerpt" not in payload for payload in observation_payloads)

    final_event = events[-1]
    assert final_event.node_name == "finalizer"
    assert final_event.reward_facts.citation_invalid == 0
    assert final_event.reward_facts.context_tokens >= 0


def test_model_research_policy_preserves_provider_provenance_in_a_restricted_ref() -> None:
    class LocalProvider:
        async def complete(self, request):
            return AgentModelResponse(
                model_id="research-local-model",
                model_revision="r1",
                structured_output={
                    "plan_id": "research-plan-real-provider",
                    "version": 1,
                    "outline": [],
                    "sub_questions": [],
                    "rationale_summary": "Collect verifiable evidence.",
                },
                raw_content='{"plan_id":"research-plan-real-provider"}',
                token_ids=[10, 11, 12],
                token_logprobs=[-0.1, -0.2, -0.3],
                token_role_spans=[
                    TokenRoleSpan(role=TokenRole.SYSTEM, start=0, end=1, trainable=False),
                    TokenRoleSpan(role=TokenRole.ASSISTANT_ACTION, start=1, end=3, trainable=True),
                ],
                token_trace_source=TokenTraceSource.LOCAL,
                usage=ModelUsage(input_tokens=1, output_tokens=2, total_tokens=3),
                latency_ms={"provider": 5.0},
                provider_request_id="research-provider-request-1",
            )

    async def scenario():
        artifacts = InMemoryResearchArtifactStore()
        policy = ModelResearchPolicy(LocalProvider(), raw_output_store=artifacts)
        from app.agentic_platform.deepresearch.state import initial_research_state

        turn = await policy.create_plan(initial_research_state(_task()))
        return turn, artifacts.payloads

    turn, payloads = asyncio.run(scenario())

    assert turn.model_id == "research-local-model"
    assert turn.model_revision == "r1"
    assert turn.usage.total_tokens == 3
    assert turn.raw_model_output_ref is not None
    assert turn.trainable is True
    assert "raw_content" not in turn.model_dump(mode="json")
    assert turn.raw_model_output_ref.artifact_id in payloads


def test_parent_runtime_preallocates_the_delegate_transition_id_for_deep_research() -> None:
    class CapturingDelegateExecutor:
        def __init__(self) -> None:
            self.parent_transition_id: str | None = None
            self.task: ResearchTaskPacket | None = None

        async def execute(self, state, decision, *, idempotency_key: str):
            raise AssertionError("parent-aware dispatch should be used")

        async def execute_with_parent_transition(
            self,
            state,
            decision,
            *,
            idempotency_key: str,
            parent_transition_id: str,
        ) -> ActionExecutionResult:
            del idempotency_key
            self.parent_transition_id = parent_transition_id
            self.task = research_task_from_parent_decision(
                state,
                decision,
                parent_transition_id=parent_transition_id,
            )
            return ActionExecutionResult(state_delta=StateDelta(), subagent_turns_used=1)

    async def scenario():
        delegate = AgentDecision(
            action_type=AgentActionType.DELEGATE,
            plan_step_id="research",
            rationale_summary="Delegate a bounded evidence search.",
            expected_state_change=ExpectedStateChange(summary="Attach a research trace."),
            delegate_agent="deep_research",
            task_packet=SubAgentTaskPacket(
                task_id="nested-research-task",
                objective="Find sampling-rate evidence.",
                max_turns=4,
                max_skill_calls=2,
            ),
        )
        final = AgentDecision(
            action_type=AgentActionType.FINALIZE,
            plan_step_id="research",
            rationale_summary="Finish after the delegate result.",
            expected_state_change=ExpectedStateChange(summary="Persist final output."),
            final_output=AgentOutput(summary="Done.", user_visible=True),
        )
        captured = CapturingDelegateExecutor()
        transitions = InMemoryTransitionSink()
        kernel = AgentKernel(
            policy=ReplayPolicy(plans=[agent_plan()], decisions=[delegate, final]),
            context_builder=ContextBuilder(token_budget=4_000),
            skill_registry=build_default_skill_registry(),
            skill_action_executor=object(),
            subagent_executor=captured,
            checkpointer=InMemoryCheckpointHandle(),
            transition_sink=transitions,
        )
        await kernel.start(task_state())
        return captured, transitions.events

    captured, transitions = asyncio.run(scenario())

    delegate_transition = next(event for event in transitions if event.parsed_decision.action_type == AgentActionType.DELEGATE)
    assert captured.parent_transition_id == delegate_transition.transition_id
    assert captured.task is not None
    assert captured.task.parent_transition_id == delegate_transition.transition_id
