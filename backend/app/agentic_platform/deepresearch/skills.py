from __future__ import annotations

from pydantic import Field, field_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.plan import RetryPolicy
from app.agentic_platform.skills.base import BaseSkill, IdempotencyMode, ObservationTrainingRole, SkillCost, SkillSpec
from app.agentic_platform.skills.context import SkillExecutionContext

from .domain_router import ResearchCapabilityFlags, ResearchDomainRouter, StudyHubResearchEnvironment
from .state import (
    DeepResearchState,
    ResearchActionType,
    ResearchContextAction,
    ResearchDecision,
    ResearchPlan,
    ResearchStateDelta,
)


RESEARCH_INTERNAL_SCOPES = ["agentic.admin", "research.internal"]
RESEARCH_WEB_SCOPES = ["agentic.admin", "research.web"]
RESEARCH_SCHOLAR_SCOPES = ["agentic.admin", "research.scholar"]
RESEARCH_ANALYSIS_SCOPES = ["agentic.admin", "research.analysis"]
RESEARCH_RETRY_POLICY = RetryPolicy(max_attempts=2, retryable_error_codes=["timeout", "transient"])


class ResearchStateInput(DomainModel):
    state: DeepResearchState


class ResearchPlanInput(ResearchStateInput):
    plan: ResearchPlan


class ResearchSearchInput(ResearchStateInput):
    query: str = Field(min_length=1, max_length=1_000)

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class ResearchReadInput(ResearchStateInput):
    source_ids: list[str] = Field(min_length=1, max_length=24)
    query: str | None = Field(default=None, max_length=1_000)

    @field_validator("source_ids")
    @classmethod
    def validate_source_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("source IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("source IDs must be unique")
        return values

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class ResearchClaimsInput(ResearchStateInput):
    claim_candidates: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("claim_candidates")
    @classmethod
    def validate_candidates(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("claim candidates must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("claim candidates must be unique")
        return values


class ResearchContextInput(ResearchStateInput):
    context_action: ResearchContextAction


class ResearchReportInput(ResearchStateInput):
    report_title: str | None = Field(default=None, max_length=512)

    @field_validator("report_title")
    @classmethod
    def reject_blank_title(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class ResearchSkillOutput(DomainModel):
    delta: ResearchStateDelta = Field(default_factory=ResearchStateDelta)
    summary: str = Field(min_length=1, max_length=2_000)
    error_code: str | None = Field(default=None, max_length=128)
    recoverable: bool = False


def _router_for_context(context: SkillExecutionContext) -> ResearchDomainRouter:
    environment = context.research_environment
    if environment is None:
        environment = StudyHubResearchEnvironment(
            session=context.require_live_session(),
            material_repo=context.require_material_repo(),
            materials_service=context.require_materials_service(),
            pdf_evidence_service=context.require_pdf_evidence_service(),
            admin_actor_id=context.admin_actor_id,
            role_mask=context.role_mask,
        )
    return ResearchDomainRouter(
        environment,
        flags=context.research_capability_flags or ResearchCapabilityFlags(),
    )


class _ResearchRouterSkill(BaseSkill[ResearchStateInput, ResearchSkillOutput]):
    action_type: ResearchActionType

    async def execute(self, context: SkillExecutionContext, payload: ResearchStateInput) -> ResearchSkillOutput:
        decision = self._decision(payload)
        result = await _router_for_context(context).execute(payload.state, decision)
        return ResearchSkillOutput(
            delta=result.delta,
            summary=result.summary,
            error_code=result.error_code,
            recoverable=result.recoverable,
        )

    def _decision(self, payload: ResearchStateInput) -> ResearchDecision:
        return ResearchDecision(
            action_type=self.action_type,
            rationale_summary=f"Execute the registered {self.spec.name} capability.",
        )


class ResearchPlanSkill(BaseSkill[ResearchPlanInput, ResearchSkillOutput]):
    input_model = ResearchPlanInput
    output_model = ResearchSkillOutput
    spec = SkillSpec(
        name="research.plan",
        version="1.0",
        description="Apply a policy-created typed research plan to an isolated research state.",
        input_model="ResearchPlanInput",
        output_model="ResearchSkillOutput",
        side_effect="none",
        permission_scopes=RESEARCH_ANALYSIS_SCOPES,
        timeout_seconds=5.0,
        retry_policy=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.HIDDEN,
        environment_adapter="research_domain",
        reward_hooks=["constraint_delta"],
        cost_model=SkillCost(estimated_context_tokens=250),
    )

    async def execute(self, context: SkillExecutionContext, payload: ResearchPlanInput) -> ResearchSkillOutput:
        del context
        return ResearchSkillOutput(
            delta=ResearchStateDelta(plan=payload.plan),
            summary=f"Prepared research plan {payload.plan.plan_id} version {payload.plan.version}.",
        )


class SearchInternalResearchSkill(_ResearchRouterSkill):
    input_model = ResearchSearchInput
    output_model = ResearchSkillOutput
    action_type = ResearchActionType.SEARCH_INTERNAL
    spec = SkillSpec(
        name="research.search_internal",
        version="1.0",
        description="Search administrator-authorized StudyHub materials through the internal adapter.",
        input_model="ResearchSearchInput",
        output_model="ResearchSkillOutput",
        side_effect="read",
        permission_scopes=RESEARCH_INTERNAL_SCOPES,
        timeout_seconds=15.0,
        retry_policy=RESEARCH_RETRY_POLICY,
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="studyhub_internal_research",
        reward_hooks=["candidate_rank_delta"],
        cost_model=SkillCost(estimated_context_tokens=500),
    )

    def _decision(self, payload: ResearchSearchInput) -> ResearchDecision:
        return ResearchDecision(
            action_type=self.action_type,
            rationale_summary="Search administrator-authorized internal materials.",
            query=payload.query,
        )


class ReadInternalResearchSkill(_ResearchRouterSkill):
    input_model = ResearchReadInput
    output_model = ResearchSkillOutput
    action_type = ResearchActionType.READ_INTERNAL
    spec = SkillSpec(
        name="research.read_internal",
        version="1.0",
        description="Read page-level evidence from selected authorized internal materials.",
        input_model="ResearchReadInput",
        output_model="ResearchSkillOutput",
        side_effect="read",
        permission_scopes=RESEARCH_INTERNAL_SCOPES,
        timeout_seconds=30.0,
        retry_policy=RESEARCH_RETRY_POLICY,
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="studyhub_internal_research",
        reward_hooks=["evidence_added", "citation_supported"],
        cost_model=SkillCost(estimated_context_tokens=1_200),
    )

    def _decision(self, payload: ResearchReadInput) -> ResearchDecision:
        return ResearchDecision(
            action_type=self.action_type,
            rationale_summary="Read selected internal sources as page-level evidence.",
            source_ids=payload.source_ids,
            query=payload.query,
        )


class SearchWebResearchSkill(SearchInternalResearchSkill):
    action_type = ResearchActionType.SEARCH_WEB
    spec = SkillSpec(
        name="research.search_web",
        version="1.0",
        description="Search the configured Web research adapter when the capability flag permits it.",
        input_model="ResearchSearchInput",
        output_model="ResearchSkillOutput",
        side_effect="external",
        permission_scopes=RESEARCH_WEB_SCOPES,
        timeout_seconds=30.0,
        retry_policy=RESEARCH_RETRY_POLICY,
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="web_research_adapter",
        reward_hooks=["candidate_rank_delta"],
        cost_model=SkillCost(estimated_context_tokens=600),
    )


class ReadWebResearchSkill(ReadInternalResearchSkill):
    action_type = ResearchActionType.READ_WEB
    spec = SkillSpec(
        name="research.read_web",
        version="1.0",
        description="Read selected Web sources when the Web capability flag permits it.",
        input_model="ResearchReadInput",
        output_model="ResearchSkillOutput",
        side_effect="external",
        permission_scopes=RESEARCH_WEB_SCOPES,
        timeout_seconds=30.0,
        retry_policy=RESEARCH_RETRY_POLICY,
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="web_research_adapter",
        reward_hooks=["evidence_added", "citation_supported"],
        cost_model=SkillCost(estimated_context_tokens=1_200),
    )


class SearchScholarResearchSkill(SearchInternalResearchSkill):
    action_type = ResearchActionType.SEARCH_SCHOLAR
    spec = SkillSpec(
        name="research.search_scholar",
        version="1.0",
        description="Search the configured Scholar adapter when the capability flag permits it.",
        input_model="ResearchSearchInput",
        output_model="ResearchSkillOutput",
        side_effect="external",
        permission_scopes=RESEARCH_SCHOLAR_SCOPES,
        timeout_seconds=30.0,
        retry_policy=RESEARCH_RETRY_POLICY,
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="scholar_research_adapter",
        reward_hooks=["candidate_rank_delta"],
        cost_model=SkillCost(estimated_context_tokens=600),
    )


class ExtractClaimsResearchSkill(_ResearchRouterSkill):
    input_model = ResearchClaimsInput
    output_model = ResearchSkillOutput
    action_type = ResearchActionType.EXTRACT_CLAIMS
    spec = SkillSpec(
        name="research.extract_claims",
        version="1.0",
        description="Extract typed candidate claims from the append-only evidence ledger.",
        input_model="ResearchClaimsInput",
        output_model="ResearchSkillOutput",
        side_effect="none",
        permission_scopes=RESEARCH_ANALYSIS_SCOPES,
        timeout_seconds=8.0,
        retry_policy=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="research_domain",
        reward_hooks=["evidence_added"],
        cost_model=SkillCost(estimated_context_tokens=750),
    )

    def _decision(self, payload: ResearchClaimsInput) -> ResearchDecision:
        return ResearchDecision(
            action_type=self.action_type,
            rationale_summary="Extract candidate claims from available evidence.",
            claim_candidates=payload.claim_candidates,
        )


class UpdateEvidenceResearchSkill(_ResearchRouterSkill):
    input_model = ResearchStateInput
    output_model = ResearchSkillOutput
    action_type = ResearchActionType.UPDATE_EVIDENCE
    spec = SkillSpec(
        name="research.update_evidence",
        version="1.0",
        description="Reconcile claim and evidence links without deleting source records.",
        input_model="ResearchStateInput",
        output_model="ResearchSkillOutput",
        side_effect="none",
        permission_scopes=RESEARCH_ANALYSIS_SCOPES,
        timeout_seconds=8.0,
        retry_policy=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="research_domain",
        reward_hooks=["citation_supported", "citation_invalid"],
        cost_model=SkillCost(estimated_context_tokens=800),
    )


class CrossValidateResearchSkill(UpdateEvidenceResearchSkill):
    action_type = ResearchActionType.CROSS_VALIDATE
    spec = SkillSpec(
        name="research.cross_validate",
        version="1.0",
        description="Record conflicts and unresolved questions across independent evidence.",
        input_model="ResearchStateInput",
        output_model="ResearchSkillOutput",
        side_effect="none",
        permission_scopes=RESEARCH_ANALYSIS_SCOPES,
        timeout_seconds=8.0,
        retry_policy=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="research_domain",
        reward_hooks=["citation_supported", "citation_invalid"],
        cost_model=SkillCost(estimated_context_tokens=800),
    )


class ManageResearchContextSkill(_ResearchRouterSkill):
    input_model = ResearchContextInput
    output_model = ResearchSkillOutput
    action_type = ResearchActionType.MANAGE_CONTEXT
    spec = SkillSpec(
        name="research.manage_context",
        version="1.0",
        description="Move evidence in or out of the working context while preserving the ledger.",
        input_model="ResearchContextInput",
        output_model="ResearchSkillOutput",
        side_effect="none",
        permission_scopes=RESEARCH_ANALYSIS_SCOPES,
        timeout_seconds=8.0,
        retry_policy=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.HIDDEN,
        environment_adapter="research_context_manager",
        reward_hooks=["context_tokens"],
        cost_model=SkillCost(estimated_context_tokens=300),
    )

    def _decision(self, payload: ResearchContextInput) -> ResearchDecision:
        return ResearchDecision(
            action_type=self.action_type,
            rationale_summary="Apply the policy-selected research context action.",
            context_action=payload.context_action,
        )


class WriteResearchReportSkill(_ResearchRouterSkill):
    input_model = ResearchReportInput
    output_model = ResearchSkillOutput
    action_type = ResearchActionType.WRITE_REPORT
    spec = SkillSpec(
        name="research.write_report",
        version="1.0",
        description="Build a structured research report draft from claims and evidence.",
        input_model="ResearchReportInput",
        output_model="ResearchSkillOutput",
        side_effect="none",
        permission_scopes=RESEARCH_ANALYSIS_SCOPES,
        timeout_seconds=10.0,
        retry_policy=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="research_report_builder",
        reward_hooks=["citation_supported", "citation_invalid"],
        cost_model=SkillCost(estimated_context_tokens=1_000),
    )

    def _decision(self, payload: ResearchReportInput) -> ResearchDecision:
        return ResearchDecision(
            action_type=self.action_type,
            rationale_summary="Draft a structured report from the current research state.",
            report_title=payload.report_title,
        )


class ValidateResearchReportSkill(_ResearchRouterSkill):
    input_model = ResearchStateInput
    output_model = ResearchSkillOutput
    action_type = ResearchActionType.VALIDATE_REPORT
    spec = SkillSpec(
        name="research.validate_report",
        version="1.0",
        description="Verify every report claim has an evidence-grounded citation link.",
        input_model="ResearchStateInput",
        output_model="ResearchSkillOutput",
        side_effect="none",
        permission_scopes=RESEARCH_ANALYSIS_SCOPES,
        timeout_seconds=8.0,
        retry_policy=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.HIDDEN,
        environment_adapter="citation_verifier",
        reward_hooks=["citation_supported", "citation_invalid"],
        cost_model=SkillCost(estimated_context_tokens=600),
    )


def build_research_skills() -> tuple[BaseSkill, ...]:
    """Return the complete PR7 capability set without imposing an execution order."""

    return (
        ResearchPlanSkill(),
        SearchInternalResearchSkill(),
        ReadInternalResearchSkill(),
        SearchWebResearchSkill(),
        ReadWebResearchSkill(),
        SearchScholarResearchSkill(),
        ExtractClaimsResearchSkill(),
        UpdateEvidenceResearchSkill(),
        CrossValidateResearchSkill(),
        ManageResearchContextSkill(),
        WriteResearchReportSkill(),
        ValidateResearchReportSkill(),
    )
