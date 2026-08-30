from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from studyhub_agent.guardrails.budget import BudgetState
from studyhub_agent.guardrails.permissions import PermissionContext
from studyhub_agent.guardrails.privacy import sanitize_output
from studyhub_agent.runtime.identity import AgentIdentity
from studyhub_agent.runtime.session import TaskSpec
from studyhub_agent.tools.schemas import TOOL_DEFINITIONS, ToolDefinition

ToolHandler = Callable[[dict[str, Any], "ToolExecutionContext"], Awaitable[Any]]


class ToolValidationError(ValueError):
    pass


@dataclass(slots=True)
class ToolExecutionContext:
    identity: AgentIdentity
    task: TaskSpec
    permissions: PermissionContext
    budget: BudgetState
    memory_namespace: str


def _validate_scalar(name: str, value: Any, schema: dict[str, Any]) -> None:
    expected = schema.get("type")
    if expected == "string":
        if not isinstance(value, str):
            raise ToolValidationError(f"{name} must be a string")
        if len(value) < int(schema.get("minLength", 0)) or len(value) > int(schema.get("maxLength", 2**31)):
            raise ToolValidationError(f"{name} has an invalid length")
    elif expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolValidationError(f"{name} must be an integer")
        if value < int(schema.get("minimum", -(2**31))) or value > int(schema.get("maximum", 2**31)):
            raise ToolValidationError(f"{name} is outside the allowed range")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolValidationError(f"{name} is not an allowed value")


def validate_arguments(definition: ToolDefinition, arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ToolValidationError("tool arguments must be an object")
    schema = definition.parameters
    properties = schema.get("properties", {})
    unknown = set(arguments) - set(properties)
    if unknown and schema.get("additionalProperties") is False:
        raise ToolValidationError(f"unknown tool arguments: {', '.join(sorted(unknown))}")
    missing = set(schema.get("required", [])) - set(arguments)
    if missing:
        raise ToolValidationError(f"missing tool arguments: {', '.join(sorted(missing))}")
    normalized = dict(arguments)
    for name, property_schema in properties.items():
        if name not in normalized and "default" in property_schema:
            normalized[name] = property_schema["default"]
        if name in normalized:
            _validate_scalar(name, normalized[name], property_schema)
    if definition.name == "knowledge_browse" and not (normalized.get("material_id") or normalized.get("source_id")):
        raise ToolValidationError("knowledge_browse requires material_id or source_id")
    return normalized


class ToolRegistry:
    def __init__(self, definitions: Mapping[str, ToolDefinition] | None = None) -> None:
        self._definitions = dict(TOOL_DEFINITIONS if definitions is None else definitions)
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, name: str, handler: ToolHandler) -> None:
        if name not in self._definitions:
            raise KeyError(f"tool schema is not owned by this registry: {name}")
        if name in self._handlers:
            raise ValueError(f"tool already registered: {name}")
        self._handlers[name] = handler

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._handlers)

    def definition(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise KeyError(f"tool schema is not owned by this registry: {name}") from exc

    def schemas(self, allowed_tools: list[str] | None = None) -> list[dict[str, Any]]:
        allowed = set(allowed_tools or self._handlers)
        return [self._definitions[name].as_openai_function() for name in sorted(self._handlers) if name in allowed]

    async def dispatch(self, name: str, arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
        if name not in context.task.allowed_tools:
            raise PermissionError(f"tool is not allowed for this task: {name}")
        handler = self._handlers.get(name)
        if handler is None:
            raise KeyError(f"tool is not registered: {name}")
        normalized = validate_arguments(self.definition(name), arguments)
        serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        context.budget.authorize_tool(name, fingerprint)
        result = await handler(normalized, context)
        return sanitize_output(result)
