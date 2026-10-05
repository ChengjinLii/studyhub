from collections.abc import Mapping, Sequence
from typing import Any

from studyhub_agent.contracts.architecture import Accept, FinalDecision, RunContext
from studyhub_agent.contracts.episode import AssistantTurn, Message


class ReactArchitecture:
    """No-op hooks live below the optional architecture implementations."""

    architecture_id = "react"
    version = "1.0"
    prompt_keys: tuple[str, ...] = ()
    required_policy_keys: tuple[str, ...] = ("small",)

    @property
    def contract_parameters(self) -> Mapping[str, Any]:
        return {}

    def on_start(self, ctx: RunContext) -> Sequence[Message]:
        return ()

    def before_step(self, ctx: RunContext, messages: Sequence[Message]) -> Sequence[Message]:
        return messages

    def on_final(self, ctx: RunContext, turn: AssistantTurn) -> FinalDecision:
        return Accept()

    def select_policy(self, ctx: RunContext) -> str:
        return ctx.policy_key
