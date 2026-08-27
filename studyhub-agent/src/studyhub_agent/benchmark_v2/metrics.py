from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

EvaluationStatus = Literal["SCORED", "INFRA_EXCLUDED", "INVALID_TASK", "EVALUATOR_ERROR"]


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    task_id: str
    capability_id: str
    status: EvaluationStatus
    strict_success: bool
    task_outcome: float
    answer_correctness: float
    claim_support: float
    citation_correctness: float
    citation_completeness: float
    source_quality: float
    tool_validity: float
    recovery_success: bool | None
    privacy_policy: float
    efficiency: float
    tool_calls: int
    realized_successful_policy_steps: int
    semantic_judge_status: str
    hard_gate_reasons: tuple[str, ...]
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["hard_gate_reasons"] = list(self.hard_gate_reasons)
        value["diagnostic_scalar"] = self.diagnostic_scalar
        return value

    @property
    def diagnostic_scalar(self) -> float:
        if self.status != "SCORED" or self.hard_gate_reasons:
            return 0.0
        return round(
            0.30 * self.task_outcome
            + 0.20 * self.answer_correctness
            + 0.20 * self.claim_support
            + 0.10 * self.citation_correctness
            + 0.05 * self.citation_completeness
            + 0.05 * self.tool_validity
            + 0.05 * self.privacy_policy
            + 0.05 * self.efficiency,
            6,
        )
