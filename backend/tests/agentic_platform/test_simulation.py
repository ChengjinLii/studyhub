from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.agentic_platform.domain.decision import AgentActionType, AgentDecision, ExpectedStateChange
from app.agentic_platform.domain.state import StateDelta
from app.agentic_platform.simulation.environment import EnvironmentActionResult, LiveStudyHubEnvironment, SimulatedStudyHubEnvironment
from app.agentic_platform.simulation.replay import ReplayRequest, SnapshotReplayRunner
from app.agentic_platform.simulation.scenario import ScenarioAction, ScenarioSpec
from app.agentic_platform.simulation.snapshot import EnvironmentKind, EnvironmentSnapshot
from tests.agentic_platform.factories import task_state


def _decision(index: int) -> AgentDecision:
    return AgentDecision(
        action_type=AgentActionType.REVIEW,
        plan_step_id="review",
        rationale_summary=f"Review fixture result {index} against current evidence.",
        expected_state_change=ExpectedStateChange(summary=f"Record fixture result {index}."),
    )


def _snapshot() -> EnvironmentSnapshot:
    return EnvironmentSnapshot.capture(
        task_state(),
        environment_kind=EnvironmentKind.SIMULATED,
        source="simulation-fixture",
        metadata={"fixture": "multi-turn"},
    )


def _scenario(turns: int = 10) -> tuple[ScenarioSpec, list[AgentDecision]]:
    actions = [_decision(index) for index in range(turns)]
    return (
        ScenarioSpec(
            scenario_id="simulation-10-turn",
            initial_snapshot=_snapshot(),
            actions=[
                ScenarioAction(
                    action_id=f"fixture-action-{index}",
                    expected_decision=action,
                    state_delta=StateDelta(candidate_ids_to_add=[f"candidate-{index}"]),
                )
                for index, action in enumerate(actions)
            ],
        ),
        actions,
    )


def test_same_snapshot_seed_and_actions_replay_to_the_same_state_hash_for_ten_turns() -> None:
    scenario, actions = _scenario()
    runner = SnapshotReplayRunner()
    first = asyncio.run(
        runner.replay(
            SimulatedStudyHubEnvironment(),
            ReplayRequest(replay_id="first", scenario=scenario, seed=73, actions=actions),
        )
    )
    second = asyncio.run(
        runner.replay(
            SimulatedStudyHubEnvironment(),
            ReplayRequest(
                replay_id="second",
                scenario=scenario,
                seed=73,
                actions=actions,
                expected_state_hashes=first.state_hashes,
            ),
        )
    )

    assert len(first.steps) == 10
    assert first.state_hashes == second.state_hashes
    assert first.final_state_hash == second.final_state_hash
    assert first.final_state.working_set.candidate_ids == [f"candidate-{index}" for index in range(10)]
    assert scenario.initial_snapshot.task_state.working_set.candidate_ids == []


def test_simulated_environments_hold_isolated_state_per_rollout() -> None:
    async def scenario() -> tuple[list[str], list[str]]:
        specification, actions = _scenario(turns=2)
        first = SimulatedStudyHubEnvironment()
        second = SimulatedStudyHubEnvironment()
        await first.reset(specification, seed=1)
        await second.reset(specification, seed=1)
        first_step = await first.step(actions[0])
        second_snapshot = await second.snapshot()
        return first_step.state.working_set.candidate_ids, second_snapshot.task_state.working_set.candidate_ids

    first_candidates, second_candidates = asyncio.run(scenario())

    assert first_candidates == ["candidate-0"]
    assert second_candidates == []


def test_live_environment_accepts_an_injected_open_action_executor_not_a_fixture_script() -> None:
    class DynamicExecutor:
        async def execute(self, *, state, action, scenario, seed, action_index) -> EnvironmentActionResult:
            del state, action, scenario, seed, action_index
            return EnvironmentActionResult(state_delta=StateDelta(candidate_ids_to_add=["chosen-by-policy"]))

    async def scenario() -> list[str]:
        environment = LiveStudyHubEnvironment(DynamicExecutor())
        specification = ScenarioSpec(scenario_id="live-open", initial_snapshot=_snapshot())
        await environment.reset(specification, seed=99)
        result = await environment.step(_decision(99))
        return result.state.working_set.candidate_ids

    assert asyncio.run(scenario()) == ["chosen-by-policy"]


def test_snapshot_content_hash_ignores_capture_time_but_validates_replayable_content() -> None:
    state = task_state()
    first = EnvironmentSnapshot.capture(
        state,
        environment_kind=EnvironmentKind.SNAPSHOT,
        source="fixture",
        captured_at=datetime(2026, 7, 26, tzinfo=UTC),
    )
    later = EnvironmentSnapshot.capture(
        state,
        environment_kind=EnvironmentKind.SNAPSHOT,
        source="fixture",
        captured_at=datetime(2026, 7, 27, tzinfo=UTC),
    )

    assert first.snapshot_hash == later.snapshot_hash
    assert first.initial_state_hash == later.initial_state_hash
