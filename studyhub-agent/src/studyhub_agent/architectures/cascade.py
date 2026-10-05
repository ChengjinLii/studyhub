import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from studyhub_agent.architectures.base import Continue, FinalDecision, RunContext
from studyhub_agent.architectures.react_verify import ReactVerifyArchitecture
from studyhub_agent.contracts.episode import AssistantTurn, Episode, TurnKind


@dataclass(frozen=True, slots=True)
class CascadeArchitecture(ReactVerifyArchitecture):
    escalate_ratio: float = 0.7
    architecture_id: ClassVar[str] = "cascade"
    version: ClassVar[str] = "1.0"
    required_policy_keys: ClassVar[tuple[str, ...]] = ("small", "large")

    def __post_init__(self) -> None:
        ReactVerifyArchitecture.__post_init__(self)
        if (
            type(self.escalate_ratio) not in (int, float)
            or not math.isfinite(self.escalate_ratio)
            or not 0 < self.escalate_ratio <= 1
        ):
            raise ValueError("escalate_ratio must be a finite number in (0, 1]")

    @property
    def contract_parameters(self) -> Mapping[str, Any]:
        return {"escalate_ratio": self.escalate_ratio, "max_rejections": self.max_rejections}

    def select_policy(self, ctx: RunContext) -> str:
        if "escalated_at" in ctx.trace:
            return "large"
        reason = ctx.trace.get("escalation_pending")
        if not reason and ctx.turns and ctx.turns[-1].kind is TurnKind.PARSE_ERROR:
            reason = "parse_error"
        if not reason and ctx.tool_calls_used >= ctx.spec.budget.max_tool_calls * self.escalate_ratio:
            reason = "tool_calls"
        if not reason and len(ctx.turns) >= ctx.spec.budget.max_turns * self.escalate_ratio:
            reason = "turns"
        if reason:
            ctx.trace.pop("escalation_pending", None)
            ctx.trace["escalated_at"] = len(ctx.turns)
            ctx.trace["escalation_reason"] = reason
            return "large"
        return "small"

    def on_final(self, ctx: RunContext, turn: AssistantTurn) -> FinalDecision:
        decision = ReactVerifyArchitecture.on_final(self, ctx, turn)
        if isinstance(decision, Continue) and ctx.policy_key == "small":
            # Record a request first; exhausting the turn budget is not an actual model handoff.
            ctx.trace["escalation_pending"] = "citation"
        return decision


def cascade_token_cost(episode: Episode) -> float:
    """Parameter-weighted tokens, not monetary cost; uses sampled or canonical completion ids."""
    weights = {"small": 1.0, "large": 2.25}
    total = 0.0
    for turn in episode.turns:
        if turn.policy_key not in weights:
            raise ValueError(f"unknown policy {turn.policy_key!r}")
        completion = turn.sampled_token_ids or turn.canonical_token_ids
        if not turn.prompt_token_ids or not completion:
            raise ValueError("token ids are required for cascade cost; missing data is not zero cost")
        total += (len(turn.prompt_token_ids) + len(completion)) * weights[turn.policy_key]
    return total
