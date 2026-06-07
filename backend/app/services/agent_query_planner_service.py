from __future__ import annotations

from dataclasses import dataclass, field
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

STUDY_WEAKNESS_TERMS = (
    "调制",
    "解调",
    "频谱",
    "带宽",
    "误码率",
    "匹配滤波",
    "判决",
    "信噪比",
    "傅里叶",
    "卷积",
    "链表",
    "二叉树",
    "排序",
    "积分",
    "微分",
    "极限",
    "概率",
    "分布",
)

STUDY_TIME_PHRASES: tuple[tuple[str, int], ...] = (
    ("明天", 1),
    ("后天", 2),
    ("半个月", 15),
    ("一周", 7),
    ("二周", 14),
    ("两周", 14),
    ("三周", 21),
    ("四周", 28),
    ("一个月", 30),
    ("一月", 30),
)


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
    study_constraints: dict[str, Any] = field(default_factory=dict)

    def to_prompt_payload(self) -> dict[str, Any]:
        payload = {
            "intent": self.intent,
            "confidence": self.confidence,
            "course_terms": list(self.course_terms),
            "resource_types": list(self.resource_types),
            "years": list(self.years),
            "search_terms": list(self.search_terms),
            "evidence_tasks": list(self.evidence_tasks),
            "response_guidance": list(self.response_guidance),
        }
        if self.study_constraints:
            payload["study_constraints"] = self.study_constraints
        return payload


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
        study_constraints = _extract_study_constraints(normalized)
        evidence_tasks = _build_evidence_tasks(intent, pdf_evidence, memory_context)
        response_guidance = _build_response_guidance(
            intent,
            bool(pdf_evidence),
            memory_context is not None,
            bool(study_constraints),
        )
        return AgentQueryPlan(
            intent=intent,
            confidence=confidence,
            course_terms=tuple(course_terms),
            resource_types=tuple(resource_types),
            years=tuple(years),
            search_terms=tuple(search_terms),
            evidence_tasks=tuple(evidence_tasks),
            response_guidance=tuple(response_guidance),
            study_constraints=study_constraints,
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


def _extract_study_constraints(normalized_query: str) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    horizon = _extract_study_horizon(normalized_query)
    if horizon:
        constraints.update(horizon)
    target_score = _extract_target_score(normalized_query)
    if target_score is not None:
        constraints["target_score"] = target_score
    daily_hours = _extract_daily_hours(normalized_query)
    if daily_hours is not None:
        constraints["daily_available_hours"] = daily_hours
    weak_points = _extract_weak_points(normalized_query)
    if weak_points:
        constraints["weak_points"] = weak_points
    return constraints


def _extract_study_horizon(normalized_query: str) -> dict[str, Any]:
    for phrase, days in STUDY_TIME_PHRASES:
        if phrase in normalized_query:
            return {"time_horizon": phrase, "days_until_exam": days}
    day_match = re.search(r"(?<!\d)(\d{1,3})\s*(?:天|日)\s*后", normalized_query)
    if day_match:
        days = max(0, min(180, int(day_match.group(1))))
        return {"time_horizon": f"{days}天后", "days_until_exam": days}
    week_match = re.search(r"(?<!\d)(\d{1,2})\s*(?:周|星期)\s*后", normalized_query)
    if week_match:
        weeks = max(0, min(26, int(week_match.group(1))))
        return {"time_horizon": f"{weeks}周后", "days_until_exam": weeks * 7}
    month_match = re.search(r"(?<!\d)(\d{1,2})\s*个?月\s*后", normalized_query)
    if month_match:
        months = max(0, min(6, int(month_match.group(1))))
        return {"time_horizon": f"{months}个月后", "days_until_exam": months * 30}
    return {}


def _extract_target_score(normalized_query: str) -> int | None:
    for pattern in (
        r"(?:目标|考到|想考|希望|争取).{0,8}?(\d{2,3})\s*分?",
        r"(\d{2,3})\s*分",
    ):
        match = re.search(pattern, normalized_query)
        if not match:
            continue
        score = int(match.group(1))
        if 1 <= score <= 100:
            return score
    return None


def _extract_daily_hours(normalized_query: str) -> float | None:
    match = re.search(r"(?:每天|每日|一天).{0,8}?(\d{1,2}(?:\.\d)?)\s*(?:小时|h)", normalized_query)
    if not match:
        return None
    hours = float(match.group(1))
    if 0 < hours <= 16:
        return hours
    return None


def _extract_weak_points(normalized_query: str) -> list[str]:
    if not any(marker in normalized_query for marker in ("薄弱", "不会", "不懂", "不熟", "不太会", "卡住")):
        return []
    weak_points: list[str] = []
    for term in STUDY_WEAKNESS_TERMS:
        if term.lower() in normalized_query and term not in weak_points:
            weak_points.append(term)
        if len(weak_points) >= 6:
            break
    return weak_points


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
    if any(item.question_numbers for item in pdf_evidence):
        tasks.append("cite_question_numbers")
    if memory_context and memory_context.user:
        tasks.append("personalize_with_current_user_memory")
    if memory_context and memory_context.platform:
        tasks.append("use_collective_memory_as_aggregate_signal")
    return _dedupe(tasks)


def _build_response_guidance(
    intent: str,
    has_pdf_evidence: bool,
    has_memory_context: bool,
    has_study_constraints: bool,
) -> list[str]:
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
    if has_study_constraints:
        guidance.append("如果 study_constraints 中有考试倒计时、目标分数、每日可用时间或薄弱点，必须把它们作为复习计划边界。")
    if has_memory_context:
        guidance.append("用户个人记忆只能用于当前用户个性化建议，不能写成平台集体结论。")
    return guidance


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
