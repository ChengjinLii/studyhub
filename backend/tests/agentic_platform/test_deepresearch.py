from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field

import pytest

from app.agentic_platform.deepresearch.graph import DeepResearchGraph
from app.agentic_platform.deepresearch.policy import ReplayResearchPolicy
from app.agentic_platform.deepresearch.citation import CitationVerifier
from app.agentic_platform.deepresearch.domain_router import (
    ResearchCapabilityFlags,
    ResearchDomainRouter,
    ResearchEnvironmentError,
    StudyHubResearchEnvironment,
)
from app.agentic_platform.deepresearch.state import (
    Citation,
    Claim,
    ClaimSupportStatus,
    EvidenceRecord,
    ReportSection,
    ResearchActionType,
    ResearchContextAction,
    ResearchDecision,
    ResearchSourceRef,
    ResearchSourceType,
    ResearchReport,
    ResearchTaskPacket,
    initial_research_state,
)
from app.agentic_platform.skills.context import SkillExecutionContext, SkillExecutionMode
from app.agentic_platform.skills.executor import LiveSkillExecutor, SkillPermissionDeniedError
from app.agentic_platform.skills.registry import build_default_skill_registry
from app.agentic_platform.subagents.deepresearch import DeepResearchSearchAgent
from app.services.material_pdf_evidence_service import MaterialPageEvidence


@dataclass
class FixtureResearchEnvironment:
    sources_by_query: dict[str, list[ResearchSourceRef]] = field(default_factory=dict)
    read_outcomes: dict[tuple[str, ...], deque[object]] = field(default_factory=dict)
    internal_searches: list[str] = field(default_factory=list)
    internal_reads: list[tuple[str, ...]] = field(default_factory=list)
    web_searches: list[str] = field(default_factory=list)
    scholar_searches: list[str] = field(default_factory=list)

    async def search_internal(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        del limit
        self.internal_searches.append(query)
        return [item.model_copy(deep=True) for item in self.sources_by_query.get(query, [])]

    async def read_internal(self, source_ids: list[str], query: str, *, page_limit: int) -> list[EvidenceRecord]:
        del query, page_limit
        key = tuple(source_ids)
        self.internal_reads.append(key)
        outcomes = self.read_outcomes.get(key)
        if not outcomes:
            return []
        outcome = outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, list)
        return [item.model_copy(deep=True) for item in outcome]

    async def search_web(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        del limit
        self.web_searches.append(query)
        return []

    async def read_web(self, source_ids: list[str], query: str) -> list[EvidenceRecord]:
        del source_ids, query
        return []

    async def search_scholar(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        del limit
        self.scholar_searches.append(query)
        return []


@dataclass
class AdapterMaterialsService:
    items: list[dict[str, object]]
    calls: list[dict[str, object]] = field(default_factory=list)

    def list_materials(self, session: object, current_user_id: int, **kwargs: object) -> dict[str, object]:
        self.calls.append({"session": session, "current_user_id": current_user_id, **kwargs})
        return {"items": self.items}


@dataclass
class AdapterMaterialRepo:
    calls: list[tuple[object, list[int]]] = field(default_factory=list)

    def list_materials_by_ids(self, session: object, material_ids: list[int]) -> list[object]:
        self.calls.append((session, material_ids))
        return [object() for _ in material_ids]


@dataclass
class AdapterPdfEvidenceService:
    pages: list[MaterialPageEvidence]
    calls: list[dict[str, object]] = field(default_factory=list)

    def collect_for_materials(self, materials: list[object], query: str, **kwargs: object) -> list[MaterialPageEvidence]:
        self.calls.append({"materials": materials, "query": query, **kwargs})
        return self.pages[: int(kwargs["max_results"])]


def _task(
    task_id: str,
    *,
    allowed: list[ResearchSourceType] | None = None,
    max_turns: int = 16,
    max_context_tokens: int = 16_000,
) -> ResearchTaskPacket:
    return ResearchTaskPacket(
        task_id=task_id,
        admin_actor_id=3,
        research_question="课程资料对采样率的结论是什么？",
        allowed_source_types=allowed or [ResearchSourceType.INTERNAL_MATERIAL],
        max_turns=max_turns,
        max_search_turns=5,
        max_page_reads=8,
        max_context_tokens=max_context_tokens,
    )


def _decision(action: ResearchActionType, *, query: str | None = None, source_ids: list[str] | None = None, **kwargs) -> ResearchDecision:
    return ResearchDecision(
        action_type=action,
        rationale_summary=f"Replay {action.value} for the acceptance scenario.",
        query=query,
        source_ids=source_ids or [],
        **kwargs,
    )


def _source(material_id: int, title: str = "采样理论讲义") -> ResearchSourceRef:
    return ResearchSourceRef(
        source_id=f"material:{material_id}",
        source_type=ResearchSourceType.INTERNAL_MATERIAL,
        title=title,
        source_uri=f"studyhub://materials/{material_id}",
        material_id=material_id,
        reliability=0.8,
        access_scope="admin:materials.read",
    )


def _evidence(
    evidence_id: str,
    *,
    excerpt: str = "课程强调采样率必须满足奈奎斯特条件。",
    supports: list[str] | None = None,
    contradicts: list[str] | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_type=ResearchSourceType.INTERNAL_PDF,
        source_uri=f"studyhub://materials/1/pages/{evidence_id[-1] if evidence_id[-1].isdigit() else 1}",
        title="采样理论讲义",
        material_id=1,
        page=1,
        excerpt=excerpt,
        supports_claim_ids=supports or [],
        contradicts_claim_ids=contradicts or [],
        reliability=0.9,
        access_scope="admin:materials.read",
    )


def _run(task: ResearchTaskPacket, environment: FixtureResearchEnvironment, decisions: list[ResearchDecision], *, flags=None):
    return asyncio.run(
        DeepResearchGraph(
            policy=ReplayResearchPolicy(decisions=decisions),
            router=ResearchDomainRouter(environment, flags=flags),
        ).run(task)
    )


def test_internal_materials_support_a_policy_directed_multi_round_research_run() -> None:
    environment = FixtureResearchEnvironment(
        sources_by_query={"采样率 奈奎斯特": [_source(1)]},
        read_outcomes={
            ("material:1",): deque([[_evidence("evidence-1")]]),
        },
    )
    task = _task("research-multiround")
    result = _run(
        task,
        environment,
        [
            _decision(ResearchActionType.SEARCH_INTERNAL, query="采样率 奈奎斯特"),
            _decision(ResearchActionType.READ_INTERNAL, source_ids=["material:1"]),
            _decision(
                ResearchActionType.EXTRACT_CLAIMS,
                claim_candidates=["课程强调采样率必须满足奈奎斯特条件。"],
            ),
            _decision(ResearchActionType.UPDATE_EVIDENCE),
            _decision(ResearchActionType.WRITE_REPORT),
            _decision(ResearchActionType.VALIDATE_REPORT),
            _decision(ResearchActionType.FINALIZE),
        ],
    )

    assert environment.internal_searches == ["采样率 奈奎斯特"]
    assert environment.internal_reads == [("material:1",)]
    assert len(result.packet.evidence) == 1
    assert result.packet.claims[0].status == ClaimSupportStatus.SUPPORTED
    assert result.state.citation_validation is not None
    assert result.state.citation_validation.passed is True
    assert result.packet.trace_ref.artifact_id.startswith("research_trace_")


def test_studyhub_internal_adapter_reuses_existing_material_and_pdf_services_with_admin_acl() -> None:
    session = object()
    materials_service = AdapterMaterialsService(
        [
            {
                "id": 1,
                "title": "采样理论讲义",
                "ratingAvg": 4.8,
                "downloadCount": 10,
            }
        ]
    )
    material_repo = AdapterMaterialRepo()
    pdf_service = AdapterPdfEvidenceService(
        [
            MaterialPageEvidence(
                material_id=1,
                title="采样理论讲义",
                page=3,
                text="课程强调采样率必须满足奈奎斯特条件。",
                score=80,
                source_type="lecture_notes",
            )
        ]
    )
    environment = StudyHubResearchEnvironment(
        session=session,
        material_repo=material_repo,  # type: ignore[arg-type]
        materials_service=materials_service,  # type: ignore[arg-type]
        pdf_evidence_service=pdf_service,  # type: ignore[arg-type]
        admin_actor_id=3,
        role_mask=8,
    )

    sources = asyncio.run(environment.search_internal("采样率", limit=6))
    evidence = asyncio.run(environment.read_internal(["material:1"], "采样率", page_limit=4))

    assert sources[0].source_id == "material:1"
    assert evidence[0].source_uri == "studyhub://materials/1/pages/3"
    assert materials_service.calls[0]["current_user_id"] == 3
    assert material_repo.calls == [(session, [1])]
    assert pdf_service.calls[0]["current_user_id"] == 3
    assert pdf_service.calls[0]["current_user_role_mask"] == 8
    assert pdf_service.calls[0]["force"] is True


def test_policy_can_rewrite_an_empty_first_query_without_a_hardcoded_retry_path() -> None:
    environment = FixtureResearchEnvironment(sources_by_query={"采样率 奈奎斯特": [_source(1)]})
    result = _run(
        _task("research-query-rewrite"),
        environment,
        [
            _decision(ResearchActionType.SEARCH_INTERNAL, query="模糊查询"),
            _decision(ResearchActionType.SEARCH_INTERNAL, query="采样率 奈奎斯特"),
            _decision(ResearchActionType.FINALIZE),
        ],
    )

    assert environment.internal_searches == ["模糊查询", "采样率 奈奎斯特"]
    assert result.state.search_history[0].result_count == 0
    assert result.state.search_history[1].rewritten_from_query == "模糊查询"


def test_conflicting_internal_evidence_is_preserved_and_marked_for_cross_validation() -> None:
    candidate = "资料对采样率门槛给出不同结论。"
    from app.agentic_platform.deepresearch.claims import extract_claims_from_evidence

    claim_id = extract_claims_from_evidence([], claim_candidates=[candidate])[0].claim_id
    environment = FixtureResearchEnvironment(
        read_outcomes={
            ("material:1", "material:2"): deque(
                [
                    [
                        _evidence("evidence-support", excerpt=candidate, supports=[claim_id]),
                        _evidence("evidence-contradict", excerpt=candidate, contradicts=[claim_id]),
                    ]
                ]
            )
        }
    )
    result = _run(
        _task("research-conflict"),
        environment,
        [
            _decision(ResearchActionType.READ_INTERNAL, source_ids=["material:1", "material:2"]),
            _decision(ResearchActionType.EXTRACT_CLAIMS, claim_candidates=[candidate]),
            _decision(ResearchActionType.CROSS_VALIDATE),
            _decision(ResearchActionType.FINALIZE),
        ],
    )

    assert result.state.claims[0].status == ClaimSupportStatus.CONFLICTED
    assert len(result.state.conflicts) == 1
    assert len(result.packet.evidence) == 2
    assert any("Resolve conflicting evidence" in item for item in result.packet.unresolved_questions)


def test_unreadable_pdf_is_a_recoverable_observation_that_policy_can_retry() -> None:
    environment = FixtureResearchEnvironment(
        read_outcomes={
            ("material:1",): deque(
                [
                    ResearchEnvironmentError("pdf_unreadable", "The PDF could not be read.", recoverable=True),
                    [_evidence("evidence-recovered")],
                ]
            )
        }
    )
    result = _run(
        _task("research-pdf-recovery"),
        environment,
        [
            _decision(ResearchActionType.READ_INTERNAL, source_ids=["material:1"]),
            _decision(ResearchActionType.READ_INTERNAL, source_ids=["material:1"]),
            _decision(ResearchActionType.FINALIZE),
        ],
    )

    assert environment.internal_reads == [("material:1",), ("material:1",)]
    assert "read_internal:pdf_unreadable" in result.state.rejected_paths
    assert [item.evidence_id for item in result.packet.evidence] == ["evidence-recovered"]


def test_context_compression_never_deletes_evidence_from_the_ledger() -> None:
    environment = FixtureResearchEnvironment(
        read_outcomes={
            ("material:1",): deque([[_evidence("evidence-1"), _evidence("evidence-2")]]),
        }
    )
    result = _run(
        _task("research-context-compress", max_context_tokens=2_000),
        environment,
        [
            _decision(ResearchActionType.READ_INTERNAL, source_ids=["material:1"]),
            _decision(ResearchActionType.MANAGE_CONTEXT, context_action=ResearchContextAction.COMPRESS),
            _decision(ResearchActionType.FINALIZE),
        ],
    )

    assert len(result.state.evidence_ledger) == 2
    assert result.state.research_memory.active_evidence_ids == ["evidence-2"]
    assert result.state.research_memory.archived_evidence_ids == ["evidence-1"]
    assert result.state.research_memory.summaries


def test_unsupported_claim_is_rejected_by_citation_validation() -> None:
    result = _run(
        _task("research-unsupported-claim"),
        FixtureResearchEnvironment(),
        [
            _decision(ResearchActionType.EXTRACT_CLAIMS, claim_candidates=["没有证据支持的结论。"]),
            _decision(ResearchActionType.WRITE_REPORT),
            _decision(ResearchActionType.VALIDATE_REPORT),
            _decision(ResearchActionType.FINALIZE),
        ],
    )

    validation = result.state.citation_validation
    assert validation is not None
    assert validation.passed is False
    assert validation.metrics.unsupported_claim_ids == [result.state.claims[0].claim_id]


def test_invalid_citation_target_is_rejected_by_citation_validation() -> None:
    claim = Claim(
        claim_id="claim-supported",
        statement="A supported claim.",
        status=ClaimSupportStatus.SUPPORTED,
        evidence_ids=["evidence-supported"],
        confidence=0.9,
    )
    report = ResearchReport(
        report_id="report-invalid-citation",
        title="Invalid citation fixture",
        research_question="Does citation validation reject an unknown evidence ID?",
        sections=[
            ReportSection(
                section_id="findings",
                heading="Findings",
                content="A supported claim.",
                claim_ids=[claim.claim_id],
                citations=[Citation(claim_id=claim.claim_id, evidence_id="evidence-missing")],
            )
        ],
    )

    validation = CitationVerifier().validate(report, claims=[claim], evidence=[_evidence("evidence-supported")])

    assert validation.passed is False
    assert validation.metrics.invalid_citation_count == 1


def test_disabled_web_capability_never_calls_the_external_adapter() -> None:
    environment = FixtureResearchEnvironment()
    result = _run(
        _task("research-web-disabled", allowed=[ResearchSourceType.INTERNAL_MATERIAL, ResearchSourceType.WEB]),
        environment,
        [
            _decision(ResearchActionType.SEARCH_WEB, query="external material"),
            _decision(ResearchActionType.FINALIZE),
        ],
        flags=ResearchCapabilityFlags(web_enabled=False),
    )

    assert environment.web_searches == []
    assert "search_web:capability_disabled" in result.state.rejected_paths


def test_non_admin_cannot_invoke_research_skills_even_with_a_valid_typed_state() -> None:
    task = _task("research-skill-auth")
    state = initial_research_state(task)
    executor = LiveSkillExecutor(build_default_skill_registry())
    context = SkillExecutionContext(
        admin_actor_id=3,
        role_mask=1,
        permission_scopes=frozenset(),
        mode=SkillExecutionMode.LIVE,
    )

    with pytest.raises(SkillPermissionDeniedError):
        asyncio.run(
            executor.execute(
                skill_name="research.search_internal",
                arguments={"state": state.model_dump(mode="json"), "query": "采样率"},
                context=context,
            )
        )


def test_deep_research_subagent_accepts_only_its_task_packet_and_returns_structured_artifacts() -> None:
    task = _task("research-subagent")
    task = task.model_copy(update={"parent_transition_id": "parent-transition-1"})
    environment = FixtureResearchEnvironment()
    agent = DeepResearchSearchAgent(
        DeepResearchGraph(
            policy=ReplayResearchPolicy(decisions=[_decision(ResearchActionType.FINALIZE)]),
            router=ResearchDomainRouter(environment),
        )
    )

    result = asyncio.run(agent.run(task))

    assert result.parent_transition_id == "parent-transition-1"
    assert result.artifact_refs == [result.research_packet.trace_ref]
    assert result.turns_used <= task.max_turns
    with pytest.raises(ValueError):
        ResearchTaskPacket.model_validate({**task.model_dump(mode="json"), "parent_thread": {"private": "data"}})
