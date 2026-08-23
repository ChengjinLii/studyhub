from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from studyhub_agent.rewards import RewardResult


@dataclass(frozen=True, slots=True)
class EpisodeMetrics:
    reward: RewardResult
    steps: int
    tool_calls: int
    valid_tool_calls: int
    search_calls: int
    duplicate_searches: int
    premature_final: bool


@dataclass(frozen=True, slots=True)
class AgentBenchMetrics:
    cases: int
    task_success: float
    groundedness: float
    citation_accuracy: float
    valid_tool_rate: float
    average_steps: float
    average_tool_calls: float
    duplicate_search_rate: float
    premature_final_rate: float
    violation_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unit_interval(score: float) -> float:
    return (score + 1.0) / 2.0


def aggregate_metrics(episodes: list[EpisodeMetrics]) -> AgentBenchMetrics:
    if not episodes:
        raise ValueError("at least one evaluated episode is required")
    count = len(episodes)
    total_tools = sum(item.tool_calls for item in episodes)
    total_searches = sum(item.search_calls for item in episodes)
    return AgentBenchMetrics(
        cases=count,
        task_success=round(sum(_unit_interval(item.reward.task_success) for item in episodes) / count, 6),
        groundedness=round(sum(_unit_interval(item.reward.groundedness) for item in episodes) / count, 6),
        citation_accuracy=round(sum(_unit_interval(item.reward.citation) for item in episodes) / count, 6),
        valid_tool_rate=round(sum(item.valid_tool_calls for item in episodes) / total_tools, 6) if total_tools else 1.0,
        average_steps=round(sum(item.steps for item in episodes) / count, 6),
        average_tool_calls=round(total_tools / count, 6),
        duplicate_search_rate=(
            round(sum(item.duplicate_searches for item in episodes) / total_searches, 6) if total_searches else 0.0
        ),
        premature_final_rate=round(sum(item.premature_final for item in episodes) / count, 6),
        violation_rate=round(sum(bool(item.reward.violations) for item in episodes) / count, 6),
    )
