from __future__ import annotations

from dataclasses import dataclass, field

from studyhub_agent.rewards.grounding import score_citations, score_grounding
from studyhub_agent.rewards.schema import RewardResult
from studyhub_agent.rewards.task_success import score_task_success


@dataclass(frozen=True, slots=True)
class RewardSignals:
    final_answer: str
    verifier: dict[str, object] = field(default_factory=dict)
    available_source_ids: frozenset[str] = frozenset()
    supported_claims: int = 0
    total_claims: int = 0
    valid_tool_calls: int = 0
    total_tool_calls: int = 0
    required_tool_calls: int = 0
    duplicate_tool_calls: int = 0
    steps: int = 1
    max_steps: int = 1
    premature_final: bool = False
    boundary_violations: tuple[str, ...] = ()


def _tool_quality(signals: RewardSignals) -> float:
    if signals.total_tool_calls < 0 or signals.valid_tool_calls < 0:
        raise ValueError("tool-call counts must be non-negative")
    if signals.valid_tool_calls > signals.total_tool_calls:
        raise ValueError("valid_tool_calls cannot exceed total_tool_calls")
    if signals.total_tool_calls == 0:
        return 1.0 if signals.required_tool_calls == 0 else -1.0
    return (2.0 * signals.valid_tool_calls / signals.total_tool_calls) - 1.0


def _efficiency(signals: RewardSignals) -> float:
    if signals.steps < 1 or signals.max_steps < 1 or signals.steps > signals.max_steps:
        raise ValueError("invalid step counts")
    duplicate_penalty = min(1.0, signals.duplicate_tool_calls / max(1, signals.total_tool_calls))
    budget_fraction = (signals.steps - 1) / max(1, signals.max_steps - 1)
    return max(-1.0, min(1.0, 1.0 - budget_fraction - duplicate_penalty))


def evaluate_reward(signals: RewardSignals) -> RewardResult:
    task_success, task_violations = score_task_success(signals.final_answer, signals.verifier)
    citations_required = bool(signals.verifier.get("citations_required", False))
    citation, citation_violations = score_citations(
        signals.final_answer,
        set(signals.available_source_ids),
        citations_required=citations_required,
    )
    groundedness = score_grounding(supported_claims=signals.supported_claims, total_claims=signals.total_claims)
    tool_quality = _tool_quality(signals)
    efficiency = _efficiency(signals)
    violations = list(dict.fromkeys((*signals.boundary_violations, *task_violations, *citation_violations)))
    if signals.premature_final:
        violations.append("premature_final")
    weighted = 0.35 * task_success + 0.25 * groundedness + 0.15 * citation + 0.15 * tool_quality + 0.10 * efficiency
    penalty = min(1.0, 0.25 * len(violations))
    total = max(-1.0, min(1.0, weighted - penalty))
    return RewardResult(
        total=round(total, 6),
        task_success=round(task_success, 6),
        groundedness=round(groundedness, 6),
        citation=round(citation, 6),
        tool_quality=round(tool_quality, 6),
        efficiency=round(efficiency, 6),
        violations=violations,
    )
