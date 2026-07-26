from __future__ import annotations

from pydantic import Field

from ._base import DomainModel
from .artifact import ArtifactRef


class RewardFacts(DomainModel):
    """Observed facts only; reward-policy math belongs outside the runtime."""

    terminal_success: bool | None = None
    format_valid: bool = True
    action_valid: bool = True

    constraint_delta: int = 0
    milestone_delta: int = 0
    evidence_added: int = Field(default=0, ge=0)

    citation_supported: int = Field(default=0, ge=0)
    citation_invalid: int = Field(default=0, ge=0)

    duplicate_action: bool = False
    void_turn: bool = False
    observation_corrupted: bool = False
    tool_error_recovered: bool = False

    search_query_novelty: float | None = None
    candidate_rank_delta: float | None = None
    information_potential_inputs_ref: ArtifactRef | None = None

    user_questions: int = Field(default=0, ge=0)
    tool_cost: float = Field(default=0.0, ge=0.0)
    context_tokens: int = Field(default=0, ge=0)

    trainable: bool = True
