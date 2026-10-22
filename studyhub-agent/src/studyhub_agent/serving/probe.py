from __future__ import annotations

import json
import os
import time

import httpx

from studyhub_agent.contracts.episode import Message, Sampling, TurnKind
from studyhub_agent.contracts.render import render_text
from studyhub_agent.contracts.tools import ToolSpec
from studyhub_agent.runtime.openai_client import OpenAICompatPolicyClient, _wire_messages
from studyhub_agent.runtime.tokenizer import HFTokenizer
from studyhub_agent.serving.config import ServingConfig


class ProbeError(RuntimeError):
    pass


def check_identity(client, config):
    health = client.get(config.base_url + "/health")
    health.raise_for_status()
    response = client.get(config.base_url + "/v1/models")
    response.raise_for_status()
    model = next((row for row in response.json()["data"] if row["id"] == config.served_model_name), None)
    if model is None:
        raise ProbeError("model_alias_mismatch")
    if model.get("max_model_len") is not None and model["max_model_len"] != config.max_model_len:
        raise ProbeError("model_context_mismatch")


def smoke(config: ServingConfig, *, client=None, tokenizer=None):
    headers = {"Authorization": f"Bearer {key}"} if (key := os.getenv(config.api_key_env)) else {}
    if client is None:
        with httpx.Client(timeout=120, trust_env=False, headers=headers) as owned:
            return smoke(config, client=owned, tokenizer=tokenizer)
    check_identity(client, config)
    tokenizer = tokenizer or HFTokenizer.from_model_dir(config.model_dir)
    tool = ToolSpec(
        name="studyhub_probe_add",
        version="1.0",
        description="只用于部署测试：返回两个整数相加的结果。",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "a": {"type": "integer", "description": "第一个整数"},
                "b": {"type": "integer", "description": "第二个整数"},
            },
            "required": ["a", "b"],
        },
    )
    messages = (
        Message(role="system", content="这是工具协议测试，必须执行工具，不能自行计算；工具返回后只输出结果数字。"),
        Message(role="user", content="调用 studyhub_probe_add，参数 a=17、b=26。收到结果后只回复数字。"),
    )

    def check_tokens(history, tools):
        response = client.post(
            config.base_url + "/tokenize",
            json={
                "model": config.served_model_name,
                "messages": _wire_messages(history),
                "tools": [row.to_openai() for row in tools] or None,
                "add_generation_prompt": True,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        response.raise_for_status()
        expected = tokenizer.encode(render_text(history, tools, thinking=False, add_generation_prompt=True))
        if response.json()["tokens"] != expected:
            raise ProbeError("server_tokenizer_or_template_mismatch")
        return len(expected)

    prompt_lengths = [check_tokens(messages, (tool,))]
    policy = OpenAICompatPolicyClient(
        config.base_url, config.served_model_name, client=client, tokenizer=tokenizer, api_key=key
    )
    started = time.perf_counter()
    first = policy.step(messages, (tool,), thinking=False, sampling=Sampling(seed=20261022), max_new_tokens=256)
    if (
        first.kind != TurnKind.TOOL_CALLS
        or len(first.tool_calls) != 1
        or first.dropped_reasoning
        or first.server_parse_mismatch
    ):
        raise ProbeError("tool_call_protocol_failed")
    call = first.tool_calls[0]
    if (
        call.name != tool.name
        or call.arguments != {"a": 17, "b": 26}
        or any(type(v) is not int for v in call.arguments.values())
    ):
        raise ProbeError("tool_arguments_failed")
    history = (
        *messages,
        Message(role="assistant", content=first.content, tool_calls=first.tool_calls),
        Message(
            role="tool",
            name=tool.name,
            tool_call_id=call.call_id,
            content=json.dumps({"result": call.arguments["a"] + call.arguments["b"]}, separators=(",", ":")),
        ),
        Message(role="tool", name="runtime_feedback", content='{"notice":"只输出工具返回的数字，不再调用工具"}'),
    )
    prompt_lengths.append(check_tokens(history, ()))
    final = policy.step(history, (), thinking=False, sampling=Sampling(seed=20261022), max_new_tokens=64)
    if final.kind != TurnKind.FINAL or final.content.strip() != "43" or final.dropped_reasoning:
        raise ProbeError("tool_result_followup_failed")
    try:
        metrics_available = client.get(config.base_url + "/metrics").status_code == 200
    except httpx.HTTPError:
        metrics_available = False
    return {
        "ok": True,
        "model": config.served_model_name,
        "base_url": config.base_url,
        "server_prompt_tokens_checked": prompt_lengths,
        "model_calls": 2,
        "tool_calls": 1,
        "roundtrip_seconds": time.perf_counter() - started,
        "metrics_available": metrics_available,
        "note": "这是部署协议验收，不是性能基准或训练用逐 Token 采样轨迹。",
    }
