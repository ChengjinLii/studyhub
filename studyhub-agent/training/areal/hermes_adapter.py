from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from studyhub_agent.rewards import RewardResult
from studyhub_agent.trajectory import TrajectoryEvent
from training.areal.grouped_rollout import RolloutRequest, RolloutResult


@dataclass(frozen=True, slots=True)
class HermesRolloutContext:
    task_id: str
    user_request: str
    allowed_tools: tuple[str, ...]
    environment_seed: int
    rollout_seed: int
    memory_snapshot_id: str
    group_id: str


@dataclass(frozen=True, slots=True)
class HermesRolloutOutput:
    trajectory: tuple[TrajectoryEvent, ...]
    reward: RewardResult


HermesRunner = Callable[[HermesRolloutContext], Awaitable[HermesRolloutOutput]]


class HermesArealAdapter:
    """Thin boundary: AReaL supplies a rollout request; Hermes remains the Agent loop."""

    def __init__(self, runner: HermesRunner) -> None:
        self._runner = runner

    async def run(self, request: RolloutRequest) -> RolloutResult:
        context = HermesRolloutContext(
            task_id=request.task.task_id,
            user_request=request.task.user_request,
            allowed_tools=tuple(request.task.allowed_tools),
            environment_seed=request.environment_seed,
            rollout_seed=request.rollout_seed,
            memory_snapshot_id=request.memory_snapshot_id,
            group_id=request.group_id,
        )
        output = await self._runner(context)
        return RolloutResult(request=request, trajectory=output.trajectory, reward=output.reward)
