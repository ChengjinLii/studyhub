from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Literal

from studyhub_agent.contracts.episode import Message, Sampling, TurnKind
from studyhub_agent.contracts.knowledge import CitationCheck, Evidence, KnowledgeModel, SearchResult
from studyhub_agent.contracts.knowledge_citations import check_knowledge_citations
from studyhub_agent.contracts.knowledge_prompts import KNOWLEDGE_PROMPTS, RAG_SYSTEM_KEY
from studyhub_agent.knowledge.retrieval import KnowledgeRetriever
from studyhub_agent.runtime.policy import PolicyClient


class RagAnswer(KnowledgeModel):
    status: Literal["answered", "no_evidence", "invalid_generation", "unverified", "context_budget"]
    answer: str | None
    search: SearchResult
    evidence: tuple[Evidence, ...]
    citations: CitationCheck | None = None


class RagPipeline:
    def __init__(self, retriever: KnowledgeRetriever) -> None:
        self.retriever = retriever

    def run(
        self,
        query: str,
        policy: PolicyClient,
        *,
        count_tokens: Callable[[Sequence[Message]], int],
        mode: str = "hybrid",
        limit: int = 5,
        max_context_tokens: int = 16384,
        max_new_tokens: int = 2048,
    ) -> RagAnswer:
        if not 0 < max_new_tokens < max_context_tokens:
            raise ValueError("generation budget must leave room for the prompt")
        result = self.retriever.search(query, mode=mode, limit=limit)
        evidence = tuple(hit.evidence for hit in result.hits)
        if not evidence:
            return RagAnswer(status="no_evidence", answer=None, search=result, evidence=())
        messages = (
            Message(role="system", content=KNOWLEDGE_PROMPTS.get(RAG_SYSTEM_KEY).text),
            Message(
                role="user",
                content=json.dumps(
                    {"question": query, "evidence": [row.model_dump() for row in evidence]}, ensure_ascii=False
                ),
            ),
        )
        if count_tokens(messages) > max_context_tokens - max_new_tokens:
            return RagAnswer(status="context_budget", answer=None, search=result, evidence=evidence)
        turn = policy.step(messages, (), thinking=False, sampling=Sampling(), max_new_tokens=max_new_tokens)
        if turn.kind != TurnKind.FINAL or not turn.content.strip():
            return RagAnswer(status="invalid_generation", answer=None, search=result, evidence=evidence)
        report = check_knowledge_citations(turn.content, (row.chunk_id for row in evidence))
        return RagAnswer(
            status="answered" if report.ok else "unverified",
            answer=turn.content if report.ok else None,
            search=result,
            evidence=evidence,
            citations=report,
        )
