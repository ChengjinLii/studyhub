from __future__ import annotations

from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel, Field, model_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.state import AgentTaskState
from app.agentic_platform.domain.transition import ModelUsage, TokenRoleSpan

from .context_view import ContextPurpose
from .token_trace import TokenTrace, TokenTraceSource


OutputT = TypeVar("OutputT", bound=BaseModel)


class RawModelOutputStore(Protocol):
    """Restricted storage only. No implementation may surface raw content in events."""

    async def store(
        self,
        *,
        state: AgentTaskState,
        purpose: ContextPurpose,
        raw_content: str,
        model_id: str,
        prompt_hash: str,
    ) -> ArtifactRef:
        ...


class InMemoryRestrictedRawModelOutputStore:
    """Test/development adapter; R5 replaces this with durable restricted artifacts."""

    def __init__(self) -> None:
        self.payloads: dict[str, str] = {}

    async def store(
        self,
        *,
        state: AgentTaskState,
        purpose: ContextPurpose,
        raw_content: str,
        model_id: str,
        prompt_hash: str,
    ) -> ArtifactRef:
        content_hash = canonical_hash(
            {
                "run_id": state.run_id,
                "purpose": purpose.value,
                "model_id": model_id,
                "prompt_hash": prompt_hash,
                "raw_content": raw_content,
            }
        )
        artifact_id = f"raw_model_{content_hash[:24]}"
        self.payloads[artifact_id] = raw_content
        return ArtifactRef(
            artifact_id=artifact_id,
            artifact_type=ArtifactKind.RAW_MODEL_OUTPUT,
            version=1,
            uri=f"artifact://restricted/raw-model-output/{artifact_id}",
            content_hash=content_hash,
            media_type="application/json",
            summary=f"Restricted {purpose.value} model output",
        )


class PolicyTurnResult(DomainModel, Generic[OutputT]):
    """One parsed policy result plus immutable provider provenance."""

    schema_version: str = "1.0"
    parsed_output: OutputT
    model_id: str = Field(min_length=1, max_length=256)
    model_revision: str | None = Field(default=None, max_length=256)
    prompt_hash: str = Field(min_length=1, max_length=128)
    context_hash: str = Field(min_length=1, max_length=128)
    raw_model_output_ref: ArtifactRef | None = None
    token_ids: list[int] | None = None
    token_logprobs: list[float] | None = None
    token_role_spans: list[TokenRoleSpan] = Field(default_factory=list)
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_ms: dict[str, float] = Field(default_factory=dict)
    finish_reason: str | None = Field(default=None, max_length=128)
    provider_request_id: str | None = Field(default=None, max_length=256)
    token_trace_source: TokenTraceSource = TokenTraceSource.UNAVAILABLE
    trainable: bool = False

    @model_validator(mode="after")
    def validate_token_trace(self) -> "PolicyTurnResult[OutputT]":
        trace = self.token_trace()
        if self.trainable and not trace.trainable:
            raise ValueError("trainable policy turns require an explicit local token trace")
        return self

    def token_trace(self) -> TokenTrace:
        return TokenTrace(
            source=self.token_trace_source,
            token_ids=self.token_ids,
            token_logprobs=self.token_logprobs,
            token_role_spans=self.token_role_spans,
        )

    def runtime_metadata(self) -> dict[str, object]:
        """Return checkpoint-safe provenance without parsed or raw content.

        Parsed output already has a typed home in graph state (plan, decision,
        or final output).  Raw provider content is intentionally absent from
        this model and may only be reached through ``raw_model_output_ref``.
        """

        return self.model_dump(mode="json", exclude={"parsed_output"})


def replay_turn(*, parsed_output: OutputT, purpose: ContextPurpose, context_hash: str) -> PolicyTurnResult[OutputT]:
    """Produce a deliberately non-trainable result for deterministic fixtures."""

    return PolicyTurnResult(
        parsed_output=parsed_output,
        model_id="replay",
        model_revision=None,
        prompt_hash=canonical_hash({"provider": "replay", "purpose": purpose.value, "context_hash": context_hash}),
        context_hash=context_hash,
        token_trace_source=TokenTraceSource.UNAVAILABLE,
        trainable=False,
    )


def unwrap_policy_output(value: OutputT | PolicyTurnResult[OutputT]) -> OutputT:
    """Compatibility helper for integrations that only need parsed output."""

    return value.parsed_output if isinstance(value, PolicyTurnResult) else value
