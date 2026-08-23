from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from studyhub_agent.runtime.identity import AgentIdentity
from studyhub_agent.runtime.profile import AgentProfile


@dataclass(slots=True)
class TaskSpec:
    task_id: str
    family: str
    difficulty: str
    user_request: str
    environment_seed: int
    allowed_tools: list[str]
    max_steps: int
    max_tool_calls: int
    metadata: dict[str, Any] = field(default_factory=dict)
    verifier: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.task_id = self.task_id.strip()
        self.family = self.family.strip()
        self.difficulty = self.difficulty.strip()
        self.user_request = self.user_request.strip()
        self.allowed_tools = list(dict.fromkeys(tool.strip() for tool in self.allowed_tools if tool.strip()))
        self.metadata = dict(self.metadata)
        self.verifier = dict(self.verifier)
        if not all((self.task_id, self.family, self.difficulty, self.user_request)):
            raise ValueError("task identity, family, difficulty, and user request are required")
        if self.environment_seed < 0:
            raise ValueError("environment_seed must be non-negative")
        if self.max_steps < 1 or self.max_tool_calls < 0 or self.max_tool_calls > self.max_steps:
            raise ValueError("invalid task step or tool-call budget")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TaskSpec:
        return cls(
            task_id=str(value["task_id"]),
            family=str(value["family"]),
            difficulty=str(value["difficulty"]),
            user_request=str(value["user_request"]),
            environment_seed=int(value["environment_seed"]),
            allowed_tools=[str(item) for item in value.get("allowed_tools", [])],
            max_steps=int(value["max_steps"]),
            max_tool_calls=int(value["max_tool_calls"]),
            metadata=dict(value.get("metadata", {})),
            verifier=dict(value.get("verifier", {})),
        )


@dataclass(frozen=True, slots=True)
class SessionContext:
    identity: AgentIdentity
    task: TaskSpec
    profile: AgentProfile
