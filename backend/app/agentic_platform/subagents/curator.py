from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, field_validator

from app.agentic_platform.deepresearch.state import EvidenceRecord, ResearchSourceType
from app.agentic_platform.domain.artifact import ArtifactRef
from app.agentic_platform.domain.hashing import canonical_hash
from app.learning_artifacts.schemas import DailyBrief, DailyBriefItem, EvidenceReference, MaterialAnalysis

from .base import SubAgent, SubAgentResult, SubAgentTaskPacket


class ContentCuratorTaskPacket(SubAgentTaskPacket):
    subagent_name: Literal["content_curator"] = "content_curator"
    objective: str = "Prepare a material analysis from supplied page evidence."
    max_turns: int = Field(default=6, ge=1, le=100)
    max_skill_calls: int = Field(default=0, ge=0, le=1_000)
    material_id: int = Field(gt=0)
    material_title: str = Field(min_length=1, max_length=512)
    evidence: list[EvidenceRecord] = Field(min_length=1, max_length=100)

    @field_validator("material_title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class DailyBriefTaskPacket(SubAgentTaskPacket):
    subagent_name: Literal["content_curator"] = "content_curator"
    objective: str = "Create an administrator-only daily brief preview from accepted artifacts."
    max_turns: int = Field(default=4, ge=1, le=100)
    max_skill_calls: int = Field(default=0, ge=0, le=1_000)
    for_date: date
    title: str = Field(default="Daily Agentic Learning Preview", min_length=1, max_length=512)
    preview_summaries: list[str] = Field(min_length=1, max_length=32)
    source_artifacts: list[ArtifactRef] = Field(min_length=1, max_length=64)

    @field_validator("title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("preview_summaries")
    @classmethod
    def validate_summaries(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("preview summaries must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("preview summaries must be unique")
        return values


class ContentCuratorResult(SubAgentResult):
    material_analysis: MaterialAnalysis


class DailyBriefResult(SubAgentResult):
    daily_brief: DailyBrief


class ContentCuratorAgent(SubAgent[ContentCuratorTaskPacket, ContentCuratorResult]):
    """Produces reviewable material analyses and admin-only brief candidates without persistence."""

    name = "content_curator"

    async def run(self, task: ContentCuratorTaskPacket) -> ContentCuratorResult:
        references: list[EvidenceReference] = []
        for record in task.evidence:
            if (
                record.source_type != ResearchSourceType.INTERNAL_PDF
                or record.material_id != task.material_id
                or record.page is None
            ):
                raise ValueError("material analysis requires matching internal PDF evidence")
            references.append(
                EvidenceReference(
                    evidence_id=record.evidence_id,
                    material_id=task.material_id,
                    page=record.page,
                    title=record.title,
                    source_type=record.source_type,
                )
            )
        references = list({reference.evidence_id: reference for reference in references}.values())
        analysis = MaterialAnalysis(
            analysis_id=f"material_analysis_{canonical_hash({'task': task.task_id, 'material': task.material_id})[:24]}",
            material_id=task.material_id,
            title=task.material_title,
            summary=f"Prepared from {len(references)} administrator-authorized page-level evidence records.",
            evidence_references=references,
            suggested_uses=["Administrator review before any learner-facing delivery"],
        )
        return ContentCuratorResult(
            task_id=task.task_id,
            subagent_name=self.name,
            parent_transition_id=task.parent_transition_id,
            summary=f"Prepared material analysis for {task.material_title}.",
            artifact_refs=list(task.input_artifacts),
            turns_used=1,
            material_analysis=analysis,
        )

    async def create_daily_brief(self, task: DailyBriefTaskPacket) -> DailyBriefResult:
        source_ids = [item.artifact_id for item in task.source_artifacts]
        brief = DailyBrief(
            brief_id=f"daily_brief_{canonical_hash({'task': task.task_id, 'date': task.for_date.isoformat()})[:24]}",
            for_date=task.for_date,
            title=task.title,
            items=[
                DailyBriefItem(
                    item_id=f"brief_item_{index}",
                    summary=summary,
                    source_artifact_ids=source_ids,
                )
                for index, summary in enumerate(task.preview_summaries, start=1)
            ],
            source_artifacts=list(task.source_artifacts),
            admin_preview_only=True,
        )
        return DailyBriefResult(
            task_id=task.task_id,
            subagent_name=self.name,
            parent_transition_id=task.parent_transition_id,
            summary="Prepared an administrator-only DailyBrief preview.",
            artifact_refs=list(task.source_artifacts),
            turns_used=1,
            daily_brief=brief,
        )
