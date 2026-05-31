from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ai_platform.retrieval.semantic_search import SearchResult
from ai_platform.serving.llm_provider import ChatCompletionRequest, ChatMessage, ChatProvider
from ai_platform.shared.privacy import sanitize_for_model
from ai_platform.shared.prompt_guard import PromptInjectionGuard


@dataclass(frozen=True)
class QuestionTutorRequest:
    question: str
    user_answer: str = ""
    correct_answer: str = ""
    knowledge_points: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuestionTutorResponse:
    explanation: str
    error_reasons: list[str]
    steps: list[str]
    reinforcement_queries: list[str]
    cited_item_ids: list[str]
    fallback_used: bool = False
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "explanation": self.explanation,
            "errorReasons": self.error_reasons,
            "steps": self.steps,
            "reinforcementQueries": self.reinforcement_queries,
            "citedItemIds": self.cited_item_ids,
            "fallbackUsed": self.fallback_used,
            "warnings": list(self.warnings),
        }


class MockQuestionTutor:
    """Local schema-first question tutoring prototype."""

    def explain(self, request: QuestionTutorRequest, *, candidates: list[SearchResult] | None = None) -> QuestionTutorResponse:
        guard_result = PromptInjectionGuard().inspect(" ".join([request.question, request.user_answer, request.correct_answer]))
        course_hint = request.knowledge_points[0] if request.knowledge_points else _infer_knowledge_point(request.question)
        cited_ids = [item.document.id for item in (candidates or [])[:2]]
        return QuestionTutorResponse(
            explanation=f"这道题应先定位到{course_hint}，再检查定义、边界条件和推导步骤是否一致。",
            error_reasons=_mock_error_reasons(request),
            steps=[
                f"回顾{course_hint}的基本定义和适用条件。",
                "逐步对照题干条件，确认每一步推导没有跳过边界情况。",
                "把自己的答案和标准答案差异拆成概念错误、计算错误或表达错误。",
            ],
            reinforcement_queries=[f"{course_hint} 相似题解析", f"{course_hint} 高频错题", f"{course_hint} 知识点巩固"],
            cited_item_ids=cited_ids,
            warnings=guard_result.warnings(),
        )


class LLMQuestionTutor:
    """LLM-backed tutor that can only cite retrieved candidate ids."""

    def __init__(self, chat_provider: ChatProvider, *, fallback: MockQuestionTutor | None = None) -> None:
        self.chat_provider = chat_provider
        self.fallback = fallback or MockQuestionTutor()

    def explain(self, request: QuestionTutorRequest, *, candidates: list[SearchResult] | None = None) -> QuestionTutorResponse:
        fallback_response = self.fallback.explain(request, candidates=candidates)
        guard_result = PromptInjectionGuard().inspect(" ".join([request.question, request.user_answer, request.correct_answer]))
        if guard_result.risky:
            return QuestionTutorResponse(
                explanation=fallback_response.explanation,
                error_reasons=fallback_response.error_reasons,
                steps=fallback_response.steps,
                reinforcement_queries=fallback_response.reinforcement_queries,
                cited_item_ids=fallback_response.cited_item_ids,
                fallback_used=True,
                warnings=tuple(dict.fromkeys((*fallback_response.warnings, *guard_result.warnings(), "llm_tutor_fallback:prompt_injection_guard"))),
            )
        try:
            response = self.chat_provider.complete(
                ChatCompletionRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "You are StudyHub Question Tutor. Return strict JSON only. "
                                "Explain the student's mistake using only the provided question and candidate ids. "
                                "Do not invent cited ids, contacts, payment state, permissions, URLs, or secrets."
                            ),
                        ),
                        ChatMessage(role="user", content=_tutor_prompt(request, candidates or [])),
                    ],
                    temperature=0.1,
                    max_tokens=1000,
                    response_format={"type": "json_object"},
                )
            )
            return parse_tutor_json(response.content, candidates or [], fallback=fallback_response)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            return QuestionTutorResponse(
                explanation=fallback_response.explanation,
                error_reasons=fallback_response.error_reasons,
                steps=fallback_response.steps,
                reinforcement_queries=fallback_response.reinforcement_queries,
                cited_item_ids=fallback_response.cited_item_ids,
                fallback_used=True,
                warnings=(*fallback_response.warnings, f"llm_tutor_fallback:{exc.__class__.__name__}"),
            )


def parse_tutor_json(content: str, candidates: list[SearchResult], *, fallback: QuestionTutorResponse) -> QuestionTutorResponse:
    data = _load_json_object(content)
    allowed_ids = {candidate.document.id for candidate in candidates}
    cited_ids = [item for item in _string_list(data.get("citedItemIds") or data.get("cited_item_ids")) if item in allowed_ids]
    if candidates and not cited_ids:
        raise ValueError("tutor response must cite retrieved candidate ids")
    explanation = _clean_text(data.get("explanation")) or fallback.explanation
    steps = _string_list(data.get("steps"))[:6] or fallback.steps
    error_reasons = _string_list(data.get("errorReasons") or data.get("error_reasons"))[:5] or fallback.error_reasons
    reinforcement_queries = _safe_queries(_string_list(data.get("reinforcementQueries") or data.get("reinforcement_queries"))) or fallback.reinforcement_queries
    return QuestionTutorResponse(
        explanation=explanation,
        error_reasons=error_reasons,
        steps=steps,
        reinforcement_queries=reinforcement_queries,
        cited_item_ids=cited_ids,
    )


def _tutor_prompt(request: QuestionTutorRequest, candidates: list[SearchResult]) -> str:
    payload = {
        "question": request.question,
        "userAnswer": request.user_answer,
        "correctAnswer": request.correct_answer,
        "knowledgePoints": list(request.knowledge_points),
        "candidates": [
            {
                "id": candidate.document.id,
                "type": candidate.document.type,
                "title": candidate.document.title,
                "metadata": candidate.document.metadata,
            }
            for candidate in candidates
        ],
        "requiredOutput": {
            "explanation": "short Chinese explanation",
            "errorReasons": ["specific reason"],
            "steps": ["actionable step"],
            "reinforcementQueries": ["search query for practice"],
            "citedItemIds": ["candidate id only"],
        },
    }
    return json.dumps(sanitize_for_model(payload), ensure_ascii=False)


def _mock_error_reasons(request: QuestionTutorRequest) -> list[str]:
    reasons = ["可能没有先确认题干中的关键条件。"]
    if request.user_answer and request.correct_answer and request.user_answer != request.correct_answer:
        reasons.append("用户答案与参考答案不一致，需要逐步定位差异。")
    if "链表" in request.question:
        reasons.append("链表题常见错误是没有处理空指针、头结点或尾结点边界。")
    return reasons


def _infer_knowledge_point(question: str) -> str:
    if "链表" in question:
        return "链表"
    if "导数" in question or "积分" in question:
        return "微积分"
    if "调制" in question or "信道" in question:
        return "通信原理"
    return "相关知识点"


def _safe_queries(values: list[str]) -> list[str]:
    return [value for value in values[:5] if not re.search(r"api\s*key|token|密码|qq|微信|手机号|http://|https://", value, flags=re.IGNORECASE)]


def _load_json_object(content: str) -> dict[str, Any]:
    stripped = (content or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("tutor response must be a JSON object")
    return data


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()
