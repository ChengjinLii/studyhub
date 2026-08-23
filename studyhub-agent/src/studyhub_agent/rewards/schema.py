from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

REWARD_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class RewardResult:
    total: float
    task_success: float
    groundedness: float
    citation: float
    tool_quality: float
    efficiency: float
    violations: list[str]

    def __post_init__(self) -> None:
        for name in ("total", "task_success", "groundedness", "citation", "tool_quality", "efficiency"):
            if not -1.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be in [-1, 1]")
        if len(self.violations) != len(set(self.violations)):
            raise ValueError("violations must be unique")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
