from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from app.agentic_platform.deepresearch.state import ClaimSupportStatus, ResearchPacket
from app.agentic_platform.domain.hashing import canonical_hash
from app.learning_artifacts.schemas import EvidenceReference, LearningPlan, LearningPlanStep, MaterialReference

from .base import SubAgent, SubAgentResult, SubAgentTaskPacket


class LearningPlannerTaskPacket(SubAgentTaskPacket):
    subagent_name: Literal["learning_planner"] = "learning_planner"
    objective: str = "Create an evidence-grounded learning plan from a research packet."
    max_turns: int = Field(default=8, ge=1, le=100)
    max_skill_calls: int = Field(default=0, ge=0, le=1_000)
    research_packet: ResearchPacket
    plan_title: str | None = Field(default=None, max_length=512)

    @field_validator("plan_title")
    @classmethod
    def reject_blank_title(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class LearningPlannerResult(SubAgentResult):
    learning_plan: LearningPlan


class LearningPlannerAgent(SubAgent[LearningPlannerTaskPacket, LearningPlannerResult]):
    """Pure conversion from verified ResearchPacket to a candidate LearningPlan."""

    name = "learning_planner"

    async def run(self, task: LearningPlannerTaskPacket) -> LearningPlannerResult:
        evidence = _internal_evidence_references(task.research_packet)
        materials = _material_references(evidence)
        if not evidence or not materials:
            raise ValueError("an evidence-grounded learning plan requires internal PDF evidence")
        plan = LearningPlan(
            plan_id=f"learning_plan_{canonical_hash({'task': task.task_id, 'packet': task.research_packet.packet_id})[:24]}",
            title=(task.plan_title or f"Learning plan: {task.research_packet.query}")[:512],
            research_packet_id=task.research_packet.packet_id,
            material_references=materials,
            evidence_references=evidence,
            steps=_plan_steps(task.research_packet, evidence),
            unresolved_questions=list(task.research_packet.unresolved_questions),
        )
        return LearningPlannerResult(
            task_id=task.task_id,
            subagent_name=self.name,
            parent_transition_id=task.parent_transition_id,
            summary=f"Prepared {len(plan.steps)} evidence-grounded learning plan steps for parent review.",
            artifact_refs=[task.research_packet.trace_ref],
            turns_used=1,
            learning_plan=plan,
        )


def _internal_evidence_references(packet: ResearchPacket) -> list[EvidenceReference]:
    references: list[EvidenceReference] = []
    for record in packet.evidence:
        if record.material_id is None or record.page is None:
            continue
        try:
            references.append(
                EvidenceReference(
                    evidence_id=record.evidence_id,
                    material_id=record.material_id,
                    page=record.page,
                    title=record.title,
                    source_type=record.source_type,
                )
            )
        except ValueError:
            continue
    return list({reference.evidence_id: reference for reference in references}.values())


def _material_references(evidence: list[EvidenceReference]) -> list[MaterialReference]:
    grouped: dict[int, list[EvidenceReference]] = {}
    for reference in evidence:
        grouped.setdefault(reference.material_id, []).append(reference)
    return [
        MaterialReference(
            material_id=material_id,
            title=references[0].title,
            evidence_ids=[reference.evidence_id for reference in references],
        )
        for material_id, references in sorted(grouped.items())
    ]


def _plan_steps(packet: ResearchPacket, evidence: list[EvidenceReference]) -> list[LearningPlanStep]:
    evidence_by_id = {reference.evidence_id: reference for reference in evidence}
    steps: list[LearningPlanStep] = []
    for index, claim in enumerate(packet.claims, start=1):
        if claim.status not in {ClaimSupportStatus.SUPPORTED, ClaimSupportStatus.CONFLICTED}:
            continue
        claim_evidence = [evidence_by_id[item] for item in claim.evidence_ids if item in evidence_by_id]
        if not claim_evidence:
            continue
        steps.append(
            LearningPlanStep(
                step_id=f"learn_{index}_{claim.claim_id[-12:]}",
                title=f"Study claim {index}",
                objective=claim.statement,
                material_ids=sorted({item.material_id for item in claim_evidence}),
                evidence_ids=[item.evidence_id for item in claim_evidence],
                estimated_minutes=45 if claim.status == ClaimSupportStatus.CONFLICTED else 30,
            )
        )
    if steps:
        return steps
    return [
        LearningPlanStep(
            step_id="learn_evidence_review",
            title="Review verified material evidence",
            objective=packet.query,
            material_ids=sorted({item.material_id for item in evidence}),
            evidence_ids=[item.evidence_id for item in evidence],
            estimated_minutes=30,
        )
    ]
