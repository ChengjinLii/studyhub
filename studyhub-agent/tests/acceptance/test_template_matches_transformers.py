import os
from pathlib import Path

import pytest

from studyhub_agent.contracts.episode import Message, ToolCall
from studyhub_agent.contracts.render import render_text
from studyhub_agent.tools.specs import TOOL_SPECS

MODEL_DIR = os.environ.get("STUDYHUB_AGENT_MODEL_DIR")
pytestmark = [pytest.mark.requires_model, pytest.mark.skipif(not MODEL_DIR, reason="STUDYHUB_AGENT_MODEL_DIR not set")]

CONVERSATIONS = [
    (Message(role="system", content="系统"), Message(role="user", content="找高数资料")),
    (
        Message(role="system", content="系统"),
        Message(role="user", content="找高数资料"),
        Message(role="assistant", content="检索中", tool_calls=(ToolCall(call_id="c", name="materials_search", arguments={"query": "高数\n期末", "limit": 3}),)),
        Message(role="tool", tool_call_id="c", name="materials_search", content='{"results":[]}'),
    ),
]


@pytest.mark.parametrize("thinking", [False, True])
@pytest.mark.parametrize("conversation", CONVERSATIONS)
def test_render_matches_transformers_apply_chat_template(conversation, thinking) -> None:
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(Path(MODEL_DIR))
    wire = []
    for message in conversation:
        item = {"role": message.role, "content": message.content}
        if message.tool_calls:
            item["tool_calls"] = [{"type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in message.tool_calls]
        wire.append(item)
    expected = tokenizer.apply_chat_template(
        wire, tools=[t.to_openai() for t in TOOL_SPECS], tokenize=False, add_generation_prompt=True, enable_thinking=thinking
    )
    assert render_text(conversation, TOOL_SPECS, thinking=thinking, add_generation_prompt=True) == expected
