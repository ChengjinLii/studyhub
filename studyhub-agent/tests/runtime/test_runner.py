import json
from pathlib import Path

from studyhub_agent.contracts.episode import Budget, EpisodeSpec, FailureOwner, Principal, Termination, TurnKind
from studyhub_agent.contracts.prompts import DEFAULT_PROMPTS
from studyhub_agent.environments.base import EnvironmentInfraError
from studyhub_agent.environments.replay import ReplayEnvironment, load_snapshot
from studyhub_agent.runtime.runner import EpisodeRunner
from tests.runtime.fakes import ScriptedPolicy, count_chars, final_turn, infra_failure, parse_error_turn, tool_turn

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


def _run(spec, turns):
    policy = ScriptedPolicy(list(turns))
    return RUNNER.run(spec, ReplayEnvironment(SNAPSHOT), policy), policy


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


def test_context_budget_checked_before_each_step() -> None:
    episode, policy = _run(_spec(user_message="长" * 200, budget=Budget(max_context_tokens=150, max_new_tokens=10)), [])
    assert episode.termination is Termination.CONTEXT_BUDGET
    assert policy.seen == []


def test_unknown_tool_name_in_spec_is_a_configuration_error() -> None:
    import pytest

    with pytest.raises(KeyError, match="web_fetch"):
        _run(_spec(tool_names=("web_fetch",)), [])


def test_contract_hash_depends_on_thinking() -> None:
    tools = episode_tools()
    assert RUNNER.contract_for(_spec(), tools) != RUNNER.contract_for(_spec(thinking=True), tools)
