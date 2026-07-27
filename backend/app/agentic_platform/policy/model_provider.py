from __future__ import annotations

from typing import Protocol

from pydantic import Field, field_validator, model_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.transition import ModelUsage, TokenRoleSpan

from .token_trace import TokenTraceSource

from .context_view import ContextPurpose


class AgentProviderCapabilities(DomainModel):
    provider_name: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=256)
    model_revision: str | None = Field(default=None, max_length=256)
    supports_json_schema: bool = False
    supports_tool_calls: bool = False
    supports_token_ids: bool = False
    max_context_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)


class AgentModelRequest(DomainModel):
    purpose: ContextPurpose
    rendered_prompt: str = Field(min_length=1, max_length=200_000)
    context_hash: str = Field(min_length=1, max_length=128)
    prompt_hash: str = Field(min_length=1, max_length=128)
    output_schema_name: str = Field(min_length=1, max_length=256)
    output_schema: dict[str, object]
    max_output_tokens: int = Field(gt=0, le=32_000)

    @field_validator("rendered_prompt", "context_hash", "prompt_hash", "output_schema_name")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class AgentModelResponse(DomainModel):
    """A provider response with raw content kept outside public runtime events."""

    schema_version: str = "1.0"
    model_id: str = Field(min_length=1, max_length=256)
    model_revision: str | None = Field(default=None, max_length=256)
    structured_output: dict[str, object]
    usage: ModelUsage = Field(default_factory=ModelUsage)
    token_ids: list[int] | None = None
    token_logprobs: list[float] | None = None
    token_role_spans: list[TokenRoleSpan] = Field(default_factory=list)
    token_trace_source: TokenTraceSource = TokenTraceSource.UNAVAILABLE
    raw_content: str | None = Field(default=None, max_length=200_000)
    reasoning_content_present: bool = False
    finish_reason: str | None = Field(default=None, max_length=128)
    latency_ms: dict[str, float] = Field(default_factory=dict)
    provider_request_id: str | None = Field(default=None, max_length=256)

    @field_validator("token_ids")
    @classmethod
    def validate_token_ids(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and any(token_id < 0 for token_id in value):
            raise ValueError("token IDs must be non-negative")
        return value

    @field_validator("latency_ms")
    @classmethod
    def validate_latency(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not name.strip() for name in value):
            raise ValueError("latency metric names must not be blank")
        if any(number < 0 for number in value.values()):
            raise ValueError("latency values must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_token_trace(self) -> "AgentModelResponse":
        if self.token_logprobs is not None:
            if self.token_ids is None or len(self.token_logprobs) != len(self.token_ids):
                raise ValueError("token logprobs must align with token IDs")
        if self.token_role_spans and self.token_ids is None:
            raise ValueError("token role spans require token IDs")
        if self.token_ids is not None and any(span.end > len(self.token_ids) for span in self.token_role_spans):
            raise ValueError("token role span exceeds token IDs")
        if self.token_trace_source != TokenTraceSource.LOCAL and (
            self.token_ids is not None or self.token_logprobs is not None or self.token_role_spans
        ):
            raise ValueError("only explicitly local providers may supply token traces")
        return self


class AgentModelProvider(Protocol):
    async def complete(self, request: AgentModelRequest) -> AgentModelResponse:
        ...

    async def capabilities(self) -> AgentProviderCapabilities:
        ...


class CachedAgentModelProvider:
    """In-memory, request-hash cache around an interchangeable model provider."""

    def __init__(self, provider: AgentModelProvider) -> None:
        self.provider = provider
        self._response_cache: dict[str, AgentModelResponse] = {}
        self._capabilities: AgentProviderCapabilities | None = None

    async def complete(self, request: AgentModelRequest) -> AgentModelResponse:
        cache_key = canonical_hash(request)
        cached = self._response_cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(deep=True)
        response = await self.provider.complete(request)
        self._response_cache[cache_key] = response.model_copy(deep=True)
        return response

    async def capabilities(self) -> AgentProviderCapabilities:
        if self._capabilities is None:
            self._capabilities = (await self.provider.capabilities()).model_copy(deep=True)
        return self._capabilities.model_copy(deep=True)

    def clear(self) -> None:
        self._response_cache.clear()
        self._capabilities = None
