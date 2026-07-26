from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from pydantic import Field, field_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.transition import ModelUsage

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
    """Only structured output is retained; raw reasoning text is intentionally absent."""

    model_id: str = Field(min_length=1, max_length=256)
    model_revision: str | None = Field(default=None, max_length=256)
    structured_output: dict[str, object]
    usage: ModelUsage = Field(default_factory=ModelUsage)
    token_ids: list[int] | None = None


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
