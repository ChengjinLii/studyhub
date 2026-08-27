from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

from studyhub_agent.benchmark_v1.tool_contracts import tool_schemas

SCHEMA_VERSION = "studyhub.runtime-sft-trajectory.v3"
QUALITY_TIERS = {
    "expert_action_synthetic_observation",
    "expert_action_only",
    "expert_complete",
    "oracle_derived_expert_complete",
    "deterministic_fixture_complete",
}

_TOOL_CALL_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_FUNCTION_BLOCK = re.compile(r"<function=([^>]+)>\s*(.*?)\s*</function>", re.DOTALL)
_PARAMETER_BLOCK = re.compile(r"<parameter=([^>]+)>\s*(.*?)\s*</parameter>", re.DOTALL)
_TOOL_RESPONSE_BLOCK = re.compile(r"<tool_response>\s*(.*?)\s*</tool_response>", re.DOTALL)
_TOOLS_BLOCK = re.compile(r"<tools>\s*(.*?)\s*</tools>", re.DOTALL)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: str, *, salt: str = "studyhub-runtime-sft-v3") -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def openai_tools(names: Iterable[str]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": row} for row in tool_schemas(tuple(names))]


def assistant_tool_call(
    name: str,
    arguments: Mapping[str, Any],
    *,
    call_id: str,
    content: str = "",
) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": dict(arguments)},
            }
        ],
    }


def assistant_tool_calls(
    calls: Iterable[tuple[str, Mapping[str, Any], str]],
    *,
    content: str = "",
) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": dict(arguments)},
            }
            for name, arguments, call_id in calls
        ],
    }


def tool_observation(
    name: str,
    payload: Any,
    *,
    call_id: str,
) -> dict[str, Any]:
    content = payload if isinstance(payload, str) else canonical_json(payload)
    return {
        "role": "tool",
        "name": name,
        "tool_call_id": call_id,
        "content": content,
    }


def _coerce_argument(value: str) -> Any:
    text = value.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def parse_tool_calls(value: str) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    for block in _TOOL_CALL_BLOCK.findall(value):
        function = _FUNCTION_BLOCK.search(block)
        if function:
            name = function.group(1).strip()
            arguments = {
                parameter.strip(): _coerce_argument(argument)
                for parameter, argument in _PARAMETER_BLOCK.findall(function.group(2))
            }
            calls.append((name, arguments))
            continue
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or not payload.get("name"):
            continue
        arguments = payload.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if isinstance(arguments, dict):
            calls.append((str(payload["name"]), arguments))
    return calls


def strip_tool_calls(value: str) -> str:
    return _TOOL_CALL_BLOCK.sub("", value).strip()


def parse_tool_responses(value: str) -> list[dict[str, Any]]:
    responses = []
    for block in _TOOL_RESPONSE_BLOCK.findall(value):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            responses.append({"content": block.strip()})
            continue
        if isinstance(payload, dict) and "content" in payload:
            responses.append({"name": payload.get("name"), "content": payload["content"]})
        else:
            responses.append({"content": payload})
    if not responses and value.strip():
        responses.append({"content": value.strip()})
    return responses


def tools_from_system(value: str) -> list[dict[str, Any]]:
    for block in _TOOLS_BLOCK.findall(value):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, list):
            continue
        tools = [row for row in payload if isinstance(row, dict)]
        if tools:
            return tools
    return []


def strip_legacy_tool_contract(value: str) -> str:
    text = _TOOLS_BLOCK.sub("", value)
    marker = "For each function call return a json object"
    if marker in text:
        text = text.split(marker, 1)[0]
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def normalize_legacy_conversation(
    conversations: Iterable[Mapping[str, Any]],
    *,
    role_map: Mapping[str, str],
    id_salt: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw = list(conversations)
    system_text = next(
        (str(row.get("value", "")) for row in raw if role_map.get(str(row.get("from"))) == "system"),
        "",
    )
    tools = tools_from_system(system_text)
    messages: list[dict[str, Any]] = []
    pending: list[tuple[str, str]] = []
    call_index = 0
    for row in raw:
        role = role_map.get(str(row.get("from")))
        if role is None:
            continue
        content = str(row.get("value", "")).strip()
        if role == "system":
            cleaned = strip_legacy_tool_contract(content)
            if cleaned:
                messages.append({"role": "system", "content": cleaned})
            continue
        if role == "assistant":
            calls = parse_tool_calls(content)
            if not calls:
                if content:
                    messages.append({"role": "assistant", "content": content})
                continue
            normalized_calls = []
            for name, arguments in calls:
                call_id = f"call_{stable_hash(f'{id_salt}:{call_index}:{name}')[:20]}"
                call_index += 1
                normalized_calls.append((name, arguments, call_id))
                pending.append((name, call_id))
            messages.append(assistant_tool_calls(normalized_calls, content=strip_tool_calls(content)))
            continue
        if role == "tool":
            for response in parse_tool_responses(content):
                response_name = str(response.get("name") or "")
                match_index = next(
                    (index for index, (name, _call_id) in enumerate(pending) if name == response_name),
                    0 if pending else -1,
                )
                if match_index < 0:
                    continue
                name, call_id = pending.pop(match_index)
                messages.append(tool_observation(name, response.get("content"), call_id=call_id))
            continue
        if content:
            messages.append({"role": role, "content": content})
    return messages, tools


def trajectory_fingerprint(record: Mapping[str, Any]) -> str:
    messages = deepcopy(record.get("messages", []))
    call_ids: dict[str, str] = {}
    next_call = 0
    for message in messages:
        for call in message.get("tool_calls", []):
            original = str(call.get("id", ""))
            if original not in call_ids:
                call_ids[original] = f"call_{next_call}"
                next_call += 1
            call["id"] = call_ids[original]
        if message.get("tool_call_id") is not None:
            original = str(message["tool_call_id"])
            message["tool_call_id"] = call_ids.get(original, original)
    visible = {
        "tools": record.get("tools", []),
        "messages": messages,
    }
    return hashlib.sha256(canonical_json(visible).encode()).hexdigest()


def validate_runtime_trajectory(record: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        failures.append("schema_version")
    if record.get("quality_tier") not in QUALITY_TIERS:
        failures.append("quality_tier")
    messages = record.get("messages")
    tools = record.get("tools")
    if not isinstance(messages, list) or not messages:
        return failures + ["messages"]
    if not isinstance(tools, list):
        failures.append("tools")
        tools = []
    allowed = {
        str(row.get("function", {}).get("name"))
        for row in tools
        if isinstance(row, dict) and isinstance(row.get("function"), dict)
    }
    pending: dict[str, str] = {}
    observed: set[str] = set()
    assistant_actions = 0
    final_assistant = False
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            failures.append(f"message:{index}:type")
            continue
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            failures.append(f"message:{index}:role")
            continue
        calls = message.get("tool_calls", [])
        if role == "assistant" and calls:
            assistant_actions += 1
            for call in calls:
                function = call.get("function", {}) if isinstance(call, dict) else {}
                name = str(function.get("name", ""))
                arguments = function.get("arguments")
                call_id = str(call.get("id", "")) if isinstance(call, dict) else ""
                if not name or name not in allowed:
                    failures.append(f"message:{index}:unknown_tool:{name}")
                if not isinstance(arguments, dict):
                    failures.append(f"message:{index}:arguments")
                if not call_id or call_id in pending:
                    failures.append(f"message:{index}:call_id")
                else:
                    pending[call_id] = name
        elif role == "assistant" and str(message.get("content", "")).strip():
            final_assistant = index == len(messages) - 1
        elif role == "tool":
            call_id = str(message.get("tool_call_id", ""))
            if call_id not in pending:
                failures.append(f"message:{index}:orphan_observation")
            else:
                if message.get("name") and str(message["name"]) != pending[call_id]:
                    failures.append(f"message:{index}:tool_name_mismatch")
                observed.add(call_id)
        elif role == "system" and index != 0:
            failures.append(f"message:{index}:system_position")
    if record.get("trajectory_status") == "complete":
        if not final_assistant:
            failures.append("final_assistant")
        if pending.keys() - observed:
            failures.append("missing_observation")
    runtime_native = bool(assistant_actions and observed and final_assistant)
    if bool(record.get("runtime_native")) != runtime_native:
        failures.append("runtime_native_flag")
    return failures


def make_record(
    *,
    record_id: str,
    group_id: str,
    source_dataset: str,
    source_id: str,
    task_family: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    provenance: Mapping[str, Any],
    capability_tags: Iterable[str],
    quality_tier: str,
    trajectory_status: str = "complete",
    environment_origin: str = "open_dataset",
) -> dict[str, Any]:
    runtime_native = bool(
        any(row.get("role") == "assistant" and row.get("tool_calls") for row in messages)
        and any(row.get("role") == "tool" for row in messages)
        and messages[-1].get("role") == "assistant"
        and str(messages[-1].get("content", "")).strip()
    )
    record = {
        "schema_version": SCHEMA_VERSION,
        "id": record_id,
        "group_id": group_id,
        "source_dataset": source_dataset,
        "source_id": source_id,
        "task_family": task_family,
        "capability_tags": sorted(set(capability_tags)),
        "messages": deepcopy(messages),
        "tools": deepcopy(tools),
        "trajectory_status": trajectory_status,
        "runtime_native": runtime_native,
        "quality_tier": quality_tier,
        "environment_origin": environment_origin,
        "provenance": dict(provenance),
    }
    record["content_sha256"] = trajectory_fingerprint(record)
    return record
