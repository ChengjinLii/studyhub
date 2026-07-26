from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from app.agentic_platform.deepresearch.state import EvidenceRecord, ResearchSourceType
from app.agentic_platform.domain.hashing import canonical_hash
from app.learning_artifacts.schemas import EvidenceReference, PracticeQuestion, PracticeSet

from .base import SubAgent, SubAgentResult, SubAgentTaskPacket


class AssessmentTaskPacket(SubAgentTaskPacket):
    subagent_name: Literal["assessment"] = "assessment"
    objective: str = "Compose an administrator-reviewed practice set from supplied question-page evidence."
    max_turns: int = Field(default=6, ge=1, le=100)
    max_skill_calls: int = Field(default=0, ge=0, le=1_000)
    question_evidence: list[EvidenceRecord] = Field(min_length=1, max_length=100)
    practice_title: str = Field(default="Evidence-grounded practice set", min_length=1, max_length=512)

    @field_validator("practice_title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class AssessmentResult(SubAgentResult):
    practice_set: PracticeSet


class AssessmentAgent(SubAgent[AssessmentTaskPacket, AssessmentResult]):
    """Turns supplied PDF question evidence into a candidate practice set, without inventing pages."""

    name = "assessment"

    async def run(self, task: AssessmentTaskPacket) -> AssessmentResult:
        references: list[EvidenceReference] = []
        questions: list[PracticeQuestion] = []
        for index, record in enumerate(task.question_evidence, start=1):
            if record.source_type != ResearchSourceType.INTERNAL_PDF or record.material_id is None or record.page is None:
                raise ValueError("practice composition requires real internal PDF question-page evidence")
            reference = EvidenceReference(
                evidence_id=record.evidence_id,
                material_id=record.material_id,
                page=record.page,
                title=record.title,
                source_type=record.source_type,
            )
            references.append(reference)
            questions.append(
                PracticeQuestion(
                    question_id=f"practice_{canonical_hash({'task': task.task_id, 'evidence': record.evidence_id})[:24]}",
                    prompt_excerpt=record.excerpt[:2_000],
                    source_evidence_id=record.evidence_id,
                    material_id=record.material_id,
                    page=record.page,
                )
            )
        references = list({reference.evidence_id: reference for reference in references}.values())
        questions = list({question.source_evidence_id: question for question in questions}.values())
        practice_set = PracticeSet(
            practice_set_id=f"practice_set_{canonical_hash({'task': task.task_id, 'evidence': [item.evidence_id for item in references]})[:24]}",
            title=task.practice_title,
            questions=questions,
            evidence_references=references,
        )
        return AssessmentResult(
            task_id=task.task_id,
            subagent_name=self.name,
            parent_transition_id=task.parent_transition_id,
            summary=f"Prepared {len(practice_set.questions)} practice questions grounded in supplied PDF pages.",
            artifact_refs=list(task.input_artifacts),
            turns_used=1,
            practice_set=practice_set,
        )
