from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


AGENT_SCOPES = {"learning", "greeting", "out_of_scope"}
AGENT_ROUTE_EXAMPLES = {
    "new_material_search",
    "refine_existing_answer",
    "revise_study_plan",
    "rerank_existing_materials",
    "answer_from_context",
    "ask_user_clarification",
}
AGENT_INTENT_EXAMPLES = {
    "material_recommendation",
    "exam_trend_analysis",
    "study_plan",
    "problem_tutoring",
    "material_fit_assessment",
    "pdf_summary",
    "general_learning_support",
}


AGENT_ORCHESTRATOR_SYSTEM_PROMPT = """
你是 StudyHub 学习 Agent 的编排器。你的任务不是回答用户，而是理解这一轮真正要完成的学习任务，并输出严格 JSON。

你要综合 current_user_query、conversation_context、platform_term_glossary 和 has_image 自主判断：
1. 当前内容是否属于课程学习、资料检索、题目分析、考试复习或 StudyHub 资料使用；普通问候单独标记 greeting。
2. 用简短、开放的 task_label 和 strategy 描述真正任务，不要强行归入预设意图。可以创建“公式推导”“错题诊断”“模拟考试设计”等最贴合用户的标签。
3. 是否确实需要重新检索资料。用户只要求细化已有答案时不要重新检索；用户提出新的课程、资料范围、年份或题型时应检索。
4. 生成适合 StudyHub 多词检索的 search_query。使用简短、空格分隔的核心词，保留课程名、资料类型、年份和关键知识点，去掉“帮我、怎么、一下”等对检索无帮助的表达。
5. 识别用户的学习目标、时间、基础、薄弱点、题号、偏好和期望回答结构。不要靠固定关键词机械套分类，要根据整句话和对话语境判断。

关键示例：
- 上文讨论通信原理，用户说“把第 1-7 天细化到每天两小时”：use_context=true，should_search=false，intent=study_plan。
- 上文讨论通信原理，用户说“再找一些 2023 年真题”：use_context=true，should_search=true，search_query 应包含“通信原理 2023 真题”。
- 用户说“帮我整理成两周复习计划”：如果上文已有课程和资料，沿用上下文且不重新检索；如果没有课程信息，可 ask_user_clarification。
- 用户说“ESD 有哪些常考题型和知识点”：这是 exam_trend_analysis，需要检索“电子系统设计 ESD 真题 题型 知识点”。
- 用户说“需要我帮你分析真题吗”：这是用户真实输入，不要因为句式像助手就改写用户原话；按其语义判断。
- followup_guidance 描述下一步建议的方向，不直接生成“要不要我……”式问题。建议应能转成用户点击后直接发送的任务，例如“按年份整理题型”或“把第 1-7 天细化到每天两小时”。

platform_term_glossary 是 StudyHub 当前部署的私有站内术语词典；出现缩写歧义时必须优先采用这里的课程含义。
只输出 JSON，不要输出解释、Markdown 或代码块。不要编造上下文里不存在的课程、资料标题、年份或用户约束。
""".strip()


AGENT_RESPONSE_REVIEW_SYSTEM_PROMPT = """
你是 StudyHub 学习 Agent 的语义审阅器。你要审阅一份已经生成的回答，而不是重新检索资料。

请综合用户原问题、当前对话计划、候选资料摘要和 draft_response 判断：
1. 回答是否真正沿着用户当前方向完成任务，是否误把上下文追问当成新的资料关键词搜索。
2. 回答是否错误声称“没有候选资料”、答非所问、离开学习范围，或把不确定的元数据说成已经读取的 PDF 事实。candidate_materials 非空时绝不能声称没有候选资料；可以说明“已有候选资料，但暂无页级证据”。正文中出现的资料 ID 必须属于 candidate_materials，其他 ID 和对应资料名必须删除。
3. Markdown 是否清晰，复习计划是否按天/阶段展开，题型总结是否围绕课程而非混入其他课程。
4. followup_questions 是否是用户点击后可直接发送的下一步学习任务。它们必须延续当前回答方向、使用用户口吻、彼此不同；不要输出“需要我、是否想、要不要我、你的考试日期”等助手向用户发问的句式，也不要输出泛化筛选标题。

platform_term_glossary 是当前站内课程术语的权威释义；缩写有歧义时，回答必须采用该词典和候选资料 major/college 所指向的课程语义。

尽量保留正确内容，只修正有问题的部分。若无需修改，approved=true 并原样返回 answer 和 followup_questions；若需要修改，approved=false 并返回完整修订结果。
资料标题和摘要只能证明资料大致主题，不能证明其中一定包含某类题型、章节、分值或结论。没有 available_pdf_evidence 时，相关学习建议应明确是一般性方法，不能写成“根据某资料可知”。
只输出严格 JSON，不要输出解释、Markdown 代码围栏或额外字段。不要创建候选列表中不存在的资料、资料 ID 或 PDF 页码。
""".strip()


@dataclass(frozen=True, slots=True)
class AgentOrchestrationPlan:
    scope: str
    route: str
    should_search: bool
    use_context: bool
    search_query: str
    intent: str
    confidence: float = 0.5
    course_terms: tuple[str, ...] = ()
    resource_types: tuple[str, ...] = ()
    years: tuple[str, ...] = ()
    study_constraints: dict[str, Any] = field(default_factory=dict)
    problem_context: dict[str, Any] = field(default_factory=dict)
    material_scope: dict[str, Any] = field(default_factory=dict)
    learning_preferences: dict[str, Any] = field(default_factory=dict)
    exam_analysis_focus: dict[str, Any] = field(default_factory=dict)
    evidence_tasks: tuple[str, ...] = ()
    response_guidance: tuple[str, ...] = ()
    followup_guidance: tuple[str, ...] = ()
    reason: str = "model"
    source: str = "model"

    @property
    def is_learning(self) -> bool:
        return self.scope == "learning"

    def to_query_plan_seed(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "course_terms": list(self.course_terms),
            "resource_types": list(self.resource_types),
            "years": list(self.years),
            "search_terms": _compact_list(self.search_query.split(), limit=12, max_chars=60),
            "study_constraints": self.study_constraints,
            "problem_context": self.problem_context,
            "material_scope": self.material_scope,
            "learning_preferences": self.learning_preferences,
            "exam_analysis_focus": self.exam_analysis_focus,
            "evidence_tasks": list(self.evidence_tasks),
            "response_guidance": list(self.response_guidance),
            "followup_guidance": list(self.followup_guidance),
        }


class AgentOrchestratorService:
    def build_request(
        self,
        query: str,
        *,
        context_query: str | None,
        has_image: bool,
        platform_term_glossary: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        return {
            "current_user_query": str(query or "").strip()[:1200],
            "user_query": str(query or "").strip()[:1200],
            "conversation_context": str(context_query or "").strip()[-1200:],
            "has_image": bool(has_image),
            "platform_term_glossary": platform_term_glossary or {},
            "strategy_examples": sorted(AGENT_ROUTE_EXAMPLES),
            "task_label_examples": sorted(AGENT_INTENT_EXAMPLES),
            "allowed_scope": sorted(AGENT_SCOPES),
            "output_schema": {
                "scope": "learning | greeting | out_of_scope",
                "route": "a concise free-form execution strategy label",
                "should_search": "boolean",
                "use_context": "boolean",
                "search_query": "space-separated retrieval terms; empty when should_search=false",
                "intent": "a concise free-form task label",
                "confidence": "number from 0 to 1",
                "course_terms": ["canonical course names or aliases from the conversation"],
                "resource_types": ["requested material types"],
                "years": ["explicit years"],
                "study_constraints": "object with only constraints explicitly stated or inherited from relevant context",
                "problem_context": "object describing the actual question, topic or blockage",
                "material_scope": "object describing single/multiple/existing material scope",
                "learning_preferences": "object describing study style explicitly implied by the user",
                "exam_analysis_focus": "object describing requested exam-analysis dimensions",
                "evidence_tasks": ["what evidence the answering model should inspect"],
                "response_guidance": ["how the final answer should be organized"],
                "followup_guidance": ["2-3 concrete next-task directions in user voice"],
                "reason": "brief internal explanation",
            },
        }

    def parse(self, value: Any, *, fallback: AgentOrchestrationPlan) -> AgentOrchestrationPlan:
        if not isinstance(value, dict):
            return fallback
        scope = _enum(value.get("scope"), AGENT_SCOPES, fallback.scope)
        route = _clean_text(value.get("route"), max_chars=80) or fallback.route
        intent = _clean_text(value.get("intent"), max_chars=80) or fallback.intent
        should_search = bool(value.get("should_search"))
        use_context = bool(value.get("use_context"))
        search_query = _clean_text(value.get("search_query"), max_chars=500) if should_search else ""
        if should_search and not search_query:
            search_query = fallback.search_query
        return AgentOrchestrationPlan(
            scope=scope,
            route=route,
            should_search=should_search,
            use_context=use_context,
            search_query=search_query,
            intent=intent,
            confidence=_confidence(value.get("confidence"), fallback.confidence),
            course_terms=tuple(_compact_list(value.get("course_terms"), limit=5, max_chars=60)),
            resource_types=tuple(_compact_list(value.get("resource_types"), limit=6, max_chars=60)),
            years=tuple(_compact_years(value.get("years"))),
            study_constraints=_compact_mapping(value.get("study_constraints")),
            problem_context=_compact_mapping(value.get("problem_context")),
            material_scope=_compact_mapping(value.get("material_scope")),
            learning_preferences=_compact_mapping(value.get("learning_preferences")),
            exam_analysis_focus=_compact_mapping(value.get("exam_analysis_focus")),
            evidence_tasks=tuple(_compact_list(value.get("evidence_tasks"), limit=8, max_chars=160)),
            response_guidance=tuple(_compact_list(value.get("response_guidance"), limit=8, max_chars=160)),
            followup_guidance=tuple(_compact_list(value.get("followup_guidance"), limit=3, max_chars=80)),
            reason=_clean_text(value.get("reason"), max_chars=160) or "model",
            source="model",
        )


def _enum(value: Any, allowed: set[str], fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else fallback


def _confidence(value: Any, fallback: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return fallback


def _clean_text(value: Any, *, max_chars: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_chars]


def _compact_list(value: Any, *, limit: int, max_chars: int) -> list[str]:
    items = value if isinstance(value, (list, tuple)) else []
    result: list[str] = []
    for item in items:
        cleaned = _clean_text(item, max_chars=max_chars)
        if cleaned and cleaned not in result:
            result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _compact_years(value: Any) -> list[str]:
    result: list[str] = []
    for item in _compact_list(value, limit=8, max_chars=20):
        for year in re.findall(r"(?<!\d)(20[0-3]\d)(?!\d)", item):
            if year not in result:
                result.append(year)
    return result[:8]


def _compact_mapping(value: Any, *, depth: int = 0) -> dict[str, Any]:
    if not isinstance(value, dict) or depth > 2:
        return {}
    result: dict[str, Any] = {}
    for raw_key, raw_value in list(value.items())[:16]:
        key = _clean_text(raw_key, max_chars=60)
        if not key:
            continue
        if isinstance(raw_value, dict):
            nested = _compact_mapping(raw_value, depth=depth + 1)
            if nested:
                result[key] = nested
        elif isinstance(raw_value, (list, tuple)):
            items = _compact_list(raw_value, limit=10, max_chars=120)
            if items:
                result[key] = items
        elif isinstance(raw_value, bool):
            result[key] = raw_value
        elif isinstance(raw_value, (int, float)):
            result[key] = raw_value
        else:
            cleaned = _clean_text(raw_value, max_chars=160)
            if cleaned:
                result[key] = cleaned
    return result
