from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from app.agentic_platform.domain import DomainModel


class MaterialSearchFilters(DomainModel):
    school: str | None = Field(default=None, max_length=120)
    college: str | None = Field(default=None, max_length=120)
    major: str | None = Field(default=None, max_length=255)
    tag: str | None = Field(default=None, max_length=80)

    @field_validator("school", "college", "major", "tag")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class MaterialSearchInput(DomainModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=6, ge=1, le=12)
    filters: MaterialSearchFilters = Field(default_factory=MaterialSearchFilters)

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class MaterialSummary(DomainModel):
    material_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)
    tags: list[str] = Field(default_factory=list)
    is_free: bool
    school: str | None = Field(default=None, max_length=120)
    college: str | None = Field(default=None, max_length=120)
    major: str | None = Field(default=None, max_length=255)
    course_category: str | None = Field(default=None, max_length=32)
    rating_avg: float = Field(default=0.0, ge=0.0)
    rating_count: int = Field(default=0, ge=0)
    download_count: int = Field(default=0, ge=0)
    quality_signals: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)

    @field_validator("title", "description", "school", "college", "major", "course_category")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("tags", "quality_signals", "risk_signals")
    @classmethod
    def validate_unique_values(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("values must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("values must be unique")
        return values


class MaterialSearchOutput(DomainModel):
    query: str = Field(min_length=1, max_length=500)
    materials: list[MaterialSummary] = Field(default_factory=list)
    retrieval_engine: str = Field(min_length=1, max_length=128)
    count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_count(self) -> "MaterialSearchOutput":
        if self.count != len(self.materials):
            raise ValueError("count must equal material list length")
        return self


class MaterialInspectInput(DomainModel):
    material_ids: list[int] = Field(min_length=1, max_length=12)

    @field_validator("material_ids")
    @classmethod
    def validate_material_ids(cls, material_ids: list[int]) -> list[int]:
        if any(material_id <= 0 for material_id in material_ids):
            raise ValueError("material IDs must be positive")
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("material IDs must be unique")
        return material_ids


class MaterialInspectOutput(DomainModel):
    materials: list[MaterialSummary] = Field(default_factory=list)
    missing_material_ids: list[int] = Field(default_factory=list)

    @field_validator("missing_material_ids")
    @classmethod
    def validate_missing_ids(cls, material_ids: list[int]) -> list[int]:
        if any(material_id <= 0 for material_id in material_ids):
            raise ValueError("material IDs must be positive")
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("material IDs must be unique")
        return material_ids


class ReadPdfEvidenceInput(MaterialInspectInput):
    query: str = Field(min_length=1, max_length=500)
    max_pages: int = Field(default=4, ge=1, le=8)
    page_numbers: list[int] = Field(default_factory=list, max_length=16)

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("page_numbers")
    @classmethod
    def validate_page_numbers(cls, pages: list[int]) -> list[int]:
        if any(page <= 0 for page in pages):
            raise ValueError("page numbers must be positive")
        if len(pages) != len(set(pages)):
            raise ValueError("page numbers must be unique")
        return pages


class MaterialPageEvidenceOutput(DomainModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    material_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=120)
    page: int = Field(gt=0)
    excerpt: str = Field(min_length=1, max_length=700)
    question_types: list[str] = Field(default_factory=list)
    question_numbers: list[str] = Field(default_factory=list)
    source_type: str = Field(default="unknown", min_length=1, max_length=64)
    solution_signals: list[str] = Field(default_factory=list)
    anchor_terms: list[str] = Field(default_factory=list)


class ReadPdfEvidenceOutput(DomainModel):
    available: bool
    evidence: list[MaterialPageEvidenceOutput] = Field(default_factory=list)
    reason: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_availability(self) -> "ReadPdfEvidenceOutput":
        if self.available != bool(self.evidence):
            raise ValueError("available must match evidence presence")
        return self


class FindQuestionPagesInput(ReadPdfEvidenceInput):
    pass


class FindQuestionPagesOutput(DomainModel):
    pages: list[MaterialPageEvidenceOutput] = Field(default_factory=list)


class FindAnswerPagesInput(ReadPdfEvidenceInput):
    pass


class FindAnswerPagesOutput(DomainModel):
    pages: list[MaterialPageEvidenceOutput] = Field(default_factory=list)


class CompareMaterialsInput(MaterialInspectInput):
    material_ids: list[int] = Field(min_length=2, max_length=8)


class MaterialComparison(DomainModel):
    material_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=120)
    is_free: bool
    tags: list[str] = Field(default_factory=list)
    rating_avg: float = Field(default=0.0, ge=0.0)
    download_count: int = Field(default=0, ge=0)
    quality_signals: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)


class CompareMaterialsOutput(DomainModel):
    comparisons: list[MaterialComparison] = Field(default_factory=list)
    missing_material_ids: list[int] = Field(default_factory=list)
