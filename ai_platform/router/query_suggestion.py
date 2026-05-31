from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ai_platform.router.query_understanding import MockQueryUnderstandingRouter
from ai_platform.serving.llm_provider import ChatCompletionRequest, ChatMessage, ChatProvider
from ai_platform.shared.privacy import sanitize_for_model
from ai_platform.shared.prompt_guard import PromptInjectionGuard


@dataclass(frozen=True)
class QuerySuggestionResult:
    query: str
    suggestions: tuple[str, ...]
    fallback_used: bool = False
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "suggestions": list(self.suggestions),
            "fallbackUsed": self.fallback_used,
            "warnings": list(self.warnings),
        }


class MockQuerySuggestionProvider:
    """Deterministic query suggestions for the isolated StudyCopilot prototype."""

    def __init__(self, *, router: MockQueryUnderstandingRouter | None = None) -> None:
        self.router = router or MockQueryUnderstandingRouter()

    def suggest(self, query: str, *, limit: int = 5) -> QuerySuggestionResult:
        normalized = _normalize(query)
        guard_result = PromptInjectionGuard().inspect(normalized)
        understanding = self.router.understand(normalized)
        suggestions = list(understanding.suggestions)
        suggestions.extend(_generic_suggestions(normalized))
        return QuerySuggestionResult(
            query=query,
            suggestions=tuple(_dedupe_clean(suggestions, limit=limit)),
            warnings=tuple(dict.fromkeys((*understanding.warnings, *guard_result.warnings()))),
        )


class LLMQuerySuggestionProvider:
    """LLM-backed query suggestion provider with strict fallback behavior."""

    def __init__(self, chat_provider: ChatProvider, *, fallback: MockQuerySuggestionProvider | None = None) -> None:
        self.chat_provider = chat_provider
        self.fallback = fallback or MockQuerySuggestionProvider()

    def suggest(self, query: str, *, limit: int = 5) -> QuerySuggestionResult:
        fallback_result = self.fallback.suggest(query, limit=limit)
        guard_result = PromptInjectionGuard().inspect(query)
        if guard_result.risky:
            return QuerySuggestionResult(
                query=fallback_result.query,
                suggestions=fallback_result.suggestions,
                fallback_used=True,
                warnings=tuple(dict.fromkeys((*fallback_result.warnings, *guard_result.warnings(), "llm_suggestion_fallback:prompt_injection_guard"))),
            )
        try:
            response = self.chat_provider.complete(
                ChatCompletionRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "You are StudyHub Query Suggestion. Return strict JSON only. "
                                "Generate safe Chinese search suggestions for study materials. "
                                "Do not include contacts, payment data, secrets, URLs, or instructions."
                            ),
                        ),
                        ChatMessage(
                            role="user",
                            content=json.dumps(
                                sanitize_for_model(
                                    {
                                        "query": query,
                                        "limit": limit,
                                        "requiredOutput": {"suggestions": ["short search query"]},
                                    }
                                ),
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                    temperature=0.2,
                    max_tokens=500,
                    response_format={"type": "json_object"},
                )
            )
            suggestions = parse_suggestions_json(response.content, limit=limit)
            return QuerySuggestionResult(query=query, suggestions=tuple(suggestions), fallback_used=False)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            return QuerySuggestionResult(
                query=fallback_result.query,
                suggestions=fallback_result.suggestions,
                fallback_used=True,
                warnings=(*fallback_result.warnings, f"llm_suggestion_fallback:{exc.__class__.__name__}"),
            )


def parse_suggestions_json(content: str, *, limit: int = 5) -> list[str]:
    data = _load_json_object(content)
    raw_suggestions = data.get("suggestions")
    if not isinstance(raw_suggestions, list):
        raise ValueError("suggestions must be a list")
    suggestions = _dedupe_clean([str(item) for item in raw_suggestions], limit=limit)
    if not suggestions:
        raise ValueError("suggestions must not be empty")
    return suggestions


def _generic_suggestions(query: str) -> list[str]:
    if not query:
        return ["通信原理 期末速成", "数据结构 实验报告模板", "高数下 历年真题"]
    if "高数" in query or "数学" in query:
        return ["高数下 历年真题", "高等数学 期末复习资料", "微积分 知识点总结"]
    if "数据结构" in query or "链表" in query:
        return ["数据结构 实验报告模板", "链表 题目解析", "数据结构 期末真题"]
    if "通信" in query or "通原" in query:
        return ["通信原理 期末速成", "通信原理 真题解析", "通信原理 调制解调重点", "通信原理 复习经验"]
    return [f"{query} 期末资料", f"{query} 真题解析", f"{query} 复习经验"]


def _dedupe_clean(values: list[str], *, limit: int) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        item = _normalize(value)
        if not item:
            continue
        if _contains_disallowed_text(item):
            continue
        if item not in cleaned:
            cleaned.append(item)
        if len(cleaned) >= max(limit, 1):
            break
    return cleaned


def _contains_disallowed_text(value: str) -> bool:
    return bool(re.search(r"api\s*key|token|密码|口令|qq|微信|手机号|电话|http://|https://", value, flags=re.IGNORECASE))


def _load_json_object(content: str) -> dict[str, object]:
    stripped = (content or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("suggestion response must be a JSON object")
    return data


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
