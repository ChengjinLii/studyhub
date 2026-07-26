from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.artifact import ArtifactRef


RESEARCH_SCHEMA_VERSION = "1.0"


class ResearchSourceType(StrEnum):
    INTERNAL_MATERIAL = "internal_material"
    INTERNAL_PDF = "internal_pdf"
    WEB = "web"
    SCHOLAR = "scholar"


class ClaimSupportStatus(StrEnum):
    DRAFT = "draft"
    SUPPORTED = "supported"
    CONFLICTED = "conflicted"
    UNSUPPORTED = "unsupported"


class ResearchActionType(StrEnum):
    PLAN = "plan"
    SEARCH_INTERNAL = "search_internal"
    READ_INTERNAL = "read_internal"
    SEARCH_WEB = "search_web"
    READ_WEB = "read_web"
    SEARCH_SCHOLAR = "search_scholar"
    EXTRACT_CLAIMS = "extract_claims"
    UPDATE_EVIDENCE = "update_evidence"
    CROSS_VALIDATE = "cross_validate"
    MANAGE_CONTEXT = "manage_context"
    WRITE_REPORT = "write_report"
    VALIDATE_REPORT = "validate_report"
    FINALIZE = "finalize"
    ABORT = "abort"


class ResearchContextAction(StrEnum):
    COMPRESS = "compress"
    SNIPPET = "snippet"
    ROLLBACK = "rollback"
    DROP = "drop"
    RESTORE_ARTIFACT = "restore_artifact"


class ResearchSourceRef(DomainModel):
    source_id: str = Field(min_length=1, max_length=128)
    source_type: ResearchSourceType
    title: str = Field(min_length=1, max_length=512)
    source_uri: str = Field(min_length=1, max_length=2_048)
    material_id: int | None = Field(default=None, gt=0)
    reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    access_scope: str = Field(default="admin", min_length=1, max_length=128)

    @field_validator("source_id", "title", "source_uri", "access_scope")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class EvidenceRecord(DomainModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    source_type: ResearchSourceType
    source_uri: str = Field(min_length=1, max_length=2_048)
    title: str = Field(min_length=1, max_length=512)
    material_id: int | None = Field(default=None, gt=0)
    page: int | None = Field(default=None, gt=0)
    excerpt: str = Field(min_length=1, max_length=3_000)
    supports_claim_ids: list[str] = Field(default_factory=list)
    contradicts_claim_ids: list[str] = Field(default_factory=list)
    reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    access_scope: str = Field(default="admin", min_length=1, max_length=128)
    retrieved_at: datetime | None = None

    @field_validator("evidence_id", "source_uri", "title", "excerpt", "access_scope")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("supports_claim_ids", "contradicts_claim_ids")
    @classmethod
    def validate_claim_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("claim IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("claim IDs must be unique")
        return values

    @model_validator(mode="after")
    def reject_conflicting_links(self) -> "EvidenceRecord":
        overlap = set(self.supports_claim_ids) & set(self.contradicts_claim_ids)
        if overlap:
            raise ValueError(f"evidence cannot both support and contradict claims: {sorted(overlap)}")
        return self


class Claim(DomainModel):
    claim_id: str = Field(min_length=1, max_length=128)
    statement: str = Field(min_length=1, max_length=2_000)
    status: ClaimSupportStatus = ClaimSupportStatus.DRAFT
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("claim_id", "statement")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("evidence IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("evidence IDs must be unique")
        return values


class ResearchConflict(DomainModel):
    conflict_id: str = Field(min_length=1, max_length=128)
    claim_id: str = Field(min_length=1, max_length=128)
    supporting_evidence_ids: list[str] = Field(min_length=1)
    contradicting_evidence_ids: list[str] = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=2_000)

    @field_validator("conflict_id", "claim_id", "summary")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("supporting_evidence_ids", "contradicting_evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("evidence IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("evidence IDs must be unique")
        return values


class ResearchSection(DomainModel):
    section_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    objective: str = Field(min_length=1, max_length=1_000)

    @field_validator("section_id", "title", "objective")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class SubQuestion(DomainModel):
    question_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=2_000)
    is_resolved: bool = False

    @field_validator("question_id", "question")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class ResearchPlan(DomainModel):
    plan_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    outline: list[ResearchSection] = Field(default_factory=list)
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    rationale_summary: str = Field(min_length=1, max_length=2_000)

    @field_validator("plan_id", "rationale_summary")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "ResearchPlan":
        for label, values in (
            ("section", [section.section_id for section in self.outline]),
            ("sub-question", [item.question_id for item in self.sub_questions]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} IDs must be unique")
        return self


class SearchAttempt(DomainModel):
    attempt_id: str = Field(min_length=1, max_length=128)
    source_type: ResearchSourceType
    query: str = Field(min_length=1, max_length=1_000)
    result_count: int = Field(ge=0)
    rewritten_from_query: str | None = Field(default=None, max_length=1_000)
    summary: str = Field(min_length=1, max_length=1_000)

    @field_validator("attempt_id", "query", "rewritten_from_query", "summary")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class ResearchMemory(DomainModel):
    version: int = Field(default=1, ge=1)
    active_evidence_ids: list[str] = Field(default_factory=list)
    archived_evidence_ids: list[str] = Field(default_factory=list)
    summaries: list[str] = Field(default_factory=list)
    last_action: ResearchContextAction | None = None

    @field_validator("active_evidence_ids", "archived_evidence_ids", "summaries")
    @classmethod
    def validate_nonblank_unique(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("research memory values must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("research memory values must be unique")
        return values

    @model_validator(mode="after")
    def reject_active_archived_overlap(self) -> "ResearchMemory":
        overlap = set(self.active_evidence_ids) & set(self.archived_evidence_ids)
        if overlap:
            raise ValueError(f"active and archived evidence overlap: {sorted(overlap)}")
        return self


class ResearchBudget(DomainModel):
    remaining_turns: int = Field(ge=0)
    remaining_search_turns: int = Field(ge=0)
    remaining_page_reads: int = Field(ge=0)
    remaining_context_tokens: int = Field(ge=0)


class ResearchBudgetConsumption(DomainModel):
    turns: int = Field(default=0, ge=0)
    search_turns: int = Field(default=0, ge=0)
    page_reads: int = Field(default=0, ge=0)
    context_tokens: int = Field(default=0, ge=0)


class Citation(DomainModel):
    claim_id: str = Field(min_length=1, max_length=128)
    evidence_id: str = Field(min_length=1, max_length=128)

    @field_validator("claim_id", "evidence_id")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class ReportSection(DomainModel):
    section_id: str = Field(min_length=1, max_length=128)
    heading: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=8_000)
    claim_ids: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)

    @field_validator("section_id", "heading", "content")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class ResearchReport(DomainModel):
    report_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    research_question: str = Field(min_length=1, max_length=4_000)
    sections: list[ReportSection] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    suggested_next_actions: list[str] = Field(default_factory=list)

    @field_validator("report_id", "title", "research_question")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class CitationMetrics(DomainModel):
    cited_claim_count: int = Field(default=0, ge=0)
    supported_claim_count: int = Field(default=0, ge=0)
    unsupported_claim_ids: list[str] = Field(default_factory=list)
    invalid_citation_count: int = Field(default=0, ge=0)


class CitationValidationResult(DomainModel):
    passed: bool
    metrics: CitationMetrics = Field(default_factory=CitationMetrics)
    summary: str = Field(min_length=1, max_length=2_000)

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class ResearchTaskPacket(DomainModel):
    """A sub-agent receives only this bounded packet, never its parent Thread."""

    schema_version: str = RESEARCH_SCHEMA_VERSION
    task_id: str = Field(min_length=1, max_length=128)
    admin_actor_id: int = Field(gt=0)
    research_question: str = Field(min_length=1, max_length=4_000)
    allowed_source_types: list[ResearchSourceType] = Field(default_factory=lambda: [ResearchSourceType.INTERNAL_MATERIAL])
    max_turns: int = Field(default=12, ge=1, le=200)
    max_search_turns: int = Field(default=4, ge=0, le=100)
    max_page_reads: int = Field(default=10, ge=0, le=500)
    max_context_tokens: int = Field(default=16_000, ge=1, le=200_000)
    input_artifacts: list[ArtifactRef] = Field(default_factory=list)
    parent_transition_id: str | None = Field(default=None, max_length=128)

    @field_validator("task_id", "research_question", "parent_transition_id")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("allowed_source_types")
    @classmethod
    def require_source_types(cls, values: list[ResearchSourceType]) -> list[ResearchSourceType]:
        if not values:
            raise ValueError("at least one source type must be allowed")
        if len(values) != len(set(values)):
            raise ValueError("allowed source types must be unique")
        return values


class DeepResearchState(DomainModel):
    schema_version: str = RESEARCH_SCHEMA_VERSION
    task: ResearchTaskPacket
    research_question: str = Field(min_length=1, max_length=4_000)
    plan: ResearchPlan | None = None
    search_history: list[SearchAttempt] = Field(default_factory=list)
    visited_sources: list[ResearchSourceRef] = Field(default_factory=list)
    evidence_ledger: list[EvidenceRecord] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    conflicts: list[ResearchConflict] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    rejected_paths: list[str] = Field(default_factory=list)
    research_memory: ResearchMemory = Field(default_factory=ResearchMemory)
    budget: ResearchBudget
    report: ResearchReport | None = None
    citation_validation: CitationValidationResult | None = None
    terminal_reason: str | None = Field(default=None, max_length=2_000)

    @field_validator("research_question", "terminal_reason")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("unresolved_questions", "rejected_paths")
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("research text values must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("research text values must be unique")
        return values

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "DeepResearchState":
        for label, values in (
            ("source", [item.source_id for item in self.visited_sources]),
            ("evidence", [item.evidence_id for item in self.evidence_ledger]),
            ("claim", [item.claim_id for item in self.claims]),
            ("conflict", [item.conflict_id for item in self.conflicts]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} IDs must be unique")
        known_evidence = {item.evidence_id for item in self.evidence_ledger}
        if not set(self.research_memory.active_evidence_ids) <= known_evidence:
            raise ValueError("research memory references unknown active evidence")
        if not set(self.research_memory.archived_evidence_ids) <= known_evidence:
            raise ValueError("research memory references unknown archived evidence")
        return self


class ResearchDecision(DomainModel):
    schema_version: str = RESEARCH_SCHEMA_VERSION
    action_type: ResearchActionType
    rationale_summary: str = Field(min_length=1, max_length=2_000)
    query: str | None = Field(default=None, max_length=1_000)
    source_ids: list[str] = Field(default_factory=list)
    claim_candidates: list[str] = Field(default_factory=list)
    context_action: ResearchContextAction | None = None
    report_title: str | None = Field(default=None, max_length=512)

    @field_validator("rationale_summary", "query", "report_title")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("source_ids", "claim_candidates")
    @classmethod
    def validate_nonblank_unique_lists(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("values must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("values must be unique")
        return values

    @model_validator(mode="after")
    def validate_payload(self) -> "ResearchDecision":
        search_actions = {
            ResearchActionType.SEARCH_INTERNAL,
            ResearchActionType.SEARCH_WEB,
            ResearchActionType.SEARCH_SCHOLAR,
        }
        read_actions = {ResearchActionType.READ_INTERNAL, ResearchActionType.READ_WEB}
        if self.action_type in search_actions and self.query is None:
            raise ValueError(f"{self.action_type.value} requires query")
        if self.action_type in read_actions and not self.source_ids:
            raise ValueError(f"{self.action_type.value} requires source_ids")
        if self.action_type == ResearchActionType.MANAGE_CONTEXT and self.context_action is None:
            raise ValueError("manage_context requires context_action")
        if self.action_type != ResearchActionType.MANAGE_CONTEXT and self.context_action is not None:
            raise ValueError(f"{self.action_type.value} does not allow context_action")
        return self


class ResearchStateDelta(DomainModel):
    plan: ResearchPlan | None = None
    sources_to_add: list[ResearchSourceRef] = Field(default_factory=list)
    evidence_to_add: list[EvidenceRecord] = Field(default_factory=list)
    claims_to_add: list[Claim] = Field(default_factory=list)
    claim_updates: dict[str, Claim] = Field(default_factory=dict)
    evidence_updates: dict[str, EvidenceRecord] = Field(default_factory=dict)
    conflicts_to_add: list[ResearchConflict] = Field(default_factory=list)
    unresolved_questions_to_add: list[str] = Field(default_factory=list)
    unresolved_questions_to_remove: list[str] = Field(default_factory=list)
    rejected_paths_to_add: list[str] = Field(default_factory=list)
    search_attempt: SearchAttempt | None = None
    research_memory: ResearchMemory | None = None
    report: ResearchReport | None = None
    citation_validation: CitationValidationResult | None = None
    budget_consumption: ResearchBudgetConsumption = Field(default_factory=ResearchBudgetConsumption)
    terminal_reason: str | None = Field(default=None, max_length=2_000)

    @field_validator(
        "unresolved_questions_to_add",
        "unresolved_questions_to_remove",
        "rejected_paths_to_add",
    )
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("research text values must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("research text values must be unique")
        return values

    @field_validator("claim_updates", "evidence_updates")
    @classmethod
    def validate_update_keys(cls, values: dict[str, object]) -> dict[str, object]:
        if any(not key.strip() for key in values):
            raise ValueError("update IDs must not be blank")
        return values

    @model_validator(mode="after")
    def reject_unresolved_conflict(self) -> "ResearchStateDelta":
        overlap = set(self.unresolved_questions_to_add) & set(self.unresolved_questions_to_remove)
        if overlap:
            raise ValueError(f"unresolved question changes conflict: {sorted(overlap)}")
        return self


class ResearchPacket(DomainModel):
    schema_version: str = RESEARCH_SCHEMA_VERSION
    packet_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=4_000)
    sub_questions: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    conflicts: list[ResearchConflict] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    citation_metrics: CitationMetrics = Field(default_factory=CitationMetrics)
    source_coverage: dict[str, int] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    suggested_next_actions: list[str] = Field(default_factory=list)
    trace_ref: ArtifactRef

    @field_validator("packet_id", "query")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


def initial_research_state(task: ResearchTaskPacket) -> DeepResearchState:
    return DeepResearchState(
        task=task,
        research_question=task.research_question,
        budget=ResearchBudget(
            remaining_turns=task.max_turns,
            remaining_search_turns=task.max_search_turns,
            remaining_page_reads=task.max_page_reads,
            remaining_context_tokens=task.max_context_tokens,
        ),
        unresolved_questions=[task.research_question],
    )


def _append_unique(existing: list, additions: Iterable, *, key) -> list:
    result = list(existing)
    known = {key(item) for item in result}
    for item in additions:
        if key(item) not in known:
            result.append(item)
            known.add(key(item))
    return result


def apply_research_delta(state: DeepResearchState, delta: ResearchStateDelta) -> DeepResearchState:
    """Return a validated successor state without mutating a research run."""

    budget = state.budget
    consumed = delta.budget_consumption
    remaining = ResearchBudget(
        remaining_turns=budget.remaining_turns - consumed.turns,
        remaining_search_turns=budget.remaining_search_turns - consumed.search_turns,
        remaining_page_reads=budget.remaining_page_reads - consumed.page_reads,
        remaining_context_tokens=budget.remaining_context_tokens - consumed.context_tokens,
    )
    successor = state.model_copy(deep=True)
    successor.plan = delta.plan or successor.plan
    successor.visited_sources = _append_unique(successor.visited_sources, delta.sources_to_add, key=lambda item: item.source_id)
    successor.evidence_ledger = _append_unique(successor.evidence_ledger, delta.evidence_to_add, key=lambda item: item.evidence_id)
    successor.claims = _append_unique(successor.claims, delta.claims_to_add, key=lambda item: item.claim_id)
    if delta.evidence_updates:
        successor.evidence_ledger = [
            delta.evidence_updates.get(item.evidence_id, item) for item in successor.evidence_ledger
        ]
    if delta.claim_updates:
        successor.claims = [delta.claim_updates.get(item.claim_id, item) for item in successor.claims]
    successor.conflicts = _append_unique(successor.conflicts, delta.conflicts_to_add, key=lambda item: item.conflict_id)
    if delta.search_attempt is not None:
        successor.search_history = _append_unique(successor.search_history, [delta.search_attempt], key=lambda item: item.attempt_id)
    removed = set(delta.unresolved_questions_to_remove)
    successor.unresolved_questions = [item for item in successor.unresolved_questions if item not in removed]
    successor.unresolved_questions = _append_unique(
        successor.unresolved_questions,
        delta.unresolved_questions_to_add,
        key=lambda item: item,
    )
    successor.rejected_paths = _append_unique(successor.rejected_paths, delta.rejected_paths_to_add, key=lambda item: item)
    successor.research_memory = delta.research_memory or successor.research_memory
    successor.report = delta.report or successor.report
    successor.citation_validation = delta.citation_validation or successor.citation_validation
    successor.budget = remaining
    if delta.terminal_reason is not None:
        successor.terminal_reason = delta.terminal_reason
    return DeepResearchState.model_validate(successor.model_dump(mode="python"))
