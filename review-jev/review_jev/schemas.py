from __future__ import annotations

import math
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
    scope: Literal["submission", "text", "image"] = "submission"
    input_id: str | None = None
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


class GuardScore(StrictModel):
    model: str = Field(min_length=1, max_length=256)
    model_revision: str | None = Field(default=None, min_length=1, max_length=256)
    modality: Literal["text", "image"]
    input_id: str = Field(min_length=1, max_length=100)
    policy_id: Literal["text_safety", "sexual", "dangerous", "violence"]
    task_type: Literal["multiclass", "binary"]
    scoring_method: Literal["teacher_forced_sequence", "native_yes_no"]
    probabilities: dict[str, float]
    log_scores: dict[str, float]
    temperature: float = Field(default=1, gt=0, le=10, allow_inf_nan=False)
    calibrated_probabilities: dict[str, float] | None = None
    calibration_id: str | None = None
    calibrated: bool = False

    @model_validator(mode="before")
    @classmethod
    def numeric_scores(cls, values):
        if isinstance(values, dict):
            for key in ("probabilities", "log_scores", "calibrated_probabilities"):
                data = values.get(key)
                if isinstance(data, dict) and any(
                    isinstance(v, bool) or not isinstance(v, (int, float)) for v in data.values()
                ):
                    raise ValueError("guard scores must be numeric")
        return values

    @model_validator(mode="after")
    def valid_distribution(self) -> GuardScore:
        text = self.modality == "text"
        keys = {"Safe", "Controversial", "Unsafe"} if text else {"Yes", "No"}
        if (
            (self.task_type == "multiclass") != text
            or (self.policy_id == "text_safety") != text
            or (self.scoring_method == "teacher_forced_sequence") != text
        ):
            raise ValueError("inconsistent guard task")
        if set(self.log_scores) != keys or any(
            not math.isfinite(value) for value in self.log_scores.values()
        ):
            raise ValueError("invalid guard log scores")
        for distribution in (self.probabilities, self.calibrated_probabilities):
            if distribution is not None and (
                set(distribution) != keys
                or any(not math.isfinite(v) or not 0 <= v <= 1 for v in distribution.values())
                or not math.isclose(sum(distribution.values()), 1, abs_tol=1e-5)
            ):
                raise ValueError("invalid guard probability distribution")
        if self.calibrated != bool(self.calibration_id and self.calibrated_probabilities):
            raise ValueError("calibration requires probabilities and an artifact identity")
        if not self.calibrated and (
            self.calibration_id is not None or self.calibrated_probabilities is not None
        ):
            raise ValueError("incomplete calibration metadata")
        return self

    @property
    def decision_probabilities(self) -> dict[str, float]:
        return self.calibrated_probabilities or self.probabilities


class OCRAttempt(StrictModel):
    image_id: str
    status: Literal["completed", "empty", "unavailable", "disabled", "low_confidence"]
    characters: int = Field(default=0, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class Coverage(StrictModel):
    modality: Literal["text", "image", "ocr"]
    input_ids: list[str]
    status: Literal["completed", "unavailable", "not_requested"]
    reason: str | None = None


class CopyrightAssessment(StrictModel):
    status: Literal["no_obvious_risk", "needs_review", "undetermined"]
    declaration_verified: Literal[False] = False
    reference_search_performed: bool = False
    external_search_performed: Literal[False] = False
    matched_reference_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ModelAttempt(StrictModel):
    tier: Literal["text", "image", "single"]
    input_ids: list[str] = Field(default_factory=list)
    model: str
    model_revision: str | None = None
    backend: str
    outcome: Literal["accepted", "manual_review", "unavailable", "demo"]
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    confidence_threshold: float | None = Field(default=None, gt=0.5, le=1, allow_inf_nan=False)
    confidence_method: Literal["candidate_probability", "rule_probability"] | None = None
    review_reason: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    model_assessment: ModelAssessment | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    elapsed_ms: float = Field(ge=0)


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
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    model_attempts: list[ModelAttempt] = Field(default_factory=list, max_length=2)
    guard_scores: list[GuardScore] = Field(default_factory=list, max_length=13)
    coverage: list[Coverage] = Field(default_factory=list)
    ocr_attempts: list[OCRAttempt] = Field(default_factory=list, max_length=4)
    calibrated_for_studyhub: bool = False
    content_sha256: str
    image_sha256: dict[str, str]
    findings: list[Finding]
    copyright: CopyrightAssessment
    warnings: list[str]
    usage: dict[str, int]
    elapsed_ms: float
