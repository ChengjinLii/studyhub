from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.domain.decision import AgentActionType, AgentDecision, AgentOutput, ExpectedStateChange
from app.agentic_platform.domain.hashing import canonical_json
from app.agentic_platform.policy.capability_probe import CapabilityProbe
from app.agentic_platform.policy.context_builder import ContextBuilder
from app.agentic_platform.policy.model_policy import InvalidModelOutputError, ModelPolicy, render_policy_prompt
from app.agentic_platform.policy.model_provider import (
    AgentModelRequest,
    AgentModelResponse,
    AgentProviderCapabilities,
    CachedAgentModelProvider,
)
from app.agentic_platform.policy.replay_policy import ReplayPolicy
from app.agentic_platform.skills.registry import build_default_skill_registry
from tests.agentic_platform.factories import agent_plan, decision, task_state


def _artifact_ref() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="artifact-context",
        artifact_type=ArtifactKind.RESEARCH_MEMORY,
        version=1,
        uri="artifact://private/research-memory?access_token=super-secret-token",
        content_hash="content-hash",
        summary="Research summary with token=super-secret-token",
    )


def _state_with_sensitive_values():
    state = task_state()
    return state.model_copy(
        update={
            "goal": state.goal.model_copy(update={"statement": "Build plan api_key=super-secret-key"}),
            "active_artifacts": [_artifact_ref()],
        }
    )


def test_context_builder_separates_phase_views_redacts_secrets_and_honors_token_budget() -> None:
    state = _state_with_sensitive_values()
    registry = build_default_skill_registry()
    builder = ContextBuilder(token_budget=2_000)

    planner = builder.build_planner_context(state, registry.list())
    policy = builder.build_policy_context(
        state,
        registry.list(),
        observation_summaries=["tool_secret=super-secret-observation " + "x" * 8_000],
    )
    final = builder.build_final_context(state)
    rendered = canonical_json(policy)

    assert planner.capabilities
    assert planner.working_set.candidate_ids == []
    assert policy.capabilities
    assert final.capabilities == []
    assert "super-secret-key" not in rendered
    assert "super-secret-token" not in rendered
    assert "super-secret-observation" not in rendered
    assert "artifact://" not in rendered
    assert policy.estimated_tokens <= policy.token_budget
    assert policy.capability_count == len(registry.names())
    assert policy.capability_count == len(policy.capabilities)


def test_context_compaction_keeps_the_capability_catalog_while_only_compacting_the_view() -> None:
    state = task_state()
    registry = build_default_skill_registry()
    context = ContextBuilder(token_budget=1_200).build_policy_context(
        state,
        registry.list(),
        observation_summaries=[
            "non-secret observation one " + "x" * 10_000,
            "non-secret observation two " + "y" * 10_000,
        ],
    )

    assert context.truncated is True
    assert context.estimated_tokens <= context.token_budget
    assert context.capability_count == len(registry.names())
    assert context.capability_count == len(context.capabilities)


def test_prompt_hash_is_stable_and_sensitive_to_context_business_changes() -> None:
    state = task_state()
    context = ContextBuilder(token_budget=4_000).build_policy_context(state, build_default_skill_registry().list())

    first = render_policy_prompt(context, AgentDecision)
    second = render_policy_prompt(context, AgentDecision)
    changed_context = context.model_copy(update={"goal": "A materially changed learning goal"})
    changed = render_policy_prompt(changed_context, AgentDecision)

    assert first.context_hash == second.context_hash
    assert first.prompt_hash == second.prompt_hash
    assert first.rendered_prompt == second.rendered_prompt
    assert first.prompt_hash != changed.prompt_hash


def test_replay_policy_completes_without_any_model_provider() -> None:
    state = task_state()
    registry = build_default_skill_registry()
    builder = ContextBuilder(token_budget=4_000)
    scripted_decision = AgentDecision(
        action_type=AgentActionType.REVIEW,
        plan_step_id="review",
        rationale_summary="Replay the fixed review action.",
        expected_state_change=ExpectedStateChange(summary="No state change for policy smoke test."),
    )
    scripted_final = AgentOutput(summary="Replay final output")
    replay = ReplayPolicy(plans=[agent_plan()], decisions=[scripted_decision], final_outputs=[scripted_final])

    plan = asyncio.run(replay.create_plan(state, builder.build_planner_context(state, registry.list())))
    action = asyncio.run(replay.decide(state, builder.build_policy_context(state, registry.list())))
    output = asyncio.run(replay.finalize(state, builder.build_final_context(state)))

    assert plan.parsed_output.plan_id == "plan-1"
    assert action.parsed_output == scripted_decision
    assert output.parsed_output == scripted_final
    assert {plan.model_id, action.model_id, output.model_id} == {"replay"}
    assert not plan.trainable and plan.token_ids is None
    assert not hasattr(replay, "provider")


@dataclass
class FakeProvider:
    responses: list[dict[str, object]]
    calls: list[AgentModelRequest] = field(default_factory=list)
    capability_calls: int = 0

    async def complete(self, request: AgentModelRequest) -> AgentModelResponse:
        self.calls.append(request)
        return AgentModelResponse(model_id="fake-model", structured_output=self.responses.pop(0))

    async def capabilities(self) -> AgentProviderCapabilities:
        self.capability_calls += 1
        return AgentProviderCapabilities(
            provider_name="fake",
            model_id="fake-model",
            supports_json_schema=True,
            supports_token_ids=True,
            max_context_tokens=16_000,
            max_output_tokens=2_000,
        )


def test_model_policy_uses_replaceable_structured_provider_and_cached_capabilities() -> None:
    state = task_state()
    builder = ContextBuilder(token_budget=4_000)
    registry = build_default_skill_registry()
    provider = FakeProvider(
        responses=[
            agent_plan().model_dump(mode="json"),
            decision().model_dump(mode="json"),
            AgentOutput(summary="Model final").model_dump(mode="json"),
            agent_plan().model_dump(mode="json"),
        ]
    )
    policy = ModelPolicy(provider)

    plan = asyncio.run(policy.create_plan(state, builder.build_planner_context(state, registry.list())))
    action = asyncio.run(policy.decide(state, builder.build_policy_context(state, registry.list())))
    output = asyncio.run(policy.finalize(state, builder.build_final_context(state)))
    cached = CachedAgentModelProvider(provider)
    request = provider.calls[0]
    first_cached = asyncio.run(cached.complete(request))
    second_cached = asyncio.run(cached.complete(request))
    capabilities = asyncio.run(cached.capabilities())
    again_capabilities = asyncio.run(cached.capabilities())
    probe = CapabilityProbe()

    assert plan.parsed_output.plan_id == "plan-1"
    assert action.parsed_output.action_type == AgentActionType.REVIEW
    assert output.parsed_output.summary == "Model final"
    assert plan.model_id == "fake-model"
    assert plan.context_hash and plan.prompt_hash
    assert first_cached == second_cached
    assert len(provider.calls) == 4  # Three direct model-policy calls plus one cached-provider miss.
    assert capabilities == again_capabilities
    assert provider.capability_calls == 1
    assert asyncio.run(probe.fingerprint(cached)) == asyncio.run(probe.fingerprint(cached))


def test_invalid_model_output_becomes_a_safe_structured_failure() -> None:
    state = task_state()
    provider = FakeProvider(responses=[{"rationale_summary": "api_key=super-secret-model-output"}])
    policy = ModelPolicy(provider)
    context = ContextBuilder(token_budget=4_000).build_policy_context(state, build_default_skill_registry().list())

    with pytest.raises(InvalidModelOutputError) as captured:
        asyncio.run(policy.decide(state, context))

    error = captured.value
    assert error.purpose.value == "policy"
    assert error.response_hash
    assert "super-secret-model-output" not in str(error)
