from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

ALLOWED_JSON_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object", "null"})
TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+$")
MAX_ENUM_VALUES = 32

Capability = Literal["live", "snapshot"]


class ToolSpecError(ValueError):
    """Raised when a tool specification violates the runtime contract."""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    version: str
    description: str
    parameters: dict[str, Any]
    capability: Capability = "snapshot"
    mcp_name: str | None = None

    def __post_init__(self) -> None:
        lint_tool_spec(self)

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }

    def canonical(self) -> dict[str, Any]:
        return json.loads(
            json.dumps(
                {
                    "name": self.name,
                    "version": self.version,
                    "description": self.description,
                    "parameters": self.parameters,
                    "capability": self.capability,
                    "mcp_name": self.mcp_name,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )


def lint_tool_spec(spec: ToolSpec) -> None:
    if not TOOL_NAME_PATTERN.match(spec.name):
        raise ToolSpecError(f"tool name {spec.name!r} must match {TOOL_NAME_PATTERN.pattern}")
    if not VERSION_PATTERN.match(spec.version):
        raise ToolSpecError(f"tool {spec.name}: version {spec.version!r} must look like 1.0")
    if not spec.description.strip():
        raise ToolSpecError(f"tool {spec.name}: description must not be empty")
    params = spec.parameters
    if params.get("type") != "object":
        raise ToolSpecError(f"tool {spec.name}: parameters must be a JSON Schema object")
    if params.get("additionalProperties") is not False:
        raise ToolSpecError(f"tool {spec.name}: parameters must set additionalProperties to false")
    properties = params.get("properties", {})
    missing = set(params.get("required", [])) - set(properties)
    if missing:
        raise ToolSpecError(f"tool {spec.name}: required names unknown properties {sorted(missing)}")
    for prop_name, schema in properties.items():
        _lint_property(spec.name, prop_name, schema)


def _lint_property(tool: str, prop_name: str, schema: dict[str, Any]) -> None:
    prop_type = schema.get("type")
    if prop_type not in ALLOWED_JSON_TYPES:
        raise ToolSpecError(f"tool {tool}: property {prop_name} has invalid type {prop_type!r}")
    if not str(schema.get("description", "")).strip():
        raise ToolSpecError(f"tool {tool}: property {prop_name} needs a description")
    if len(schema.get("enum", [])) > MAX_ENUM_VALUES:
        raise ToolSpecError(f"tool {tool}: property {prop_name} enum exceeds {MAX_ENUM_VALUES} values")
    if prop_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict) or items.get("type") not in ALLOWED_JSON_TYPES:
            raise ToolSpecError(f"tool {tool}: array property {prop_name} needs typed items")
