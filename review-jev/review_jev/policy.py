from __future__ import annotations

import hashlib
from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .schemas import StrictModel


class Rule(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    category: Literal["compliance", "privacy", "integrity", "copyright", "quality"]
    question: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=500)
    review_threshold: float = Field(gt=0, lt=1, allow_inf_nan=False)
    reject_threshold: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    positive_means: Literal["risk", "clear"] = "risk"

    @model_validator(mode="after")
    def safe_thresholds(self) -> Rule:
        if self.reject_threshold is not None and self.reject_threshold <= self.review_threshold:
            raise ValueError("reject_threshold must be greater than review_threshold")
        if self.category in {"copyright", "quality"} and self.reject_threshold is not None:
            raise ValueError("copyright and quality findings require human review, not rejection")
        return self


class Policy(StrictModel):
    version: str = Field(min_length=1, max_length=64)
    instructions: str = Field(min_length=1, max_length=4000)
    rules: list[Rule] = Field(min_length=1, max_length=32)
    sha256: str = ""

    @model_validator(mode="after")
    def unique_rules(self) -> Policy:
        if len({rule.id for rule in self.rules}) != len(self.rules):
            raise ValueError("policy rule ids must be unique")
        return self


def load_policy(path: str | Path | None = None) -> Policy:
    raw = (
        Path(path).read_bytes()
        if path
        else files("review_jev").joinpath("policies/studyhub-v1.json").read_bytes()
    )
    policy = Policy.model_validate_json(raw)
    policy.sha256 = hashlib.sha256(raw).hexdigest()
    return policy
