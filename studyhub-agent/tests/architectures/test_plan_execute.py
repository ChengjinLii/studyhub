import json

import pytest

from studyhub_agent.architectures import PlanExecuteArchitecture
from studyhub_agent.contracts.episode import Budget, Termination
from studyhub_agent.contracts.prompts import PLAN_REMINDER_PROMPT_KEY, PLAN_REQUEST_PROMPT_KEY
from studyhub_agent.environments.replay import ReplayEnvironment
from tests.architectures.test_hooks import RUNNER, SNAPSHOT, _spec
from tests.runtime.fakes import ScriptedPolicy, final_turn, parse_error_turn, tool_turn


def test_plan_is_recorded_and_execution_uses_registered_reminder() -> None:
    plan = "1. 检索提纲\n2. 阅读预览\n3. 引用回答"
    policy = ScriptedPolicy(
        [
            final_turn(plan),
            tool_turn(("materials_search", {"query": "提纲"})),
            tool_turn(("materials_read", {"material_id": 101})),
            final_turn("极限与导数 [101:1]"),
        ]
    )
    episode = RUNNER.run(_spec(), ReplayEnvironment(SNAPSHOT), policy, architecture=PlanExecuteArchitecture())
    assert episode.final_answer == "极限与导数 [101:1]"
    assert episode.architecture == "plan_execute@1.0"
    assert episode.architecture_trace["plan"] == plan
    assert episode.architecture_trace["continues"] == [{"turn": 0, "reason": "plan"}]
    request = json.loads(policy.seen[0][-1].content)
    assert request["instruction"] == RUNNER._prompts.get(PLAN_REQUEST_PROMPT_KEY).text
    for view in policy.seen[1:]:
        reminder = json.loads(view[-1].content)
        assert reminder["notice"] == "plan_reminder" and reminder["plan"] == plan
        assert reminder["instruction"] == RUNNER._prompts.get(PLAN_REMINDER_PROMPT_KEY).text
    assert not any('"notice":"plan_reminder"' in message.content for message in episode.messages)


@pytest.mark.parametrize("first", [tool_turn(("materials_search", {"query": "提纲"})), parse_error_turn()])
def test_non_final_first_turn_skips_planning_without_capturing_later_answer(first) -> None:
    policy = ScriptedPolicy([first, final_turn("直接回答")])
    episode = RUNNER.run(_spec(), ReplayEnvironment(SNAPSHOT), policy, architecture=PlanExecuteArchitecture())
    assert episode.final_answer == "直接回答"
    assert episode.architecture_trace["plan_skipped"] is True
    assert episode.architecture_trace["plan_skip_reason"] == first.kind.value
    assert "plan" not in episode.architecture_trace and "continues" not in episode.architecture_trace


def test_plan_truncation_affects_reminder_but_not_original_history() -> None:
    plan = "计划内容" * 200
    policy = ScriptedPolicy([final_turn(plan), final_turn("答案")])
    architecture = PlanExecuteArchitecture(max_plan_chars=100)
    episode = RUNNER.run(_spec(), ReplayEnvironment(SNAPSHOT), policy, architecture=architecture)
    assert episode.architecture_trace["plan"] == plan[:100]
    assert episode.architecture_trace["plan_truncated"] is True
    assert next(message.content for message in episode.messages if message.role == "assistant") == plan
    assert json.loads(policy.seen[1][-1].content)["plan"] == plan[:100]
    assert RUNNER.contract_for(_spec(), (), architecture=architecture) != RUNNER.contract_for(
        _spec(), (), architecture=PlanExecuteArchitecture(max_plan_chars=101)
    )


def test_planning_cannot_escape_last_turn_budget() -> None:
    episode = RUNNER.run(
        _spec(budget=Budget(max_turns=1)),
        ReplayEnvironment(SNAPSHOT),
        ScriptedPolicy([final_turn("1. 检索\n2. 阅读\n3. 回答")]),
        architecture=PlanExecuteArchitecture(),
    )
    assert episode.termination is Termination.MAX_TURNS and episode.final_answer is None


def test_empty_plan_requests_execution_without_empty_reminder() -> None:
    policy = ScriptedPolicy([final_turn("  "), final_turn("答案")])
    episode = RUNNER.run(_spec(), ReplayEnvironment(SNAPSHOT), policy, architecture=PlanExecuteArchitecture())
    assert episode.final_answer == "答案"
    assert episode.architecture_trace["plan_skipped"] is True
    assert episode.architecture_trace["plan_skip_reason"] == "empty_plan"
    assert json.loads(policy.seen[1][-1].content)["notice"] == "execute_plan"


def test_plan_state_does_not_leak_between_episodes() -> None:
    architecture = PlanExecuteArchitecture()
    for plan in ("第一份计划", "第二份计划"):
        episode = RUNNER.run(
            _spec(),
            ReplayEnvironment(SNAPSHOT),
            ScriptedPolicy([final_turn(plan), final_turn("答案")]),
            architecture=architecture,
        )
        assert episode.architecture_trace["plan"] == plan
        assert len(episode.architecture_trace["continues"]) == 1


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_plan_limits_are_rejected(limit) -> None:
    with pytest.raises(ValueError, match="max_plan_chars"):
        PlanExecuteArchitecture(max_plan_chars=limit)
