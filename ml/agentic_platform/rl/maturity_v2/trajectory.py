"""Pure trajectory-return and group-relative credit assignment utilities."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    state_id: str
    step_index: int
    action_code: str
    reward: float
    success_transition: bool


@dataclass(frozen=True, slots=True)
class TrajectoryRollout:
    episode_id: str
    rollout_index: int
    steps: tuple[TrajectoryStep, ...]
    completed: bool


@dataclass(frozen=True, slots=True)
class CreditedDecision:
    episode_id: str
    rollout_index: int
    state_id: str
    step_index: int
    action_code: str
    immediate_reward: float
    return_to_go: float
    advantage: float


def credit_trajectories(
    trajectories: list[TrajectoryRollout],
    *,
    discount: float,
    terminal_bonus: float,
    failure_penalty: float,
    epsilon: float = 1e-6,
) -> list[CreditedDecision]:
    if not trajectories:
        raise ValueError("trajectory group must not be empty")
    if not 0 < discount <= 1:
        raise ValueError("trajectory discount must be in (0, 1]")
    returns: dict[tuple[int, int], float] = {}
    shaped_rewards: dict[tuple[int, int], float] = {}
    for trajectory in trajectories:
        if not trajectory.steps:
            raise ValueError("trajectory must contain at least one decision")
        rewards = [float(step.reward) for step in trajectory.steps]
        rewards[-1] += terminal_bonus if trajectory.completed else -failure_penalty
        running = 0.0
        for step, shaped in reversed(list(zip(trajectory.steps, rewards, strict=True))):
            running = shaped + discount * running
            key = (trajectory.rollout_index, step.step_index)
            returns[key] = running
            shaped_rewards[key] = shaped

    by_step: dict[int, list[tuple[int, float]]] = {}
    for trajectory in trajectories:
        for step in trajectory.steps:
            by_step.setdefault(step.step_index, []).append(
                (trajectory.rollout_index, returns[(trajectory.rollout_index, step.step_index)])
            )
    advantages: dict[tuple[int, int], float] = {}
    for step_index, values in by_step.items():
        mean = sum(value for _, value in values) / len(values)
        variance = sum((value - mean) ** 2 for _, value in values) / len(values)
        deviation = math.sqrt(variance)
        for rollout_index, value in values:
            advantages[(rollout_index, step_index)] = (
                0.0 if deviation < epsilon else (value - mean) / (deviation + epsilon)
            )

    credited: list[CreditedDecision] = []
    for trajectory in trajectories:
        for step in trajectory.steps:
            key = (trajectory.rollout_index, step.step_index)
            credited.append(
                CreditedDecision(
                    episode_id=trajectory.episode_id,
                    rollout_index=trajectory.rollout_index,
                    state_id=step.state_id,
                    step_index=step.step_index,
                    action_code=step.action_code,
                    immediate_reward=shaped_rewards[key],
                    return_to_go=returns[key],
                    advantage=advantages[key],
                )
            )
    return credited
