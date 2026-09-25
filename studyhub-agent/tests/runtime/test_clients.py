import json

import httpx
import pytest

from studyhub_agent.contracts.episode import Message, Sampling, ToolCall, TurnKind
from studyhub_agent.contracts.render import canonical_completion_text
from studyhub_agent.runtime.openai_client import OpenAICompatPolicyClient, _wire_message
from studyhub_agent.runtime.policy import PolicyInfraError
from studyhub_agent.runtime.token_client import Generation, SGLangGenerateBackend, TokenPolicyClient
from studyhub_agent.tools.specs import select_tools
from tests.runtime.fakes import CharTokenizer

TOOLS = select_tools(["materials_search", "materials_read"])
HISTORY = (Message(role="system", content="系统"), Message(role="user", content="找线性代数笔记"))
CALL = ToolCall(call_id="call_0", name="materials_search", arguments={"query": "线性代数 笔记", "limit": 3})
ASSISTANT = Message(role="assistant", content="我先检索。", tool_calls=(CALL,))
CANONICAL = canonical_completion_text(HISTORY, ASSISTANT, TOOLS, thinking=False)
ASSISTANT_THINKING = Message(role="assistant", content="我先检索。", tool_calls=(CALL,), reasoning="推理一下")
CANONICAL_THINKING = canonical_completion_text(HISTORY, ASSISTANT_THINKING, TOOLS, thinking=True)


class CannedBackend:
    def __init__(self, text: str, *, finish_reason: str = "stop") -> None:
        self.text = text
        self.finish_reason = finish_reason
        self.last_input: list[int] = []

    def generate(self, input_ids, *, sampling, max_new_tokens, stop_token_ids) -> Generation:
        self.last_input = list(input_ids)
        ids = tuple(ord(ch) for ch in self.text)
        return Generation(output_ids=ids, logprobs=tuple(-0.1 for _ in ids), finish_reason=self.finish_reason)


def _openai_transport(
    message: dict, *, thinking: bool = False, finish_reason: str = "tool_calls"
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"][0]["function"]["name"] == "materials_search"
        assert body["chat_template_kwargs"] == {"enable_thinking": thinking}
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": finish_reason}]})

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
    assert token_turn.canonical_token_ids == openai_turn.canonical_token_ids == tuple(ord(ch) for ch in CANONICAL)
    # sampled_token_ids is the token client's literal sampled ids; the OpenAI client never gets
    # token-level sampling info, so it stays empty.
    assert token_turn.sampled_token_ids == tuple(ord(ch) for ch in generated)
    assert openai_turn.sampled_token_ids == ()
    assert token_turn.non_canonical is False and openai_turn.server_parse_mismatch is False


def test_token_and_openai_clients_produce_identical_canonical_completion_with_thinking() -> None:
    generated = CANONICAL_THINKING.removesuffix("<|im_end|>\n")
    token_client = TokenPolicyClient(CharTokenizer(), CannedBackend(generated))
    token_turn = token_client.step(HISTORY, TOOLS, thinking=True, sampling=Sampling(), max_new_tokens=256)

    openai_message = {
        "role": "assistant",
        "content": "我先检索。",
        "reasoning_content": "推理一下",
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
        client=httpx.Client(transport=_openai_transport(openai_message, thinking=True)),
    )
    openai_turn = openai_client.step(HISTORY, TOOLS, thinking=True, sampling=Sampling(), max_new_tokens=256)

    assert token_turn.kind is openai_turn.kind is TurnKind.TOOL_CALLS
    assert token_turn.tool_calls == openai_turn.tool_calls
    assert token_turn.canonical_text == openai_turn.canonical_text == CANONICAL_THINKING
    assert token_turn.reasoning == openai_turn.reasoning == "推理一下"
    assert openai_turn.dropped_reasoning is False
    assert token_turn.non_canonical is False and openai_turn.server_parse_mismatch is False


def test_token_client_sends_rendered_prompt_and_keeps_logprobs() -> None:
    backend = CannedBackend("好的，答案是 A。")
    turn = TokenPolicyClient(CharTokenizer(), backend).step(
        HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=64
    )
    assert "".join(chr(i) for i in backend.last_input).endswith("<think>\n\n</think>\n\n")
    assert turn.kind is TurnKind.FINAL and len(turn.completion_logprobs) == len(turn.sampled_token_ids)
    assert turn.prompt_token_ids == tuple(backend.last_input)


def test_token_client_trims_raw_text_at_endoftext_stop_token() -> None:
    # <|endoftext|> is a valid stop token alongside <|im_end|>; text generated after it must not
    # leak into the turn.
    turn = TokenPolicyClient(CharTokenizer(), CannedBackend("答案是 A<|endoftext|>junk")).step(
        HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=64
    )
    assert turn.kind is TurnKind.FINAL
    assert turn.raw_text == "答案是 A"


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


def test_openai_drops_reasoning_when_thinking_is_false() -> None:
    # A server can return reasoning_content even when the caller asked for enable_thinking=False
    # (e.g. a misconfigured or non-compliant server). Rendering it anyway would inject a
    # reasoning_content field the chat template was never asked to produce. Drop it instead, and
    # flag that it happened.
    message = {"role": "assistant", "content": "答案是 A", "reasoning_content": "不应该出现"}
    client = OpenAICompatPolicyClient("http://t", "m", client=httpx.Client(transport=_openai_transport(message)))
    turn = client.step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=64)
    assert turn.kind is TurnKind.FINAL
    assert turn.reasoning == ""
    assert turn.dropped_reasoning is True
    assert "不应该出现" not in turn.canonical_text


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


def test_sglang_backend_missing_logprobs_raise_policy_infra_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "a", "meta_info": {"finish_reason": {"type": "stop"}}})

    backend = SGLangGenerateBackend("http://sglang", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(PolicyInfraError):
        backend.generate([1], sampling=Sampling(), max_new_tokens=4, stop_token_ids=())


def test_sglang_backend_null_logprobs_raise_policy_infra_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        meta_info = {"output_token_logprobs": None, "finish_reason": {"type": "stop"}}
        return httpx.Response(200, json={"text": "a", "meta_info": meta_info})

    backend = SGLangGenerateBackend("http://sglang", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(PolicyInfraError):
        backend.generate([1], sampling=Sampling(), max_new_tokens=4, stop_token_ids=())


def test_sglang_backend_malformed_logprob_entries_raise_policy_infra_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Each entry should be [logprob, token_id, token_str]; this one is missing the token id.
        meta_info = {"output_token_logprobs": [[-0.5]], "finish_reason": {"type": "stop"}}
        return httpx.Response(200, json={"text": "a", "meta_info": meta_info})

    backend = SGLangGenerateBackend("http://sglang", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(PolicyInfraError):
        backend.generate([1], sampling=Sampling(), max_new_tokens=4, stop_token_ids=())


def test_sglang_backend_abort_finish_reason_raises_policy_infra_error() -> None:
    # "abort" means the request was cancelled/aborted at the infra level (e.g. server shutdown,
    # request cancellation) -- it is not a model output at all, so it must never reach the parser.
    def handler(request: httpx.Request) -> httpx.Response:
        meta_info = {"output_token_logprobs": [[-0.1, 97, "a"]], "finish_reason": {"type": "abort"}}
        return httpx.Response(200, json={"text": "a", "meta_info": meta_info})

    backend = SGLangGenerateBackend("http://sglang", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(PolicyInfraError):
        backend.generate([1], sampling=Sampling(), max_new_tokens=4, stop_token_ids=())


def test_token_client_finish_reason_length_becomes_truncated_parse_error() -> None:
    # A truncated completion must never be treated as a valid FINAL/TOOL_CALLS turn -- it would
    # otherwise silently become bad SFT data (a cut-off "final answer" or a cut-off tool call).
    turn = TokenPolicyClient(CharTokenizer(), CannedBackend("这是一个被截断的答", finish_reason="length")).step(
        HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=8
    )
    assert turn.kind is TurnKind.PARSE_ERROR
    assert turn.parse_error == "truncated"


def test_openai_finish_reason_length_becomes_truncated_parse_error() -> None:
    message = {"role": "assistant", "content": "这是一个被截断的答"}
    client = OpenAICompatPolicyClient(
        "http://t", "m", client=httpx.Client(transport=_openai_transport(message, finish_reason="length"))
    )
    turn = client.step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=8)
    assert turn.kind is TurnKind.PARSE_ERROR
    assert turn.parse_error == "truncated"


def test_wire_message_sends_tool_result_with_its_real_call_id() -> None:
    tool_message = Message(role="tool", tool_call_id="call_0", name="materials_search", content='{"ok": true}')
    assert _wire_message(tool_message) == {"role": "tool", "content": '{"ok": true}', "tool_call_id": "call_0"}


def test_wire_message_sends_runtime_feedback_without_call_id_as_user_tool_response() -> None:
    feedback = Message(role="tool", name="runtime_feedback", content='{"error": "malformed_tool_call"}')
    assert _wire_message(feedback) == {
        "role": "user",
        "content": '<tool_response>\n{"error": "malformed_tool_call"}\n</tool_response>',
    }


def test_openai_parse_error_raw_text_is_content_and_tool_calls_not_envelope() -> None:
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "x", "type": "function", "function": {"name": "materials_search", "arguments": "{not json"}}
        ],
    }
    client = OpenAICompatPolicyClient("http://t", "m", client=httpx.Client(transport=_openai_transport(message)))
    turn = client.step(HISTORY, TOOLS, thinking=False, sampling=Sampling(), max_new_tokens=64)
    assert turn.kind is TurnKind.PARSE_ERROR
    expected_tool_calls_json = json.dumps(message["tool_calls"], ensure_ascii=False)
    assert turn.raw_text == "\n" + expected_tool_calls_json
    assert "choices" not in turn.raw_text and '"role"' not in turn.raw_text
