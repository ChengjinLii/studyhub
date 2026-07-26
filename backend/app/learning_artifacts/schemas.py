from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from app.agentic_platform.deepresearch.state import ResearchSourceType
from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.artifact import ArtifactRef


LEARNING_ARTIFACT_SCHEMA_VERSION = "1.0"


class LearningArtifactType(StrEnum):
    LEARNING_PLAN = "learning_plan"
    PRACTICE_SET = "practice_set"
    MATERIAL_ANALYSIS = "material_analysis"
    DAILY_BRIEF = "daily_brief"


class MaterialReference(DomainModel):
    material_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=512)
    evidence_ids: list[str] = Field(min_length=1, max_length=128)

    @field_validator("title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
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


class EvidenceReference(DomainModel):
    """A small citation pointer; raw PDF text stays in the source artifact/service."""

    evidence_id: str = Field(min_length=1, max_length=128)
    material_id: int = Field(gt=0)
    page: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=512)
    source_type: ResearchSourceType = ResearchSourceType.INTERNAL_PDF

    @field_validator("evidence_id", "title")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def require_internal_page_evidence(self) -> "EvidenceReference":
        if self.source_type != ResearchSourceType.INTERNAL_PDF:
            raise ValueError("learning artifacts may reference only internal PDF page evidence")
        return self


class LearningPlanStep(DomainModel):
    step_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    objective: str = Field(min_length=1, max_length=2_000)
    material_ids: list[int] = Field(min_length=1, max_length=32)
    evidence_ids: list[str] = Field(min_length=1, max_length=128)
    estimated_minutes: int = Field(default=30, ge=5, le=480)

    @field_validator("step_id", "title", "objective")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("material_ids")
    @classmethod
    def validate_material_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("material IDs must be positive")
        if len(values) != len(set(values)):
            raise ValueError("material IDs must be unique")
        return values

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("evidence IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("evidence IDs must be unique")
        return values


class LearningPlan(DomainModel):
    schema_version: str = LEARNING_ARTIFACT_SCHEMA_VERSION
    artifact_type: Literal[LearningArtifactType.LEARNING_PLAN] = LearningArtifactType.LEARNING_PLAN
    plan_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    research_packet_id: str = Field(min_length=1, max_length=128)
    material_references: list[MaterialReference] = Field(min_length=1, max_length=64)
    evidence_references: list[EvidenceReference] = Field(min_length=1, max_length=512)
    steps: list[LearningPlanStep] = Field(min_length=1, max_length=128)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=128)

    @field_validator("plan_id", "title", "research_packet_id")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("unresolved_questions")
    @classmethod
    def validate_questions(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("unresolved questions must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("unresolved questions must be unique")
        return values

    @model_validator(mode="after")
    def validate_material_and_evidence_links(self) -> "LearningPlan":
        material_ids = [item.material_id for item in self.material_references]
        evidence_ids = [item.evidence_id for item in self.evidence_references]
        step_ids = [item.step_id for item in self.steps]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("material references must be unique")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence references must be unique")
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("learning plan step IDs must be unique")
        known_materials = set(material_ids)
        known_evidence = set(evidence_ids)
        for reference in self.material_references:
            if not set(reference.evidence_ids) <= known_evidence:
                raise ValueError("material reference points to unknown evidence")
        for step in self.steps:
            if not set(step.material_ids) <= known_materials:
                raise ValueError("learning plan step points to unknown material")
            if not set(step.evidence_ids) <= known_evidence:
                raise ValueError("learning plan step points to unknown evidence")
        return self


class PracticeQuestion(DomainModel):
    question_id: str = Field(min_length=1, max_length=128)
    prompt_excerpt: str = Field(min_length=1, max_length=2_000)
    source_evidence_id: str = Field(min_length=1, max_length=128)
    material_id: int = Field(gt=0)
    page: int = Field(gt=0)

    @field_validator("question_id", "prompt_excerpt", "source_evidence_id")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class PracticeSet(DomainModel):
    schema_version: str = LEARNING_ARTIFACT_SCHEMA_VERSION
    artifact_type: Literal[LearningArtifactType.PRACTICE_SET] = LearningArtifactType.PRACTICE_SET
    practice_set_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    questions: list[PracticeQuestion] = Field(min_length=1, max_length=100)
    evidence_references: list[EvidenceReference] = Field(min_length=1, max_length=256)

    @field_validator("practice_set_id", "title")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def require_real_question_page_links(self) -> "PracticeSet":
        question_ids = [item.question_id for item in self.questions]
        evidence_ids = [item.evidence_id for item in self.evidence_references]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("practice question IDs must be unique")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("practice evidence IDs must be unique")
        by_evidence = {item.evidence_id: item for item in self.evidence_references}
        for question in self.questions:
            source = by_evidence.get(question.source_evidence_id)
            if source is None:
                raise ValueError("practice question must cite a real question-page evidence record")
            if source.material_id != question.material_id or source.page != question.page:
                raise ValueError("practice question page does not match its evidence reference")
        return self


class MaterialAnalysis(DomainModel):
    schema_version: str = LEARNING_ARTIFACT_SCHEMA_VERSION
    artifact_type: Literal[LearningArtifactType.MATERIAL_ANALYSIS] = LearningArtifactType.MATERIAL_ANALYSIS
    analysis_id: str = Field(min_length=1, max_length=128)
    material_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=512)
    summary: str = Field(min_length=1, max_length=4_000)
    evidence_references: list[EvidenceReference] = Field(min_length=1, max_length=256)
    suggested_uses: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("analysis_id", "title", "summary")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("suggested_uses")
    @classmethod
    def validate_uses(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("suggested uses must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("suggested uses must be unique")
        return values

    @model_validator(mode="after")
    def require_matching_material_evidence(self) -> "MaterialAnalysis":
        if any(reference.material_id != self.material_id for reference in self.evidence_references):
            raise ValueError("material analysis may only cite evidence from its material")
        return self


class DailyBriefItem(DomainModel):
    item_id: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=2_000)
    source_artifact_ids: list[str] = Field(min_length=1, max_length=64)

    @field_validator("item_id", "summary")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("source_artifact_ids")
    @classmethod
    def validate_source_artifact_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("source artifact IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("source artifact IDs must be unique")
        return values


class DailyBrief(DomainModel):
    schema_version: str = LEARNING_ARTIFACT_SCHEMA_VERSION
    artifact_type: Literal[LearningArtifactType.DAILY_BRIEF] = LearningArtifactType.DAILY_BRIEF
    brief_id: str = Field(min_length=1, max_length=128)
    for_date: date
    title: str = Field(min_length=1, max_length=512)
    items: list[DailyBriefItem] = Field(min_length=1, max_length=64)
    source_artifacts: list[ArtifactRef] = Field(min_length=1, max_length=64)
    admin_preview_only: Literal[True] = True

    @field_validator("brief_id", "title")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_item_sources(self) -> "DailyBrief":
        item_ids = [item.item_id for item in self.items]
        source_ids = {item.artifact_id for item in self.source_artifacts}
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("daily brief item IDs must be unique")
        for item in self.items:
            if not set(item.source_artifact_ids) <= source_ids:
                raise ValueError("daily brief item points to an unknown source artifact")
        return self


LearningArtifact: TypeAlias = LearningPlan | PracticeSet | MaterialAnalysis | DailyBrief


def artifact_identifier(artifact: LearningArtifact) -> str:
    return {
        LearningArtifactType.LEARNING_PLAN: artifact.plan_id if isinstance(artifact, LearningPlan) else None,
        LearningArtifactType.PRACTICE_SET: artifact.practice_set_id if isinstance(artifact, PracticeSet) else None,
        LearningArtifactType.MATERIAL_ANALYSIS: artifact.analysis_id if isinstance(artifact, MaterialAnalysis) else None,
        LearningArtifactType.DAILY_BRIEF: artifact.brief_id if isinstance(artifact, DailyBrief) else None,
    }[artifact.artifact_type] or ""


def validate_learning_artifact(value: LearningArtifact | dict[str, object]) -> LearningArtifact:
    """Validate untrusted candidate data before an artifact repository is touched."""

    if isinstance(value, (LearningPlan, PracticeSet, MaterialAnalysis, DailyBrief)):
        return value.model_copy(deep=True)
    artifact_type = value.get("artifact_type") if isinstance(value, dict) else None
    parsers = {
        LearningArtifactType.LEARNING_PLAN.value: LearningPlan,
        LearningArtifactType.PRACTICE_SET.value: PracticeSet,
        LearningArtifactType.MATERIAL_ANALYSIS.value: MaterialAnalysis,
        LearningArtifactType.DAILY_BRIEF.value: DailyBrief,
    }
    parser = parsers.get(str(artifact_type))
    if parser is None:
        raise ValueError("unsupported learning artifact type")
    return parser.model_validate(value)
