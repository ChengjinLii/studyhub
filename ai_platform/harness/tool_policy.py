from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_ALLOWED_TOOLS = frozenset(
    {
        "router.understand",
        "searchrec.hybrid_retrieval",
        "reranker.rerank",
        "genrec.compose",
        "memory.extract_candidates",
    }
)


class ToolPolicyError(RuntimeError):
    """Raised when an Agent tries to use a tool outside its allow-list."""


@dataclass(frozen=True)
class ToolUseRecord:
    name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "metadata": self.metadata}


class ToolPolicy:
    """Small Engineering Harness allow-list for isolated Agent prototypes."""

    def __init__(self, allowed_tools: set[str] | frozenset[str] | None = None) -> None:
        self.allowed_tools = frozenset(allowed_tools or DEFAULT_ALLOWED_TOOLS)
        self._records: list[ToolUseRecord] = []

    def require(self, tool_name: str, **metadata: Any) -> None:
        if tool_name not in self.allowed_tools:
            raise ToolPolicyError(f"tool is not allowed: {tool_name}")
        self._records.append(ToolUseRecord(name=tool_name, metadata=_safe_metadata(metadata)))

    def records(self) -> list[ToolUseRecord]:
        return list(self._records)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowedTools": sorted(self.allowed_tools),
            "records": [record.to_dict() for record in self._records],
        }


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, (list, tuple, set)):
            safe[key] = [item for item in value if isinstance(item, (str, int, float, bool))]
        else:
            safe[key] = str(type(value).__name__)
    return safe
