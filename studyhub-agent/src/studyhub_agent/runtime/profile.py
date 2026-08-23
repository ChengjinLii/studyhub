from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentProfile:
    prompt_version: str
    tool_schema_version: str
    max_turns: int
    max_tool_calls: int
    enabled_capabilities: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.prompt_version = self.prompt_version.strip()
        self.tool_schema_version = self.tool_schema_version.strip()
        capabilities = (item.strip() for item in self.enabled_capabilities if item.strip())
        self.enabled_capabilities = list(dict.fromkeys(capabilities))
        if not self.prompt_version or not self.tool_schema_version:
            raise ValueError("prompt and tool schema versions are required")
        if self.max_turns < 1 or self.max_tool_calls < 0:
            raise ValueError("profile budgets must be non-negative and include at least one turn")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AgentProfile:
        return cls(
            prompt_version=str(value["prompt_version"]),
            tool_schema_version=str(value["tool_schema_version"]),
            max_turns=int(value["max_turns"]),
            max_tool_calls=int(value["max_tool_calls"]),
            enabled_capabilities=[str(item) for item in value.get("enabled_capabilities", [])],
        )
