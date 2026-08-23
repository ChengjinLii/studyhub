from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    pass


@dataclass(slots=True)
class BudgetState:
    max_steps: int
    max_tool_calls: int
    steps: int = 0
    tool_calls: int = 0
    tool_history: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.max_tool_calls < 0 or self.max_tool_calls > self.max_steps:
            raise ValueError("invalid step or tool-call budget")

    def record_model_step(self) -> None:
        if self.steps >= self.max_steps:
            raise BudgetExceeded("step budget exhausted")
        self.steps += 1

    def authorize_tool(self, tool_name: str, arguments_fingerprint: str) -> None:
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded("tool-call budget exhausted")
        self.tool_calls += 1
        self.tool_history.append((tool_name, arguments_fingerprint))

    @property
    def duplicate_tool_calls(self) -> int:
        return len(self.tool_history) - len(set(self.tool_history))
