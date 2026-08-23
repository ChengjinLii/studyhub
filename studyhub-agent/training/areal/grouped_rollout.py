from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from studyhub_agent.rewards import RewardResult
from studyhub_agent.runtime import TaskSpec
from studyhub_agent.trajectory import TrajectoryEvent


@dataclass(frozen=True, slots=True)
class RolloutRequest:
    task: TaskSpec
    group_id: str
    environment_seed: int
    rollout_seed: int
    memory_snapshot_id: str


@dataclass(frozen=True, slots=True)
class RolloutResult:
    request: RolloutRequest
    trajectory: tuple[TrajectoryEvent, ...]
    reward: RewardResult


@dataclass(frozen=True, slots=True)
class GroupedEpisode:
    group_id: str
    task_id: str
    environment_seed: int
    memory_snapshot_id: str
    rollouts: tuple[RolloutResult, ...]


RolloutFunction = Callable[[RolloutRequest], Awaitable[RolloutResult]]


class GroupedEpisodeCoordinator:
    async def run_group(
        self,
        task: TaskSpec,
        *,
        group_size: int,
        rollout_fn: RolloutFunction,
        memory_snapshot_id: str,
    ) -> GroupedEpisode:
        if group_size < 2:
            raise ValueError("group_size must be at least 2")
        if not memory_snapshot_id.strip():
            raise ValueError("memory_snapshot_id is required")
        digest = hashlib.sha256(f"{task.task_id}:{task.environment_seed}:{memory_snapshot_id}".encode()).hexdigest()[
            :16
        ]
        group_id = f"group:{digest}"
        results: list[RolloutResult] = []
        for index in range(group_size):
            request = RolloutRequest(
                task=task,
                group_id=group_id,
                environment_seed=task.environment_seed,
                rollout_seed=task.environment_seed + index + 1,
                memory_snapshot_id=memory_snapshot_id,
            )
            result = await rollout_fn(request)
            self._validate_result(request, result)
            results.append(result)
        return GroupedEpisode(
            group_id=group_id,
            task_id=task.task_id,
            environment_seed=task.environment_seed,
            memory_snapshot_id=memory_snapshot_id,
            rollouts=tuple(results),
        )

    @staticmethod
    def _validate_result(request: RolloutRequest, result: RolloutResult) -> None:
        if result.request != request:
            raise ValueError("rollout result request does not match the coordinated request")
        if any(event.group_id != request.group_id for event in result.trajectory):
            raise ValueError("trajectory event escaped its rollout group")
        if any(event.task_id != request.task.task_id for event in result.trajectory):
            raise ValueError("trajectory event task does not match the grouped task")
