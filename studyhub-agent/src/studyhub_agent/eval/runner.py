from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from studyhub_agent.eval.cases import AgentBenchCase
from studyhub_agent.eval.metrics import AgentBenchMetrics, EpisodeMetrics, aggregate_metrics
from studyhub_agent.rewards import RewardSignals, evaluate_reward
from studyhub_agent.trajectory import TrajectoryEvent


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    final_answer: str
    events: tuple[TrajectoryEvent, ...]
    reward_signals: RewardSignals
    valid_tool_calls: int
    search_calls: int
    duplicate_searches: int
    premature_final: bool = False


class EvaluationPolicy(Protocol):
    async def run(self, case: AgentBenchCase) -> PolicyOutcome: ...


class AgentBenchRunner:
    def __init__(self, policy: EvaluationPolicy) -> None:
        self._policy = policy

    async def run(self, cases: list[AgentBenchCase]) -> AgentBenchMetrics:
        evaluated: list[EpisodeMetrics] = []
        for case in cases:
            outcome = await self._policy.run(case)
            reward = evaluate_reward(outcome.reward_signals)
            tool_calls = sum(event.event_type == "tool_call" for event in outcome.events)
            evaluated.append(
                EpisodeMetrics(
                    reward=reward,
                    steps=len(outcome.events),
                    tool_calls=tool_calls,
                    valid_tool_calls=outcome.valid_tool_calls,
                    search_calls=outcome.search_calls,
                    duplicate_searches=outcome.duplicate_searches,
                    premature_final=outcome.premature_final,
                )
            )
        return aggregate_metrics(evaluated)
