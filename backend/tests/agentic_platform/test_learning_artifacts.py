from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.agentic_platform.deepresearch.state import (
    CitationMetrics,
    Claim,
    ClaimSupportStatus,
    EvidenceRecord,
    ResearchPacket,
    ResearchSourceType,
)
from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.subagents.assessment import AssessmentAgent, AssessmentTaskPacket
from app.agentic_platform.subagents.curator import ContentCuratorAgent, ContentCuratorTaskPacket, DailyBriefTaskPacket
from app.agentic_platform.subagents.planner import LearningPlannerAgent, LearningPlannerTaskPacket
from app.learning_artifacts.services import ArtifactAcceptanceError, LearningArtifactService
from app.models import Base
from app.models.agentic_runtime import AgentArtifactRecord


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[AgentArtifactRecord.__table__])
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as database_session:
        yield database_session
        database_session.rollback()
    engine.dispose()


def _trace_ref() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="research-trace-1",
        artifact_type=ArtifactKind.OTHER,
        version=1,
        uri="artifact://agentic/research-traces/research-trace-1",
        content_hash="trace-hash",
        media_type="application/json",
        summary="Research trace",
    )


def _evidence(evidence_id: str = "evidence-question-1") -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_type=ResearchSourceType.INTERNAL_PDF,
        source_uri="studyhub://materials/5/pages/7",
        title="概率论真题",
        material_id=5,
        page=7,
        excerpt="第 1 题：根据给定分布计算期望值。",
        reliability=0.9,
        access_scope="admin:materials.read",
    )


def _research_packet() -> ResearchPacket:
    evidence = _evidence()
    claim = Claim(
        claim_id="claim-probability-1",
        statement="资料包含需要计算期望值的概率论题目。",
        status=ClaimSupportStatus.SUPPORTED,
        evidence_ids=[evidence.evidence_id],
        confidence=0.9,
    )
    return ResearchPacket(
        packet_id="research-packet-1",
        query="概率论期望值如何复习？",
        sub_questions=["应优先练习哪些题型？"],
        claims=[claim],
        evidence=[evidence],
        citation_metrics=CitationMetrics(cited_claim_count=1, supported_claim_count=1),
        source_coverage={"internal_pdf": 1},
        confidence=0.9,
        suggested_next_actions=["Practice the cited question page"],
        trace_ref=_trace_ref(),
    )


def _planner_result():
    task = LearningPlannerTaskPacket(
        task_id="planner-task-1",
        admin_actor_id=3,
        parent_transition_id="transition-parent-1",
        research_packet=_research_packet(),
    )
    return asyncio.run(LearningPlannerAgent().run(task))


def test_deep_research_packet_converts_to_an_evidence_grounded_learning_plan() -> None:
    result = _planner_result()

    assert result.parent_transition_id == "transition-parent-1"
    assert result.learning_plan.research_packet_id == "research-packet-1"
    assert result.learning_plan.material_references[0].material_id == 5
    assert result.learning_plan.evidence_references[0].evidence_id == "evidence-question-1"
    assert result.learning_plan.steps[0].evidence_ids == ["evidence-question-1"]
    assert result.artifact_refs == [_trace_ref()]


def test_pdf_question_evidence_converts_to_a_page_grounded_practice_set() -> None:
    task = AssessmentTaskPacket(
        task_id="assessment-task-1",
        admin_actor_id=3,
        question_evidence=[_evidence()],
    )
    result = asyncio.run(AssessmentAgent().run(task))

    question = result.practice_set.questions[0]
    assert question.source_evidence_id == "evidence-question-1"
    assert question.material_id == 5
    assert question.page == 7
    assert result.practice_set.evidence_references[0].source_type == ResearchSourceType.INTERNAL_PDF


def test_specialist_subagents_return_candidates_without_a_database_dependency() -> None:
    planner = LearningPlannerAgent()
    assessment = AssessmentAgent()
    curator = ContentCuratorAgent()

    assert not hasattr(planner, "repository")
    assert not hasattr(assessment, "repository")
    assert not hasattr(curator, "repository")
    assert _planner_result().learning_plan.artifact_type.value == "learning_plan"


def test_invalid_artifact_is_rejected_before_any_persistence(session: Session) -> None:
    service = LearningArtifactService()
    invalid = {"artifact_type": "learning_plan", "plan_id": "missing-required-evidence"}

    review = service.review(invalid)
    assert review.accepted is False
    with pytest.raises(ArtifactAcceptanceError):
        service.accept(invalid)
    assert session.scalar(select(func.count()).select_from(AgentArtifactRecord)) == 0


def test_parent_acceptance_persists_new_versions_when_a_plan_changes(session: Session) -> None:
    service = LearningArtifactService()
    first = _planner_result().learning_plan
    second = first.model_copy(update={"title": "Revised probability study plan"})

    first_record = service.persist(
        session,
        service.accept(first),
        thread_id="artifact-thread-1",
        admin_actor_id=3,
        artifact_key="probability-plan",
        idempotency_key="plan-v1",
    )
    second_record = service.persist(
        session,
        service.accept(second),
        thread_id="artifact-thread-1",
        admin_actor_id=3,
        artifact_key="probability-plan",
        idempotency_key="plan-v2",
    )

    assert first_record.created is True
    assert second_record.created is True
    assert [first_record.artifact_ref.version, second_record.artifact_ref.version] == [1, 2]
    assert second_record.artifact_ref.artifact_type == ArtifactKind.LEARNING_PLAN
    assert session.scalar(select(func.count()).select_from(AgentArtifactRecord)) == 2


def test_parent_rejects_an_idempotency_key_reused_for_changed_artifact_content(session: Session) -> None:
    service = LearningArtifactService()
    first = _planner_result().learning_plan
    changed = first.model_copy(update={"title": "Changed title under same idempotency key"})

    service.persist(
        session,
        service.accept(first),
        thread_id="artifact-thread-idempotency",
        admin_actor_id=3,
        artifact_key="probability-plan",
        idempotency_key="stable-request",
    )
    with pytest.raises(ArtifactAcceptanceError):
        service.persist(
            session,
            service.accept(changed),
            thread_id="artifact-thread-idempotency",
            admin_actor_id=3,
            artifact_key="probability-plan",
            idempotency_key="stable-request",
        )


def test_daily_brief_is_always_an_admin_preview_candidate() -> None:
    curator = ContentCuratorAgent()
    result = asyncio.run(
        curator.create_daily_brief(
            DailyBriefTaskPacket(
                task_id="daily-brief-task-1",
                admin_actor_id=3,
                for_date=date(2026, 7, 26),
                preview_summaries=["Review the new evidence-grounded learning plan."],
                source_artifacts=[_trace_ref()],
            )
        )
    )

    assert result.daily_brief.admin_preview_only is True
    assert result.daily_brief.items[0].source_artifact_ids == ["research-trace-1"]


def test_content_curator_returns_an_evidence_grounded_material_analysis() -> None:
    result = asyncio.run(
        ContentCuratorAgent().run(
            ContentCuratorTaskPacket(
                task_id="curator-task-1",
                admin_actor_id=3,
                material_id=5,
                material_title="概率论真题",
                evidence=[_evidence()],
            )
        )
    )

    assert result.material_analysis.material_id == 5
    assert result.material_analysis.evidence_references[0].page == 7
