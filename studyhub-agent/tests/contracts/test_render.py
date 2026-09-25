import pytest

from studyhub_agent.contracts.episode import Message, ToolCall, TurnKind
from studyhub_agent.contracts.render import (
    RenderError,
    canonical_completion_text,
    parse_completion,
    render_text,
)
from studyhub_agent.contracts.tools import ToolSpec

SEARCH = ToolSpec(
    name="materials_search",
    version="1.0",
    description="检索资料",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "关键词"},
            "limit": {"type": "integer", "description": "条数"},
            "filters": {"type": "object", "description": "过滤条件"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)
TOOLS = (SEARCH,)
HISTORY = (
    Message(role="system", content="系统提示"),
    Message(role="user", content="找高数资料"),
)


def test_generation_prompt_disables_thinking_with_empty_block() -> None:
    text = render_text(HISTORY, TOOLS, thinking=False, add_generation_prompt=True)
    assert text.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    assert '"name": "materials_search"' in text


def test_generation_prompt_with_thinking_opens_block() -> None:
    text = render_text(HISTORY, TOOLS, thinking=True, add_generation_prompt=True)
    assert text.endswith("<|im_start|>assistant\n<think>\n")


def test_parse_final_answer() -> None:
    parsed = parse_completion("这是答案。", TOOLS, thinking=False)
    assert parsed.kind is TurnKind.FINAL
    assert parsed.content == "这是答案。"


def test_parse_tool_call_with_preamble() -> None:
    text = (
        "先检索一下。\n\n<tool_call>\n<function=materials_search>\n<parameter=query>\n"
        "高等数学 期末\n</parameter>\n<parameter=limit>\n5\n</parameter>\n</function>\n</tool_call>"
    )
    parsed = parse_completion(text, TOOLS, thinking=False)
    assert parsed.kind is TurnKind.TOOL_CALLS
    assert parsed.content == "先检索一下。"
    assert parsed.tool_calls == (
        ToolCall(call_id="call_0", name="materials_search", arguments={"query": "高等数学 期末", "limit": 5}),
    )


def test_parse_multiline_chinese_value_round_trips() -> None:
    call = ToolCall(
        call_id="call_0",
        name="materials_search",
        arguments={"query": "线性代数\n第二章 习题", "filters": {"school": "电子科技大学"}},
    )
    assistant = Message(role="assistant", content="", tool_calls=(call,))
    completion = canonical_completion_text(HISTORY, assistant, TOOLS, thinking=False)
    assert completion.endswith("<|im_end|>\n")
    parsed = parse_completion(completion, TOOLS, thinking=False)
    assert parsed.tool_calls == (call,)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("101", 101), (" 7 ", 7)],
)
def test_integer_parameter_coercion(raw, expected) -> None:
    text = (
        "<tool_call>\n<function=materials_search>\n<parameter=query>\nq\n</parameter>\n<parameter=limit>\n"
        f"{raw}"
        "\n</parameter>\n</function>\n</tool_call>"
    )
    assert parse_completion(text, TOOLS, thinking=False).tool_calls[0].arguments["limit"] == expected


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (
            "<tool_call>\n<function=materials_search>\n<parameter=query>\nq\n</parameter>\n<parameter=limit>\n"
            "abc\n</parameter>\n</function>\n</tool_call>",
            "invalid_argument",
        ),
        (
            "<tool_call>\n<function=materials_search>\n<parameter=limit>\n3\n</parameter>\n</function>\n</tool_call>",
            "missing_required",
        ),
        ("<tool_call>\n<function=unknown_tool>\n</function>\n</tool_call>", "unknown_tool"),
        (
            "<tool_call>\n<function=materials_search>\n<parameter=query>\nq\n</parameter>\n</function>\n</tool_call>\n"
            "答案在此",
            "text_after_tool_call",
        ),
        ("<tool_call>\n<function=materials_search>\n<parameter=query>\nq\n", "malformed_tool_call"),
        (
            "<tool_call>\n<function=materials_search>\n<parameter=bogus>\nq\n</parameter>\n</function>\n</tool_call>",
            "unknown_parameter",
        ),
        ("   ", "empty_response"),
    ],
)
def test_parse_errors_are_reported_not_raised(text, error) -> None:
    parsed = parse_completion(text, TOOLS, thinking=False)
    assert parsed.kind is TurnKind.PARSE_ERROR
    assert parsed.error is not None and parsed.error.startswith(error)
    assert parsed.tool_calls == ()


def test_value_containing_parameter_close_tag_is_rejected_by_renderer() -> None:
    call = ToolCall(call_id="c", name="materials_search", arguments={"query": "x</parameter>y"})
    with pytest.raises(RenderError):
        canonical_completion_text(HISTORY, Message(role="assistant", tool_calls=(call,)), TOOLS, thinking=False)


def test_prefix_property_holds_for_tool_turns() -> None:
    call = ToolCall(call_id="c", name="materials_search", arguments={"query": "概率论"})
    assistant = Message(role="assistant", content="检索中", tool_calls=(call,))
    prompt = render_text(HISTORY, TOOLS, thinking=False, add_generation_prompt=True)
    full = render_text((*HISTORY, assistant), TOOLS, thinking=False, add_generation_prompt=False)
    assert full == prompt + canonical_completion_text(HISTORY, assistant, TOOLS, thinking=False)


def test_canonical_argument_order_follows_schema() -> None:
    reordered = ToolCall(call_id="c", name="materials_search", arguments={"limit": 3, "query": "概率论"})
    in_order = ToolCall(call_id="c", name="materials_search", arguments={"query": "概率论", "limit": 3})
    first = canonical_completion_text(
        HISTORY, Message(role="assistant", tool_calls=(reordered,)), TOOLS, thinking=False
    )
    second = canonical_completion_text(
        HISTORY, Message(role="assistant", tool_calls=(in_order,)), TOOLS, thinking=False
    )
    assert first == second
    assert first.index("<parameter=query>") < first.index("<parameter=limit>")


def test_thinking_completion_splits_reasoning() -> None:
    parsed = parse_completion("先想想\n</think>\n\n最终答案", TOOLS, thinking=True)
    assert parsed.kind is TurnKind.FINAL
    assert parsed.content == "最终答案"


def test_trailing_end_of_turn_token_is_ignored() -> None:
    assert parse_completion("答案<|im_end|>", TOOLS, thinking=False).content == "答案"
