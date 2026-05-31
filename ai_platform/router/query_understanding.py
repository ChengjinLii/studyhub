from __future__ import annotations

import json
import re
from typing import Any

from ai_platform.router.prompt_templates import QUERY_UNDERSTANDING_SYSTEM_PROMPT, QUERY_UNDERSTANDING_USER_TEMPLATE
from ai_platform.router.schemas import QueryEntities, QueryUnderstanding, SearchTask
from ai_platform.serving.llm_provider import ChatCompletionRequest, ChatMessage, ChatProvider
from ai_platform.shared.privacy import sanitize_for_model
from ai_platform.shared.prompt_guard import PromptInjectionGuard


COURSE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("通信原理", ("通信原理", "通原")),
    ("数据结构", ("数据结构", "链表", "二叉树", "图算法", "排序算法")),
    ("高等数学", ("高等数学", "高数", "微积分", "导数", "积分")),
)

MATERIAL_TYPE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("速成资料", ("速成", "冲刺", "速查")),
    ("真题解析", ("真题", "历年题", "试卷", "答案解析")),
    ("实验报告", ("实验报告", "模板")),
    ("课程笔记", ("笔记", "知识点", "重点")),
    ("经验分享", ("经验", "备考", "复习顺序")),
)

KNOWLEDGE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("调制解调", ("调制", "解调")),
    ("信道编码", ("信道编码", "编码")),
    ("随机过程", ("随机过程",)),
    ("链表", ("链表",)),
    ("二叉树", ("二叉树", "树")),
    ("图算法", ("图算法", "最短路", "图")),
    ("微积分", ("微积分", "导数", "积分", "极限")),
)


class MockQueryUnderstandingRouter:
    """Deterministic local router that mirrors the future LLM JSON contract."""

    def understand(self, query: str) -> QueryUnderstanding:
        normalized = _normalize(query)
        guard_result = PromptInjectionGuard().inspect(normalized)
        if not normalized:
            return QueryUnderstanding(
                raw_query=query,
                intent="material_search",
                query_rewrite="",
                entities=QueryEntities(),
                search_tasks=(SearchTask(type="material", query="", top_k=5),),
                fallback_used=True,
                warnings=("empty_query",),
            )

        entities = QueryEntities(
            course=_find_alias(normalized, COURSE_ALIASES),
            school="电子科技大学" if "电子科技大学" in normalized or "成电" in normalized else None,
            exam_time=_find_exam_time(normalized),
            level=_find_level(normalized),
            material_types=tuple(_find_all_aliases(normalized, MATERIAL_TYPE_ALIASES)),
            knowledge_points=tuple(_find_all_aliases(normalized, KNOWLEDGE_ALIASES)),
            budget=_find_budget(normalized),
        )
        intent = _infer_intent(normalized, entities)
        rewrite = _rewrite_query(normalized, entities, intent)
        tasks = tuple(_build_search_tasks(rewrite, intent, entities))
        return QueryUnderstanding(
            raw_query=query,
            intent=intent,
            query_rewrite=rewrite,
            entities=entities,
            search_tasks=tasks,
            suggestions=tuple(_build_suggestions(entities, intent)),
            warnings=guard_result.warnings(),
        )


class LLMQueryUnderstandingRouter:
    """LLM-backed router with strict parsing and deterministic fallback."""

    def __init__(self, chat_provider: ChatProvider, *, fallback: MockQueryUnderstandingRouter | None = None) -> None:
        self.chat_provider = chat_provider
        self.fallback = fallback or MockQueryUnderstandingRouter()

    def understand(self, query: str) -> QueryUnderstanding:
        fallback_result = self.fallback.understand(query)
        guard_result = PromptInjectionGuard().inspect(query)
        if guard_result.risky:
            return QueryUnderstanding(
                raw_query=fallback_result.raw_query,
                intent=fallback_result.intent,
                query_rewrite=fallback_result.query_rewrite,
                entities=fallback_result.entities,
                search_tasks=fallback_result.search_tasks,
                suggestions=fallback_result.suggestions,
                fallback_used=True,
                warnings=tuple(dict.fromkeys((*fallback_result.warnings, *guard_result.warnings(), "llm_router_fallback:prompt_injection_guard"))),
            )
        try:
            response = self.chat_provider.complete(
                ChatCompletionRequest(
                    messages=[
                        ChatMessage(role="system", content=QUERY_UNDERSTANDING_SYSTEM_PROMPT),
                        ChatMessage(role="user", content=QUERY_UNDERSTANDING_USER_TEMPLATE.format(query=sanitize_for_model(query))),
                    ],
                    temperature=0.0,
                    max_tokens=900,
                    response_format={"type": "json_object"},
                )
            )
            return parse_query_understanding_json(query, response.content, fallback_result=fallback_result)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            return QueryUnderstanding(
                raw_query=fallback_result.raw_query,
                intent=fallback_result.intent,
                query_rewrite=fallback_result.query_rewrite,
                entities=fallback_result.entities,
                search_tasks=fallback_result.search_tasks,
                suggestions=fallback_result.suggestions,
                fallback_used=True,
                warnings=(*fallback_result.warnings, f"llm_router_fallback:{exc.__class__.__name__}"),
            )


def parse_query_understanding_json(
    raw_query: str,
    content: str,
    *,
    fallback_result: QueryUnderstanding | None = None,
) -> QueryUnderstanding:
    data = _load_json_object(content)
    fallback = fallback_result or MockQueryUnderstandingRouter().understand(raw_query)
    intent = _safe_intent(str(data.get("intent") or fallback.intent), fallback.intent)
    query_rewrite = _normalize(str(data.get("queryRewrite") or data.get("query_rewrite") or fallback.query_rewrite or raw_query))
    entities = _parse_entities(data.get("entities"), fallback.entities)
    tasks = tuple(_parse_search_tasks(data.get("searchTasks") or data.get("search_tasks"), fallback.search_tasks))
    if not tasks:
        tasks = fallback.search_tasks
    suggestions = tuple(_string_list(data.get("suggestions"))) or fallback.suggestions
    return QueryUnderstanding(
        raw_query=raw_query,
        intent=intent,
        query_rewrite=query_rewrite,
        entities=entities,
        search_tasks=tasks,
        suggestions=suggestions,
        fallback_used=False,
        warnings=tuple(_string_list(data.get("warnings"))),
    )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _load_json_object(content: str) -> dict[str, Any]:
    stripped = (content or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("router response must be a JSON object")
    return data


def _safe_intent(value: str, fallback: str) -> str:
    allowed = {"material_search", "request_search", "experience_search", "study_plan", "question_help"}
    return value if value in allowed else fallback


def _parse_entities(value: object, fallback: QueryEntities) -> QueryEntities:
    if not isinstance(value, dict):
        return fallback
    return QueryEntities(
        course=_optional_str(value.get("course"), fallback.course),
        school=_optional_str(value.get("school"), fallback.school),
        college=_optional_str(value.get("college"), fallback.college),
        major=_optional_str(value.get("major"), fallback.major),
        grade=_optional_str(value.get("grade"), fallback.grade),
        exam_time=_optional_str(value.get("examTime") or value.get("exam_time"), fallback.exam_time),
        level=_optional_str(value.get("level"), fallback.level),
        material_types=tuple(_string_list(value.get("materialTypes") or value.get("material_types"))) or fallback.material_types,
        knowledge_points=tuple(_string_list(value.get("knowledgePoints") or value.get("knowledge_points"))) or fallback.knowledge_points,
        budget=_optional_str(value.get("budget"), fallback.budget),
    )


def _parse_search_tasks(value: object, fallback: tuple[SearchTask, ...]) -> list[SearchTask]:
    if not isinstance(value, list):
        return list(fallback)
    tasks: list[SearchTask] = []
    for item in value[:6]:
        if not isinstance(item, dict):
            continue
        task_type = str(item.get("type") or "material")
        if task_type not in {"material", "column", "request"}:
            task_type = "material"
        query = _normalize(str(item.get("query") or ""))
        if not query:
            continue
        top_k = item.get("topK") or item.get("top_k") or 5
        try:
            parsed_top_k = min(max(int(top_k), 1), 10)
        except (TypeError, ValueError):
            parsed_top_k = 5
        tasks.append(SearchTask(type=task_type, query=query, top_k=parsed_top_k))
    return tasks


def _optional_str(value: object, fallback: str | None) -> str | None:
    if value is None:
        return fallback
    normalized = _normalize(str(value))
    return normalized or fallback


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    for item in value:
        normalized = _normalize(str(item))
        if normalized:
            values.append(normalized)
    return values


def _find_alias(text: str, aliases: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    for canonical, terms in aliases:
        if any(term in text for term in terms):
            return canonical
    return None


def _find_all_aliases(text: str, aliases: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
    values: list[str] = []
    for canonical, terms in aliases:
        if any(term in text for term in terms):
            values.append(canonical)
    return values


def _find_exam_time(text: str) -> str | None:
    if "两周" in text or "2周" in text:
        return "两周后"
    if "期末" in text:
        return "期末"
    if "考前" in text:
        return "考前"
    return None


def _find_level(text: str) -> str | None:
    if "基础一般" in text or "基础差" in text or "零基础" in text:
        return "基础一般"
    if "基础好" in text or "有基础" in text:
        return "有基础"
    return None


def _find_budget(text: str) -> str | None:
    match = re.search(r"预算\s*(\d+)|(\d+)\s*元", text)
    if not match:
        return None
    return next(group for group in match.groups() if group)


def _infer_intent(text: str, entities: QueryEntities) -> str:
    if any(term in text for term in ("为什么", "错了", "讲解", "这道题", "题目")):
        return "question_help"
    if any(term in text for term in ("安排", "计划", "两周", "复习路径", "怎么复习")):
        return "study_plan"
    if any(term in text for term in ("求购", "求 ", "求", "需要")) and "报告" in text:
        return "request_search"
    if "求购" in text or text.startswith("求") or "有没有" in text and entities.material_types:
        return "request_search"
    if "经验" in text:
        return "experience_search"
    return "material_search"


def _rewrite_query(text: str, entities: QueryEntities, intent: str) -> str:
    parts = [value for value in (entities.course, entities.exam_time, *entities.material_types) if value]
    if intent == "question_help":
        parts.extend(entities.knowledge_points)
        parts.append("题目 讲解")
    elif intent == "study_plan":
        parts.extend(("复习", "资料", "真题"))
    elif intent == "experience_search":
        parts.append("备考经验")
    elif intent == "request_search":
        parts.append("求购")
    if not parts:
        return text
    deduped = list(dict.fromkeys(parts))
    return " ".join(deduped)


def _build_search_tasks(rewrite: str, intent: str, entities: QueryEntities) -> list[SearchTask]:
    if intent == "question_help":
        question_query = " ".join(part for part in (entities.course, *entities.knowledge_points, "题目 解析") if part)
        return [SearchTask(type="material", query=question_query or rewrite, top_k=5)]
    if intent == "study_plan":
        course = entities.course or rewrite
        return [
            SearchTask(type="material", query=f"{course} 期末 速成 笔记", top_k=5),
            SearchTask(type="material", query=f"{course} 真题 解析", top_k=5),
            SearchTask(type="column", query=f"{course} 复习 经验", top_k=3),
        ]
    if intent == "request_search":
        return [SearchTask(type="request", query=rewrite, top_k=5)]
    if intent == "experience_search":
        return [SearchTask(type="column", query=rewrite, top_k=5)]
    return [SearchTask(type="material", query=rewrite, top_k=5)]


def _build_suggestions(entities: QueryEntities, intent: str) -> list[str]:
    course = entities.course or "课程"
    if intent == "question_help":
        return [f"{course} 相似题解析", f"{course} 高频错题", f"{course} 知识点巩固"]
    if intent == "study_plan":
        return [f"{course} 两周复习计划", f"{course} 期末真题解析", f"{course} 速成笔记"]
    return [f"{course} 期末资料", f"{course} 真题解析", f"{course} 复习经验"]
