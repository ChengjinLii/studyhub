from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from studyhub_agent.contracts.episode import AssistantTurn, Message, Sampling, ToolCall, TurnKind
from studyhub_agent.contracts.tools import ToolSpec
from studyhub_agent.runtime.policy import PolicyInfraError


def tool_turn(*calls: tuple[str, dict], preamble: str = "") -> AssistantTurn:
    tool_calls = tuple(
        ToolCall(call_id=f"call_{i}", name=name, arguments=args) for i, (name, args) in enumerate(calls)
    )
    return AssistantTurn(
        kind=TurnKind.TOOL_CALLS,
        content=preamble,
        tool_calls=tool_calls,
        raw_text="<tool>",
        canonical_text="<tool>",
    )


def final_turn(text: str) -> AssistantTurn:
    return AssistantTurn(kind=TurnKind.FINAL, content=text, raw_text=text, canonical_text=text)


def parse_error_turn(code: str = "malformed_tool_call") -> AssistantTurn:
    return AssistantTurn(kind=TurnKind.PARSE_ERROR, raw_text="<bad", canonical_text="<bad", parse_error=code)


@dataclass
class ScriptedPolicy:
    turns: list[AssistantTurn | Exception]
    seen: list[tuple[Message, ...]] = field(default_factory=list)

    def step(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        thinking: bool,
        sampling: Sampling,
        max_new_tokens: int,
    ) -> AssistantTurn:
        self.seen.append(tuple(messages))
        item = self.turns.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def infra_failure() -> PolicyInfraError:
    return PolicyInfraError("sglang connection refused")


def count_chars(messages: Sequence[Message], tools: Sequence[ToolSpec], thinking: bool) -> int:
    return sum(len(message.content) for message in messages)
