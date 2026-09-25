from studyhub_agent.contracts.episode import (
    AssistantTurn,
    Episode,
    EpisodeSpec,
    FailureOwner,
    Message,
    Observation,
    Principal,
    Termination,
    ToolCall,
    TurnKind,
)
from studyhub_agent.graders.base import TaskSpec
from studyhub_agent.graders.exact_match import ExactMatchGrader

SPEC = EpisodeSpec(
    episode_id="e",
    task_id="t",
    user_message="q",
    principal=Principal(principal_id="u"),
    tool_names=("materials_search",),
)


def _episode(
    final: str | None,
    termination=Termination.FINAL_ANSWER,
    owner=FailureOwner.NONE,
    tools=("materials_search",),
) -> Episode:
    turns = tuple(
        AssistantTurn(
            kind=TurnKind.TOOL_CALLS,
            tool_calls=(ToolCall(call_id="c", name=name, arguments={}),),
            raw_text="",
            canonical_text="",
        )
        for name in tools
    )
    observations = tuple(Observation(call_id="c", name=name, ok=True, payload={}) for name in tools)
    return Episode(
        spec=SPEC,
        contract_hash="sha256:x",
        messages=(Message(role="user", content="q"),),
        turns=turns,
        observations=observations,
        termination=termination,
        failure_owner=owner,
        final_answer=final,
    )


def test_pass_requires_answer_match_and_required_tools() -> None:
    task = TaskSpec(
        task_id="t",
        expected_final=" 2027-01-08 ",
        required_tools=("materials_search",),
    )
    result = ExactMatchGrader().grade(_episode("2027-01-08"), task)
    assert (
        result.strict_pass
        and result.hard_gates == {
            "final_answer_present": True,
            "required_tools_used": True,
            "answer_matches": True,
        }
    )


def test_missing_tool_fails_gate() -> None:
    task = TaskSpec(task_id="t", expected_final="a", required_tools=("materials_read",))
    result = ExactMatchGrader().grade(_episode("a"), task)
    assert not result.strict_pass and result.hard_gates["required_tools_used"] is False


def test_infra_failure_is_attributed_not_scored_as_model_failure() -> None:
    result = ExactMatchGrader().grade(
        _episode(None, Termination.INFRA_ERROR, FailureOwner.INFRA),
        TaskSpec(task_id="t", expected_final="a"),
    )
    assert not result.strict_pass and result.failure_owner is FailureOwner.INFRA


def test_wrong_answer_is_model_failure() -> None:
    result = ExactMatchGrader().grade(
        _episode("b"), TaskSpec(task_id="t", expected_final="a")
    )
    assert (
        result.failure_owner is FailureOwner.MODEL
        and result.scores["answer_match"] == 0.0
    )


def test_required_tool_only_attempted_not_executed_fails_gate() -> None:
    # A tool call can appear in episode.turns (the model attempted it) without a matching
    # observation -- e.g. the runner cut it off at the tool budget before executing it (see
    # runtime.runner). "used" must reflect what actually ran, not what the model merely attempted.
    episode = Episode(
        spec=SPEC,
        contract_hash="sha256:x",
        messages=(Message(role="user", content="q"),),
        turns=(
            AssistantTurn(
                kind=TurnKind.TOOL_CALLS,
                tool_calls=(ToolCall(call_id="c", name="materials_search", arguments={}),),
                raw_text="",
                canonical_text="",
            ),
        ),
        observations=(),
        termination=Termination.TOOL_BUDGET,
        failure_owner=FailureOwner.MODEL,
        final_answer=None,
    )
    task = TaskSpec(task_id="t", required_tools=("materials_search",))
    result = ExactMatchGrader().grade(episode, task)
    assert result.hard_gates["required_tools_used"] is False
