from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_GUARD_MODEL = "Qwen/Qwen3Guard-Gen-0.6B"
DEFAULT_IMAGE_MODEL = "google/shieldgemma-2-4b-it"
DEFAULT_GUARD_REVISION = "fada3b2f655b89601929198343c94cd2f64d93cc"
DEFAULT_IMAGE_REVISION = "eaf60452b5fc41a911338a022e628b0c15283897"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["auto", "qwen3guard", "shieldgemma2", "demo"] = "auto"
    model: str = DEFAULT_IMAGE_MODEL
    model_revision: str | None = None
    text_model: str = DEFAULT_GUARD_MODEL
    text_model_revision: str | None = DEFAULT_GUARD_REVISION
    device: str = "auto"
    text_device: str = "cpu"
    text_confidence_threshold: float = Field(default=0.85, gt=0.5, le=1, allow_inf_nan=False)
    image_confidence_threshold: float = Field(default=0.85, gt=0.5, le=1, allow_inf_nan=False)
    text_temperature: float = Field(default=1, gt=0, le=10, allow_inf_nan=False)
    image_temperature: float = Field(default=1, gt=0, le=10, allow_inf_nan=False)
    calibration_path: str | None = None
    ocr_backend: Literal["tesseract", "disabled"] = "tesseract"
    ocr_languages: str = Field(default="chi_sim+eng", pattern=r"^[A-Za-z0-9_+.-]{1,100}$")
    ocr_timeout_seconds: float = Field(default=15, gt=0, le=120, allow_inf_nan=False)
    ocr_min_confidence: float = Field(default=0.6, ge=0, le=1, allow_inf_nan=False)
    max_ocr_characters: int = Field(default=20_000, ge=1, le=40_000)
    timeout_seconds: float = Field(default=120, gt=0, le=600, allow_inf_nan=False)
    max_input_tokens: int = Field(default=8192, ge=256, le=32768)
    policy_path: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    allow_auto_approve: bool = False
    allow_auto_reject: bool = False
    max_concurrent_reviews: int = Field(default=2, ge=1, le=16)

    @model_validator(mode="before")
    @classmethod
    def model_defaults(cls, values):
        if isinstance(values, dict):
            values = dict(values)
            if values.get("backend") == "qwen3guard":
                values.setdefault("model", DEFAULT_GUARD_MODEL)
            if "model_revision" not in values and values.get("model") == DEFAULT_GUARD_MODEL:
                values["model_revision"] = DEFAULT_GUARD_REVISION
            elif "model_revision" not in values and values.get("model", DEFAULT_IMAGE_MODEL) == (
                DEFAULT_IMAGE_MODEL
            ):
                values["model_revision"] = DEFAULT_IMAGE_REVISION
            if values.get("text_model", DEFAULT_GUARD_MODEL) != DEFAULT_GUARD_MODEL:
                values.setdefault("text_model_revision", None)
        return values

    @classmethod
    def from_env(cls) -> Settings:
        mapping = {key: f"REVIEW_JEV_{key.upper()}" for key in cls.model_fields}
        mapping.update(
            timeout_seconds="REVIEW_JEV_TIMEOUT",
            policy_path="REVIEW_JEV_POLICY",
            max_concurrent_reviews="REVIEW_JEV_CONCURRENCY",
        )
        return cls.model_validate(
            {key: os.environ[env] for key, env in mapping.items() if os.environ.get(env)}
        )
