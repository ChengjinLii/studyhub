from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import Field

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.hashing import canonical_hash
from app.repos.material_repo import MaterialRepository
from app.services.material_pdf_evidence_service import MaterialPdfEvidenceService
from app.services.materials_service import MaterialsService

from .claims import extract_claims_from_evidence, reconcile_claims, unresolved_claim_questions
from .context_manager import ResearchContextManager
from .evidence import evidence_from_internal_pdf, source_from_internal_material
from .report import build_research_report
from .state import (
    DeepResearchState,
    EvidenceRecord,
    ResearchActionType,
    ResearchBudgetConsumption,
    ResearchDecision,
    ResearchSourceRef,
    ResearchSourceType,
    ResearchStateDelta,
)


class ResearchCapabilityDisabledError(PermissionError):
    pass


class ResearchEnvironmentError(RuntimeError):
    def __init__(self, code: str, summary: str, *, recoverable: bool = True) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary
        self.recoverable = recoverable


class ResearchEnvironment(Protocol):
    async def search_internal(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        ...

    async def read_internal(self, source_ids: list[str], query: str, *, page_limit: int) -> list[EvidenceRecord]:
        ...

    async def search_web(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        ...

    async def read_web(self, source_ids: list[str], query: str) -> list[EvidenceRecord]:
        ...

    async def search_scholar(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        ...


class WebResearchAdapter(Protocol):
    """Narrow external capability contract injected into a research run."""

    async def search_web(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        ...

    async def read_web(self, source_ids: list[str], query: str) -> list[EvidenceRecord]:
        ...

    async def search_scholar(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        ...


@dataclass(frozen=True, slots=True)
class ResearchCapabilityFlags:
    web_enabled: bool = False
    scholar_enabled: bool = False


class ResearchExecutionResult(DomainModel):
    delta: ResearchStateDelta = Field(default_factory=ResearchStateDelta)
    summary: str = Field(min_length=1, max_length=2_000)
    error_code: str | None = Field(default=None, max_length=128)
    recoverable: bool = False


class ResearchDomainRouter:
    """Executes an arbitrary policy-selected research action through typed adapters."""

    def __init__(
        self,
        environment: ResearchEnvironment,
        *,
        flags: ResearchCapabilityFlags | None = None,
        context_manager: ResearchContextManager | None = None,
    ) -> None:
        self.environment = environment
        self.flags = flags or ResearchCapabilityFlags()
        self.context_manager = context_manager or ResearchContextManager()

    async def execute(self, state: DeepResearchState, decision: ResearchDecision) -> ResearchExecutionResult:
        try:
            return await self._execute(state, decision)
        except ResearchCapabilityDisabledError as exc:
            return self._error(state, decision, "capability_disabled", str(exc), recoverable=False)
        except ResearchEnvironmentError as exc:
            return self._error(state, decision, exc.code, exc.summary, recoverable=exc.recoverable)
        except Exception:  # noqa: BLE001 - raw source failures are not surfaced into model context.
            return self._error(state, decision, "research_environment_error", "Research source operation failed.", recoverable=True)

    async def _execute(self, state: DeepResearchState, decision: ResearchDecision) -> ResearchExecutionResult:
        action = decision.action_type
        if action == ResearchActionType.SEARCH_INTERNAL:
            return await self._search(state, decision, ResearchSourceType.INTERNAL_MATERIAL)
        if action == ResearchActionType.SEARCH_WEB:
            return await self._search(state, decision, ResearchSourceType.WEB)
        if action == ResearchActionType.SEARCH_SCHOLAR:
            return await self._search(state, decision, ResearchSourceType.SCHOLAR)
        if action == ResearchActionType.READ_INTERNAL:
            return await self._read(state, decision, ResearchSourceType.INTERNAL_PDF)
        if action == ResearchActionType.READ_WEB:
            return await self._read(state, decision, ResearchSourceType.WEB)
        if action == ResearchActionType.EXTRACT_CLAIMS:
            claims = extract_claims_from_evidence(state.evidence_ledger, claim_candidates=decision.claim_candidates)
            existing = {claim.claim_id for claim in state.claims}
            additions = [claim for claim in claims if claim.claim_id not in existing]
            return ResearchExecutionResult(
                delta=ResearchStateDelta(claims_to_add=additions),
                summary=f"Extracted {len(additions)} candidate claims from the evidence ledger.",
            )
        if action in {ResearchActionType.UPDATE_EVIDENCE, ResearchActionType.CROSS_VALIDATE}:
            reconciliation = reconcile_claims(state.claims, state.evidence_ledger)
            unresolved = unresolved_claim_questions(
                [*state.claims, *reconciliation.claim_updates.values()]
            )
            delta = reconciliation.model_copy(
                update={
                    "unresolved_questions_to_add": unresolved,
                    "unresolved_questions_to_remove": [
                        item for item in state.unresolved_questions if item not in unresolved and item != state.research_question
                    ],
                }
            )
            return ResearchExecutionResult(
                delta=delta,
                summary="Cross-validated claim support and recorded any evidence conflicts.",
            )
        if action == ResearchActionType.MANAGE_CONTEXT:
            assert decision.context_action is not None
            result = self.context_manager.apply(state, decision.context_action)
            return ResearchExecutionResult(delta=result.delta, summary=result.summary)
        if action == ResearchActionType.WRITE_REPORT:
            report = build_research_report(state, title=decision.report_title)
            return ResearchExecutionResult(
                delta=ResearchStateDelta(report=report),
                summary="Wrote a structured research report draft for citation validation.",
            )
        if action == ResearchActionType.VALIDATE_REPORT:
            if state.report is None:
                return self._error(
                    state,
                    decision,
                    "report_missing",
                    "Cannot validate citations until a report draft exists.",
                    recoverable=True,
                )
            from .citation import CitationVerifier

            validation = CitationVerifier().validate(
                state.report,
                claims=list(state.claims),
                evidence=list(state.evidence_ledger),
            )
            unresolved = [
                f"Support report claim: {claim_id}" for claim_id in validation.metrics.unsupported_claim_ids
            ]
            return ResearchExecutionResult(
                delta=ResearchStateDelta(citation_validation=validation, unresolved_questions_to_add=unresolved),
                summary=validation.summary,
            )
        if action == ResearchActionType.PLAN:
            return ResearchExecutionResult(summary="Policy requested a research-plan revision.")
        if action in {ResearchActionType.FINALIZE, ResearchActionType.ABORT}:
            return ResearchExecutionResult(summary=f"Policy selected {action.value}.")
        return ResearchExecutionResult(summary=f"No dedicated executor is registered for {action.value}.")

    async def _search(
        self,
        state: DeepResearchState,
        decision: ResearchDecision,
        source_type: ResearchSourceType,
    ) -> ResearchExecutionResult:
        assert decision.query is not None
        self._assert_source_allowed(state, source_type)
        if state.budget.remaining_search_turns <= 0:
            raise ResearchEnvironmentError("search_budget_exhausted", "Research search budget is exhausted.", recoverable=False)
        if source_type == ResearchSourceType.INTERNAL_MATERIAL:
            sources = await self.environment.search_internal(decision.query, limit=12)
        elif source_type == ResearchSourceType.WEB:
            if not self.flags.web_enabled:
                raise ResearchCapabilityDisabledError("Web research is disabled by configuration.")
            sources = await self.environment.search_web(decision.query, limit=12)
        else:
            if not self.flags.scholar_enabled:
                raise ResearchCapabilityDisabledError("Scholar research is disabled by configuration.")
            sources = await self.environment.search_scholar(decision.query, limit=12)
        previous_empty = next((item for item in reversed(state.search_history) if item.result_count == 0), None)
        attempt = {
            "attempt_id": f"search_{canonical_hash({'task': state.task.task_id, 'query': decision.query, 'count': len(state.search_history)})[:24]}",
            "source_type": source_type,
            "query": decision.query,
            "result_count": len(sources),
            "rewritten_from_query": previous_empty.query if previous_empty and previous_empty.query != decision.query else None,
            "summary": f"{source_type.value} search returned {len(sources)} sources.",
        }
        return ResearchExecutionResult(
            delta=ResearchStateDelta(
                sources_to_add=sources,
                search_attempt=attempt,
                budget_consumption=ResearchBudgetConsumption(search_turns=1),
            ),
            summary=attempt["summary"],
        )

    async def _read(
        self,
        state: DeepResearchState,
        decision: ResearchDecision,
        source_type: ResearchSourceType,
    ) -> ResearchExecutionResult:
        self._assert_source_allowed(state, source_type)
        if state.budget.remaining_page_reads <= 0:
            raise ResearchEnvironmentError("page_read_budget_exhausted", "Research page-read budget is exhausted.", recoverable=False)
        query = decision.query or state.research_question
        if source_type == ResearchSourceType.INTERNAL_PDF:
            evidence = await self.environment.read_internal(
                decision.source_ids,
                query,
                page_limit=state.budget.remaining_page_reads,
            )
        else:
            if not self.flags.web_enabled:
                raise ResearchCapabilityDisabledError("Web research is disabled by configuration.")
            evidence = await self.environment.read_web(
                decision.source_ids[: state.budget.remaining_page_reads],
                query,
            )
        if not evidence:
            raise ResearchEnvironmentError("source_unreadable", "Requested sources produced no readable evidence.", recoverable=True)
        activation = self.context_manager.activate_evidence(state, [record.evidence_id for record in evidence])
        delta = activation.model_copy(
            update={
                "evidence_to_add": evidence,
                "budget_consumption": ResearchBudgetConsumption(page_reads=min(len(evidence), state.budget.remaining_page_reads)),
            }
        )
        return ResearchExecutionResult(delta=delta, summary=f"Read {len(evidence)} page-level evidence records.")

    @staticmethod
    def _assert_source_allowed(state: DeepResearchState, source_type: ResearchSourceType) -> None:
        allowed = set(state.task.allowed_source_types)
        internal_types = {ResearchSourceType.INTERNAL_MATERIAL, ResearchSourceType.INTERNAL_PDF}
        if source_type in internal_types and ResearchSourceType.INTERNAL_MATERIAL in allowed:
            return
        if source_type not in allowed:
            raise ResearchCapabilityDisabledError(f"Source type is not allowed for this task: {source_type.value}")

    @staticmethod
    def _error(
        state: DeepResearchState,
        decision: ResearchDecision,
        code: str,
        summary: str,
        *,
        recoverable: bool,
    ) -> ResearchExecutionResult:
        path = f"{decision.action_type.value}:{code}"
        return ResearchExecutionResult(
            delta=ResearchStateDelta(
                rejected_paths_to_add=[path],
                unresolved_questions_to_add=[f"Recover from {decision.action_type.value}: {summary}"],
            ),
            summary=summary,
            error_code=code,
            recoverable=recoverable,
        )


class StudyHubResearchEnvironment:
    """Read-only adapter over the existing material search and PDF evidence services."""

    def __init__(
        self,
        *,
        session,
        material_repo: MaterialRepository,
        materials_service: MaterialsService,
        pdf_evidence_service: MaterialPdfEvidenceService,
        admin_actor_id: int,
        role_mask: int,
        web_adapter: WebResearchAdapter | None = None,
    ) -> None:
        self.session = session
        self.material_repo = material_repo
        self.materials_service = materials_service
        self.pdf_evidence_service = pdf_evidence_service
        self.admin_actor_id = admin_actor_id
        self.role_mask = role_mask
        self.web_adapter = web_adapter

    async def search_internal(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        response = self.materials_service.list_materials(
            self.session,
            self.admin_actor_id,
            keyword=query,
            school=None,
            college=None,
            major=None,
            tag=None,
            grade_value=None,
            course_category=None,
            price=None,
            sort="relevance",
            page=1,
            size=min(max(limit, 1), 12),
        )
        items = response.get("items") if isinstance(response, dict) else []
        return [source_from_internal_material(item) for item in items if isinstance(item, dict) and item.get("id")]

    async def read_internal(self, source_ids: list[str], query: str, *, page_limit: int) -> list[EvidenceRecord]:
        material_ids = [int(source_id.removeprefix("material:")) for source_id in source_ids if source_id.startswith("material:")]
        if not material_ids:
            raise ResearchEnvironmentError("invalid_internal_source", "No internal material IDs were supplied.", recoverable=False)
        materials = self.material_repo.list_materials_by_ids(self.session, material_ids)
        pages = self.pdf_evidence_service.collect_for_materials(
            materials,
            query,
            current_user_id=self.admin_actor_id,
            current_user_role_mask=self.role_mask,
            force=True,
            max_materials=len(material_ids),
            max_results=max(1, page_limit),
        )
        return [evidence_from_internal_pdf(item) for item in pages]

    async def search_web(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        if self.web_adapter is None:
            raise ResearchEnvironmentError("web_adapter_unavailable", "No Web research adapter is configured.", recoverable=False)
        return await self.web_adapter.search_web(query, limit=limit)

    async def read_web(self, source_ids: list[str], query: str) -> list[EvidenceRecord]:
        if self.web_adapter is None:
            raise ResearchEnvironmentError("web_adapter_unavailable", "No Web research adapter is configured.", recoverable=False)
        return await self.web_adapter.read_web(source_ids, query)

    async def search_scholar(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        if self.web_adapter is None:
            raise ResearchEnvironmentError("scholar_adapter_unavailable", "No Scholar research adapter is configured.", recoverable=False)
        return await self.web_adapter.search_scholar(query, limit=limit)
