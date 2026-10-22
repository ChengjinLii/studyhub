import json

import pytest

from studyhub_agent.contracts.episode import Message, ToolCall
from studyhub_agent.contracts.render import _template, render_text
from studyhub_agent.runtime.openai_client import _wire_messages


@pytest.mark.parametrize(
    "ids",
    [(None,), (None, None), ("call_0", None), (None, "call_0"), ("call_0", None, "call_1", None), ("call_0", "call_1")],
)
def test_adjacent_tool_feedback_preserves_pinned_template_and_real_call_ids(ids):
    history = (
        Message(role="system", content="system"),
        Message(role="user", content="user"),
        Message(
            role="assistant",
            tool_calls=tuple(ToolCall(call_id=call_id, name="add", arguments={"a": 17}) for call_id in ids if call_id),
            content="" if any(ids) else "bad-tool-call",
        ),
        *(Message(role="tool", tool_call_id=call_id, content=f" 结果-{index} \n") for index, call_id in enumerate(ids)),
    )
    wires = _wire_messages(history)
    assert [row["tool_call_id"] for row in wires if row["role"] == "tool"] == [value for value in ids if value]
    for row in wires:
        for call in row.get("tool_calls", []):
            call["function"]["arguments"] = json.loads(call["function"]["arguments"])
    expected = render_text(history, (), thinking=False, add_generation_prompt=True)
    actual = _template().render(messages=wires, tools=None, enable_thinking=False, add_generation_prompt=True)
    assert actual == expected
