from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TOOL_SCHEMA_VERSION = "v1"

# Hermes owns general web execution and the external-memory lifecycle. StudyHub
# only owns capabilities whose semantics depend on its materials, ACLs, or
# aggregate learning data. The replay names remain in schema v1 solely so
# frozen historical fixtures can still be reproduced.
STUDYHUB_DOMAIN_TOOL_NAMES = frozenset(
    {
        "knowledge_search",
        "knowledge_read",
        "knowledge_browse",
        "collective_memory_search",
    }
)
HERMES_NATIVE_TOOL_NAMES = frozenset({"web_search", "web_extract"})
HERMES_MEMORY_TOOL_NAMES = frozenset({"personal_memory_search"})
REPLAY_COMPAT_TOOL_NAMES = frozenset({"web_search", "web_fetch", "personal_memory_search"})


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    read_only: bool = True

    def as_openai_function(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _object_schema(*, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def tool_definitions() -> tuple[ToolDefinition, ...]:
    query = {"type": "string", "minLength": 1, "maxLength": 500}
    limit = {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}
    return (
        ToolDefinition(
            name="knowledge_search",
            description=(
                "Search StudyHub knowledge chunks. Results are filtered by the current user's ACL before return."
            ),
            parameters=_object_schema(properties={"query": query, "limit": limit}, required=["query"]),
        ),
        ToolDefinition(
            name="knowledge_read",
            description="Read one ACL-authorized StudyHub knowledge chunk by source_id.",
            parameters=_object_schema(
                properties={"source_id": {"type": "string", "minLength": 1, "maxLength": 160}},
                required=["source_id"],
            ),
        ),
        ToolDefinition(
            name="knowledge_browse",
            description="Browse ACL-authorized chunks adjacent to a StudyHub material or source.",
            parameters=_object_schema(
                properties={
                    "material_id": {"type": "integer", "minimum": 1},
                    "source_id": {"type": "string", "minLength": 1, "maxLength": 160},
                    "limit": limit,
                },
                required=[],
            ),
        ),
        ToolDefinition(
            name="web_search",
            description="Search the configured web provider for public sources. Does not fetch arbitrary URLs.",
            parameters=_object_schema(properties={"query": query, "limit": limit}, required=["query"]),
        ),
        ToolDefinition(
            name="web_fetch",
            description="Fetch a public HTTP(S) page through the SSRF, redirect, size, and content-type guard.",
            parameters=_object_schema(
                properties={"url": {"type": "string", "minLength": 8, "maxLength": 2048}},
                required=["url"],
            ),
        ),
        ToolDefinition(
            name="personal_memory_search",
            description="Recall memories only from the current user's isolated namespace.",
            parameters=_object_schema(properties={"query": query, "limit": limit}, required=["query"]),
        ),
        ToolDefinition(
            name="collective_memory_search",
            description=(
                "Search read-only, anonymized aggregate learning patterns without returning "
                "user records or transcripts."
            ),
            parameters=_object_schema(
                properties={
                    "query": query,
                    "course": {"type": "string", "maxLength": 120},
                    "limit": limit,
                },
                required=["query"],
            ),
        ),
    )


TOOL_DEFINITIONS = {definition.name: definition for definition in tool_definitions()}
STUDYHUB_DOMAIN_TOOL_DEFINITIONS = {
    name: TOOL_DEFINITIONS[name] for name in STUDYHUB_DOMAIN_TOOL_NAMES
}
