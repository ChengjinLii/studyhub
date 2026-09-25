from __future__ import annotations

from typing import Any, Protocol

from studyhub_agent.contracts.episode import EpisodeSpec, Observation, ToolCall
from studyhub_agent.contracts.tools import ToolSpec


class EnvironmentInfraError(RuntimeError):
    """The environment's backing service failed; not the model's fault."""


class Environment(Protocol):
    def reset(self, spec: EpisodeSpec) -> None: ...

    def tool_specs(self) -> tuple[ToolSpec, ...]: ...

    def execute(self, call: ToolCall) -> Observation: ...

    def trace(self) -> dict[str, Any]: ...
