from __future__ import annotations

import os
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_GUARD_MODEL = "Qwen/Qwen3Guard-Gen-0.6B"
DEFAULT_ONEJEV_MODEL = "OmniJev/OneJev-4B"
DEFAULT_GUARD_REVISION = "fada3b2f655b89601929198343c94cd2f64d93cc"
DEFAULT_ONEJEV_REVISION = "c88e18653ceb7a8770716287f55fdefc79d6b588"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["auto", "qwen3guard", "onejev-http", "torch", "demo"] = "auto"
    image_backend: Literal["torch", "onejev-http"] = "torch"
    onejev_url: str = "http://127.0.0.1:8000"
    model: str = DEFAULT_ONEJEV_MODEL
    model_revision: str | None = None
    text_model: str = DEFAULT_GUARD_MODEL
    text_model_revision: str | None = DEFAULT_GUARD_REVISION
    served_model: str = "jev-latest"
    timeout_seconds: float = Field(default=120, gt=0, le=600)
    device: str = "auto"
    text_device: str = "cpu"
    max_input_tokens: int = Field(default=8192, ge=256, le=32768)
    policy_path: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    allow_auto_approve: bool = False
    allow_auto_reject: bool = False
    max_concurrent_reviews: int = Field(default=2, ge=1, le=16)

    @model_validator(mode="before")
    @classmethod
    def backend_model_default(cls, values):
        if isinstance(values, dict):
            values = dict(values)
            backend = values.get("backend", "auto")
            values.setdefault(
                "model", (DEFAULT_GUARD_MODEL if backend == "qwen3guard" else DEFAULT_ONEJEV_MODEL)
            )
            if "model_revision" not in values:
                if values["model"] == DEFAULT_GUARD_MODEL:
                    values["model_revision"] = DEFAULT_GUARD_REVISION
                elif values["model"] == DEFAULT_ONEJEV_MODEL:
                    values["model_revision"] = DEFAULT_ONEJEV_REVISION
            if (
                "text_model_revision" not in values
                and values.get("text_model", DEFAULT_GUARD_MODEL) != DEFAULT_GUARD_MODEL
            ):
                values["text_model_revision"] = None
        return values

    @field_validator("onejev_url")
    @classmethod
    def valid_backend_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError("OneJev URL must be an HTTP(S) base URL without credentials or query")
        return value.rstrip("/")

    @classmethod
    def from_env(cls) -> Settings:
        mapping = {
            "backend": "REVIEW_JEV_BACKEND",
            "image_backend": "REVIEW_JEV_IMAGE_BACKEND",
            "onejev_url": "REVIEW_JEV_ONEJEV_URL",
            "model": "REVIEW_JEV_MODEL",
            "model_revision": "REVIEW_JEV_MODEL_REVISION",
            "text_model": "REVIEW_JEV_TEXT_MODEL",
            "text_model_revision": "REVIEW_JEV_TEXT_MODEL_REVISION",
            "served_model": "REVIEW_JEV_SERVED_MODEL",
            "timeout_seconds": "REVIEW_JEV_TIMEOUT",
            "device": "REVIEW_JEV_DEVICE",
            "text_device": "REVIEW_JEV_TEXT_DEVICE",
            "max_input_tokens": "REVIEW_JEV_MAX_INPUT_TOKENS",
            "policy_path": "REVIEW_JEV_POLICY",
            "api_key": "REVIEW_JEV_API_KEY",
            "allow_auto_approve": "REVIEW_JEV_ALLOW_AUTO_APPROVE",
            "allow_auto_reject": "REVIEW_JEV_ALLOW_AUTO_REJECT",
            "max_concurrent_reviews": "REVIEW_JEV_CONCURRENCY",
        }
        return cls.model_validate(
            {key: os.environ[env] for key, env in mapping.items() if os.environ.get(env)}
        )
