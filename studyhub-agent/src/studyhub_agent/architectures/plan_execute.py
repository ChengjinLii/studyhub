import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from studyhub_agent.architectures.base import Accept, Continue, FinalDecision, ReactArchitecture, RunContext
from studyhub_agent.contracts.episode import AssistantTurn, Message, TurnKind
from studyhub_agent.contracts.prompts import PLAN_REMINDER_PROMPT_KEY, PLAN_REQUEST_PROMPT_KEY


@dataclass(frozen=True, slots=True)
class PlanExecuteArchitecture(ReactArchitecture):
    max_plan_chars: int = 400
    architecture_id: ClassVar[str] = "plan_execute"
    version: ClassVar[str] = "1.0"
    prompt_keys: ClassVar[tuple[str, ...]] = (PLAN_REQUEST_PROMPT_KEY, PLAN_REMINDER_PROMPT_KEY)

    def __post_init__(self) -> None:
        if type(self.max_plan_chars) is not int or self.max_plan_chars < 1:
            raise ValueError("max_plan_chars must be a positive integer")

    @property
    def contract_parameters(self) -> Mapping[str, Any]:
        return {"max_plan_chars": self.max_plan_chars}

    def on_start(self, ctx: RunContext) -> Sequence[Message]:
        return (self._feedback(ctx, "plan_request", PLAN_REQUEST_PROMPT_KEY),)

    def before_step(self, ctx: RunContext, messages: Sequence[Message]) -> Sequence[Message]:
        self._mark_skipped(ctx)
        if ctx.trace.get("plan"):
            return (*messages, self._feedback(ctx, "plan_reminder", PLAN_REMINDER_PROMPT_KEY))
        return messages

    def on_final(self, ctx: RunContext, turn: AssistantTurn) -> FinalDecision:
        self._mark_skipped(ctx)
        if len(ctx.turns) != 1 or ctx.trace.get("plan_skipped"):
            return Accept()
        plan = turn.content.strip()
        if plan:
            ctx.trace["plan"] = plan[: self.max_plan_chars]
            ctx.trace["plan_truncated"] = len(plan) > self.max_plan_chars
            ctx.trace["plan_turn"] = 0
        else:
            ctx.trace["plan_skipped"] = True
            ctx.trace["plan_skip_reason"] = "empty_plan"
        return Continue((self._feedback(ctx, "execute_plan", PLAN_REMINDER_PROMPT_KEY),), "plan")

    @staticmethod
    def _mark_skipped(ctx: RunContext) -> None:
        if ctx.turns and ctx.turns[0].kind is not TurnKind.FINAL:
            ctx.trace["plan_skipped"] = True
            ctx.trace["plan_skip_reason"] = ctx.turns[0].kind.value

    @staticmethod
    def _feedback(ctx: RunContext, notice: str, prompt_key: str) -> Message:
        payload = {"notice": notice, "instruction": ctx.prompts[prompt_key].text}
        if "plan" in ctx.trace:
            payload["plan"] = ctx.trace["plan"]
        return Message(
            role="tool",
            name="runtime_feedback",
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
