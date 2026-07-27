from __future__ import annotations

import asyncio
import json
from time import perf_counter
from typing import Any

import httpx

from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.transition import ModelUsage, TokenRoleSpan

from .model_provider import AgentModelRequest, AgentModelResponse, AgentProviderCapabilities
from .token_trace import TokenTraceSource


class AgentModelProviderError(RuntimeError):
    """Safe provider failure: messages never contain credentials or raw output."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class ModelResponseQuarantinedError(AgentModelProviderError):
    """Malformed model content retained only by a restricted artifact sink."""

    def __init__(self, *, code: str, raw_content: str, retryable: bool = False) -> None:
        self.raw_content = raw_content
        self.content_hash = canonical_hash(raw_content)
        super().__init__(code, retryable=retryable)


class OpenAICompatibleProvider:
    """OpenAI chat-completions JSON provider with safe retry and provenance.

    It treats remote API output as teacher data. Token IDs are accepted only
    when an explicitly local OpenAI-compatible endpoint returns its native
    tokenizer trace; no token IDs are synthesized from token strings.
    """

    provider_name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_id: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        model_revision: str | None = None,
        token_trace_source: TokenTraceSource = TokenTraceSource.TEACHER_API,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized_base_url = base_url.rstrip("/")
        if not normalized_base_url:
            raise ValueError("base_url must not be blank")
        if not api_key.strip():
            raise ValueError("api_key must not be blank")
        if not model_id.strip():
            raise ValueError("model_id must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")
        self.base_url = normalized_base_url
        self._api_key = api_key
        self.model_id = model_id
        self.model_revision = model_revision
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.token_trace_source = token_trace_source
        self._client = client

    async def complete(self, request: AgentModelRequest) -> AgentModelResponse:
        started = perf_counter()
        last_error: AgentModelProviderError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._post_chat_completion(request)
                if response.status_code in {429, 500, 503}:
                    last_error = AgentModelProviderError(
                        f"openai_compatible_http_{response.status_code}",
                        retryable=True,
                    )
                    if attempt < self.max_retries:
                        await self._backoff(attempt)
                        continue
                    raise last_error
                if response.status_code >= 400:
                    raise AgentModelProviderError(f"openai_compatible_http_{response.status_code}", retryable=False)
                return self._parse_response(response, elapsed_ms=(perf_counter() - started) * 1_000)
            except (httpx.TimeoutException, httpx.NetworkError):
                last_error = AgentModelProviderError("openai_compatible_network_timeout", retryable=True)
                if attempt < self.max_retries:
                    await self._backoff(attempt)
                    continue
                raise last_error
            except AgentModelProviderError as exc:
                if exc.retryable and attempt < self.max_retries:
                    last_error = exc
                    await self._backoff(attempt)
                    continue
                raise
        raise last_error or AgentModelProviderError("openai_compatible_request_failed", retryable=True)

    async def capabilities(self) -> AgentProviderCapabilities:
        return AgentProviderCapabilities(
            provider_name=self.provider_name,
            model_id=self.model_id,
            model_revision=self.model_revision,
            supports_json_schema=True,
            supports_tool_calls=False,
            supports_token_ids=self.token_trace_source == TokenTraceSource.LOCAL,
            max_context_tokens=0,
            max_output_tokens=32_000,
        )

    async def _post_chat_completion(self, request: AgentModelRequest) -> httpx.Response:
        payload = {
            "model": self.model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return exactly one JSON object. Do not reveal hidden reasoning. "
                        'JSON example: {"result":"schema-compliant value"}.'
                    ),
                },
                {"role": "user", "content": request.rendered_prompt},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": request.max_output_tokens,
            "user": f"run_{canonical_hash({'context_hash': request.context_hash})[:32]}",
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._client is not None:
            return await self._client.post("/chat/completions", headers=headers, json=payload)
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            return await client.post("/chat/completions", headers=headers, json=payload)

    def _parse_response(self, response: httpx.Response, *, elapsed_ms: float) -> AgentModelResponse:
        raw_response = response.text
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ModelResponseQuarantinedError(
                code="openai_compatible_invalid_response_json",
                raw_content=raw_response,
                retryable=False,
            ) from exc
        if not isinstance(payload, dict):
            raise ModelResponseQuarantinedError(
                code="openai_compatible_invalid_response_shape",
                raw_content=raw_response,
                retryable=False,
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ModelResponseQuarantinedError(
                code="openai_compatible_missing_choice",
                raw_content=raw_response,
                retryable=False,
            )
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ModelResponseQuarantinedError(
                code="openai_compatible_missing_message",
                raw_content=raw_response,
                retryable=False,
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise AgentModelProviderError("openai_compatible_empty_content", retryable=True)
        try:
            structured_output = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ModelResponseQuarantinedError(
                code="openai_compatible_invalid_model_json",
                raw_content=content,
                retryable=False,
            ) from exc
        if not isinstance(structured_output, dict):
            raise ModelResponseQuarantinedError(
                code="openai_compatible_model_json_not_object",
                raw_content=content,
                retryable=False,
            )
        token_ids, token_logprobs, token_role_spans = self._extract_local_token_trace(payload=payload, message=message)
        model_id = payload.get("model") if isinstance(payload.get("model"), str) and payload["model"].strip() else self.model_id
        response_id = self._request_id(response, payload)
        return AgentModelResponse(
            model_id=model_id,
            model_revision=self.model_revision,
            structured_output=structured_output,
            usage=_usage_from_payload(payload.get("usage")),
            token_ids=token_ids,
            token_logprobs=token_logprobs,
            token_role_spans=token_role_spans,
            token_trace_source=self.token_trace_source if token_ids is not None else TokenTraceSource.UNAVAILABLE,
            raw_content=content,
            reasoning_content_present=bool(message.get("reasoning_content")),
            finish_reason=choice.get("finish_reason") if isinstance(choice.get("finish_reason"), str) else None,
            latency_ms={"provider_request": max(0.0, round(elapsed_ms, 3))},
            provider_request_id=response_id,
        )

    def _extract_local_token_trace(
        self,
        *,
        payload: dict[str, Any],
        message: dict[str, Any],
    ) -> tuple[list[int] | None, list[float] | None, list[TokenRoleSpan]]:
        if self.token_trace_source != TokenTraceSource.LOCAL:
            return None, None, []
        raw_ids = message.get("token_ids", payload.get("token_ids"))
        raw_logprobs = message.get("token_logprobs", payload.get("token_logprobs"))
        raw_spans = message.get("token_role_spans", payload.get("token_role_spans", []))
        if not isinstance(raw_ids, list) or any(not isinstance(item, int) or item < 0 for item in raw_ids):
            return None, None, []
        if raw_logprobs is not None and (
            not isinstance(raw_logprobs, list)
            or any(not isinstance(item, (int, float)) for item in raw_logprobs)
            or len(raw_logprobs) != len(raw_ids)
        ):
            return None, None, []
        try:
            spans = [TokenRoleSpan.model_validate(item) for item in raw_spans] if isinstance(raw_spans, list) else []
        except Exception:  # noqa: BLE001 - invalid optional traces become unavailable, not synthesized.
            return None, None, []
        if spans and any(span.end > len(raw_ids) for span in spans):
            return None, None, []
        return list(raw_ids), [float(item) for item in raw_logprobs] if raw_logprobs is not None else None, spans

    async def _backoff(self, attempt: int) -> None:
        if self.retry_backoff_seconds:
            await asyncio.sleep(self.retry_backoff_seconds * (attempt + 1))

    @staticmethod
    def _request_id(response: httpx.Response, payload: dict[str, Any]) -> str | None:
        for header in ("x-request-id", "request-id"):
            value = response.headers.get(header)
            if value and value.strip():
                return value[:256]
        value = payload.get("id")
        return value[:256] if isinstance(value, str) and value.strip() else None


def _usage_from_payload(raw_usage: object) -> ModelUsage:
    usage = raw_usage if isinstance(raw_usage, dict) else {}
    input_tokens = _nonnegative_int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
    output_tokens = _nonnegative_int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
    cached_details = usage.get("prompt_tokens_details")
    cached_input_tokens = (
        _nonnegative_int(cached_details.get("cached_tokens", 0)) if isinstance(cached_details, dict) else 0
    )
    total_tokens = max(
        input_tokens + output_tokens,
        _nonnegative_int(usage.get("total_tokens", input_tokens + output_tokens)),
    )
    return ModelUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        total_tokens=total_tokens,
    )


def _nonnegative_int(value: object) -> int:
    return int(value) if isinstance(value, int | float) and value >= 0 else 0
