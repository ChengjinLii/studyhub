"""Canonical, raw-content-free transitions for DeepResearch subagents.

The parent runtime and the research graph intentionally have different state
machines.  This contract records the latter without pretending a research
decision is a parent ``AgentDecision``.  It keeps child ordering, parent
linkage, model provenance, and sanitized tool observation metadata explicit.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import Field, field_validator, model_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.domain.data_policy import TrainingDataPolicy
from app.agentic_platform.domain.hashing import canonical_hash, canonical_model_hash
from app.agentic_platform.domain.reward_facts import RewardFacts
from app.agentic_platform.domain.transition import ModelTurnPurpose, ModelUsage, TokenRoleSpan

from .state import DeepResearchState, ResearchActionType, ResearchDecision, ResearchSourceType, ResearchStateDelta


class ResearchToolObservation(DomainModel):
    """Sanitized description of a search/read result, never raw page content."""

    schema_version: str = "1.0"
    action_type: ResearchActionType
    query: str | None = Field(default=None, max_length=1_000)
    source_types: list[ResearchSourceType] = Field(default_factory=list)
    result_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    error_code: str | None = Field(default=None, max_length=128)

    @field_validator("query", "error_code")
    @classmethod
    def reject_blank_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("source_ids", "evidence_ids")
    @classmethod
    def validate_unique_nonblank_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("observation IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("observation IDs must be unique")
        return values


class ResearchModelTurn(DomainModel):
    """Provider provenance for a research planner/policy/finalizer call."""

    schema_version: str = "1.0"
    turn_purpose: ModelTurnPurpose
    model_id: str = Field(min_length=1, max_length=256)
    model_revision: str | None = Field(default=None, max_length=256)
    prompt_template_hash: str = Field(min_length=1, max_length=128)
    context_hash: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(default="legacy-unavailable-policy", min_length=1, max_length=128)
    skill_catalog_hash: str = Field(default="legacy-unavailable-catalog", min_length=1, max_length=128)
    retriever_version: str = Field(default="legacy-unavailable-retriever", min_length=1, max_length=128)
    environment_snapshot_id: str = Field(default="legacy-unavailable-environment", min_length=1, max_length=128)
    environment_snapshot_hash: str = Field(default="legacy-unavailable-environment", min_length=1, max_length=128)
    raw_model_output_ref: ArtifactRef | None = None
    token_ids: list[int] | None = None
    token_logprobs: list[float] | None = None
    token_role_spans: list[TokenRoleSpan] = Field(default_factory=list)
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_ms: dict[str, float] = Field(default_factory=dict)
    finish_reason: str | None = Field(default=None, max_length=128)
    provider_request_id: str | None = Field(default=None, max_length=256)
    training_eligible: bool = False
    quarantine_reason: str | None = Field(default=None, max_length=512)
    data_policy: TrainingDataPolicy = Field(default_factory=TrainingDataPolicy.internal_eval_only)

    @field_validator(
        "model_id",
        "model_revision",
        "prompt_template_hash",
        "context_hash",
        "policy_version",
        "skill_catalog_hash",
        "retriever_version",
        "environment_snapshot_id",
        "environment_snapshot_hash",
        "finish_reason",
        "provider_request_id",
        "quarantine_reason",
    )
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("token_ids")
    @classmethod
    def validate_token_ids(cls, values: list[int] | None) -> list[int] | None:
        if values is not None and any(value < 0 for value in values):
            raise ValueError("token IDs must be non-negative")
        return values

    @field_validator("latency_ms")
    @classmethod
    def validate_latency(cls, values: dict[str, float]) -> dict[str, float]:
        if any(not key.strip() for key in values):
            raise ValueError("latency metric names must not be blank")
        if any(value < 0 for value in values.values()):
            raise ValueError("latency values must be non-negative")
        return values

    @model_validator(mode="after")
    def validate_token_trace(self) -> "ResearchModelTurn":
        if self.token_logprobs is not None:
            if self.token_ids is None or len(self.token_logprobs) != len(self.token_ids):
                raise ValueError("token logprobs must align with raw token IDs")
        if self.token_role_spans and self.token_ids is None:
            raise ValueError("token role spans require raw token IDs")
        if self.token_ids is not None and any(span.end > len(self.token_ids) for span in self.token_role_spans):
            raise ValueError("token role span exceeds raw token IDs")
        if self.training_eligible and self.token_ids is None:
            raise ValueError("training-eligible turns require raw token IDs")
        if self.training_eligible and not any(span.trainable for span in self.token_role_spans):
            raise ValueError("training-eligible turns require trainable token spans")
        if self.token_ids is None and self.quarantine_reason != "missing_student_tokenization":
            raise ValueError("turns without raw token IDs require missing_student_tokenization")
        return self


class ResearchRuntimeMetadata(DomainModel):
    """Run-level provenance copied onto each DeepResearch model child turn.

    It captures the production wiring only; it deliberately contains no
    prescribed search sequence or fixed decision policy.
    """

    schema_version: str = "1.0"
    policy_version: str = Field(default="legacy-unavailable-policy", min_length=1, max_length=128)
    skill_catalog_hash: str = Field(default="legacy-unavailable-catalog", min_length=1, max_length=128)
    retriever_version: str = Field(default="legacy-unavailable-retriever", min_length=1, max_length=128)
    environment_snapshot_id: str = Field(default="legacy-unavailable-environment", min_length=1, max_length=128)
    environment_snapshot_hash: str = Field(default="legacy-unavailable-environment", min_length=1, max_length=128)
    data_policy: TrainingDataPolicy = Field(default_factory=TrainingDataPolicy.internal_eval_only)

    @field_validator(
        "policy_version",
        "skill_catalog_hash",
        "retriever_version",
        "environment_snapshot_id",
        "environment_snapshot_hash",
    )
    @classmethod
    def reject_blank_provenance(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("research runtime provenance must not be blank")
        return value


class DeepResearchChildTransition(DomainModel):
    """One immutable state transition in an isolated DeepResearch graph."""

    schema_version: str = "1.0"
    child_transition_id: str = Field(min_length=1, max_length=128)
    parent_transition_id: str | None = Field(default=None, max_length=128)
    previous_child_transition_id: str | None = Field(default=None, max_length=128)
    sequence_in_subagent: int = Field(ge=0)
    subagent_name: str = Field(default="deep_research", min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    graph_thread_id: str = Field(min_length=1, max_length=256)
    node_name: str = Field(min_length=1, max_length=128)

    policy_version: str = Field(default="legacy-unavailable-policy", min_length=1, max_length=128)
    skill_catalog_hash: str = Field(default="legacy-unavailable-catalog", min_length=1, max_length=128)
    retriever_version: str = Field(default="legacy-unavailable-retriever", min_length=1, max_length=128)
    environment_snapshot_id: str = Field(default="legacy-unavailable-environment", min_length=1, max_length=128)
    environment_snapshot_hash: str = Field(default="legacy-unavailable-environment", min_length=1, max_length=128)
    state_before_hash: str = Field(min_length=1, max_length=128)
    state_after_hash: str = Field(min_length=1, max_length=128)
    parsed_decision: ResearchDecision | None = None
    state_delta: ResearchStateDelta = Field(default_factory=ResearchStateDelta)
    context_view_ref: ArtifactRef | None = None
    observation_ref: ArtifactRef | None = None
    observation: ResearchToolObservation | None = None
    model_turn: ResearchModelTurn | None = None
    reward_facts: RewardFacts = Field(default_factory=RewardFacts)
    data_policy: TrainingDataPolicy = Field(default_factory=TrainingDataPolicy.internal_eval_only)
    error_code: str | None = Field(default=None, max_length=128)
    summary: str = Field(min_length=1, max_length=2_000)

    @field_validator(
        "child_transition_id",
        "parent_transition_id",
        "previous_child_transition_id",
        "subagent_name",
        "task_id",
        "graph_thread_id",
        "node_name",
        "policy_version",
        "skill_catalog_hash",
        "retriever_version",
        "environment_snapshot_id",
        "environment_snapshot_hash",
        "state_before_hash",
        "state_after_hash",
        "error_code",
        "summary",
    )
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_child_linkage(self) -> "DeepResearchChildTransition":
        if self.subagent_name != "deep_research":
            raise ValueError("child transition subagent_name must be deep_research")
        if self.observation is not None and self.observation_ref is None:
            raise ValueError("research tool observation requires an artifact reference")
        return self

    def canonical_hash(self) -> str:
        return canonical_model_hash(self)


class ResearchChildTransitionSink(Protocol):
    async def emit(self, event: DeepResearchChildTransition) -> None:
        ...


class InMemoryResearchChildTransitionSink:
    def __init__(self) -> None:
        self.events: list[DeepResearchChildTransition] = []
        self._hashes_by_id: dict[str, str] = {}

    async def emit(self, event: DeepResearchChildTransition) -> None:
        event_hash = event.canonical_hash()
        existing = self._hashes_by_id.get(event.child_transition_id)
        if existing is not None:
            if existing != event_hash:
                raise ValueError(f"research child transition ID collision: {event.child_transition_id}")
            return
        self._hashes_by_id[event.child_transition_id] = event_hash
        self.events.append(event.model_copy(deep=True))


class NullResearchChildTransitionSink:
    async def emit(self, event: DeepResearchChildTransition) -> None:
        del event


class ResearchArtifactStore(Protocol):
    async def store_json(
        self,
        state: DeepResearchState,
        *,
        artifact_type: ArtifactKind | str,
        artifact_key: str,
        payload: object,
        summary: str,
        idempotency_key: str,
    ) -> ArtifactRef:
        ...


class InMemoryResearchArtifactStore:
    """Test adapter with idempotent refs; R5 supplies the durable backend."""

    def __init__(self) -> None:
        self.payloads: dict[str, object] = {}
        self._by_idempotency: dict[tuple[str, str], ArtifactRef] = {}
        self._versions: dict[tuple[str, str, str], int] = {}

    async def store_json(
        self,
        state: DeepResearchState,
        *,
        artifact_type: ArtifactKind | str,
        artifact_key: str,
        payload: object,
        summary: str,
        idempotency_key: str,
    ) -> ArtifactRef:
        identity = (state.task.task_id, idempotency_key)
        existing = self._by_idempotency.get(identity)
        if existing is not None:
            return existing.model_copy(deep=True)
        kind = str(artifact_type)
        version_key = (state.task.task_id, kind, artifact_key)
        version = self._versions.get(version_key, 0) + 1
        self._versions[version_key] = version
        content_hash = canonical_hash(payload)
        artifact_id = f"research_artifact_{content_hash[:24]}_{version}"
        reference = ArtifactRef(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            version=version,
            uri=f"artifact://agentic/deep-research/{artifact_id}/v{version}",
            content_hash=content_hash,
            media_type="application/json",
            summary=summary[:1_024],
        )
        self.payloads[artifact_id] = payload
        self._by_idempotency[identity] = reference.model_copy(deep=True)
        return reference
