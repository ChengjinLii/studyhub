"""Open environment protocol and stateful StudyHub environment adapters."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from app.agentic_platform.domain import DomainModel, apply_state_delta
from app.agentic_platform.domain.artifact import ArtifactRef
from app.agentic_platform.domain.decision import AgentDecision
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.observation import Observation
from app.agentic_platform.domain.reward_facts import RewardFacts
from app.agentic_platform.domain.state import AgentTaskState, StateDelta
from app.agentic_platform.domain.state_abstract import state_group_key_v2
from app.agentic_platform.domain.transition import ExecutionError, VerifierResult

from .scenario import ScenarioSpec
from .snapshot import EnvironmentKind, EnvironmentSnapshot


class EnvironmentNotReadyError(RuntimeError):
    pass


class ScenarioActionExhaustedError(LookupError):
    pass


class ScenarioActionMismatchError(ValueError):
    pass


class EnvironmentActionResult(DomainModel):
    """Typed effect returned by a live or simulated environment adapter."""

    schema_version: str = "1.0"
    state_delta: StateDelta = Field(default_factory=StateDelta)
    observation: Observation | None = None
    verifier_result: VerifierResult | None = None
    reward_facts: RewardFacts = Field(default_factory=RewardFacts)
    error: ExecutionError | None = None


class EnvironmentReset(DomainModel):
    schema_version: str = "1.0"
    scenario_id: str = Field(min_length=1, max_length=128)
    seed: int = Field(ge=0)
    snapshot: EnvironmentSnapshot
    state: AgentTaskState
    state_hash: str = Field(min_length=1, max_length=128)
    state_abstract_key: str = Field(min_length=1, max_length=256)
    state_group_key_v2: str = Field(min_length=1, max_length=256)


class EnvironmentStep(DomainModel):
    schema_version: str = "1.0"
    environment_kind: EnvironmentKind
    snapshot_id: str = Field(min_length=1, max_length=128)
    action_index: int = Field(ge=0)
    action: AgentDecision
    action_hash: str = Field(min_length=1, max_length=128)
    state_before_hash: str = Field(min_length=1, max_length=128)
    state_after_hash: str = Field(min_length=1, max_length=128)
    state_abstract_key: str = Field(min_length=1, max_length=256)
    state_group_key_v2: str = Field(min_length=1, max_length=256)
    state: AgentTaskState
    state_delta: StateDelta
    observation: Observation | None = None
    verifier_result: VerifierResult | None = None
    reward_facts: RewardFacts
    error: ExecutionError | None = None


class AgentEnvironment(Protocol):
    """The stable boundary used by live, snapshot, and simulated rollouts."""

    async def reset(self, scenario: ScenarioSpec, seed: int) -> EnvironmentReset:
        ...

    async def step(self, action: AgentDecision) -> EnvironmentStep:
        ...

    async def snapshot(self) -> EnvironmentSnapshot:
        ...

    async def restore(self, snapshot: EnvironmentSnapshot) -> None:
        ...


class EnvironmentActionExecutor(Protocol):
    """Live/snapshot action adapter; it receives the policy's unconstrained action."""

    async def execute(
        self,
        *,
        state: AgentTaskState,
        action: AgentDecision,
        scenario: ScenarioSpec,
        seed: int,
        action_index: int,
    ) -> EnvironmentActionResult:
        ...


class _StatefulStudyHubEnvironment:
    environment_kind: EnvironmentKind

    def __init__(self, action_executor: EnvironmentActionExecutor | None = None) -> None:
        self._action_executor = action_executor
        self._scenario: ScenarioSpec | None = None
        self._snapshot: EnvironmentSnapshot | None = None
        self._state: AgentTaskState | None = None
        self._seed: int | None = None
        self._action_index = 0

    async def reset(self, scenario: ScenarioSpec, seed: int) -> EnvironmentReset:
        if seed < 0:
            raise ValueError("environment seed must be non-negative")
        self._scenario = scenario.model_copy(deep=True)
        self._snapshot = self._scenario.initial_snapshot.model_copy(deep=True)
        self._state = self._snapshot.task_state.model_copy(deep=True)
        self._seed = seed
        self._action_index = self._snapshot.turn_index
        group_key = state_group_key_v2(self._state)
        return EnvironmentReset(
            scenario_id=self._scenario.scenario_id,
            seed=seed,
            snapshot=self._snapshot.model_copy(deep=True),
            state=self._state.model_copy(deep=True),
            state_hash=canonical_hash(self._state),
            state_abstract_key=group_key,
            state_group_key_v2=group_key,
        )

    async def step(self, action: AgentDecision) -> EnvironmentStep:
        state = self._require_state().model_copy(deep=True)
        scenario = self._require_scenario().model_copy(deep=True)
        seed = self._require_seed()
        action_index = self._action_index
        result = await self._execute_action(
            state=state.model_copy(deep=True),
            action=action.model_copy(deep=True),
            scenario=scenario,
            seed=seed,
            action_index=action_index,
        )
        successor = apply_state_delta(state, result.state_delta)
        self._state = successor.model_copy(deep=True)
        self._action_index += 1
        group_key = state_group_key_v2(successor)
        return EnvironmentStep(
            environment_kind=self.environment_kind,
            snapshot_id=self._require_snapshot().snapshot_id,
            action_index=action_index,
            action=action.model_copy(deep=True),
            action_hash=canonical_hash(action),
            state_before_hash=canonical_hash(state),
            state_after_hash=canonical_hash(successor),
            state_abstract_key=group_key,
            state_group_key_v2=group_key,
            state=successor.model_copy(deep=True),
            state_delta=result.state_delta.model_copy(deep=True),
            observation=result.observation.model_copy(deep=True) if result.observation else None,
            verifier_result=result.verifier_result.model_copy(deep=True) if result.verifier_result else None,
            reward_facts=result.reward_facts.model_copy(deep=True),
            error=result.error.model_copy(deep=True) if result.error else None,
        )

    async def snapshot(self) -> EnvironmentSnapshot:
        state = self._require_state()
        scenario = self._require_scenario()
        original = self._require_snapshot()
        metadata = dict(original.metadata)
        metadata.update({"scenario_id": scenario.scenario_id, "seed": self._require_seed()})
        return EnvironmentSnapshot.capture(
            state,
            environment_kind=self.environment_kind,
            source=self.environment_kind.value,
            artifact_refs=_unique_artifact_refs([*original.artifact_refs, *state.active_artifacts]),
            metadata=metadata,
            turn_index=self._action_index,
        )

    async def restore(self, snapshot: EnvironmentSnapshot) -> None:
        self._snapshot = snapshot.model_copy(deep=True)
        self._state = snapshot.task_state.model_copy(deep=True)
        self._action_index = snapshot.turn_index
        if self._scenario is None:
            self._scenario = ScenarioSpec(
                scenario_id=f"restore_{snapshot.snapshot_id}",
                initial_snapshot=snapshot.model_copy(deep=True),
            )
        if self._seed is None:
            self._seed = 0

    async def _execute_action(
        self,
        *,
        state: AgentTaskState,
        action: AgentDecision,
        scenario: ScenarioSpec,
        seed: int,
        action_index: int,
    ) -> EnvironmentActionResult:
        if self._action_executor is None:
            raise EnvironmentNotReadyError("environment has no action executor")
        return await self._action_executor.execute(
            state=state,
            action=action,
            scenario=scenario,
            seed=seed,
            action_index=action_index,
        )

    def _require_state(self) -> AgentTaskState:
        if self._state is None:
            raise EnvironmentNotReadyError("environment must be reset or restored before use")
        return self._state

    def _require_scenario(self) -> ScenarioSpec:
        if self._scenario is None:
            raise EnvironmentNotReadyError("environment must be reset or restored before use")
        return self._scenario

    def _require_snapshot(self) -> EnvironmentSnapshot:
        if self._snapshot is None:
            raise EnvironmentNotReadyError("environment must be reset or restored before use")
        return self._snapshot

    def _require_seed(self) -> int:
        if self._seed is None:
            raise EnvironmentNotReadyError("environment must be reset or restored before use")
        return self._seed


class LiveStudyHubEnvironment(_StatefulStudyHubEnvironment):
    """Live adapter whose injected executor decides how each valid action runs."""

    environment_kind = EnvironmentKind.LIVE


class SnapshotStudyHubEnvironment(_StatefulStudyHubEnvironment):
    """Offline/snapshot adapter backed by an injected deterministic executor."""

    environment_kind = EnvironmentKind.SNAPSHOT


class SimulatedStudyHubEnvironment(_StatefulStudyHubEnvironment):
    """Scenario fixture environment for deterministic tests and rollouts only."""

    environment_kind = EnvironmentKind.SIMULATED

    async def _execute_action(
        self,
        *,
        state: AgentTaskState,
        action: AgentDecision,
        scenario: ScenarioSpec,
        seed: int,
        action_index: int,
    ) -> EnvironmentActionResult:
        del state, seed
        if action_index >= len(scenario.actions):
            raise ScenarioActionExhaustedError("scenario has no remaining fixture action")
        expected = scenario.actions[action_index]
        if canonical_hash(action) != expected.decision_hash:
            raise ScenarioActionMismatchError(
                f"scenario action mismatch at index {action_index}; caller-selected action differs from fixture"
            )
        return EnvironmentActionResult(
            state_delta=expected.state_delta.model_copy(deep=True),
            observation=expected.observation.model_copy(deep=True) if expected.observation else None,
            verifier_result=expected.verifier_result.model_copy(deep=True) if expected.verifier_result else None,
            reward_facts=expected.reward_facts.model_copy(deep=True),
            error=expected.error.model_copy(deep=True) if expected.error else None,
        )


def _unique_artifact_refs(references: list[ArtifactRef]) -> list[ArtifactRef]:
    result: list[ArtifactRef] = []
    known: set[tuple[str, int]] = set()
    for reference in references:
        key = (reference.artifact_id, reference.version)
        if key not in known:
            result.append(reference.model_copy(deep=True))
            known.add(key)
    return result
