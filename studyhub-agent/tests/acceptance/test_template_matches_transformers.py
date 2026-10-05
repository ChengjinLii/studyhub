import os
from pathlib import Path

import pytest

from studyhub_agent.contracts.episode import Message, ToolCall
from studyhub_agent.contracts.render import render_text
from studyhub_agent.tools.specs import TOOL_SPECS

MODEL_DIR = os.environ.get("STUDYHUB_AGENT_MODEL_DIR")
LARGE_MODEL_DIR = os.environ.get("STUDYHUB_AGENT_LARGE_MODEL_DIR")
pytestmark = pytest.mark.requires_model

CONVERSATIONS = [
    (Message(role="system", content="系统"), Message(role="user", content="找高数资料")),
    (
        Message(role="system", content="系统"),
        Message(role="user", content="找高数资料"),
        Message(
            role="assistant",
            content="检索中",
            tool_calls=(ToolCall(call_id="c", name="materials_search", arguments={"query": "高数\n期末", "limit": 3}),),
        ),
        Message(role="tool", tool_call_id="c", name="materials_search", content='{"results":[]}'),
    ),
    (
        Message(role="system", content="系统"),
        Message(role="user", content="找高数资料"),
        Message(role="assistant", content="未读页引用 [101:2]"),
        Message(role="tool", name="runtime_feedback", content='{"notice":"citation_check_failed","unread":[[101,2]]}'),
    ),
    (
        Message(role="system", content="系统"),
        Message(role="user", content="查找提纲"),
        Message(role="tool", name="runtime_feedback", content='{"notice":"plan_request","instruction":"先写计划"}'),
        Message(role="assistant", content="1. 检索\n2. 阅读\n3. 引用回答"),
        Message(role="tool", name="runtime_feedback", content='{"notice":"execute_plan","instruction":"执行计划"}'),
        Message(role="tool", name="runtime_feedback", content='{"notice":"plan_reminder","plan":"1. 检索"}'),
    ),
    (
        Message(role="system", content="系统"),
        Message(role="user", content="查找提纲"),
        Message(
            role="assistant",
            tool_calls=(ToolCall(call_id="c", name="materials_read", arguments={"material_id": 101, "page": 1}),),
        ),
        Message(
            role="tool",
            tool_call_id="c",
            name="materials_read",
            content='{"compacted":true,"result":{"material_id":101,"page":1,"text":"摘要","citation":"[101:1]"}}',
        ),
        Message(
            role="tool", name="runtime_feedback", content='{"notice":"context_compaction","instruction":"正文已压缩"}'
        ),
    ),
]


@pytest.mark.parametrize(
    "model_dir",
    [
        pytest.param(MODEL_DIR, id="4b", marks=pytest.mark.skipif(not MODEL_DIR, reason="4B tokenizer path not set")),
        pytest.param(
            LARGE_MODEL_DIR,
            id="9b",
            marks=pytest.mark.skipif(not LARGE_MODEL_DIR, reason="9B tokenizer path not set"),
        ),
    ],
)
@pytest.mark.parametrize("thinking", [False, True])
@pytest.mark.parametrize("conversation", CONVERSATIONS)
def test_render_matches_transformers_apply_chat_template(conversation, thinking, model_dir) -> None:
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(Path(model_dir), local_files_only=True)
    wire = []
    for message in conversation:
        item = {"role": message.role, "content": message.content}
        if message.tool_calls:
            item["tool_calls"] = [
                {"type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in message.tool_calls
            ]
        wire.append(item)
    expected = tokenizer.apply_chat_template(
        wire,
        tools=[t.to_openai() for t in TOOL_SPECS],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=thinking,
    )
    assert render_text(conversation, TOOL_SPECS, thinking=thinking, add_generation_prompt=True) == expected
