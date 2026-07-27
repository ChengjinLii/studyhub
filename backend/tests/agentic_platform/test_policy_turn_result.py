from __future__ import annotations

import asyncio

import pytest

from app.agentic_platform.domain.decision import AgentActionType
from app.agentic_platform.domain.transition import ModelUsage, TokenRole, TokenRoleSpan
from app.agentic_platform.policy.context_builder import ContextBuilder
from app.agentic_platform.policy.model_policy import InvalidModelOutputError, ModelPolicy
from app.agentic_platform.policy.model_provider import AgentModelRequest, AgentModelResponse
from app.agentic_platform.policy.openai_compatible_provider import ModelResponseQuarantinedError
from app.agentic_platform.policy.provider_factory import (
    AgentModelProviderConfigurationError,
    build_agent_model_provider,
)
from app.agentic_platform.policy.token_trace import TokenTraceSource
from app.agentic_platform.policy.turn_result import InMemoryRestrictedRawModelOutputStore, PolicyTurnResult
from app.core.config import Settings
from app.agentic_platform.skills.registry import build_default_skill_registry
from tests.agentic_platform.factories import decision, task_state


class _Provider:
    def __init__(self, response: AgentModelResponse) -> None:
        self.response = response
        self.requests: list[AgentModelRequest] = []

    async def complete(self, request: AgentModelRequest) -> AgentModelResponse:
        self.requests.append(request)
        return self.response

    async def capabilities(self):
        raise AssertionError("not needed by ModelPolicy")


class _QuarantinedProvider:
    async def complete(self, request: AgentModelRequest) -> AgentModelResponse:
        del request
        raise ModelResponseQuarantinedError(
            code="openai_compatible_invalid_model_json",
            raw_content="private malformed raw output",
        )

    async def capabilities(self):
        raise AssertionError("not needed by ModelPolicy")


def test_policy_turn_result_preserves_model_metadata_and_restricted_raw_output() -> None:
    state = task_state()
    store = InMemoryRestrictedRawModelOutputStore()
    response = AgentModelResponse(
        model_id="local-policy-model",
        model_revision="revision-7",
        structured_output=decision().model_dump(mode="json"),
        usage=ModelUsage(input_tokens=12, output_tokens=5, total_tokens=17),
        token_ids=[11, 12],
        token_logprobs=[-0.1, -0.2],
        token_role_spans=[TokenRoleSpan(role=TokenRole.ASSISTANT_ACTION, start=0, end=2, trainable=True)],
        token_trace_source=TokenTraceSource.LOCAL,
        raw_content='{"action_type":"review"}',
        finish_reason="stop",
        latency_ms={"provider_request": 4.5},
        provider_request_id="provider-request-1",
    )
    policy = ModelPolicy(_Provider(response), raw_output_store=store)
    context = ContextBuilder(token_budget=4_000).build_policy_context(state, build_default_skill_registry().list())

    turn = asyncio.run(policy.decide(state, context))

    assert turn.parsed_output.action_type == AgentActionType.REVIEW
    assert turn.model_id == "local-policy-model"
    assert turn.model_revision == "revision-7"
    assert turn.usage.total_tokens == 17
    assert turn.latency_ms == {"provider_request": 4.5}
    assert turn.token_ids == [11, 12]
    assert turn.token_role_spans[0].trainable is True
    assert turn.trainable is True
    assert turn.raw_model_output_ref is not None
    assert store.payloads[turn.raw_model_output_ref.artifact_id] == '{"action_type":"review"}'
    assert "action_type" not in turn.raw_model_output_ref.summary


def test_invalid_json_is_quarantined_in_restricted_store_and_safe_error() -> None:
    state = task_state()
    store = InMemoryRestrictedRawModelOutputStore()
    policy = ModelPolicy(_QuarantinedProvider(), raw_output_store=store)
    context = ContextBuilder(token_budget=4_000).build_policy_context(state, build_default_skill_registry().list())

    with pytest.raises(InvalidModelOutputError) as captured:
        asyncio.run(policy.decide(state, context))

    error = captured.value
    assert error.raw_model_output_ref is not None
    assert store.payloads[error.raw_model_output_ref.artifact_id] == "private malformed raw output"
    assert "private malformed raw output" not in str(error)


def test_policy_turn_rejects_teacher_tokens_and_replay_stays_non_trainable() -> None:
    with pytest.raises(ValueError, match="teacher or unavailable"):
        PolicyTurnResult(
            parsed_output=decision(),
            model_id="teacher",
            prompt_hash="prompt",
            context_hash="context",
            token_ids=[1],
            token_trace_source=TokenTraceSource.TEACHER_API,
        )

    replay_turn = PolicyTurnResult(
        parsed_output=decision(),
        model_id="replay",
        prompt_hash="prompt",
        context_hash="context",
        token_trace_source=TokenTraceSource.UNAVAILABLE,
        trainable=False,
    )
    assert replay_turn.trainable is False
    assert replay_turn.token_ids is None


def test_provider_factory_requires_explicit_opt_in_configuration() -> None:
    with pytest.raises(AgentModelProviderConfigurationError):
        build_agent_model_provider(Settings())

    configured = Settings(
        agentic_model_provider="openai_compatible",
        agentic_model_base_url="https://model.test/v1",
        agentic_model_api_key="test-key",
        agentic_model_id="test-model",
    )
    provider = build_agent_model_provider(configured)
    assert provider.model_id == "test-model"
