from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studyhub_agent.trajectory.runtime_sft import (
    assistant_tool_call,
    make_record,
    normalize_legacy_conversation,
    stable_hash,
    tool_observation,
    validate_runtime_trajectory,
)

TERMINAL_ACTIONS = {
    "answer",
    "finalaction",
    "finalanswer",
    "finish",
    "finishaction",
}
_ACTION_KEYS = {"action", "tool", "command", "api", "name"}
_ARGUMENT_KEYS = {"arguments", "parameters", "actioninput", "input", "args"}
_FINAL_KEYS = {"finalanswer", "answer", "content", "response"}
_ERROR = re.compile(
    r"(?:\berror\b|\bfailed\b|\bfailure\b|\binvalid\b|not found|timed out|unable to)",
    re.IGNORECASE,
)
_STATEFUL = re.compile(
    r"(?:create|update|delete|remove|add|set|book|cancel|send|write|save|purchase|buy)",
    re.IGNORECASE,
)
_LABEL_ACTION = re.compile(
    r"(?im)^(?:action|tool|command|api)\s*:\s*(.+?)\s*$",
)
_LABEL_ARGUMENTS = re.compile(
    r"(?ims)^(?:arguments|parameters|action\s*input|input|args)\s*:\s*(\{.*\})\s*$",
)
_TOOLBENCH_ROOT = re.compile(r"^Step\s+\d+\s*:\s*", re.IGNORECASE)
_UNRESOLVED_FINAL = re.compile(
    r"(?:\b(?:could not|couldn't|cannot|can't|unable to|failed to)\b|\bgive up\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedAction:
    name: str
    arguments: dict[str, Any]
    final_answer: str = ""

    @property
    def terminal(self) -> bool:
        return canonical_action_name(self.name) in TERMINAL_ACTIONS


def canonical_action_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _dict_casefold(value: Mapping[str, Any]) -> dict[str, Any]:
    return {re.sub(r"[^a-z0-9]", "", str(key).casefold()): item for key, item in value.items()}


def _parse_mapping(value: str) -> Mapping[str, Any] | None:
    text = value.strip()
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(text)
        except (ValueError, SyntaxError, json.JSONDecodeError):
            continue
        if isinstance(parsed, Mapping):
            return parsed
    return None


def _parse_call_expression(value: str) -> tuple[str, dict[str, Any]]:
    text = value.strip().strip("`")
    if "(" not in text or not text.endswith(")"):
        return text, {}
    name, raw_arguments = text.split("(", 1)
    raw_arguments = raw_arguments[:-1].strip()
    if not raw_arguments:
        return name.strip(), {}
    parsed = _parse_mapping(raw_arguments)
    return name.strip(), dict(parsed or {})


def parse_structured_action(content: str) -> ParsedAction | None:
    payload = _parse_mapping(content)
    if payload is not None:
        folded = _dict_casefold(payload)
        action_value = next((folded[key] for key in _ACTION_KEYS if key in folded), None)
        if action_value is None:
            return None
        name, embedded = _parse_call_expression(str(action_value))
        argument_value = next((folded[key] for key in _ARGUMENT_KEYS if key in folded), None)
        if isinstance(argument_value, str):
            argument_value = _parse_mapping(argument_value)
        arguments = dict(argument_value) if isinstance(argument_value, Mapping) else embedded
        normalized_arguments = _dict_casefold(arguments)
        final = next(
            (str(normalized_arguments[key]).strip() for key in _FINAL_KEYS if key in normalized_arguments),
            "",
        )
        return ParsedAction(name=name, arguments=arguments, final_answer=final)

    action_match = _LABEL_ACTION.search(content)
    if action_match is None:
        return None
    name, arguments = _parse_call_expression(action_match.group(1))
    if not arguments:
        argument_match = _LABEL_ARGUMENTS.search(content)
        if argument_match is not None:
            parsed_arguments = _parse_mapping(argument_match.group(1))
            if parsed_arguments is not None:
                arguments = dict(parsed_arguments)
    final = ""
    if canonical_action_name(name) in TERMINAL_ACTIONS:
        folded = _dict_casefold(arguments)
        final = next((str(folded[key]).strip() for key in _FINAL_KEYS if key in folded), "")
    return ParsedAction(name=name, arguments=arguments, final_answer=final)


def _json_object_after_marker(value: str, marker: str) -> Mapping[str, Any] | None:
    offset = value.find(marker)
    if offset < 0:
        return None
    start = value.find("{", offset + len(marker))
    if start < 0:
        return None
    try:
        parsed, _end = json.JSONDecoder().raw_decode(value[start:])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def iter_json_array(path: Path, *, chunk_size: int = 1024 * 1024) -> Iterator[dict[str, Any]]:
    """Stream a top-level JSON array without loading multi-gigabyte source files."""
    decoder = json.JSONDecoder()
    buffer = ""
    started = False
    with path.open(encoding="utf-8") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if chunk:
                buffer += chunk
            elif not buffer.strip():
                break
            while True:
                buffer = buffer.lstrip()
                if not started:
                    if not buffer:
                        break
                    if buffer[0] != "[":
                        raise ValueError(f"expected a top-level JSON array: {path}")
                    buffer = buffer[1:]
                    started = True
                    continue
                buffer = buffer.lstrip(" \t\r\n,")
                if buffer.startswith("]"):
                    return
                if not buffer:
                    break
                try:
                    value, end = decoder.raw_decode(buffer)
                except json.JSONDecodeError:
                    break
                if not isinstance(value, dict):
                    raise ValueError(f"expected JSON objects in source array: {path}")
                yield value
                buffer = buffer[end:]
            if not chunk:
                raise ValueError(f"truncated JSON array: {path}")


def _toolbench_api_list(system: str) -> list[dict[str, Any]]:
    marker = "Specifically, you have access to the following APIs:"
    offset = system.find(marker)
    if offset < 0:
        return []
    value = system[offset + len(marker) :].strip()
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(value)
        except (ValueError, SyntaxError, json.JSONDecodeError):
            continue
        if not isinstance(parsed, list):
            continue
        tools = []
        for item in parsed:
            if not isinstance(item, Mapping) or not item.get("name"):
                continue
            name = str(item["name"])
            if canonical_action_name(name) in TERMINAL_ACTIONS:
                continue
            parameters = item.get("parameters", {"type": "object", "properties": {}})
            if not isinstance(parameters, Mapping):
                continue
            normalized_parameters = dict(parameters)
            normalized_parameters.pop("optional", None)
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": str(item.get("description", ""))[:1000],
                        "parameters": normalized_parameters,
                    },
                }
            )
        return tools
    return []


def parse_toolbench_tools(system: str) -> list[dict[str, Any]]:
    official_tools = _toolbench_api_list(system)
    if official_tools:
        return official_tools
    header = re.compile(r"(?m)^([A-Za-z0-9_.-]+):\s*")
    matches = list(header.finditer(system))
    tools: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        name = match.group(1).strip()
        if canonical_action_name(name) in TERMINAL_ACTIONS:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(system)
        block = system[match.end() : end]
        parameters = _json_object_after_marker(block, "Input parameters are as follows:")
        if parameters is None:
            continue
        description = block.split("Input parameters are as follows:", 1)[0].strip()
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description[:1000],
                    "parameters": dict(parameters),
                },
            }
        )
    return tools


def _fallback_tool(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    properties = {
        str(key): {"type": _json_type(value)}
        for key, value in sorted(arguments.items(), key=lambda item: str(item[0]))
    }
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "Tool schema normalized from the recorded action and its arguments.",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": sorted(properties),
            },
        },
    }


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return "string"


def _recorded_observation(value: str) -> tuple[bool, str]:
    text = value.strip()
    payload = _parse_mapping(text)
    if payload is None:
        return bool(text), text
    folded = _dict_casefold(payload)
    error = str(folded.get("error", "")).strip()
    response = folded.get("response")
    if response is None:
        response = folded.get("result")
    if not error and (response is None or response == ""):
        return False, text
    return True, text


def observation_has_error(value: str) -> bool:
    payload = _parse_mapping(value)
    if payload is not None:
        folded = _dict_casefold(payload)
        if str(folded.get("error", "")).strip():
            return True
        response = folded.get("response", folded.get("result", ""))
        return bool(_ERROR.search(str(response)))
    return bool(_ERROR.search(value))


def add_policy_metadata(record: dict[str, Any], *, planning_only: bool = False) -> dict[str, Any]:
    call_messages = [message for message in record["messages"] if message.get("tool_calls")]
    calls = [call for message in call_messages for call in message.get("tool_calls", [])]
    names = [str(call.get("function", {}).get("name", "")) for call in calls]
    observations = [message for message in record["messages"] if message.get("role") == "tool"]
    recovery = False
    for index, message in enumerate(record["messages"]):
        if message.get("role") != "tool" or not observation_has_error(str(message.get("content", ""))):
            continue
        if any(row.get("tool_calls") for row in record["messages"][index + 1 :]):
            recovery = True
            break
    behavior = []
    if calls and observations:
        behavior.append("observation_conditioned")
    if len(call_messages) >= 2:
        behavior.append("multi_turn")
    if len(set(names)) >= 2:
        behavior.append("multi_tool")
    if recovery:
        behavior.append("recovery_negative")
    if any(_STATEFUL.search(name) for name in names):
        behavior.append("stateful_function")
    if planning_only:
        behavior.append("planning_only")
    if not calls:
        behavior.append("direct_abstention")
    exact_path = " -> ".join(names + ["FINAL"]) if names else "DIRECT -> FINAL"
    normalized_names = [canonical_action_name(name) for name in names]
    has_search = any("search" in name for name in normalized_names)
    has_read = any("read" in name or "fetch" in name for name in normalized_names)
    if recovery:
        abstract_path = "failure -> retry -> final"
    elif has_search and has_read:
        abstract_path = "search -> read -> final"
    elif len(set(names)) >= 2:
        abstract_path = "toolA -> toolB -> final"
    elif len(call_messages) >= 2:
        abstract_path = "single-tool-repeat -> final"
    elif calls:
        abstract_path = "single-tool -> final"
    else:
        abstract_path = "planning/direct -> final" if planning_only else "direct -> final"
    record["behavior_tags"] = sorted(set(behavior))
    record["tool_path_signature"] = exact_path
    record["abstract_tool_path"] = abstract_path
    record["tool_call_count"] = len(calls)
    record["tool_turn_count"] = len(call_messages)
    record["policy_quality_tier"] = (
        "A"
        if calls and observations and len(call_messages) >= 2
        else "B"
        if calls and observations
        else "C"
    )
    return record


def iter_hermes_records(
    root: Path,
    *,
    revision: str,
    license_name: str,
    source_url: str,
) -> Iterable[tuple[dict[str, Any] | None, str]]:
    role_map = {"system": "system", "human": "user", "gpt": "assistant", "tool": "tool"}
    function_files = (
        "func-calling.json",
        "glaive-function-calling-5k.json",
        "func-calling-singleturn.json",
    )
    for filename in function_files:
        path = root / filename
        for index, row in enumerate(json.loads(path.read_text(encoding="utf-8"))):
            source_id = str(row.get("id", index))
            messages, tools = normalize_legacy_conversation(
                row.get("conversations", []),
                role_map=role_map,
                id_salt=f"hermes:{filename}:{source_id}",
            )
            calls = [call for message in messages for call in message.get("tool_calls", [])]
            observations = [message for message in messages if message.get("role") == "tool"]
            complete = bool(
                calls
                and len(observations) >= len(calls)
                and messages
                and messages[-1].get("role") == "assistant"
                and not messages[-1].get("tool_calls")
                and str(messages[-1].get("content", "")).strip()
            )
            if not complete:
                yield None, f"{filename}:incomplete_or_action_only"
                continue
            conversation_root = next(
                (str(message.get("content", "")) for message in messages if message.get("role") == "user"),
                source_id,
            )
            record = make_record(
                record_id=f"hermes:{filename}:{source_id}",
                group_id=f"hermes:{stable_hash(conversation_root, salt='hermes-conversation-root')}",
                source_dataset=f"hermes_{filename.removesuffix('.json').replace('-', '_')}",
                source_id=f"{filename}:{source_id}",
                task_family="open_function_calling",
                messages=messages,
                tools=tools,
                provenance={
                    "revision": revision,
                    "license": license_name,
                    "source_url": source_url,
                    "raw_file": filename,
                    "transform_version": "open-agentic-sft-v2",
                },
                capability_tags=["function_calling", "tool_protocol"],
                quality_tier="expert_recorded_complete",
            )
            record["source_family"] = "hermes"
            add_policy_metadata(record)
            failures = validate_runtime_trajectory(record)
            if failures:
                yield None, f"{filename}:runtime_contract:{','.join(failures)}"
                continue
            yield record, "accepted"

    for filename in ("json-mode-agentic.json", "json-mode-singleturn.json"):
        path = root / filename
        for index, row in enumerate(json.loads(path.read_text(encoding="utf-8"))):
            raw = row.get("conversations", [])
            messages = [
                {"role": role_map[item["from"]], "content": str(item.get("value", "")).strip()}
                for item in raw
                if item.get("from") in role_map and str(item.get("value", "")).strip()
            ]
            if not messages or messages[-1].get("role") != "assistant":
                yield None, f"{filename}:missing_final"
                continue
            source_id = str(row.get("id", index))
            conversation_root = next(
                (str(message.get("content", "")) for message in messages if message.get("role") == "user"),
                source_id,
            )
            record = make_record(
                record_id=f"hermes:{filename}:{source_id}",
                group_id=f"hermes:{stable_hash(conversation_root, salt='hermes-conversation-root')}",
                source_dataset=f"hermes_{filename.removesuffix('.json').replace('-', '_')}",
                source_id=f"{filename}:{source_id}",
                task_family="structured_output",
                messages=messages,
                tools=[],
                provenance={
                    "revision": revision,
                    "license": license_name,
                    "source_url": source_url,
                    "raw_file": filename,
                    "transform_version": "open-agentic-sft-v2",
                },
                capability_tags=["structured_output"],
                quality_tier="expert_recorded_complete",
            )
            record["source_family"] = "hermes"
            add_policy_metadata(record, planning_only=True)
            failures = validate_runtime_trajectory(record)
            if failures:
                yield None, f"{filename}:runtime_contract:{','.join(failures)}"
                continue
            yield record, "accepted"


def parse_agent_flan_toolbench_react(
    row: Mapping[str, Any],
    *,
    revision: str,
    license_name: str,
    source_url: str,
) -> tuple[dict[str, Any] | None, str]:
    conversation = row.get("conversation")
    if not isinstance(conversation, list) or len(conversation) < 5:
        return None, "agent_flan_react:short_or_missing_conversation"
    system = str(conversation[0].get("content", ""))
    if conversation[0].get("role") != "system" or conversation[1].get("role") != "user":
        return None, "agent_flan_react:unexpected_prefix"
    tools = parse_toolbench_tools(system)
    tools_by_name = {str(tool["function"]["name"]): tool for tool in tools}
    row_id = str(row.get("id", ""))
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": "Use the available tools when needed and ground the final answer in their observations.",
        },
        {"role": "user", "content": str(conversation[1].get("content", "")).strip()},
    ]
    final_answer = ""
    call_index = 0
    index = 2
    while index < len(conversation):
        assistant = conversation[index]
        if assistant.get("role") != "assistant":
            return None, "agent_flan_react:assistant_turn_expected"
        action = parse_structured_action(str(assistant.get("content", "")))
        if action is None or not action.name:
            return None, "agent_flan_react:unparseable_action"
        if action.terminal:
            final_answer = action.final_answer
            if not final_answer:
                return None, "agent_flan_react:terminal_without_final"
            index += 1
            break
        if index + 1 >= len(conversation) or conversation[index + 1].get("role") != "user":
            return None, "agent_flan_react:missing_observation"
        observation_ok, observation = _recorded_observation(
            str(conversation[index + 1].get("content", ""))
        )
        if not observation_ok:
            return None, "agent_flan_react:corrupt_observation"
        if action.name not in tools_by_name:
            tools_by_name[action.name] = _fallback_tool(action.name, action.arguments)
        call_id = f"call_{stable_hash(f'agent-flan:{row_id}:{call_index}')[:20]}"
        messages.append(assistant_tool_call(action.name, action.arguments, call_id=call_id))
        messages.append(tool_observation(action.name, observation, call_id=call_id))
        call_index += 1
        index += 2
    if not final_answer or index != len(conversation) or not 2 <= call_index <= 8:
        return None, "agent_flan_react:incomplete_or_call_budget"
    messages.append({"role": "assistant", "content": final_answer})
    source_id = str(row.get("id", stable_hash(json.dumps(row, sort_keys=True))))
    record = make_record(
        record_id=f"agent-flan-react:{source_id}",
        group_id=f"agent-flan:{source_id}",
        source_dataset="agent_flan_toolbench_react",
        source_id=source_id,
        task_family="open_tool_execution",
        messages=messages,
        tools=[tools_by_name[name] for name in sorted(tools_by_name)],
        provenance={
            "revision": revision,
            "license": license_name,
            "source_url": source_url,
            "raw_file": "data/toolbench_react_10p.jsonl",
            "transform_version": "open-agentic-sft-v2",
        },
        capability_tags=["tool_routing", "multi_tool", "recovery"],
        quality_tier="expert_recorded_complete",
    )
    record["source_family"] = "agent_flan"
    add_policy_metadata(record)
    failures = validate_runtime_trajectory(record)
    if failures:
        return None, f"agent_flan_react:runtime_contract:{','.join(failures)}"
    return record, "accepted"


def parse_agent_flan_negative(
    row: Mapping[str, Any],
    *,
    revision: str,
    license_name: str,
    source_url: str,
) -> tuple[dict[str, Any] | None, str]:
    conversation = row.get("conversation")
    if not isinstance(conversation, list) or len(conversation) != 3:
        return None, "agent_flan_negative:unexpected_conversation"
    messages = [
        {"role": str(item.get("role")), "content": str(item.get("content", "")).strip()}
        for item in conversation
    ]
    if [message["role"] for message in messages] != ["system", "user", "assistant"]:
        return None, "agent_flan_negative:unexpected_roles"
    if not all(message["content"] for message in messages):
        return None, "agent_flan_negative:empty_content"
    source_id = str(row.get("id", stable_hash(json.dumps(row, sort_keys=True))))
    record = make_record(
        record_id=f"agent-flan-negative:{source_id}",
        group_id=f"agent-flan:{source_id}",
        source_dataset="agent_flan_toolbench_negative",
        source_id=source_id,
        task_family="tool_abstention",
        messages=messages,
        tools=[],
        provenance={
            "revision": revision,
            "license": license_name,
            "source_url": source_url,
            "raw_file": "data/toolbench_negative.jsonl",
            "transform_version": "open-agentic-sft-v2",
        },
        capability_tags=["negative_tool_use", "abstention"],
        quality_tier="expert_recorded_complete",
    )
    record["source_family"] = "agent_flan"
    add_policy_metadata(record)
    record["behavior_tags"] = sorted(set(record["behavior_tags"] + ["recovery_negative"]))
    failures = validate_runtime_trajectory(record)
    if failures:
        return None, f"agent_flan_negative:runtime_contract:{','.join(failures)}"
    return record, "accepted"


def parse_toolbench_record(
    row: Mapping[str, Any],
    *,
    revision: str,
    license_name: str,
    source_url: str,
    archive_sha256: str,
) -> tuple[dict[str, Any] | None, str]:
    conversation = row.get("conversations")
    if not isinstance(conversation, list) or len(conversation) < 7:
        return None, "toolbench:short_or_missing_conversation"
    if conversation[0].get("from") != "system" or conversation[1].get("from") != "user":
        return None, "toolbench:unexpected_prefix"
    if any(item.get("from") == "user" for item in conversation[2:]):
        return None, "toolbench:retry_prefix_or_role_drift"

    tools = parse_toolbench_tools(str(conversation[0].get("value", "")))
    tools_by_name = {str(tool["function"]["name"]): tool for tool in tools}
    user = str(conversation[1].get("value", "")).replace("\nBegin!\n", "\n").strip()
    if not user:
        return None, "toolbench:empty_user"
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": "Use the available tools when needed and ground the final answer in their observations.",
        },
        {"role": "user", "content": user},
    ]
    observations: list[str] = []
    final_answer = ""
    call_index = 0
    raw_id = str(row.get("id", ""))
    index = 2
    while index < len(conversation):
        assistant = conversation[index]
        if assistant.get("from") != "assistant":
            return None, "toolbench:assistant_turn_expected"
        action = parse_structured_action(str(assistant.get("value", "")))
        if action is None or not action.name:
            return None, "toolbench:unparseable_action"
        if action.terminal:
            return_type = canonical_action_name(str(action.arguments.get("return_type", "give_answer")))
            if return_type != "giveanswer" or not action.final_answer:
                return None, "toolbench:give_up_or_empty_final"
            final_answer = action.final_answer.strip()
            index += 1
            break
        if index + 1 >= len(conversation) or conversation[index + 1].get("from") != "function":
            return None, "toolbench:missing_observation"
        observation_ok, observation = _recorded_observation(
            str(conversation[index + 1].get("value", ""))
        )
        if not observation_ok:
            return None, "toolbench:corrupt_observation"
        if action.name not in tools_by_name:
            return None, "toolbench:tool_schema_missing"
        call_id = f"call_{stable_hash(f'toolbench:{raw_id}:{call_index}')[:20]}"
        messages.append(assistant_tool_call(action.name, action.arguments, call_id=call_id))
        messages.append(tool_observation(action.name, observation, call_id=call_id))
        observations.append(observation)
        call_index += 1
        index += 2

    if not final_answer or index != len(conversation) or not 2 <= call_index <= 8:
        return None, "toolbench:incomplete_or_call_budget"
    if not any(not observation_has_error(value) for value in observations):
        return None, "toolbench:no_successful_observation"
    if observation_has_error(observations[-1]) or _UNRESOLVED_FINAL.search(final_answer):
        return None, "toolbench:unresolved_failure"
    messages.append({"role": "assistant", "content": final_answer})

    root = _TOOLBENCH_ROOT.sub("", raw_id).strip() or user
    source_id = stable_hash(json.dumps(row, ensure_ascii=False, sort_keys=True), salt="toolbench-source")
    record = make_record(
        record_id=f"toolbench:{source_id}",
        group_id=f"toolbench:{stable_hash(root, salt='toolbench-conversation-root')}",
        source_dataset="toolbench_toolllama_g123_dfs_train",
        source_id=source_id,
        task_family="open_tool_execution",
        messages=messages,
        tools=[tools_by_name[name] for name in sorted(tools_by_name)],
        provenance={
            "revision": revision,
            "license": license_name,
            "source_url": source_url,
            "raw_file": "data/toolllama_G123_dfs_train.json",
            "archive_sha256": archive_sha256,
            "transform_version": "open-agentic-sft-v2",
        },
        capability_tags=["tool_routing", "multi_tool", "recovery"],
        quality_tier="expert_recorded_complete",
    )
    record["source_family"] = "toolbench"
    add_policy_metadata(record)
    failures = validate_runtime_trajectory(record)
    if failures:
        return None, f"toolbench:runtime_contract:{','.join(failures)}"
    return record, "accepted"
