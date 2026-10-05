from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_DATA_CHARS = 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 100
Decision = Literal["approve", "manual_review", "reject"]
GuardCategory = Literal[
    "Violent",
    "Non-violent Illegal Acts",
    "Sexual Content or Sexual Acts",
    "PII",
    "Suicide & Self-Harm",
    "Unethical Acts",
    "Politically Sensitive Topics",
    "Copyright Violation",
    "Jailbreak",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ImageInput(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    data: str = Field(min_length=1, max_length=MAX_IMAGE_DATA_CHARS)


class Content(StrictModel):
    title: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=3000)
    text: str = Field(default="", max_length=20_000)
    customPreviewText: str = Field(default="", max_length=800)
    images: list[ImageInput] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def meaningful_content(self) -> Content:
        if not any((self.title, self.description, self.text, self.customPreviewText, self.images)):
            raise ValueError("provide non-empty text or at least one image")
        if len({image.id for image in self.images}) != len(self.images):
            raise ValueError("image ids must be unique")
        return self


class SubmissionContext(StrictModel):
    kind: Literal["material", "experience", "comment", "request", "marketplace"] = "material"
    publication_intent: Literal["FREE", "PAID", "CONTACT"] = "FREE"
    school: str = Field(default="", max_length=120)
    course: str = Field(default="", max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def bounded_tags(self) -> SubmissionContext:
        if any(len(tag) > 80 for tag in self.tags):
            raise ValueError("each tag must be at most 80 characters")
        return self


class RightsDeclaration(StrictModel):
    basis: Literal["original", "authorized", "open_license", "public_domain", "unknown"] = "unknown"
    copyrightOwner: str = Field(default="", max_length=120)
    source_url: str = Field(default="", max_length=2048)
    license: str = Field(default="", max_length=100)
    attested: bool = False
    authorization_note: str = Field(default="", max_length=2000)
    attribution: str = Field(default="", max_length=1000)
    modified: bool = False


class Reference(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    text: str = Field(default="", max_length=20_000)
    image_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def nonempty_reference(self) -> Reference:
        if not self.text and self.image_sha256 is None:
            raise ValueError("a reference needs text or an image SHA-256")
        return self


class ReviewRequest(StrictModel):
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    content: Content
    context: SubmissionContext = Field(default_factory=SubmissionContext)
    rights: RightsDeclaration = Field(default_factory=RightsDeclaration)
    references: list[Reference] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def unique_references(self) -> ReviewRequest:
        if len({ref.id for ref in self.references}) != len(self.references):
            raise ValueError("reference ids must be unique")
        return self


class Finding(StrictModel):
    rule_id: str
    category: str
    source: Literal["model", "declaration", "reference"]
    scope: Literal["submission", "text"] = "submission"
    outcome: Literal["clear", "review", "reject", "unavailable"]
    risk_probability: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    reason: str
    evidence: list[str] = Field(default_factory=list)


class ModelAssessment(StrictModel):
    safety: Literal["Safe", "Controversial", "Unsafe"]
    categories: list[GuardCategory] = Field(default_factory=list, max_length=9)
    scope: Literal["text"] = "text"
    policy: Literal["qwen3guard"] = "qwen3guard"
    custom_studyhub_policy_applied: Literal[False] = False
    images_evaluated: Literal[False] = False

    @model_validator(mode="after")
    def consistent_categories(self) -> ModelAssessment:
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("duplicate guard categories")
        if self.safety != "Safe" and not self.categories:
            raise ValueError("non-safe assessment must include a category")
        return self


class CopyrightAssessment(StrictModel):
    status: Literal["no_obvious_risk", "needs_review", "undetermined"]
    declaration_verified: Literal[False] = False
    reference_search_performed: bool = False
    external_search_performed: Literal[False] = False
    matched_reference_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ReviewResponse(StrictModel):
    request_id: str
    review_id: str
    status: Literal["completed", "partial", "degraded", "demo"]
    decision: Decision
    decision_reasons: list[str]
    policy_version: str
    policy_sha256: str
    model: str
    model_revision: str | None = None
    backend: str
    model_assessment: ModelAssessment | None = None
    calibrated_for_studyhub: Literal[False] = False
    content_sha256: str
    image_sha256: dict[str, str]
    findings: list[Finding]
    copyright: CopyrightAssessment
    warnings: list[str]
    usage: dict[str, int]
    elapsed_ms: float
