import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from studyhub_agent.architectures.base import Accept, Continue, FinalDecision, ReactArchitecture, RunContext
from studyhub_agent.architectures.citations import check_citations
from studyhub_agent.contracts.episode import AssistantTurn, Message
from studyhub_agent.contracts.prompts import VERIFY_FEEDBACK_PROMPT_KEY


@dataclass(frozen=True, slots=True)
class ReactVerifyArchitecture(ReactArchitecture):
    max_rejections: int = 2
    architecture_id: ClassVar[str] = "react_verify"
    version: ClassVar[str] = "1.0"
    prompt_keys: ClassVar[tuple[str, ...]] = (VERIFY_FEEDBACK_PROMPT_KEY,)

    def __post_init__(self) -> None:
        if type(self.max_rejections) is not int or self.max_rejections < 0:
            raise ValueError("max_rejections must be a non-negative integer")

    @property
    def contract_parameters(self) -> Mapping[str, Any]:
        return {"max_rejections": self.max_rejections}

    def on_final(self, ctx: RunContext, turn: AssistantTurn) -> FinalDecision:
        report = check_citations(turn.content, ctx.read_pages)
        ctx.trace.setdefault("citation_checks", []).append(
            {
                "turn": len(ctx.turns) - 1,
                "ok": report.ok,
                "cited": [list(pair) for pair in report.cited],
                "unread": [list(pair) for pair in report.unread],
                "missing": report.missing,
                "invalid": report.invalid,
            }
        )
        ctx.trace["citation_verified"] = report.ok
        rejections = ctx.trace.get("verify_rejections", 0)
        if report.ok:
            return Accept()
        if rejections >= self.max_rejections:
            # This is a bounded repair strategy, not a safety gate or an entailment checker.
            ctx.trace["verify_limit_reached"] = True
            return Accept()
        ctx.trace["verify_rejections"] = rejections + 1
        feedback = Message(
            role="tool",
            name="runtime_feedback",
            content=json.dumps(
                {
                    "notice": "citation_check_failed",
                    "unread": report.unread,
                    "missing": report.missing,
                    "invalid": report.invalid,
                    "read_pages": sorted(ctx.read_pages),
                    "instruction": ctx.prompts[VERIFY_FEEDBACK_PROMPT_KEY].text,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        return Continue(feedback=(feedback,), reason="citation")
