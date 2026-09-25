from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2.exceptions import TemplateError
from jinja2.sandbox import ImmutableSandboxedEnvironment

from studyhub_agent.contracts.episode import Message, ToolCall, TurnKind
from studyhub_agent.contracts.tools import ToolSpec

TEMPLATE_PATH = Path(__file__).parent / "templates" / "qwen3_5.jinja"
TEMPLATE_SHA256 = "a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715"
END_OF_TURN = "<|im_end|>"
_THINK_CLOSE = "</think>"

_CALL = re.compile(r"\s*<tool_call>\s*<function=([^>\n]+)>\n?(.*?)</function>\s*</tool_call>", re.DOTALL)
_PARAM = re.compile(r"<parameter=([^>\n]+)>\n(.*?)\n</parameter>", re.DOTALL)


class RenderError(ValueError):
    """A message cannot be represented faithfully by the chat template."""


@dataclass(frozen=True, slots=True)
class ParsedCompletion:
    kind: TurnKind
    content: str
    tool_calls: tuple[ToolCall, ...]
    error: str | None
    reasoning: str = ""


def _raise_exception(message: str) -> None:
    raise RenderError(message)


def _tojson(value: Any, indent: int | None = None) -> str:
    # Matches transformers' chat-template tojson filter (ensure_ascii=False).
    return json.dumps(value, ensure_ascii=False, indent=indent)


@lru_cache(maxsize=1)
def _template():
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if digest != TEMPLATE_SHA256:
        raise RenderError(f"chat template digest {digest} does not match the pinned contract digest")
    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    env.filters["tojson"] = _tojson
    env.globals["raise_exception"] = _raise_exception
    return env.from_string(source)


def _ordered_arguments(arguments: dict[str, Any], spec: ToolSpec | None) -> dict[str, Any]:
    """Canonical argument order: the tool schema's property order, unknown keys last (alphabetical)."""
    order = list(spec.parameters.get("properties", {})) if spec else []
    rank = {name: index for index, name in enumerate(order)}
    return {key: arguments[key] for key in sorted(arguments, key=lambda key: (rank.get(key, len(order)), key))}


def _message_dict(message: Message, specs: dict[str, ToolSpec]) -> dict[str, Any]:
    if message.role != "assistant":
        return {"role": message.role, "content": message.content}
    result: dict[str, Any] = {"role": "assistant", "content": message.content}
    # Only set reasoning_content when we actually have reasoning to carry. Passing "" here would
    # make the template treat it as a defined string and skip its own </think> extraction fallback
    # (used e.g. for historical parse-error feedback whose content still contains a literal
    # "</think>" marker), which would otherwise double up the closing tag.
    if message.reasoning:
        result["reasoning_content"] = message.reasoning
    if message.tool_calls:
        for call in message.tool_calls:
            for value in call.arguments.values():
                if isinstance(value, str) and "</parameter>" in value:
                    raise RenderError(f"argument of {call.name} contains a </parameter> tag")
        result["tool_calls"] = [
            {
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": _ordered_arguments(call.arguments, specs.get(call.name)),
                },
            }
            for call in message.tool_calls
        ]
    return result


def render_text(
    messages: Sequence[Message],
    tools: Sequence[ToolSpec],
    *,
    thinking: bool,
    add_generation_prompt: bool,
) -> str:
    try:
        return _template().render(
            messages=[_message_dict(message, {tool.name: tool for tool in tools}) for message in messages],
            tools=[tool.to_openai() for tool in tools] or None,
            add_generation_prompt=add_generation_prompt,
            enable_thinking=thinking,
        )
    except TemplateError as exc:
        raise RenderError(str(exc)) from exc


def canonical_completion_text(
    history: Sequence[Message],
    assistant: Message,
    tools: Sequence[ToolSpec],
    *,
    thinking: bool,
) -> str:
    prompt = render_text(history, tools, thinking=thinking, add_generation_prompt=True)
    full = render_text((*history, assistant), tools, thinking=thinking, add_generation_prompt=False)
    if not full.startswith(prompt):
        raise RenderError("chat template violates the prompt prefix property")
    return full[len(prompt) :]


def parse_completion(text: str, tools: Sequence[ToolSpec], *, thinking: bool) -> ParsedCompletion:
    body = text.split(END_OF_TURN, 1)[0]
    reasoning = ""
    if thinking:
        if _THINK_CLOSE not in body:
            return _error("unclosed_think")
        reasoning_part, body = body.split(_THINK_CLOSE, 1)
        reasoning = reasoning_part.strip()
    start = body.find("<tool_call>")
    if start < 0:
        content = body.strip()
        if not content:
            return _error("empty_response")
        return ParsedCompletion(TurnKind.FINAL, content, (), None, reasoning)
    preamble = body[:start].strip()
    specs = {tool.name: tool for tool in tools}
    calls: list[ToolCall] = []
    position = start
    while True:
        match = _CALL.match(body, position)
        if match is None:
            break
        call, error = _parse_call(match.group(1).strip(), match.group(2), specs, index=len(calls))
        if error:
            return _error(error)
        calls.append(call)
        position = match.end()
    remainder = body[position:]
    if remainder.strip():
        return _error("malformed_tool_call" if "<tool_call>" in remainder else "text_after_tool_call")
    if not calls:
        return _error("malformed_tool_call")
    return ParsedCompletion(TurnKind.TOOL_CALLS, preamble, tuple(calls), None, reasoning)


def _error(code: str) -> ParsedCompletion:
    return ParsedCompletion(TurnKind.PARSE_ERROR, "", (), code)


def _parse_call(
    name: str,
    body: str,
    specs: dict[str, ToolSpec],
    *,
    index: int,
) -> tuple[ToolCall | None, str | None]:
    spec = specs.get(name)
    if spec is None:
        return None, f"unknown_tool: {name}"
    properties = spec.parameters.get("properties", {})
    arguments: dict[str, Any] = {}
    for match in _PARAM.finditer(body):
        param, raw = match.group(1).strip(), match.group(2)
        if param not in properties:
            return None, f"unknown_parameter: {name}.{param}"
        value, ok = _coerce(raw, properties[param])
        if not ok:
            return None, f"invalid_argument: {name}.{param}"
        arguments[param] = value
    if _PARAM.sub("", body).strip():
        return None, f"malformed_tool_call: {name}"
    missing = [param for param in spec.parameters.get("required", []) if param not in arguments]
    if missing:
        return None, f"missing_required: {name}.{','.join(missing)}"
    return ToolCall(call_id=f"call_{index}", name=name, arguments=arguments), None


_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _matches_schema(value: Any, schema: dict[str, Any]) -> bool:
    kind = schema.get("type")
    if kind == "string":
        if not isinstance(value, str):
            return False
    else:
        expected = _TYPE_MAP.get(kind)
        if expected is None:
            return False
        if kind in {"integer", "number"} and isinstance(value, bool):
            return False
        if not isinstance(value, expected):
            return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    return True


_PYTHON_LITERALS: dict[str, dict[str, Any]] = {
    "boolean": {"true": True, "false": False},
    "null": {"none": None, "null": None},
}


def _coerce(raw: str, schema: dict[str, Any]) -> tuple[Any, bool]:
    kind = schema.get("type")
    stripped = raw.strip()
    if kind == "string":
        value: Any = raw
    elif kind in _PYTHON_LITERALS and stripped.lower() in _PYTHON_LITERALS[kind]:
        # The template renders a scalar (non-list/dict) argument with Jinja's `string` filter, so a
        # Python bool/None value comes out as the literal text "True"/"False"/"None", not JSON's
        # "true"/"false"/"null". Accept both spellings, case-insensitively, so these round-trip.
        value = _PYTHON_LITERALS[kind][stripped.lower()]
    else:
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            return None, False
    if not _matches_schema(value, schema):
        return None, False
    if kind == "array":
        items_schema = schema.get("items")
        if isinstance(items_schema, dict) and not all(_matches_schema(element, items_schema) for element in value):
            return None, False
    return value, True
