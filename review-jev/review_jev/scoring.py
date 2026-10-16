from __future__ import annotations

import math
from pathlib import Path

from pydantic import Field, model_validator

from .schemas import GuardScore, StrictModel


def softmax(scores: dict[str, float], temperature: float = 1) -> dict[str, float]:
    if (
        not scores
        or isinstance(temperature, bool)
        or not math.isfinite(temperature)
        or not 0 < temperature <= 10
        or any(not math.isfinite(value) for value in scores.values())
    ):
        raise ValueError("invalid candidate scores or temperature")
    maximum = max(scores.values())
    weights = {key: math.exp((value - maximum) / temperature) for key, value in scores.items()}
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


class CalibrationEntry(StrictModel):
    model: str
    model_revision: str = Field(min_length=1)
    policy_id: str
    calibration_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    temperature: float = Field(gt=0, le=10, allow_inf_nan=False)


class Calibration(StrictModel):
    version: int = 1
    entries: list[CalibrationEntry] = Field(max_length=32)

    @model_validator(mode="after")
    def unique_entries(self) -> Calibration:
        keys = [(e.model, e.model_revision, e.policy_id) for e in self.entries]
        if self.version != 1 or len(keys) != len(set(keys)):
            raise ValueError("unsupported or duplicate calibration entries")
        return self

    @classmethod
    def load(cls, path: str | None) -> Calibration:
        return cls.model_validate_json(Path(path).read_bytes()) if path else cls(entries=[])

    def apply(self, score: GuardScore) -> GuardScore:
        entry = next(
            (
                entry
                for entry in self.entries
                if (entry.model, entry.model_revision, entry.policy_id)
                == (score.model, score.model_revision, score.policy_id)
            ),
            None,
        )
        if entry is None:
            return score
        return GuardScore.model_validate(
            {
                **score.model_dump(),
                "calibrated_probabilities": softmax(score.log_scores, entry.temperature),
                "calibration_id": entry.calibration_id,
                "calibrated": True,
            }
        )
