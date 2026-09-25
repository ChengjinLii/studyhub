import json
from collections.abc import Sequence

import httpx
import pytest

from studyhub_agent.contracts.episode import Message, Sampling, ToolCall, TurnKind
from studyhub_agent.contracts.render import canonical_completion_text
from studyhub_agent.runtime.openai_client import OpenAICompatPolicyClient
from studyhub_agent.runtime.policy import PolicyInfraError
from studyhub_agent.runtime.token_client import Generation, SGLangGenerateBackend, TokenPolicyClient
from studyhub_agent.tools.specs import select_tools

TOOLS = select_tools(["materials_search", "materials_read"])
HISTORY = (Message(role="system", content="系统"), Message(role="user", content="找线性代数笔记"))
CALL = ToolCall(call_id="call_0", name="materials_search", arguments={"query": "线性代数 笔记", "limit": 3})
ASSISTANT = Message(role="assistant", content="我先检索。", tool_calls=(CALL,))
CANONICAL = canonical_completion_text(HISTORY, ASSISTANT, TOOLS, thinking=False)


class CharTokenizer:
    stop_token_ids: tuple[int, ...] = ()

    def encode(self, text: str) -> list[int]:
        return [ord(ch) for ch in text]

    def decode(self, ids: Sequence[int]) -> str:
        return "".join(chr(i) for i in ids)


class CannedBackend:
    def __init__(self, text: str) -> None:
        self.text = text
        self.last_input: list[int] = []

    def generate(self, input_ids, *, sampling, max_new_tokens, stop_token_ids) -> Generation:
        self.last_input = list(input_ids)
        ids = tuple(ord(ch) for ch in self.text)
        return Generation(output_ids=ids, logprobs=tuple(-0.1 for _ in ids), finish_reason="stop")


def _openai_transport(message: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"][0]["function"]["name"] == "materials_search"
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "tool_calls"}]})

    return httpx.MockTransport(handler)


def test_token_and_openai_clients_produce_identical_canonical_completion() -> None:
    generated = CANONICAL.removesuffix("<|im_end|>\n")
    token_client = TokenPolicyClient(CharTokenizer(), CannedBackend(generated))
    token_turn = token_client.step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=256)

    openai_message = {
        "role": "assistant",
        "content": "我先检索。",
        "tool_calls": [
            {
                "id": "x",
                "type": "function",
                "function": {
                    "name": "materials_search",
                    "arguments": json.dumps({"limit": 3, "query": "线性代数 笔记"}, ensure_ascii=False),
                },
            }
        ],
    }
    openai_client = OpenAICompatPolicyClient(
        "http://teacher",
        "qwen",
        tokenizer=CharTokenizer(),
        client=httpx.Client(transport=_openai_transport(openai_message)),
    )
    openai_turn = openai_client.step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=256)

    assert token_turn.kind is openai_turn.kind is TurnKind.TOOL_CALLS
    assert token_turn.tool_calls == openai_turn.tool_calls
    assert token_turn.canonical_text == openai_turn.canonical_text == CANONICAL
    assert openai_turn.completion_token_ids == tuple(ord(ch) for ch in CANONICAL)
    assert token_turn.non_canonical is False and openai_turn.server_parse_mismatch is False


def test_token_client_sends_rendered_prompt_and_keeps_logprobs() -> None:
    backend = CannedBackend("好的，答案是 A。")
    turn = TokenPolicyClient(CharTokenizer(), backend).step(
        HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=64
    )
    assert "".join(chr(i) for i in backend.last_input).endswith("<think>\n\n</think>\n\n")
    assert turn.kind is TurnKind.FINAL and len(turn.completion_logprobs) == len(turn.completion_token_ids)
    assert turn.prompt_token_ids == tuple(backend.last_input)


def test_token_client_flags_non_canonical_whitespace() -> None:
    turn = TokenPolicyClient(CharTokenizer(), CannedBackend("答案。   ")).step(
        HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=64
    )
    assert turn.kind is TurnKind.FINAL and turn.non_canonical is True


def test_openai_invalid_arguments_become_parse_error() -> None:
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "x", "type": "function", "function": {"name": "materials_search", "arguments": "{not json"}}
        ],
    }
    client = OpenAICompatPolicyClient("http://t", "m", client=httpx.Client(transport=_openai_transport(message)))
    turn = client.step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=64)
    assert turn.kind is TurnKind.PARSE_ERROR and turn.parse_error.startswith("invalid_arguments_json")


def test_openai_mixed_answer_and_tool_call_is_a_tool_turn_with_preamble() -> None:
    message = {
        "role": "assistant",
        "content": "答案是 A",
        "tool_calls": [
            {"id": "x", "type": "function", "function": {"name": "materials_search", "arguments": '{"query": "a"}'}}
        ],
    }
    client = OpenAICompatPolicyClient("http://t", "m", client=httpx.Client(transport=_openai_transport(message)))
    turn = client.step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=64)
    assert turn.kind is TurnKind.TOOL_CALLS and turn.content == "答案是 A"


def test_http_failures_raise_policy_infra_error() -> None:
    failing = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503, text="overloaded")))
    with pytest.raises(PolicyInfraError):
        OpenAICompatPolicyClient("http://t", "m", client=failing).step(
            HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=8
        )
    backend = SGLangGenerateBackend("http://sglang", client=failing)
    with pytest.raises(PolicyInfraError):
        backend.generate([1, 2], sampling=Sampling(), max_new_tokens=8, stop_token_ids=())


def test_sglang_backend_request_and_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["input_ids"] == [5, 6]
        assert body["sampling_params"]["max_new_tokens"] == 8
        assert body["return_logprob"] is True
        meta_info = {
            "output_token_logprobs": [[-0.5, 97, "a"], [-0.25, 98, "b"]],
            "finish_reason": {"type": "stop"},
        }
        return httpx.Response(200, json={"text": "ab", "meta_info": meta_info})

    backend = SGLangGenerateBackend("http://sglang", client=httpx.Client(transport=httpx.MockTransport(handler)))
    generation = backend.generate([5, 6], sampling=Sampling(), max_new_tokens=8, stop_token_ids=(151645,))
    assert generation == Generation(output_ids=(97, 98), logprobs=(-0.5, -0.25), finish_reason="stop")
