import json

import httpx
import pytest

from studyhub_agent.architectures import CascadeArchitecture, PlanExecuteArchitecture, ReactContextArchitecture
from studyhub_agent.architectures.cascade import cascade_token_cost
from studyhub_agent.contracts.episode import Budget, Message, Termination
from studyhub_agent.contracts.prompts import DEFAULT_PROMPTS
from studyhub_agent.contracts.render import canonical_completion_text
from studyhub_agent.environments.replay import ReplayEnvironment
from studyhub_agent.runtime.openai_client import OpenAICompatPolicyClient
from studyhub_agent.runtime.runner import EpisodeRunner
from studyhub_agent.runtime.token_client import TokenPolicyClient
from studyhub_agent.runtime.tokenizer import token_counter
from studyhub_agent.tools.specs import select_tools
from tests.architectures.test_hooks import SNAPSHOT, _spec
from tests.runtime.fakes import CharTokenizer, tool_turn
from tests.runtime.test_runner import _SequencedBackend


def _policy(backend, outputs, tokenizer, requests):
    if backend == "token":
        history = (Message(role="system", content="s"), Message(role="user", content="q"))
        texts = [
            canonical_completion_text(history, output, select_tools(_spec().tool_names), thinking=False).removesuffix(
                "<|im_end|>\n"
            )
            for output in outputs
        ]
        return TokenPolicyClient(tokenizer, _SequencedBackend(texts))

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

    return OpenAICompatPolicyClient(
        "http://model.invalid",
        "test-model",
        tokenizer=tokenizer,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.parametrize("backend", ["token", "openai"])
@pytest.mark.parametrize("variant", ["plan_execute", "react_context", "cascade"])
def test_new_architectures_with_real_client_code_and_mocked_generation(backend, variant) -> None:
    tokenizer = CharTokenizer()
    requests = []
    outputs = [
        Message(role="assistant", tool_calls=tool_turn(("materials_search", {"query": "提纲"})).tool_calls),
        Message(role="assistant", tool_calls=tool_turn(("materials_read", {"material_id": 101})).tool_calls),
        Message(role="assistant", content="极限与导数 [101:1]"),
    ]
    if variant == "plan_execute":
        architecture = PlanExecuteArchitecture()
        outputs.insert(0, Message(role="assistant", content="1. 检索\n2. 阅读\n3. 回答"))
    elif variant == "react_context":
        architecture = ReactContextArchitecture(keep_recent_tools=0, context_threshold=0.1)
    else:
        architecture = CascadeArchitecture()
        outputs[-1] = Message(role="assistant", content="错误 [101:2]")
    materials = tuple(
        row.model_copy(update={"preview_pages": ("极限与导数" * 3000,)}) if row.material_id == 101 else row
        for row in SNAPSHOT.materials
    )
    snapshot = SNAPSHOT.model_copy(update={"materials": materials})
    spec = _spec(budget=Budget(max_context_tokens=100_000, max_new_tokens=100))
    counter = token_counter(tokenizer)
    runner = EpisodeRunner(prompts=DEFAULT_PROMPTS, tokenizer_revision="test", count_tokens=counter)
    policy = _policy(backend, outputs, tokenizer, requests)
    options = {}
    if variant == "cascade":
        large = _policy(backend, [Message(role="assistant", content="极限与导数 [101:1]")], tokenizer, requests)
        options = {
            "policies": {"small": policy, "large": large},
            "models": {"small": "4B", "large": "9B"},
            "model_revisions": {"small": "test", "large": "test"},
        }
    episode = runner.run(spec, ReplayEnvironment(snapshot), policy, architecture=architecture, **options)
    assert episode.final_answer == "极限与导数 [101:1]" and episode.termination is Termination.FINAL_ANSWER
    assert all(turn.prompt_token_ids and turn.canonical_token_ids for turn in episode.turns)
    assert len(episode.observations[-1].payload["text"]) == 15000
    if variant == "react_context":
        assert episode.architecture_trace["compactions"][-1]["after_tokens"] < 10_000
    if variant == "cascade":
        assert episode.turns[-1].policy_key == "large" and cascade_token_cost(episode) > 0
    if backend == "openai":
        encoded = json.dumps(requests, ensure_ascii=False)
        tool_payloads = [
            message for request in requests for message in request["messages"] if message["role"] == "tool"
        ]
        assert "read_pages" not in json.dumps(tool_payloads) and "returned_material_ids" not in encoded
        if variant == "plan_execute":
            assert "plan_reminder" in encoded
        if variant == "react_context":
            assert "context_compaction" in encoded
            recent_content = json.dumps(requests[-1], ensure_ascii=False)
            assert "极限与导数" * 100 not in recent_content
