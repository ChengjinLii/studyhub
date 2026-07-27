from __future__ import annotations

import asyncio

import httpx
import pytest

from app.agentic_platform.domain.transition import TokenRole, TokenRoleSpan
from app.agentic_platform.policy.context_view import ContextPurpose
from app.agentic_platform.policy.model_provider import AgentModelRequest
from app.agentic_platform.policy.openai_compatible_provider import (
    AgentModelProviderError,
    ModelResponseQuarantinedError,
    OpenAICompatibleProvider,
)
from app.agentic_platform.policy.token_trace import TokenTraceSource


def _request() -> AgentModelRequest:
    return AgentModelRequest(
        purpose=ContextPurpose.POLICY,
        rendered_prompt='Return JSON only. JSON example: {"answer":"value"}.',
        context_hash="context-hash",
        prompt_hash="prompt-hash",
        output_schema_name="FixtureOutput",
        output_schema={"type": "object"},
        max_output_tokens=256,
    )


def test_openai_compatible_provider_preserves_safe_response_metadata_without_logging_key(caplog) -> None:
    secret = "do-not-log-this-api-key"
    requests: list[httpx.Request] = []

    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            body = __import__("json").loads(request.content)
            assert request.url.path == "/chat/completions"
            assert body["response_format"] == {"type": "json_object"}
            assert body["user"].startswith("run_")
            assert "JSON example" in body["messages"][0]["content"]
            return httpx.Response(
                200,
                headers={"x-request-id": "request-42"},
                json={
                    "id": "body-id",
                    "model": "provider-actual-model",
                    "choices": [
                        {
                            "message": {
                                "content": '{"answer":"structured"}',
                                "reasoning_content": "private reasoning must not persist",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 7,
                        "total_tokens": 18,
                        "prompt_tokens_details": {"cached_tokens": 3},
                    },
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://model.test") as client:
            provider = OpenAICompatibleProvider(
                base_url="https://model.test",
                api_key=secret,
                model_id="configured-model",
                client=client,
            )
            response = await provider.complete(_request())
            assert response.model_id == "provider-actual-model"
            assert response.usage.input_tokens == 11
            assert response.usage.output_tokens == 7
            assert response.usage.cached_input_tokens == 3
            assert response.usage.total_tokens == 18
            assert response.provider_request_id == "request-42"
            assert response.finish_reason == "stop"
            assert response.reasoning_content_present is True
            assert response.raw_content == '{"answer":"structured"}'
            assert response.token_ids is None
            assert response.token_trace_source == TokenTraceSource.UNAVAILABLE
            assert response.latency_ms["provider_request"] >= 0

    asyncio.run(scenario())
    assert requests[0].headers["authorization"] == f"Bearer {secret}"
    assert secret not in caplog.text


def test_empty_content_and_retryable_status_are_retried() -> None:
    calls = 0

    async def scenario() -> None:
        nonlocal calls

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            if calls == 1:
                return httpx.Response(429, json={"error": {"message": "try later"}})
            if calls == 2:
                return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})
            return httpx.Response(
                200,
                json={
                    "model": "retry-model",
                    "choices": [{"message": {"content": '{"answer":"after retry"}'}, "finish_reason": "stop"}],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://model.test") as client:
            provider = OpenAICompatibleProvider(
                base_url="https://model.test",
                api_key="test-key",
                model_id="configured-model",
                max_retries=2,
                retry_backoff_seconds=0,
                client=client,
            )
            response = await provider.complete(_request())
            assert response.structured_output == {"answer": "after retry"}

    asyncio.run(scenario())
    assert calls == 3


def test_invalid_json_is_quarantined_without_echoing_raw_content() -> None:
    raw_content = "this is not JSON and must never appear in an exception"

    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(200, json={"choices": [{"message": {"content": raw_content}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://model.test") as client:
            provider = OpenAICompatibleProvider(
                base_url="https://model.test",
                api_key="test-key",
                model_id="configured-model",
                client=client,
            )
            with pytest.raises(ModelResponseQuarantinedError) as captured:
                await provider.complete(_request())
            assert captured.value.code == "openai_compatible_invalid_model_json"
            assert captured.value.raw_content == raw_content
            assert raw_content not in str(captured.value)

    asyncio.run(scenario())


def test_teacher_api_never_synthesizes_token_ids_but_explicit_local_trace_is_preserved() -> None:
    response_payload = {
        "choices": [
            {
                "message": {
                    "content": '{"answer":"trace"}',
                    "token_ids": [101, 102],
                    "token_logprobs": [-0.1, -0.2],
                    "token_role_spans": [
                        TokenRoleSpan(role=TokenRole.ASSISTANT_ACTION, start=0, end=2, trainable=True).model_dump(
                            mode="json"
                        )
                    ],
                }
            }
        ]
    }

    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(200, json=response_payload)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://model.test") as client:
            teacher = OpenAICompatibleProvider(
                base_url="https://model.test",
                api_key="test-key",
                model_id="teacher",
                client=client,
            )
            teacher_response = await teacher.complete(_request())
            assert teacher_response.token_ids is None
            assert teacher_response.token_role_spans == []

            local = OpenAICompatibleProvider(
                base_url="https://model.test",
                api_key="test-key",
                model_id="local",
                token_trace_source=TokenTraceSource.LOCAL,
                client=client,
            )
            local_response = await local.complete(_request())
            assert local_response.token_ids == [101, 102]
            assert local_response.token_logprobs == [-0.1, -0.2]
            assert local_response.token_role_spans[0].role == TokenRole.ASSISTANT_ACTION
            assert local_response.token_trace_source == TokenTraceSource.LOCAL

    asyncio.run(scenario())


def test_non_retryable_http_error_exposes_only_stable_code() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(401, json={"error": {"message": "sensitive provider detail"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://model.test") as client:
            provider = OpenAICompatibleProvider(
                base_url="https://model.test",
                api_key="test-key",
                model_id="configured-model",
                client=client,
            )
            with pytest.raises(AgentModelProviderError) as captured:
                await provider.complete(_request())
            assert captured.value.code == "openai_compatible_http_401"
            assert captured.value.retryable is False
            assert "sensitive provider detail" not in str(captured.value)

    asyncio.run(scenario())
