"""Deterministic replay over the open :class:`AgentEnvironment` protocol."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.decision import AgentDecision
from app.agentic_platform.domain.state import AgentTaskState
from app.agentic_platform.policy.replay_policy import ReplayPolicy, ReplayScriptExhaustedError

from .environment import AgentEnvironment, EnvironmentReset, EnvironmentStep
from .scenario import ScenarioSpec


class ReplayHashMismatchError(AssertionError):
    pass


class ReplayRequest(DomainModel):
    """Caller-supplied actions to replay from an immutable starting snapshot."""

    schema_version: str = "1.0"
    replay_id: str = Field(min_length=1, max_length=128)
    scenario: ScenarioSpec
    seed: int = Field(ge=0)
    actions: list[AgentDecision] = Field(default_factory=list)
    expected_state_hashes: list[str] = Field(default_factory=list)

    @field_validator("replay_id")
    @classmethod
    def reject_blank_replay_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("expected_state_hashes")
    @classmethod
    def reject_blank_state_hashes(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("expected state hashes must not be blank")
        return values

    @model_validator(mode="after")
    def validate_expected_hash_count(self) -> "ReplayRequest":
        if self.expected_state_hashes and len(self.expected_state_hashes) != len(self.actions) + 1:
            raise ValueError("expected state hashes must include reset state plus one value per action")
        return self


class ReplayResult(DomainModel):
    schema_version: str = "1.0"
    replay_id: str = Field(min_length=1, max_length=128)
    reset: EnvironmentReset
    steps: list[EnvironmentStep]
    state_hashes: list[str]
    final_state: AgentTaskState
    final_state_hash: str = Field(min_length=1, max_length=128)


class SnapshotReplayRunner:
    """Replay caller-provided actions without imposing a business workflow."""

    async def replay(self, environment: AgentEnvironment, request: ReplayRequest) -> ReplayResult:
        reset = await environment.reset(request.scenario.model_copy(deep=True), request.seed)
        state_hashes = [reset.state_hash]
        self._assert_hash(request, index=0, actual=reset.state_hash)
        steps: list[EnvironmentStep] = []
        for index, action in enumerate(request.actions, start=1):
            step = await environment.step(action.model_copy(deep=True))
            steps.append(step.model_copy(deep=True))
            state_hashes.append(step.state_after_hash)
            self._assert_hash(request, index=index, actual=step.state_after_hash)
        final_state = steps[-1].state.model_copy(deep=True) if steps else reset.state.model_copy(deep=True)
        return ReplayResult(
            replay_id=request.replay_id,
            reset=reset.model_copy(deep=True),
            steps=steps,
            state_hashes=state_hashes,
            final_state=final_state,
            final_state_hash=state_hashes[-1],
        )

    @staticmethod
    def _assert_hash(request: ReplayRequest, *, index: int, actual: str) -> None:
        if not request.expected_state_hashes:
            return
        expected = request.expected_state_hashes[index]
        if actual != expected:
            raise ReplayHashMismatchError(
                f"replay {request.replay_id} diverged at state {index}: expected {expected}, got {actual}"
            )


__all__ = [
    "ReplayHashMismatchError",
    "ReplayPolicy",
    "ReplayRequest",
    "ReplayResult",
    "ReplayScriptExhaustedError",
    "SnapshotReplayRunner",
]
