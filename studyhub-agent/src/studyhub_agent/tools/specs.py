from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from studyhub_agent.contracts.tools import ToolSpec

POLICY_TOPICS = ("refund", "copyright", "download", "account", "payout")


def _object(properties: dict[str, dict[str, Any]], required: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="materials_search",
        version="1.0",
        description="按关键词检索 StudyHub 资料，返回资料元数据（不含正文）。可按学校、课程过滤。",
        parameters=_object(
            {
                "query": {"type": "string", "description": "检索关键词，例如课程名、考试类型"},
                "school": {"type": "string", "description": "可选，学校全称"},
                "course": {"type": "string", "description": "可选，课程名"},
                "limit": {"type": "integer", "description": "返回条数，1-10，默认 5"},
            },
            ["query"],
        ),
        mcp_name="materials.search",
    ),
    ToolSpec(
        name="materials_get",
        version="1.0",
        description="读取一份已检索到的资料的详情：价格、页数、简介、标签。",
        parameters=_object({"material_id": {"type": "integer", "description": "资料 ID"}}, ["material_id"]),
        mcp_name="materials.get",
    ),
    ToolSpec(
        name="materials_recommend",
        version="1.0",
        description="根据学习需求推荐资料，返回资料元数据。",
        parameters=_object(
            {
                "context": {"type": "string", "description": "用户的学习需求描述"},
                "limit": {"type": "integer", "description": "返回条数，1-5，默认 3"},
            },
            ["context"],
        ),
        mcp_name="materials.recommend",
    ),
    ToolSpec(
        name="platform_policy",
        version="1.0",
        description="查询 StudyHub 平台规则原文。",
        parameters=_object(
            {"topic": {"type": "string", "description": "规则主题", "enum": list(POLICY_TOPICS)}},
            ["topic"],
        ),
        mcp_name="platform.policy",
    ),
    ToolSpec(
        name="materials_read",
        version="1.0",
        description="读取已检索到的资料的公开预览页正文。",
        parameters=_object(
            {
                "material_id": {"type": "integer", "description": "资料 ID"},
                "page": {"type": "integer", "description": "预览页码，从 1 开始，默认 1"},
            },
            ["material_id"],
        ),
    ),
    ToolSpec(
        name="web_extract",
        version="1.0",
        description="提取网页正文（只读快照）。一次最多 3 个网址。",
        parameters=_object(
            {"urls": {"type": "array", "description": "要提取的网址列表", "items": {"type": "string"}}},
            ["urls"],
        ),
    ),
    ToolSpec(
        name="memory_get",
        version="1.0",
        description="读取当前用户的学习记忆，例如考试日期、学习目标。",
        parameters=_object(
            {
                "keys": {
                    "type": "array",
                    "description": "可选，要读取的键；不填返回全部",
                    "items": {"type": "string"},
                }
            },
            [],
        ),
    ),
    ToolSpec(
        name="memory_update",
        version="1.0",
        description="写入当前用户的一条学习记忆。不要写入邮箱、电话、证件号等个人信息。",
        parameters=_object(
            {
                "key": {"type": "string", "description": "记忆键，小写英文和下划线"},
                "value": {"type": "string", "description": "记忆内容"},
            },
            ["key", "value"],
        ),
    ),
)

TOOLS_BY_NAME: Mapping[str, ToolSpec] = MappingProxyType({spec.name: spec for spec in TOOL_SPECS})


def mcp_name_for(tool_name: str) -> str | None:
    return TOOLS_BY_NAME[tool_name].mcp_name


def select_tools(names: Sequence[str]) -> tuple[ToolSpec, ...]:
    unknown = [name for name in names if name not in TOOLS_BY_NAME]
    if unknown:
        raise KeyError(f"unknown tools: {', '.join(unknown)}")
    return tuple(TOOLS_BY_NAME[name] for name in names)
