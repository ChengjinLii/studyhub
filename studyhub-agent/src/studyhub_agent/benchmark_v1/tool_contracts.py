from __future__ import annotations

from copy import deepcopy
from typing import Any

TOOL_CONTRACT_VERSION = "studyhub.agent-tools.v3"


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


QUERY = {"type": "string", "minLength": 1, "maxLength": 500}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}

_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "name": "knowledge_search",
        "description": "Search the ACL-filtered, frozen StudyHub material snapshot.",
        "parameters": _object({"query": QUERY, "limit": LIMIT}, ["query"]),
    },
    {
        "name": "knowledge_read",
        "description": "Read one ACL-authorized StudyHub source by source_id.",
        "parameters": _object(
            {"source_id": {"type": "string", "minLength": 1, "maxLength": 180}},
            ["source_id"],
        ),
    },
    {
        "name": "knowledge_browse",
        "description": "Browse ACL-authorized chunks belonging to one material.",
        "parameters": _object(
            {
                "material_id": {"type": "integer", "minimum": 1},
                "limit": LIMIT,
            },
            ["material_id"],
        ),
    },
    {
        "name": "web_search",
        "description": "Search the frozen public Web replay snapshot.",
        "parameters": _object({"query": QUERY, "limit": LIMIT}, ["query"]),
    },
    {
        "name": "web_fetch",
        "description": "Fetch one public page returned by the Web replay environment.",
        "parameters": _object(
            {"url": {"type": "string", "minLength": 8, "maxLength": 2048}},
            ["url"],
        ),
    },
    {
        "name": "personal_memory_search",
        "description": "Search only the current simulated user's isolated learning memories.",
        "parameters": _object({"query": QUERY, "limit": LIMIT}, ["query"]),
    },
    {
        "name": "collective_memory_search",
        "description": "Search anonymized aggregate learning patterns; no user records are exposed.",
        "parameters": _object(
            {
                "query": QUERY,
                "course": {"type": "string", "maxLength": 120},
                "limit": LIMIT,
            },
            ["query"],
        ),
    },
    {
        "name": "learning_profile_get",
        "description": "Read the current simulated user's non-sensitive learning profile.",
        "parameters": _object({}, []),
    },
    {
        "name": "study_plan_update",
        "description": "Create or replace a study-plan item inside the isolated task sandbox.",
        "parameters": _object(
            {
                "topic": {"type": "string", "minLength": 1, "maxLength": 120},
                "weekly_minutes": {"type": "integer", "minimum": 15, "maximum": 2400},
                "resource_ids": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "maxItems": 12,
                },
            },
            ["topic", "weekly_minutes", "resource_ids"],
        ),
    },
    {
        "name": "material_bookmark_add",
        "description": "Bookmark a free or ACL-authorized material in the isolated task sandbox.",
        "parameters": _object(
            {"material_id": {"type": "integer", "minimum": 1}},
            ["material_id"],
        ),
    },
    {
        "name": "learning_progress_record",
        "description": "Record a topic status and optional score in the isolated task sandbox.",
        "parameters": _object(
            {
                "topic": {"type": "string", "minLength": 1, "maxLength": 120},
                "status": {"type": "string", "enum": ["not_started", "learning", "review", "mastered"]},
                "score": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            ["topic", "status"],
        ),
    },
)

TOOL_SCHEMAS = {row["name"]: row for row in _SCHEMAS}


def tool_schemas(names: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    unknown = set(names) - set(TOOL_SCHEMAS)
    if unknown:
        raise KeyError(f"unknown v3 tool schemas: {sorted(unknown)}")
    return [deepcopy(TOOL_SCHEMAS[name]) for name in names]
