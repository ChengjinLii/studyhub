import json
from dataclasses import dataclass
from typing import ClassVar

from studyhub_agent.architectures.base import Accept, Continue, FinalDecision, ReactArchitecture, RunContext
from studyhub_agent.contracts.episode import AssistantTurn, Message
from studyhub_agent.contracts.knowledge_citations import check_knowledge_citations
from studyhub_agent.contracts.knowledge_prompts import KNOWLEDGE_VERIFY_KEY


@dataclass(frozen=True, slots=True)
class KnowledgeVerifyArchitecture(ReactArchitecture):
    architecture_id: ClassVar[str] = "knowledge_verify"
    version: ClassVar[str] = "1.0"
    prompt_keys: ClassVar[tuple[str, ...]] = (KNOWLEDGE_VERIFY_KEY,)

    def on_final(self, ctx: RunContext, turn: AssistantTurn) -> FinalDecision:
        evidence = {
            key
            for observation in ctx.observations
            if observation.ok and observation.name in {"search_knowledge", "read_document"}
            for key in observation.details.get("evidence_ids", ())
        }
        report = check_knowledge_citations(turn.content, evidence)
        ctx.trace.setdefault("citation_checks", []).append(report.model_dump())
        ctx.trace["citation_verified"] = report.ok
        if report.ok:
            return Accept()
        # Invalid citations never become a successful answer merely because retries ran out.
        # The existing runner's turn/token budgets bound repair attempts.
        feedback = {
            **report.model_dump(),
            "available_evidence_ids": sorted(evidence),
            "instruction": ctx.prompts[KNOWLEDGE_VERIFY_KEY].text,
        }
        return Continue(
            feedback=(Message(role="tool", name="runtime_feedback", content=json.dumps(feedback, ensure_ascii=False)),),
            reason="knowledge_citation",
        )
