from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from studyhub_agent.contracts.episode import AssistantTurn, Message, Sampling
from studyhub_agent.contracts.tools import ToolSpec


class PolicyInfraError(RuntimeError):
    """The model server failed (timeout, connection, 5xx); the episode is not the model's fault."""


class PolicyClient(Protocol):
    def step(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        thinking: bool,
        sampling: Sampling,
        max_new_tokens: int,
    ) -> AssistantTurn: ...
