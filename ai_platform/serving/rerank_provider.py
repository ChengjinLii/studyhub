from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from ai_platform.retrieval.semantic_search import SearchResult
from ai_platform.serving.llm_provider import ChatCompletionRequest, ChatMessage, ChatProvider
from ai_platform.shared.mock_embedding import expand_tokens, tokenize
from ai_platform.shared.privacy import sanitize_for_model


@dataclass(frozen=True)
class RerankResult:
    search_result: SearchResult
    score: float
    reason: str

    def to_dict(self) -> dict[str, object]:
        payload = self.search_result.to_dict()
        payload["rerankScore"] = round(self.score, 4)
        payload["rerankReason"] = self.reason
        return payload


class RerankProvider(Protocol):
    name: str

    def rerank(self, query: str, candidates: list[SearchResult], *, top_k: int = 5) -> list[RerankResult]:
        ...


class MockRerankProvider:
    """Local reranker with the same call shape as a future external rerank API."""

    name = "mock-lexical-reranker"

    def rerank(self, query: str, candidates: list[SearchResult], *, top_k: int = 5) -> list[RerankResult]:
        query_terms = _important_terms(query)
        ranked: list[RerankResult] = []
        for candidate in candidates:
            doc = candidate.document
            doc_terms = _important_terms(doc.searchable_text)
            overlap = len(query_terms & doc_terms)
            normalized_overlap = overlap / max(1, len(query_terms))
            semantic_bonus = min(candidate.dense_score, 1.0) * 0.1
            sparse_bonus = min(candidate.sparse_score, 2.0) * 0.03
            exact_title_bonus = _title_bonus(query_terms, _important_terms(doc.title))
            score = normalized_overlap * 0.74 + exact_title_bonus + semantic_bonus + sparse_bonus
            reason = _build_reason(query_terms, doc_terms, doc.title)
            ranked.append(RerankResult(search_result=candidate, score=score, reason=reason))
        ranked.sort(key=lambda item: (item.score, item.search_result.score), reverse=True)
        return ranked[: max(1, top_k)]


class ChatRerankProvider:
    """Chat-provider based reranker with deterministic fallback.

    This is useful when the configured model does not expose a dedicated rerank
    endpoint. It validates candidate ids and scores before accepting output.
    """

    name = "chat-reranker"

    def __init__(self, chat_provider: ChatProvider, *, fallback: MockRerankProvider | None = None) -> None:
        self.chat_provider = chat_provider
        self.fallback = fallback or MockRerankProvider()

    def rerank(self, query: str, candidates: list[SearchResult], *, top_k: int = 5) -> list[RerankResult]:
        fallback_results = self.fallback.rerank(query, candidates, top_k=top_k)
        if not candidates:
            return []
        try:
            response = self.chat_provider.complete(
                ChatCompletionRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "You are StudyHub's rerank model. Return strict JSON only. "
                                "Use only candidate ids from the user payload. Do not invent ids."
                            ),
                        ),
                        ChatMessage(role="user", content=_rerank_prompt(query, candidates, top_k=top_k)),
                    ],
                    temperature=0.0,
                    max_tokens=900,
                    response_format={"type": "json_object"},
                )
            )
            return _parse_chat_rerank_json(response.content, candidates, fallback_results=fallback_results, top_k=top_k)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError):
            return fallback_results


def _important_terms(text: str) -> set[str]:
    return {token for token in expand_tokens(tokenize(text)) if len(token) > 1}


def _title_bonus(query_terms: set[str], title_terms: set[str]) -> float:
    if not query_terms:
        return 0.0
    return min(0.32, len(query_terms & title_terms) / len(query_terms) * 0.42)


def _build_reason(query_terms: set[str], doc_terms: set[str], title: str) -> str:
    matched = sorted(query_terms & doc_terms)
    if matched:
        preview = "、".join(matched[:4])
        return f"候选内容《{title}》命中了 {preview} 等查询要点。"
    return f"候选内容《{title}》保留为语义召回结果，可作为兜底参考。"


def _rerank_prompt(query: str, candidates: list[SearchResult], *, top_k: int) -> str:
    payload = {
            "query": query,
            "topK": top_k,
            "candidates": [
                {
                    "id": candidate.document.id,
                    "type": candidate.document.type,
                    "title": candidate.document.title,
                    "text": candidate.document.text[:500],
                    "metadata": candidate.document.metadata,
                }
                for candidate in candidates[:20]
            ],
            "requiredOutput": {
                "ranked": [
                    {
                        "id": "candidate id only",
                        "score": "float from 0 to 1",
                        "reason": "short Chinese reason grounded in candidate content",
                    }
                ]
            },
        }
    return json.dumps(
        sanitize_for_model(payload),
        ensure_ascii=False,
    )


def _parse_chat_rerank_json(
    content: str,
    candidates: list[SearchResult],
    *,
    fallback_results: list[RerankResult],
    top_k: int,
) -> list[RerankResult]:
    data = _load_json_object(content)
    raw_ranked = data.get("ranked")
    if not isinstance(raw_ranked, list):
        raise ValueError("rerank response missing ranked list")
    candidates_by_id = {candidate.document.id: candidate for candidate in candidates}
    results: list[RerankResult] = []
    seen: set[str] = set()
    for item in raw_ranked:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("id") or "")
        if candidate_id in seen or candidate_id not in candidates_by_id:
            continue
        seen.add(candidate_id)
        score = _bounded_score(item.get("score"))
        reason = _clean_reason(item.get("reason")) or "由 Chat rerank provider 判定为相关候选。"
        results.append(RerankResult(search_result=candidates_by_id[candidate_id], score=score, reason=reason))
    if not results:
        raise ValueError("rerank response did not cite valid candidate ids")
    results.sort(key=lambda result: result.score, reverse=True)
    if len(results) < min(top_k, len(candidates)):
        existing_ids = {result.search_result.document.id for result in results}
        results.extend(result for result in fallback_results if result.search_result.document.id not in existing_ids)
    return results[: max(1, top_k)]


def _load_json_object(content: str) -> dict[str, object]:
    stripped = (content or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("rerank response must be a JSON object")
    return data


def _bounded_score(value: object) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _clean_reason(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:160]
