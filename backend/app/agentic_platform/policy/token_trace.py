from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.transition import TokenRoleSpan


class TokenTraceSource(StrEnum):
    """Origin is explicit so teacher API output cannot masquerade as RL tokens."""

    LOCAL = "local"
    TEACHER_API = "teacher_api"
    UNAVAILABLE = "unavailable"


class TokenTrace(DomainModel):
    schema_version: str = "1.0"
    source: TokenTraceSource = TokenTraceSource.UNAVAILABLE
    token_ids: list[int] | None = None
    token_logprobs: list[float] | None = None
    token_role_spans: list[TokenRoleSpan] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_trace(self) -> "TokenTrace":
        if self.token_logprobs is not None:
            if self.token_ids is None or len(self.token_logprobs) != len(self.token_ids):
                raise ValueError("token logprobs must align with token IDs")
        if self.token_role_spans and self.token_ids is None:
            raise ValueError("token role spans require token IDs")
        if self.token_ids is not None and any(token_id < 0 for token_id in self.token_ids):
            raise ValueError("token IDs must be non-negative")
        if self.token_ids is not None and any(span.end > len(self.token_ids) for span in self.token_role_spans):
            raise ValueError("token role span exceeds token IDs")
        if self.source != TokenTraceSource.LOCAL and (
            self.token_ids is not None or self.token_logprobs is not None or self.token_role_spans
        ):
            raise ValueError("teacher or unavailable traces cannot contain local tokenizer data")
        return self

    @property
    def trainable(self) -> bool:
        return self.source == TokenTraceSource.LOCAL and self.token_ids is not None and bool(self.token_role_spans)
