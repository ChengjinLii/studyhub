from __future__ import annotations

from collections import Counter

from app.agentic_platform.domain.artifact import ArtifactRef
from app.agentic_platform.domain.hashing import canonical_hash

from .citation import CitationVerifier
from .state import Citation, ClaimSupportStatus, DeepResearchState, ReportSection, ResearchPacket, ResearchReport, ResearchSection


def build_research_report(state: DeepResearchState, *, title: str | None = None) -> ResearchReport:
    """Create a structured draft; citation validation remains a separate action."""

    report_id = f"report_{canonical_hash({'task': state.task.task_id, 'claims': [claim.claim_id for claim in state.claims]})[:24]}"
    section_specs = state.plan.outline if state.plan is not None and state.plan.outline else []
    if not section_specs:
        section_specs = [ResearchSection(section_id="findings", title="Findings", objective=state.research_question)]
    sections: list[ReportSection] = []
    for spec in section_specs:
        claims = list(state.claims)
        citations = [
            Citation(claim_id=claim.claim_id, evidence_id=evidence_id)
            for claim in claims
            if claim.status == ClaimSupportStatus.SUPPORTED
            for evidence_id in claim.evidence_ids[:3]
        ]
        content = "\n".join(claim.statement for claim in claims) or "No verified claims are available yet."
        sections.append(
            ReportSection(
                section_id=spec.section_id,
                heading=spec.title,
                content=content[:8_000],
                claim_ids=[claim.claim_id for claim in claims],
                citations=citations,
            )
        )
    return ResearchReport(
        report_id=report_id,
        title=(title or f"Research: {state.research_question}")[:512],
        research_question=state.research_question,
        sections=sections,
        unresolved_questions=list(state.unresolved_questions),
        suggested_next_actions=_suggested_actions(state),
    )


def build_research_packet(state: DeepResearchState, *, trace_ref: ArtifactRef) -> ResearchPacket:
    report = state.report or build_research_report(state)
    validation = state.citation_validation or CitationVerifier().validate(
        report,
        claims=list(state.claims),
        evidence=list(state.evidence_ledger),
    )
    support_scores = [claim.confidence for claim in state.claims if claim.status == ClaimSupportStatus.SUPPORTED]
    confidence = sum(support_scores) / len(support_scores) if support_scores else 0.0
    coverage = Counter(record.source_type.value for record in state.evidence_ledger)
    sub_questions = [item.question for item in state.plan.sub_questions] if state.plan else [state.research_question]
    return ResearchPacket(
        packet_id=f"packet_{canonical_hash({'task': state.task.task_id, 'trace': trace_ref.artifact_id})[:24]}",
        query=state.research_question,
        sub_questions=sub_questions,
        claims=list(state.claims),
        evidence=list(state.evidence_ledger),
        conflicts=list(state.conflicts),
        unresolved_questions=list(state.unresolved_questions),
        citation_metrics=validation.metrics,
        source_coverage=dict(sorted(coverage.items())),
        confidence=confidence,
        suggested_next_actions=list(report.suggested_next_actions),
        trace_ref=trace_ref,
    )


def _suggested_actions(state: DeepResearchState) -> list[str]:
    actions: list[str] = []
    if state.unresolved_questions:
        actions.append("Collect more evidence for unresolved questions")
    if state.conflicts:
        actions.append("Cross-validate conflicting claims with independent sources")
    if not state.evidence_ledger:
        actions.append("Search permitted research domains")
    return actions or ["Review the cited report with an administrator"]
