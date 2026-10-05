from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from studyhub_agent.contracts.episode import AssistantTurn, EpisodeSpec, Message, Observation
from studyhub_agent.contracts.prompts import PromptTemplate


@dataclass(frozen=True, slots=True)
class Accept:
    pass


@dataclass(frozen=True, slots=True)
class Continue:
    feedback: tuple[Message, ...]
    reason: str


FinalDecision = Accept | Continue


@dataclass(frozen=True, slots=True)
class RunContext:
    """A per-hook snapshot; only trace is shared mutable architecture state."""

    spec: EpisodeSpec
    turns: tuple[AssistantTurn, ...]
    observations: tuple[Observation, ...]
    prompts: Mapping[str, PromptTemplate]
    trace: dict[str, Any]
    policy_key: str = "small"
    tool_calls_used: int = 0
    parse_errors: int = 0
    count_tokens: Callable[[Sequence[Message]], int] | None = None

    @property
    def read_pages(self) -> frozenset[tuple[int, int]]:
        pages: set[tuple[int, int]] = set()
        for observation in self.observations:
            if not observation.ok or observation.name != "materials_read":
                continue
            evidence = observation.details.get("read_pages", ())
            if not isinstance(evidence, (list, tuple)):
                continue
            for pair in evidence:
                if (
                    isinstance(pair, (list, tuple))
                    and len(pair) == 2
                    and all(type(value) is int and value > 0 for value in pair)
                ):
                    pages.add((pair[0], pair[1]))
        return frozenset(pages)


class Architecture(Protocol):
    architecture_id: str
    version: str
    prompt_keys: tuple[str, ...]
    required_policy_keys: tuple[str, ...]

    @property
    def contract_parameters(self) -> Mapping[str, Any]: ...

    def on_start(self, ctx: RunContext) -> Sequence[Message]: ...

    def before_step(self, ctx: RunContext, messages: Sequence[Message]) -> Sequence[Message]: ...

    def on_final(self, ctx: RunContext, turn: AssistantTurn) -> FinalDecision: ...

    def select_policy(self, ctx: RunContext) -> str: ...
