import json
from pathlib import Path

import httpx
import pytest

from studyhub_agent.architectures.react_verify import ReactVerifyArchitecture
from studyhub_agent.contracts.episode import Budget, EpisodeSpec, Observation, Principal, Termination
from studyhub_agent.contracts.render import canonical_completion_text
from studyhub_agent.environments.replay import ReplayEnvironment, load_snapshot
from studyhub_agent.runtime.openai_client import OpenAICompatPolicyClient
from studyhub_agent.runtime.token_client import TokenPolicyClient
from studyhub_agent.tools.specs import select_tools
from tests.architectures.test_hooks import RUNNER
from tests.runtime.fakes import CharTokenizer, ScriptedPolicy, final_turn, tool_turn
from tests.runtime.test_runner import _SequencedBackend

SNAPSHOT = load_snapshot(Path(__file__).parent.parent / "fixtures" / "replay_snapshot.json")


def _run(answers, *, architecture=None, environment=None, max_turns=12, read=True):
    spec = EpisodeSpec(
        episode_id="ep",
        task_id="t",
        user_message="高等数学",
        principal=Principal(principal_id="u-1001"),
        tool_names=("materials_search", "materials_read"),
        budget=Budget(max_turns=max_turns),
    )
    tools = (
        [tool_turn(("materials_search", {"query": "提纲"})), tool_turn(("materials_read", {"material_id": 101}))]
        if read
        else []
    )
    policy = ScriptedPolicy([*tools, *(final_turn(text) for text in answers)])
    episode = RUNNER.run(
        spec,
        environment or ReplayEnvironment(SNAPSHOT),
        policy,
        architecture=architecture or ReactVerifyArchitecture(),
    )
    return episode, policy


@pytest.mark.parametrize("first,missing", [("wrong [101:2]", False), ("no citation", True)])
def test_reject_then_repair_uses_real_page_evidence(first, missing) -> None:
    episode, policy = _run([first, "answer [101:1]"])
    assert episode.final_answer == "answer [101:1]"
    feedback = json.loads(policy.seen[-1][-1].content)
    assert feedback["notice"] == "citation_check_failed" and feedback["missing"] is missing
    assert feedback["read_pages"] == [[101, 1]]
    assert feedback["unread"] == ([[101, 2]] if not missing else [])
    assert episode.architecture_trace["verify_rejections"] == 1
    assert episode.architecture_trace["citation_verified"] is True


def test_no_pages_and_no_citations_does_not_force_material_reads() -> None:
    episode, _ = _run(["not found"], read=False)
    assert episode.termination is Termination.FINAL_ANSWER
    assert episode.architecture_trace["citation_verified"] is True


def test_rejection_limit_is_bounded_and_failure_remains_visible() -> None:
    episode, policy = _run(["wrong [999:1]"] * 3)
    assert len(policy.seen) == 5 and episode.termination is Termination.FINAL_ANSWER
    assert episode.architecture_trace["verify_rejections"] == 2
    assert episode.architecture_trace["verify_limit_reached"] is True
    assert episode.architecture_trace["citation_verified"] is False
    assert episode.architecture_trace["citation_checks"][-1]["unread"] == [[999, 1]]


def test_reusing_architecture_across_episodes_does_not_share_rejection_state() -> None:
    architecture = ReactVerifyArchitecture(max_rejections=1)
    for _ in range(2):
        episode, _ = _run(["wrong [999:1]", "answer [101:1]"], architecture=architecture)
        assert episode.architecture_trace["verify_rejections"] == 1
        assert episode.architecture_trace["citation_verified"] is True


def test_failed_read_details_cannot_validate_a_citation() -> None:
    class FailedRead(ReplayEnvironment):
        def execute(self, call):
            if call.name == "materials_read":
                return Observation(
                    call_id=call.call_id,
                    name=call.name,
                    ok=False,
                    payload={"error": "timeout"},
                    details={"read_pages": [[101, 1]]},
                )
            return super().execute(call)

    episode, _ = _run(["wrong [101:1]", "not found"], environment=FailedRead(SNAPSHOT))
    assert episode.architecture_trace["citation_checks"][0]["unread"] == [[101, 1]]
    assert episode.final_answer == "not found"


def test_rejected_final_on_last_turn_is_not_a_success() -> None:
    episode, _ = _run(["wrong [101:2]"], max_turns=3)
    assert episode.termination is Termination.MAX_TURNS and episode.final_answer is None
    assert episode.architecture_trace["citation_verified"] is False


def test_rejection_configuration_changes_contract_and_rejects_negative_limits() -> None:
    zero, _ = _run(["[101:1]"], architecture=ReactVerifyArchitecture(max_rejections=0))
    two, _ = _run(["[101:1]"], architecture=ReactVerifyArchitecture(max_rejections=2))
    assert zero.contract_hash != two.contract_hash
    with pytest.raises(ValueError, match="max_rejections"):
        ReactVerifyArchitecture(max_rejections=-1)


@pytest.mark.parametrize("backend", ["token", "openai"])
def test_citation_repair_through_real_policy_client_serialization(backend) -> None:
    from studyhub_agent.contracts.episode import Message

    spec = EpisodeSpec(
        episode_id="ep",
        task_id="t",
        user_message="q",
        principal=Principal(principal_id="u-1001"),
        tool_names=("materials_search", "materials_read"),
    )
    outputs = [
        Message(role="assistant", tool_calls=tool_turn(("materials_search", {"query": "提纲"})).tool_calls),
        Message(role="assistant", tool_calls=tool_turn(("materials_read", {"material_id": 101})).tool_calls),
        Message(role="assistant", content="wrong [101:2]"),
        Message(role="assistant", content="correct [101:1]"),
    ]
    tokenizer = CharTokenizer()
    if backend == "token":
        history = (Message(role="system", content="s"), Message(role="user", content="q"))
        texts = [
            canonical_completion_text(history, output, select_tools(spec.tool_names), thinking=False).removesuffix(
                "<|im_end|>\n"
            )
            for output in outputs
        ]
        policy = TokenPolicyClient(tokenizer, _SequencedBackend(texts))
    else:
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            output = outputs.pop(0)
            message = {"role": "assistant", "content": output.content}
            if output.tool_calls:
                message["tool_calls"] = [
                    {
                        "id": call.call_id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
                    }
                    for call in output.tool_calls
                ]
            return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "stop"}]})

        policy = OpenAICompatPolicyClient(
            "http://model.invalid",
            "test-model",
            tokenizer=tokenizer,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
    episode = RUNNER.run(spec, ReplayEnvironment(SNAPSHOT), policy, architecture=ReactVerifyArchitecture())
    assert episode.termination is Termination.FINAL_ANSWER and episode.final_answer == "correct [101:1]"
    assert len(episode.turns) == 4 and all(turn.canonical_token_ids for turn in episode.turns)
    assert episode.architecture_trace["citation_verified"] is True
    if backend == "openai":
        feedback = requests[-1]["messages"][-1]
        assert feedback["role"] == "user" and "citation_check_failed" in feedback["content"]
        assert "returned_material_ids" not in json.dumps(requests, ensure_ascii=False)
