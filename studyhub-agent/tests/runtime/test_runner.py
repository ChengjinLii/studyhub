import json
from pathlib import Path

import pytest

from studyhub_agent.contracts.episode import Budget, EpisodeSpec, FailureOwner, Principal, Termination, TurnKind
from studyhub_agent.contracts.prompts import DEFAULT_PROMPTS
from studyhub_agent.environments.base import EnvironmentInfraError
from studyhub_agent.environments.replay import ReplayEnvironment, load_snapshot
from studyhub_agent.runtime.runner import EpisodeRunner
from studyhub_agent.tools.specs import TOOL_SPECS
from tests.runtime.fakes import (
    ScriptedPolicy,
    count_chars,
    count_messages,
    final_turn,
    infra_failure,
    parse_error_turn,
    tool_turn,
)

SNAPSHOT = load_snapshot(Path(__file__).parent.parent / "fixtures" / "replay_snapshot.json")
RUNNER = EpisodeRunner(prompts=DEFAULT_PROMPTS, tokenizer_revision="test-rev", count_tokens=count_chars)
TOOLS = ("materials_search", "materials_read", "memory_update")


def _spec(**overrides) -> EpisodeSpec:
    base = {
        "episode_id": "ep-1",
        "task_id": "t-1",
        "user_message": "高数期末复习看什么？",
        "principal": Principal(principal_id="u-1001"),
        "tool_names": TOOLS,
    }
    return EpisodeSpec(**{**base, **overrides})


def _run(spec, turns, environment=None):
    policy = ScriptedPolicy(list(turns))
    return RUNNER.run(spec, environment or ReplayEnvironment(SNAPSHOT), policy), policy


def test_search_read_answer_happy_path() -> None:
    episode, policy = _run(
        _spec(),
        [
            tool_turn(("materials_search", {"query": "高等数学 提纲"})),
            tool_turn(("materials_read", {"material_id": 101})),
            final_turn("先看提纲第一章 [101:1]。"),
        ],
    )
    assert episode.termination is Termination.FINAL_ANSWER
    assert episode.failure_owner is FailureOwner.NONE
    assert episode.final_answer == "先看提纲第一章 [101:1]。"
    assert [obs.ok for obs in episode.observations] == [True, True]
    assert episode.turns[1].tool_calls[0].call_id == "t1_c0"
    tool_message = episode.messages[3]
    assert tool_message.role == "tool" and tool_message.tool_call_id == "t0_c0"
    assert json.loads(tool_message.content)["results"][0]["material_id"] == 101
    assert episode.environment_trace["read_material_ids"] == [101]
    assert episode.contract_hash == RUNNER.contract_for(episode.spec, episode_tools())


def episode_tools():
    from studyhub_agent.tools.specs import select_tools

    return select_tools(TOOLS)


def test_parse_error_is_fed_back_then_budget_ends_episode() -> None:
    episode, policy = _run(_spec(budget=Budget(max_parse_errors=1)), [parse_error_turn(), parse_error_turn()])
    assert episode.termination is Termination.PARSE_ERROR_BUDGET
    assert episode.failure_owner is FailureOwner.MODEL
    feedback = policy.seen[1][-1]
    assert feedback.role == "tool" and feedback.name == "runtime_feedback"
    assert json.loads(feedback.content)["error"] == "malformed_tool_call"


def test_max_turns_injects_finalize_prompt_on_last_turn() -> None:
    episode, policy = _run(
        _spec(budget=Budget(max_turns=2)),
        [tool_turn(("materials_search", {"query": "高数"})), tool_turn(("materials_search", {"query": "高数"}))],
    )
    assert episode.termination is Termination.MAX_TURNS
    last_prompt = policy.seen[-1][-1]
    assert last_prompt.name == "runtime_feedback"
    payload = json.loads(last_prompt.content)
    assert "最后一轮" in payload["instruction"]


def test_max_turns_one_still_injects_finalize_prompt() -> None:
    episode, policy = _run(
        _spec(budget=Budget(max_turns=1)),
        [tool_turn(("materials_search", {"query": "高数"}))],
    )
    assert episode.termination is Termination.MAX_TURNS
    first_prompt = policy.seen[0][-1]
    assert first_prompt.role == "tool" and first_prompt.name == "runtime_feedback"
    payload = json.loads(first_prompt.content)
    assert "最后一轮" in payload["instruction"]


def test_tool_budget_stops_before_executing() -> None:
    episode, _ = _run(
        _spec(budget=Budget(max_tool_calls=1)),
        [tool_turn(("materials_search", {"query": "a"}), ("materials_search", {"query": "b"}))],
    )
    assert episode.termination is Termination.TOOL_BUDGET
    assert episode.observations == ()
    # The budget-exceeding turn is recorded in episode.turns; messages must stay consistent with
    # it (the assistant's tool-call message present, just no tool-response messages for it).
    assert len(episode.turns) == 1
    assistant_messages = [m for m in episode.messages if m.role == "assistant"]
    assert len(assistant_messages) == 1
    assert assistant_messages[0].tool_calls == episode.turns[0].tool_calls
    assert [m for m in episode.messages if m.role == "tool"] == []


def test_turn_with_one_invalid_call_executes_nothing() -> None:
    episode, _ = _run(_spec(), [parse_error_turn("invalid_argument: materials_read.material_id"), final_turn("完成")])
    assert episode.observations == ()
    assert episode.turns[0].kind is TurnKind.PARSE_ERROR
    assert episode.termination is Termination.FINAL_ANSWER


def test_infra_error_is_explicit_not_raised() -> None:
    episode, _ = _run(_spec(), [infra_failure()])
    assert episode.termination is Termination.INFRA_ERROR
    assert episode.failure_owner is FailureOwner.INFRA
    assert "connection refused" in (episode.error_detail or "")


def test_environment_exception_ends_episode_as_env_error() -> None:
    class ExplodingEnvironment(ReplayEnvironment):
        def execute(self, call):
            raise KeyError("snapshot corrupted")

    policy = ScriptedPolicy([tool_turn(("materials_search", {"query": "a"}))])
    episode = RUNNER.run(_spec(), ExplodingEnvironment(SNAPSHOT), policy)
    assert episode.termination is Termination.ENV_ERROR
    assert episode.failure_owner is FailureOwner.ENV


def test_environment_infra_error_ends_episode_as_infra_error() -> None:
    class InfraFailingEnvironment(ReplayEnvironment):
        def execute(self, call):
            raise EnvironmentInfraError("replay backend unavailable")

    policy = ScriptedPolicy([tool_turn(("materials_search", {"query": "a"}))])
    episode = RUNNER.run(_spec(), InfraFailingEnvironment(SNAPSHOT), policy)
    assert episode.termination is Termination.INFRA_ERROR
    assert episode.failure_owner is FailureOwner.INFRA
    assert "replay backend unavailable" in (episode.error_detail or "")


def test_context_budget_before_first_policy_call_is_an_env_config_error() -> None:
    # The episode spec/budget made the prompt too big before the model ever got a turn -- that is a
    # configuration problem (budget too small for the prompt), not something the model did.
    episode, policy = _run(_spec(user_message="长" * 200, budget=Budget(max_context_tokens=150, max_new_tokens=10)), [])
    assert episode.termination is Termination.CONTEXT_BUDGET
    assert episode.failure_owner is FailureOwner.ENV
    assert policy.seen == []


def test_context_budget_after_some_turns_is_still_a_model_failure() -> None:
    # Once the model has already taken at least one turn, later blowing the context budget with its
    # own verbose output is attributed to the model, not the environment/config.
    runner = EpisodeRunner(prompts=DEFAULT_PROMPTS, tokenizer_revision="test-rev", count_tokens=count_messages)
    policy = ScriptedPolicy([tool_turn(("materials_search", {"query": "高数"}))])
    spec = _spec(budget=Budget(max_context_tokens=13, max_new_tokens=10))
    episode = runner.run(spec, ReplayEnvironment(SNAPSHOT), policy)
    assert episode.termination is Termination.CONTEXT_BUDGET
    assert episode.failure_owner is FailureOwner.MODEL
    assert len(policy.seen) == 1


def test_unknown_tool_name_in_spec_is_a_configuration_error() -> None:
    with pytest.raises(KeyError, match="web_fetch"):
        _run(_spec(tool_names=("web_fetch",)), [])


def test_duplicate_tool_names_in_spec_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="materials_search"):
        _run(_spec(tool_names=("materials_search", "materials_search")), [])


class _SubsetEnvironment(ReplayEnvironment):
    """An environment that only actually provides a strict subset of the global tool registry."""

    def tool_specs(self):
        return tuple(spec for spec in TOOL_SPECS if spec.name != "materials_read")


def test_environment_tool_subset_is_a_configuration_error_for_a_missing_tool() -> None:
    # A tool name can be perfectly valid in the *global* registry yet unavailable from this
    # particular environment; the runner must resolve tools against what the environment actually
    # provides (environment.tool_specs()), not the global registry, or it would silently prompt the
    # model with a tool the environment can never execute.
    with pytest.raises(KeyError, match="materials_read"):
        _run(_spec(), [], environment=_SubsetEnvironment(SNAPSHOT))


def test_reasoning_is_carried_into_message_history() -> None:
    episode, _ = _run(
        _spec(),
        [
            tool_turn(("materials_search", {"query": "高数"}), reasoning="先想想要不要查"),
            final_turn("完成", reasoning="复核一下"),
        ],
    )
    assistant_messages = [message for message in episode.messages if message.role == "assistant"]
    assert [message.reasoning for message in assistant_messages] == ["先想想要不要查", "复核一下"]


def test_contract_hash_depends_on_thinking() -> None:
    tools = episode_tools()
    assert RUNNER.contract_for(_spec(), tools) != RUNNER.contract_for(_spec(thinking=True), tools)
