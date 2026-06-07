from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.models.materials import MaterialRecord
from app.services.agent_memory_service import AgentMemoryContext
from app.services.material_pdf_evidence_service import MaterialPageEvidence


COURSE_ALIASES: dict[str, tuple[str, ...]] = {
    "通信原理": ("通信原理", "cps"),
    "信号与系统": ("信号与系统", "signals", "signal"),
    "数据结构": ("数据结构",),
    "高等数学": ("高数", "高等数学", "微积分"),
    "概率论": ("概率论",),
}

INTENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("exam_trend_analysis", ("常考", "往年", "历年", "真题", "题型", "考点", "期末题")),
    ("study_plan", ("复习计划", "怎么复习", "两周", "一周", "考试", "规划", "速成")),
    ("pdf_summary", ("这份资料", "这几份", "总结", "讲什么", "内容是什么", "概括")),
    ("problem_tutoring", ("错题", "不会", "怎么做", "讲解", "解析一下", "为什么")),
    ("material_recommendation", ("推荐", "找", "资料", "笔记", "讲义", "求资料")),
)

RESOURCE_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("past_exam", ("真题", "往年", "历年", "试卷", "期末题")),
    ("answer_explanation", ("解析", "答案", "标答", "讲解")),
    ("notes", ("笔记", "讲义", "导图")),
    ("crash_course", ("速成", "提纲", "复习")),
    ("experience", ("经验", "经验贴", "攻略")),
)

LOW_VALUE_TERMS = {
    "帮我",
    "一下",
    "这个",
    "那个",
    "资料",
    "怎么",
    "如何",
    "什么",
    "有没有",
    "可以",
    "现在",
    "当前",
}


@dataclass(slots=True)
class AgentQueryPlan:
    intent: str
    confidence: float
    course_terms: tuple[str, ...]
    resource_types: tuple[str, ...]
    years: tuple[str, ...]
    search_terms: tuple[str, ...]
    evidence_tasks: tuple[str, ...]
    response_guidance: tuple[str, ...]

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "course_terms": list(self.course_terms),
            "resource_types": list(self.resource_types),
            "years": list(self.years),
            "search_terms": list(self.search_terms),
            "evidence_tasks": list(self.evidence_tasks),
            "response_guidance": list(self.response_guidance),
        }


class AgentQueryPlannerService:
    """Deterministic query understanding for the StudyHub Agent.

    The planner is intentionally cheap: it uses only the user query and already
    gathered candidates/evidence/memory. It does not add database queries or
    network calls, so it can run on every Agent request.
    """

    def build_plan(
        self,
        query: str,
        *,
        materials: list[MaterialRecord],
        pdf_evidence: list[MaterialPageEvidence],
        memory_context: AgentMemoryContext | None,
    ) -> AgentQueryPlan:
        normalized = query.strip().lower()
        intent, confidence = _detect_intent(normalized)
        course_terms = _extract_course_terms(normalized, materials)
        resource_types = _extract_resource_types(normalized, materials)
        years = _extract_years(normalized, pdf_evidence, memory_context)
        search_terms = _extract_search_terms(normalized, course_terms, resource_types)
        evidence_tasks = _build_evidence_tasks(intent, pdf_evidence, memory_context)
        response_guidance = _build_response_guidance(intent, bool(pdf_evidence), memory_context is not None)
        return AgentQueryPlan(
            intent=intent,
            confidence=confidence,
            course_terms=tuple(course_terms),
            resource_types=tuple(resource_types),
            years=tuple(years),
            search_terms=tuple(search_terms),
            evidence_tasks=tuple(evidence_tasks),
            response_guidance=tuple(response_guidance),
        )


def _detect_intent(normalized_query: str) -> tuple[str, float]:
    best_intent = "material_recommendation"
    best_hits = 0
    for intent, terms in INTENT_RULES:
        hits = sum(1 for term in terms if term.lower() in normalized_query)
        if hits > best_hits:
            best_intent = intent
            best_hits = hits
    if best_hits <= 0:
        return "general_learning_support", 0.35
    return best_intent, min(0.95, 0.5 + best_hits * 0.15)


def _extract_course_terms(normalized_query: str, materials: list[MaterialRecord]) -> list[str]:
    found: list[str] = []
    for canonical, aliases in COURSE_ALIASES.items():
        if any(alias.lower() in normalized_query for alias in aliases):
            found.append(canonical)
    if found:
        return found[:4]
    for material in materials[:5]:
        for value in (material.major, material.college, material.course_category):
            if value and str(value).strip() not in found:
                found.append(str(value).strip())
                break
    return found[:4]


def _extract_resource_types(normalized_query: str, materials: list[MaterialRecord]) -> list[str]:
    found = [label for label, aliases in RESOURCE_TYPE_RULES if any(alias.lower() in normalized_query for alias in aliases)]
    if found:
        return found[:5]
    haystack = " ".join(
        " ".join([material.title or "", material.description or "", material.keywords or ""]).lower()
        for material in materials[:5]
    )
    for label, aliases in RESOURCE_TYPE_RULES:
        if any(alias.lower() in haystack for alias in aliases) and label not in found:
            found.append(label)
    return found[:5]


def _extract_years(
    normalized_query: str,
    pdf_evidence: list[MaterialPageEvidence],
    memory_context: AgentMemoryContext | None,
) -> list[str]:
    years: list[str] = []
    for year in re.findall(r"(?<!\d)(20[0-3]\d)(?!\d)", normalized_query):
        if year not in years:
            years.append(year)
    for item in pdf_evidence:
        for year in item.years:
            if year not in years:
                years.append(year)
    platform = memory_context.platform if memory_context else {}
    for item in platform.get("pdf_year_signals") or []:
        if isinstance(item, dict):
            value = str(item.get("value") or "").strip()
            if value and value not in years:
                years.append(value)
    return years[:6]


def _extract_search_terms(normalized_query: str, course_terms: list[str], resource_types: list[str]) -> list[str]:
    terms: list[str] = []
    for value in course_terms:
        if value not in terms:
            terms.append(value)
    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", normalized_query):
        if len(token) < 2 or token in LOW_VALUE_TERMS or token in terms:
            continue
        terms.append(token)
        if len(terms) >= 10:
            break
    for value in resource_types:
        if value not in terms:
            terms.append(value)
    return terms[:12]


def _build_evidence_tasks(
    intent: str,
    pdf_evidence: list[MaterialPageEvidence],
    memory_context: AgentMemoryContext | None,
) -> list[str]:
    tasks = ["rank_candidate_materials"]
    if intent in {"exam_trend_analysis", "pdf_summary", "problem_tutoring"}:
        tasks.append("read_relevant_pdf_pages")
    if intent == "exam_trend_analysis":
        tasks.extend(["aggregate_year_signals", "aggregate_question_type_signals"])
    if intent == "study_plan":
        tasks.extend(["choose_study_sequence", "adapt_to_user_profile"])
    if pdf_evidence:
        tasks.append("cite_material_pages")
    if memory_context and memory_context.user:
        tasks.append("personalize_with_current_user_memory")
    if memory_context and memory_context.platform:
        tasks.append("use_collective_memory_as_aggregate_signal")
    return _dedupe(tasks)


def _build_response_guidance(intent: str, has_pdf_evidence: bool, has_memory_context: bool) -> list[str]:
    guidance = ["只基于候选资料、PDF 证据和记忆上下文回答，不编造平台外资料。"]
    if intent == "exam_trend_analysis":
        guidance.append("优先输出常考题型、高频知识点、年份趋势、推荐资料和复习顺序。")
    elif intent == "study_plan":
        guidance.append("优先输出阶段化复习顺序、资料使用顺序和下一步学习动作。")
    elif intent == "pdf_summary":
        guidance.append("优先说明资料覆盖内容、适合人群和应该先看的页码或章节。")
    elif intent == "problem_tutoring":
        guidance.append("优先给解题思路和易错点，再推荐相关资料页。")
    else:
        guidance.append("优先解释为什么推荐这些资料，以及用户下一步应该如何筛选。")
    if has_pdf_evidence:
        guidance.append("关键结论尽量引用资料名和页码。")
    if has_memory_context:
        guidance.append("用户个人记忆只能用于当前用户个性化建议，不能写成平台集体结论。")
    return guidance


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
