import pytest
from pydantic import ValidationError

from studyhub_agent.contracts.episode import (
    AssistantTurn,
    Budget,
    Episode,
    EpisodeSpec,
    FailureOwner,
    Message,
    Observation,
    Principal,
    Termination,
    TurnKind,
)


def _spec(**overrides):
    base = {
        "episode_id": "ep-1",
        "task_id": "task-1",
        "user_message": "帮我找高数期末复习资料",
        "principal": Principal(principal_id="u-1001"),
        "tool_names": ("materials_search",),
    }
    return EpisodeSpec(**{**base, **overrides})


def test_spec_defaults_are_contract_defaults() -> None:
    spec = _spec()
    assert spec.thinking is False
    assert spec.system_prompt == "studyhub.agent.system@1.0"
    assert spec.budget.max_turns == 12


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _spec(temperature=0.7)


def test_models_are_immutable() -> None:
    spec = _spec()
    with pytest.raises(ValidationError):
        spec.thinking = True


def test_budget_requires_room_for_prompt() -> None:
    with pytest.raises(ValidationError, match="max_new_tokens"):
        Budget(max_context_tokens=1024, max_new_tokens=1024)


def test_episode_round_trips_through_json() -> None:
    episode = Episode(
        spec=_spec(),
        contract_hash="sha256:abc",
        messages=(Message(role="user", content="你好"),),
        turns=(),
        observations=(),
        termination=Termination.MAX_TURNS,
        failure_owner=FailureOwner.MODEL,
    )
    assert Episode.model_validate_json(episode.model_dump_json()) == episode


def test_observation_details_and_turn_provenance_round_trip() -> None:
    observation = Observation(
        call_id="c", name="materials_read", ok=True, payload={"text": "x"}, details={"read_pages": [[101, 1]]}
    )
    assert Observation.model_validate_json(observation.model_dump_json()) == observation
    turn = AssistantTurn(kind=TurnKind.FINAL, content="a", raw_text="a", canonical_text="a")
    assert (turn.policy_key, turn.model_id) == ("small", "")


def test_episode_provenance_defaults_do_not_share_mutable_state() -> None:
    values = dict(
        spec=_spec(),
        contract_hash="sha256:abc",
        messages=(),
        turns=(),
        observations=(),
        termination=Termination.MAX_TURNS,
        failure_owner=FailureOwner.MODEL,
    )
    first, second = Episode(**values), Episode(**values)
    assert first.architecture == "react@1.0"
    first.architecture_trace["turn"] = 1
    first.models["small"] = "test-model"
    assert second.architecture_trace == second.models == {}
