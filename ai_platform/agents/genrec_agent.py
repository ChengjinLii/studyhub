from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ai_platform.harness.tool_policy import ToolPolicy
from ai_platform.memory.user_memory import MockHermesMemoryExtractor
from ai_platform.retrieval.semantic_search import InMemorySemanticSearch, SearchResult
from ai_platform.router.query_understanding import MockQueryUnderstandingRouter
from ai_platform.router.schemas import QueryUnderstanding
from ai_platform.serving.llm_provider import ChatCompletionRequest, ChatMessage, ChatProvider
from ai_platform.serving.rerank_provider import MockRerankProvider, RerankResult
from ai_platform.shared.privacy import sanitize_for_model


@dataclass(frozen=True)
class GenRecResponse:
    understanding: QueryUnderstanding
    retrieved_candidates: list[SearchResult]
    reranked_candidates: list[RerankResult]
    answer: str
    recommended_items: list[dict[str, Any]]
    study_plan: list[dict[str, str]]
    feedback_hooks: list[str]
    memory_candidates: list[dict[str, Any]]
    tool_use_records: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "understanding": self.understanding.to_dict(),
            "retrievedCandidates": [candidate.to_dict() for candidate in self.retrieved_candidates],
            "rerankedCandidates": [candidate.to_dict() for candidate in self.reranked_candidates],
            "answer": self.answer,
            "recommendedItems": self.recommended_items,
            "studyPlan": self.study_plan,
            "feedbackHooks": self.feedback_hooks,
            "memoryCandidates": self.memory_candidates,
            "toolUseRecords": self.tool_use_records,
        }


class GenRecAgent:
    """Candidate-grounded local Agent prototype for the v9 product loop."""

    def __init__(
        self,
        searcher: InMemorySemanticSearch,
        *,
        router: MockQueryUnderstandingRouter | None = None,
        reranker: MockRerankProvider | None = None,
        memory_extractor: MockHermesMemoryExtractor | None = None,
        chat_provider: ChatProvider | None = None,
        tool_policy: ToolPolicy | None = None,
    ) -> None:
        self.searcher = searcher
        self.router = router or MockQueryUnderstandingRouter()
        self.reranker = reranker or MockRerankProvider()
        self.memory_extractor = memory_extractor or MockHermesMemoryExtractor()
        self.chat_provider = chat_provider
        self.tool_policy = tool_policy or ToolPolicy()

    def run(self, query: str, *, top_k: int = 5) -> GenRecResponse:
        self.tool_policy.require("router.understand", queryLength=len(query))
        understanding = self.router.understand(query)
        retrieved = self._retrieve(understanding, top_k=top_k)
        reranked: list[RerankResult] = []
        if retrieved:
            self.tool_policy.require("reranker.rerank", candidateCount=len(retrieved), topK=top_k)
            reranked = self.reranker.rerank(understanding.query_rewrite or query, retrieved, top_k=top_k)
        self.tool_policy.require("genrec.compose", candidateCount=len(reranked), llmEnabled=bool(self.chat_provider))
        composition = _compose_response_with_fallback(understanding, reranked, self.chat_provider)
        feedback_hooks = ["useful", "not_useful", "too_easy", "too_hard", "not_relevant"]
        self.tool_policy.require("memory.extract_candidates", recommendedCount=len(composition["recommended_items"]))
        user_memory = self.memory_extractor.extract_user_candidates(understanding)
        platform_memory = self.memory_extractor.summarize_platform_candidates(
            [item["id"] for item in composition["recommended_items"]]
        )
        return GenRecResponse(
            understanding=understanding,
            retrieved_candidates=retrieved,
            reranked_candidates=reranked,
            answer=composition["answer"],
            recommended_items=composition["recommended_items"],
            study_plan=composition["study_plan"],
            feedback_hooks=feedback_hooks,
            memory_candidates=[candidate.to_dict() for candidate in [*user_memory, *platform_memory]],
            tool_use_records=[record.to_dict() for record in self.tool_policy.records()],
        )

    def _retrieve(self, understanding: QueryUnderstanding, *, top_k: int) -> list[SearchResult]:
        by_id: dict[str, SearchResult] = {}
        for task in understanding.search_tasks:
            type_filter = task.type if task.type in {"material", "column", "request"} else None
            self.tool_policy.require("searchrec.hybrid_retrieval", taskType=task.type, topK=task.top_k)
            for result in self.searcher.search(task.query, top_k=task.top_k, type_filter=type_filter, mode="hybrid"):
                existing = by_id.get(result.document.id)
                if existing is None or result.score > existing.score:
                    by_id[result.document.id] = result
        results = list(by_id.values())
        results.sort(key=lambda item: item.score, reverse=True)
        return results[: max(top_k * 2, top_k)]


def _recommendation_payload(item: RerankResult) -> dict[str, Any]:
    document = item.search_result.document
    return {
        "id": document.id,
        "type": document.type,
        "title": document.title,
        "score": round(item.score, 4),
        "reason": item.reason,
        "metadata": document.metadata,
    }


def _build_answer(understanding: QueryUnderstanding, ranked: list[RerankResult]) -> str:
    ranked = _relevant_ranked_items(ranked)
    course = understanding.entities.course or "这门课"
    if not ranked:
        return "没有找到足够可靠的候选内容，建议先使用普通搜索或换一个更具体的关键词。"
    titles = "、".join(item.search_result.document.title for item in ranked[:2])
    if understanding.intent == "question_help":
        return f"可以先围绕{course}的相关知识点复盘，再参考候选资料中的题目解析：{titles}。"
    if understanding.intent == "study_plan":
        return f"建议先用{titles}建立复习框架，再按真题和经验内容查漏补缺。"
    if understanding.intent == "request_search":
        return f"已优先匹配求购意图，当前最相关的候选是：{titles}。"
    return f"已按你的需求重排候选内容，优先查看：{titles}。"


def _build_study_plan(understanding: QueryUnderstanding, ranked: list[RerankResult]) -> list[dict[str, str]]:
    ranked = _relevant_ranked_items(ranked)
    if understanding.intent not in {"study_plan", "question_help"}:
        return []
    first_title = ranked[0].search_result.document.title if ranked else "候选资料"
    course = understanding.entities.course or "目标课程"
    if understanding.intent == "question_help":
        return [
            {"dayRange": "第 1 步", "task": f"回到{course}对应知识点，先定位题目错误原因。"},
            {"dayRange": "第 2 步", "task": f"参考《{first_title}》中的相近内容补齐概念。"},
            {"dayRange": "第 3 步", "task": "再找 2-3 道相似题做巩固，并记录错因。"},
        ]
    return [
        {"dayRange": "第 1-3 天", "task": f"使用《{first_title}》建立{course}复习框架。"},
        {"dayRange": "第 4-8 天", "task": "按章节刷真题或实验模板，记录薄弱知识点。"},
        {"dayRange": "第 9-14 天", "task": "复盘错题和高频考点，保留最后一天做整卷模拟。"},
    ]


def _compose_response_with_fallback(
    understanding: QueryUnderstanding,
    ranked: list[RerankResult],
    chat_provider: ChatProvider | None,
) -> dict[str, Any]:
    fallback = {
        "answer": _build_answer(understanding, ranked),
        "recommended_items": [_recommendation_payload(item) for item in _relevant_ranked_items(ranked)],
        "study_plan": _build_study_plan(understanding, ranked),
    }
    if not chat_provider or not ranked:
        return fallback
    try:
        response = chat_provider.complete(
            ChatCompletionRequest(
                messages=[
                    ChatMessage(
                        role="system",
                        content=(
                            "You are StudyHub GenRec Agent. Return strict JSON only. "
                            "Use only candidate ids provided by the user. Do not invent ids, links, permissions, contacts, or payment state."
                        ),
                    ),
                    ChatMessage(role="user", content=_composition_prompt(understanding, ranked)),
                ],
                temperature=0.1,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
        )
        return _parse_composition_json(response.content, ranked, fallback=fallback)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError):
        return fallback


def _composition_prompt(understanding: QueryUnderstanding, ranked: list[RerankResult]) -> str:
    candidates = [
        {
            "id": item.search_result.document.id,
            "type": item.search_result.document.type,
            "title": item.search_result.document.title,
            "metadata": item.search_result.document.metadata,
            "rerankReason": item.reason,
        }
        for item in ranked
    ]
    payload = {
            "queryUnderstanding": understanding.to_dict(),
            "candidates": candidates,
            "requiredOutput": {
                "answer": "short Chinese answer grounded in candidates",
                "recommendedItems": [{"id": "candidate id only", "reason": "short grounded reason"}],
                "studyPlan": [{"dayRange": "短阶段", "task": "可执行任务"}],
            },
        }
    return json.dumps(
        sanitize_for_model(payload),
        ensure_ascii=False,
    )


def _parse_composition_json(content: str, ranked: list[RerankResult], *, fallback: dict[str, Any]) -> dict[str, Any]:
    data = _load_json_object(content)
    allowed_by_id = {item.search_result.document.id: item for item in ranked}
    recommended_items: list[dict[str, Any]] = []
    raw_items = data.get("recommendedItems") or data.get("recommended_items")
    if isinstance(raw_items, list):
        for raw_item in raw_items[: len(ranked)]:
            if not isinstance(raw_item, dict):
                continue
            item_id = str(raw_item.get("id") or "")
            if item_id not in allowed_by_id:
                continue
            payload = _recommendation_payload(allowed_by_id[item_id])
            reason = _clean_text(raw_item.get("reason"))
            if reason:
                payload["reason"] = reason
            recommended_items.append(payload)
    if not recommended_items:
        raise ValueError("llm composition did not cite valid candidate ids")

    study_plan: list[dict[str, str]] = []
    raw_plan = data.get("studyPlan") or data.get("study_plan")
    if isinstance(raw_plan, list):
        for raw_step in raw_plan[:6]:
            if not isinstance(raw_step, dict):
                continue
            day_range = _clean_text(raw_step.get("dayRange") or raw_step.get("day_range"))
            task = _clean_text(raw_step.get("task"))
            if day_range and task:
                study_plan.append({"dayRange": day_range, "task": task})

    return {
        "answer": _clean_text(data.get("answer")) or fallback["answer"],
        "recommended_items": recommended_items,
        "study_plan": study_plan if study_plan else fallback["study_plan"],
    }


def _load_json_object(content: str) -> dict[str, Any]:
    stripped = (content or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("composition response must be a JSON object")
    return data


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _relevant_ranked_items(ranked: list[RerankResult]) -> list[RerankResult]:
    if not ranked:
        return []
    top_score = ranked[0].score
    threshold = max(0.12, top_score * 0.55)
    filtered = [item for item in ranked if item.score >= threshold]
    return filtered[:5] if filtered else ranked[:1]
