from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from app.models.materials import MaterialRecord
from app.services.agent_memory_service import AgentMemoryContext
from app.services.material_pdf_evidence_service import MaterialPageEvidence


COURSE_ALIASES: dict[str, tuple[str, ...]] = {
    "电子系统设计": ("电子系统设计", "esd"),
    "通信原理": ("通信原理", "cps"),
    "信号与系统": ("信号与系统", "signals", "signal"),
    "数据结构": ("数据结构",),
    "高等数学": ("高数", "高等数学", "微积分"),
    "概率论": ("概率论",),
}

INTENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("exam_trend_analysis", ("常考", "往年", "历年", "真题", "题型", "考点", "期末题", "考题", "考题风格", "出题风格", "试卷", "样卷")),
    ("study_plan", ("复习计划", "怎么复习", "两周", "一周", "考试", "规划", "速成")),
    ("problem_tutoring", ("错题", "不会", "怎么做", "讲解", "解析一下", "为什么")),
    ("material_fit_assessment", ("适合我", "适合", "适不适合", "该不该看", "值得看", "能不能看", "先看这份")),
    ("pdf_summary", ("这份资料", "这几份", "总结", "讲什么", "内容是什么", "概括")),
    ("material_recommendation", ("推荐", "找", "资料", "笔记", "讲义", "求资料")),
)

RESOURCE_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("past_exam", ("真题", "往年", "历年", "试卷", "期末题", "考题", "样卷")),
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

PROBLEM_CONTEXT_MARKERS = ("错题", "不会", "怎么做", "讲解", "解析一下", "为什么", "不懂", "卡住", "看不懂")

PROBLEM_FOCUS_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("概念理解", ("概念", "为什么", "不懂", "理解不了", "看不懂")),
    ("公式推导", ("公式", "推导", "证明", "怎么推", "推不出")),
    ("计算步骤", ("计算", "步骤", "怎么算", "怎么做", "代入", "求解", "不会做")),
    ("读题定位", ("题干", "条件", "读题", "问什么", "看不懂题")),
    ("答案复盘", ("解析", "答案", "错题", "哪里错", "对答案")),
)

MULTI_MATERIAL_MARKERS = (
    "这几份",
    "这几套",
    "多份",
    "多套",
    "几份",
    "几套",
    "这些",
    "全部",
    "所有",
    "一起",
    "对比",
    "比较",
    "共同",
)

LEARNING_PREFERENCE_RULES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "foundation_first",
        "补基础优先",
        "先补课程框架、核心概念和基础例题，再进入真题训练。",
        ("基础差", "零基础", "基础不好", "基础不太好", "基础弱", "看不懂", "听不懂", "入门", "从零开始"),
    ),
    (
        "crash_course",
        "考前冲刺",
        "优先抓高频题型、分值高的考点和可快速复盘的资料页。",
        ("速成", "冲刺", "考前", "短期", "来不及", "临时抱佛脚"),
    ),
    (
        "practice_first",
        "刷题优先",
        "按题型刷真题或练习，再回查不会的知识点和解析页。",
        ("刷题", "真题", "练习", "做题", "套卷", "题海"),
    ),
    (
        "explanation_first",
        "详细解析",
        "优先选择带答案、解析和步骤的资料，按概念、公式、步骤拆开讲。",
        ("详细解析", "一步步", "讲清楚", "讲明白", "细讲", "详细讲", "详细说明"),
    ),
    (
        "weak_point_review",
        "查漏补缺",
        "围绕薄弱点和错题建立清单，用同类题复盘收束。",
        ("查漏补缺", "错题", "薄弱", "短板", "弱项", "不会的地方"),
    ),
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
    problem_context: dict[str, Any] = field(default_factory=dict)
    material_scope: dict[str, Any] = field(default_factory=dict)
    learning_preferences: dict[str, Any] = field(default_factory=dict)

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
        if self.problem_context:
            payload["problem_context"] = self.problem_context
        if self.material_scope:
            payload["material_scope"] = self.material_scope
        if self.learning_preferences:
            payload["learning_preferences"] = self.learning_preferences
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
        problem_context = _extract_problem_context(normalized, pdf_evidence, intent)
        material_scope = _extract_material_scope(normalized, materials, pdf_evidence)
        learning_preferences = _extract_learning_preferences(normalized)
        evidence_tasks = _build_evidence_tasks(
            intent,
            pdf_evidence,
            memory_context,
            problem_context,
            material_scope,
            learning_preferences,
        )
        response_guidance = _build_response_guidance(
            intent,
            bool(pdf_evidence),
            memory_context is not None,
            bool(study_constraints),
            bool(problem_context),
            material_scope,
            bool(learning_preferences),
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
            problem_context=problem_context,
            material_scope=material_scope,
            learning_preferences=learning_preferences,
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


def _extract_problem_context(
    normalized_query: str,
    pdf_evidence: list[MaterialPageEvidence],
    intent: str,
) -> dict[str, Any]:
    has_problem_marker = intent == "problem_tutoring" or any(marker in normalized_query for marker in PROBLEM_CONTEXT_MARKERS)
    if not has_problem_marker:
        return {}
    focus_areas = _extract_problem_focus_areas(normalized_query)
    question_numbers = _extract_problem_question_numbers(normalized_query)
    for item in pdf_evidence[:3]:
        for number in item.question_numbers:
            if number not in question_numbers:
                question_numbers.append(number)
    knowledge_points = [term for term in STUDY_WEAKNESS_TERMS if term.lower() in normalized_query]
    payload: dict[str, Any] = {
        "focus_areas": focus_areas[:4],
        "question_numbers": question_numbers[:6],
        "knowledge_points": knowledge_points[:6],
    }
    return {key: value for key, value in payload.items() if value}


def _extract_problem_focus_areas(normalized_query: str) -> list[str]:
    focus_areas: list[str] = []
    for label, aliases in PROBLEM_FOCUS_RULES:
        if any(alias.lower() in normalized_query for alias in aliases) and label not in focus_areas:
            focus_areas.append(label)
    return focus_areas[:4]


def _extract_problem_question_numbers(normalized_query: str) -> list[str]:
    patterns = (
        r"第\s*([0-9一二三四五六七八九十]{1,3})\s*[题問问]",
        r"\b[Qq]\s*([0-9]{1,2})\b",
        r"[Qq]uestion\s*([0-9]{1,2})",
    )
    result: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, normalized_query):
            label = f"第{str(match).strip()}题"
            if label not in result:
                result.append(label)
            if len(result) >= 6:
                return result
    return result


def _extract_material_scope(
    normalized_query: str,
    materials: list[MaterialRecord],
    pdf_evidence: list[MaterialPageEvidence],
) -> dict[str, Any]:
    if not any(marker.lower() in normalized_query for marker in MULTI_MATERIAL_MARKERS):
        return {}
    pdf_material_count = len({int(item.material_id) for item in pdf_evidence})
    payload: dict[str, Any] = {
        "mode": "multi_material",
        "candidate_material_count": len(materials),
        "pdf_evidence_material_count": pdf_material_count,
    }
    if pdf_material_count <= 1:
        payload["limitation"] = "cross_material_evidence_limited"
    return payload


def _extract_learning_preferences(normalized_query: str) -> dict[str, Any]:
    modes: list[str] = []
    labels: list[str] = []
    guidance: list[str] = []
    matched_terms: list[str] = []
    for mode, label, hint, aliases in LEARNING_PREFERENCE_RULES:
        hits = [alias for alias in aliases if alias.lower() in normalized_query]
        if not hits:
            continue
        modes.append(mode)
        labels.append(label)
        guidance.append(hint)
        matched_terms.extend(hits[:2])
        if len(modes) >= 5:
            break
    if not modes:
        return {}
    return {
        "modes": modes,
        "labels": labels,
        "guidance": guidance,
        "matched_terms": _dedupe(matched_terms)[:8],
    }


def _build_evidence_tasks(
    intent: str,
    pdf_evidence: list[MaterialPageEvidence],
    memory_context: AgentMemoryContext | None,
    problem_context: dict[str, Any] | None = None,
    material_scope: dict[str, Any] | None = None,
    learning_preferences: dict[str, Any] | None = None,
) -> list[str]:
    tasks = ["rank_candidate_materials"]
    if intent in {"exam_trend_analysis", "pdf_summary", "problem_tutoring", "material_fit_assessment"}:
        tasks.append("read_relevant_pdf_pages")
    if intent == "exam_trend_analysis":
        tasks.extend(["aggregate_year_signals", "aggregate_question_type_signals"])
        if any(item.score_points for item in pdf_evidence):
            tasks.append("aggregate_score_point_signals")
        if any(item.difficulty_signals for item in pdf_evidence):
            tasks.append("aggregate_difficulty_signals")
        if any(item.visual_signals for item in pdf_evidence):
            tasks.append("preserve_formula_or_visual_page_refs")
        if any(item.anchor_text for item in pdf_evidence):
            tasks.append("cite_anchor_snippets")
    if intent == "study_plan":
        tasks.extend(["choose_study_sequence", "adapt_to_user_profile"])
    if intent == "problem_tutoring":
        tasks.extend(["identify_problem_focus", "explain_step_by_step"])
        if problem_context:
            tasks.append("adapt_tutoring_to_problem_context")
        if problem_context and problem_context.get("question_numbers"):
            tasks.append("track_mentioned_question_numbers")
    if intent == "material_fit_assessment":
        tasks.extend(["assess_material_fit", "rank_by_quality_and_risk"])
    if material_scope and material_scope.get("mode") == "multi_material":
        tasks.extend(["compare_across_materials", "aggregate_cross_material_question_types"])
        if int(material_scope.get("pdf_evidence_material_count") or 0) >= 2:
            tasks.append("cite_each_material_sources")
    if learning_preferences:
        tasks.append("adapt_to_learning_preferences")
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
    has_problem_context: bool,
    material_scope: dict[str, Any] | None = None,
    has_learning_preferences: bool = False,
) -> list[str]:
    guidance = ["只基于候选资料、PDF 证据和记忆上下文回答，不编造平台外资料。"]
    if intent == "exam_trend_analysis":
        guidance.append("优先输出出题风格、常考题型、高频知识点、年份趋势、分值结构、难度信号、公式/图表页提示、推荐资料和复习顺序。")
    elif intent == "study_plan":
        guidance.append("优先输出阶段化复习顺序、资料使用顺序和下一步学习动作。")
    elif intent == "pdf_summary":
        guidance.append("优先说明资料覆盖内容、适合人群和应该先看的页码或章节。")
    elif intent == "problem_tutoring":
        guidance.append("优先给解题思路和易错点，再推荐相关资料页。")
    elif intent == "material_fit_assessment":
        guidance.append("优先判断资料是否适合用户当前阶段，说明适合用途、先看页码、难度风险和下一步阅读顺序。")
    else:
        guidance.append("优先解释为什么推荐这些资料，以及用户下一步应该如何筛选。")
    if has_pdf_evidence:
        guidance.append("关键结论尽量引用资料名、页码和片段锚点。")
    if has_study_constraints:
        guidance.append("如果 study_constraints 中有考试倒计时、目标分数、每日可用时间或薄弱点，必须把它们作为复习计划边界。")
    if has_problem_context:
        guidance.append("如果 problem_context 中有卡点类型、题号或知识点，必须先按这些边界拆解。")
    if material_scope and material_scope.get("mode") == "multi_material":
        guidance.append("如果 material_scope 指向多份资料，必须优先做跨资料共同题型、差异点和证据覆盖说明。")
    if has_learning_preferences:
        guidance.append("如果 learning_preferences 中有学习偏好，只能用于调整解释深度、复习顺序和资料使用建议，不要输出内部字段名。")
    if has_memory_context:
        guidance.append("用户个人记忆只能用于当前用户个性化建议，不能写成平台集体结论。")
    return guidance


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
