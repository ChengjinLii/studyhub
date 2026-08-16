"""Deterministic multi-step environment for isolated Router RL episodes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .reward import DoubleLedgerScore, RouterRewardPolicy, score_double_ledger
from .spec import RouterRLState


@dataclass(frozen=True, slots=True)
class RouterRLEnvironmentReset:
    episode_id: str
    state_id: str
    step_index: int
    request_payload: dict[str, Any]
    messages: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class RouterRLEnvironmentStep:
    episode_id: str
    state_id: str
    step_index: int
    score: DoubleLedgerScore
    terminated: bool
    success_transition: bool
    next_state_id: str | None
    next_request_payload: dict[str, Any] | None
    episode_return: float

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["score"] = self.score.to_dict()
        return value


class RouterRLEnvironment:
    """Advance only successful semantic actions through a frozen episode graph."""

    def __init__(self, states: list[RouterRLState], *, success_threshold: float = 0.65) -> None:
        if not 0 <= success_threshold <= 1:
            raise ValueError("success_threshold must be in [0, 1]")
        self._states = {state.state_id: state for state in states}
        self._episode_roots = {state.episode_id: state for state in states if state.step_index == 0}
        self._reward_policy = RouterRewardPolicy()
        self._success_threshold = success_threshold
        self._current: RouterRLState | None = None
        self._return = 0.0

    def reset(self, episode_id: str) -> RouterRLEnvironmentReset:
        try:
            self._current = self._episode_roots[episode_id]
        except KeyError as exc:
            raise KeyError(f"unknown RL episode: {episode_id}") from exc
        self._return = 0.0
        return self._reset_value(self._current)

    def step(self, output: str | dict[str, Any]) -> RouterRLEnvironmentStep:
        if self._current is None:
            raise RuntimeError("environment must be reset before step")
        state = self._current
        score = score_double_ledger(output, state, reward_policy=self._reward_policy)
        raw = score.raw
        choice_success = (
            raw.policy_reward >= self._success_threshold
            and raw.components["tool_choice"] == 1.0
            and raw.components["stop_decision"] == 1.0
        )
        terminal_bonus = 0.10 if state.terminal and choice_success else 0.0
        self._return += raw.policy_reward + terminal_bonus
        terminated = state.terminal or not choice_success
        next_state: RouterRLState | None = None
        if not terminated and state.next_state_id is not None:
            next_state = self._states[state.next_state_id]
            self._current = next_state
        else:
            self._current = None
        return RouterRLEnvironmentStep(
            episode_id=state.episode_id,
            state_id=state.state_id,
            step_index=state.step_index,
            score=score,
            terminated=terminated,
            success_transition=choice_success,
            next_state_id=next_state.state_id if next_state else None,
            next_request_payload=dict(next_state.request_payload) if next_state else None,
            episode_return=round(self._return, 6),
        )

    @staticmethod
    def _reset_value(state: RouterRLState) -> RouterRLEnvironmentReset:
        return RouterRLEnvironmentReset(
            episode_id=state.episode_id,
            state_id=state.state_id,
            step_index=state.step_index,
            request_payload=dict(state.request_payload),
            messages=tuple(dict(message) for message in state.messages),
        )
